import discord
from discord.ext import commands
from discord import app_commands
import json
import csv
import os
import asyncio
from datetime import datetime, timezone
from io import StringIO

# ─── CONFIG ───────────────────────────────────────────────────────────────────
VOICE_CHANNEL_ID = 1400622934468329612
ADMIN_ROLE_ID    = 717157700315774976
REQUIRED_SECONDS = 3600  # 1 hora
DATA_FILE        = "data.json"
# ──────────────────────────────────────────────────────────────────────────────

intents = discord.Intents.default()
intents.members = True
intents.voice_states = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

# ─── STATE ────────────────────────────────────────────────────────────────────
evento_ativo = False
# { user_id: { "nick": str, "discord_tag": str, "total_seconds": int, "entrou_em": datetime | None } }
participantes: dict = {}
# ──────────────────────────────────────────────────────────────────────────────

def salvar_dados():
    serializavel = {}
    for uid, d in participantes.items():
        serializavel[str(uid)] = {
            "nick": d["nick"],
            "discord_tag": d["discord_tag"],
            "total_seconds": d["total_seconds"],
            "entrou_em": d["entrou_em"].isoformat() if d["entrou_em"] else None
        }
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(serializavel, f, ensure_ascii=False, indent=2)

def carregar_dados():
    global participantes
    if not os.path.exists(DATA_FILE):
        return
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        raw = json.load(f)
    for uid, d in raw.items():
        participantes[int(uid)] = {
            "nick": d["nick"],
            "discord_tag": d["discord_tag"],
            "total_seconds": d["total_seconds"],
            "entrou_em": datetime.fromisoformat(d["entrou_em"]) if d["entrou_em"] else None
        }

def tem_cargo_admin(interaction: discord.Interaction) -> bool:
    return any(r.id == ADMIN_ROLE_ID for r in interaction.user.roles)

def formatar_tempo(segundos: int) -> str:
    h = segundos // 3600
    m = (segundos % 3600) // 60
    s = segundos % 60
    return f"{h}h {m:02d}min {s:02d}s"

# ─── EVENTS ───────────────────────────────────────────────────────────────────

@bot.event
async def on_ready():
    carregar_dados()
    await tree.sync()
    print(f"✅ Bot online como {bot.user} | Evento ativo: {evento_ativo}")

@bot.event
async def on_voice_state_update(member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
    global participantes

    if not evento_ativo:
        return

    # Entrou no canal do evento
    entrou = after.channel and after.channel.id == VOICE_CHANNEL_ID
    saiu   = before.channel and before.channel.id == VOICE_CHANNEL_ID and (not after.channel or after.channel.id != VOICE_CHANNEL_ID)

    if entrou:
        agora = datetime.now(timezone.utc)
        if member.id not in participantes:
            participantes[member.id] = {
                "nick": member.display_name,
                "discord_tag": str(member),
                "total_seconds": 0,
                "entrou_em": agora
            }
        else:
            # Atualiza nick caso tenha mudado
            participantes[member.id]["nick"] = member.display_name
            participantes[member.id]["discord_tag"] = str(member)
            participantes[member.id]["entrou_em"] = agora
        salvar_dados()

    elif saiu:
        if member.id in participantes and participantes[member.id]["entrou_em"]:
            agora = datetime.now(timezone.utc)
            sessao = (agora - participantes[member.id]["entrou_em"]).total_seconds()
            participantes[member.id]["total_seconds"] += int(sessao)
            participantes[member.id]["entrou_em"] = None
            salvar_dados()

# ─── COMMANDS ─────────────────────────────────────────────────────────────────

@tree.command(name="iniciar_evento", description="Inicia o CineRevo 2026 e começa a contar o tempo dos participantes")
async def iniciar_evento(interaction: discord.Interaction):
    global evento_ativo, participantes

    if not tem_cargo_admin(interaction):
        await interaction.response.send_message("❌ Você não tem permissão.", ephemeral=True)
        return

    if evento_ativo:
        await interaction.response.send_message("⚠️ O evento já está em andamento.", ephemeral=True)
        return

    evento_ativo = True
    participantes = {}
    salvar_dados()

    # Registra quem já está na call no momento do início
    guild = interaction.guild
    canal = guild.get_channel(VOICE_CHANNEL_ID)
    agora = datetime.now(timezone.utc)
    if canal:
        for member in canal.members:
            participantes[member.id] = {
                "nick": member.display_name,
                "discord_tag": str(member),
                "total_seconds": 0,
                "entrou_em": agora
            }
        salvar_dados()

    await interaction.response.send_message("🎬 **CineRevo 2026 iniciado!** Contagem de tempo ativada.", ephemeral=True)


@tree.command(name="encerrar_evento", description="Encerra o CineRevo 2026 e para a contagem de tempo")
async def encerrar_evento(interaction: discord.Interaction):
    global evento_ativo

    if not tem_cargo_admin(interaction):
        await interaction.response.send_message("❌ Você não tem permissão.", ephemeral=True)
        return

    if not evento_ativo:
        await interaction.response.send_message("⚠️ Nenhum evento em andamento.", ephemeral=True)
        return

    evento_ativo = False

    # Fecha sessões abertas de quem ainda está na call
    agora = datetime.now(timezone.utc)
    for uid, d in participantes.items():
        if d["entrou_em"]:
            sessao = (agora - d["entrou_em"]).total_seconds()
            d["total_seconds"] += int(sessao)
            d["entrou_em"] = None
    salvar_dados()

    await interaction.response.send_message("🛑 **CineRevo 2026 encerrado!** Use `/relatorio` para ver os resultados.", ephemeral=True)


@tree.command(name="relatorio", description="Gera o relatório CSV do CineRevo 2026")
async def relatorio(interaction: discord.Interaction):
    if not tem_cargo_admin(interaction):
        await interaction.response.send_message("❌ Você não tem permissão.", ephemeral=True)
        return

    if not participantes:
        await interaction.response.send_message("📭 Nenhum participante registrado ainda.", ephemeral=True)
        return

    # Fecha sessões abertas se evento ainda ativo
    agora = datetime.now(timezone.utc)
    dados_snapshot = {}
    for uid, d in participantes.items():
        total = d["total_seconds"]
        if d["entrou_em"]:
            total += int((agora - d["entrou_em"]).total_seconds())
        dados_snapshot[uid] = {
            "nick": d["nick"],
            "discord_tag": d["discord_tag"],
            "total_seconds": total
        }

    com_emblema    = [d for d in dados_snapshot.values() if d["total_seconds"] >= REQUIRED_SECONDS]
    sem_emblema    = [d for d in dados_snapshot.values() if d["total_seconds"] < REQUIRED_SECONDS]
    total_pessoas  = len(dados_snapshot)

    # Gera CSV em memória
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(["Nick do Servidor", "Discord", "Tempo Total", "Emblema"])

    todos_ordenados = sorted(dados_snapshot.values(), key=lambda x: x["total_seconds"], reverse=True)
    for d in todos_ordenados:
        emblema = "✅" if d["total_seconds"] >= REQUIRED_SECONDS else "❌"
        writer.writerow([d["nick"], d["discord_tag"], formatar_tempo(d["total_seconds"]), emblema])

    output.seek(0)
    csv_bytes = output.getvalue().encode("utf-8-sig")  # utf-8-sig abre corretamente no Excel

    arquivo = discord.File(fp=__import__("io").BytesIO(csv_bytes), filename="cinerevo2026_relatorio.csv")

    resumo = (
        f"📊 **CineRevo 2026 — Relatório**\n"
        f"✅ Com emblema: **{len(com_emblema)}** pessoas\n"
        f"❌ Sem emblema: **{len(sem_emblema)}** pessoas\n"
        f"👥 Total na call: **{total_pessoas}** pessoas"
    )

    await interaction.response.send_message(content=resumo, file=arquivo, ephemeral=True)


@tree.command(name="status_evento", description="Mostra se o evento está ativo e quantos participantes há")
async def status_evento(interaction: discord.Interaction):
    if not tem_cargo_admin(interaction):
        await interaction.response.send_message("❌ Você não tem permissão.", ephemeral=True)
        return

    status = "🟢 **Ativo**" if evento_ativo else "🔴 **Encerrado**"
    total  = len(participantes)
    na_call = sum(1 for d in participantes.values() if d["entrou_em"] is not None)

    await interaction.response.send_message(
        f"📡 Status: {status}\n👥 Participantes registrados: **{total}**\n🎙️ Agora na call: **{na_call}**",
        ephemeral=True
    )


# ─── RUN ──────────────────────────────────────────────────────────────────────
TOKEN = os.environ.get("DISCORD_TOKEN")
if not TOKEN:
    raise ValueError("❌ Variável de ambiente DISCORD_TOKEN não definida!")

bot.run(TOKEN)