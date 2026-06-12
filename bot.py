import discord
from discord.ext import commands
from discord import app_commands
import json
import csv
import os
import asyncio
from datetime import datetime, timezone
from io import StringIO, BytesIO

# ─── CONFIG ───────────────────────────────────────────────────────────────────
VOICE_CHANNEL_ID  = 1400622934468329612
ADMIN_ROLE_ID     = 717157700315774976
PAINEL_CHANNEL_ID = 798186632389197835
GUILD_ID          = 715701837650460712
REQUIRED_SECONDS  = 3600  # 1 hora
DATA_FILE         = "data.json"
PAINEL_FILE       = "painel_msg_id.txt"
INTERVALO_PAINEL  = 30  # segundos
# ──────────────────────────────────────────────────────────────────────────────

intents = discord.Intents.default()
intents.members = True
intents.voice_states = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

# ─── STATE ────────────────────────────────────────────────────────────────────
evento_ativo = False
evento_inicio: datetime | None = None
participantes: dict = {}
painel_message_id: int | None = None
dm_enviadas: set = set()  # IDs de quem já recebeu DM neste evento
# ──────────────────────────────────────────────────────────────────────────────

# ─── MENSAGEM DM ──────────────────────────────────────────────────────────────
DM_FILE = "dm_mensagem.txt"
DM_PADRAO = (
    "🎬 **Bem-vindo ao CineRevo 2026!**\n\n"
    "Para ganhar o **Emblema CineRevo 2026**, você precisa ficar no mínimo "
    "**1 hora** na call do evento.\n\n"
    "O tempo é acumulado — pode sair e voltar! ⏱️\n\n"
    "Bom evento! 🍿"
)

def carregar_dm_mensagem() -> str:
    if not os.path.exists(DM_FILE):
        return DM_PADRAO
    with open(DM_FILE, "r", encoding="utf-8") as f:
        return f.read().strip() or DM_PADRAO

def salvar_dm_mensagem(texto: str):
    with open(DM_FILE, "w", encoding="utf-8") as f:
        f.write(texto)
# ──────────────────────────────────────────────────────────────────────────────

# ─── CORES / TEMA ─────────────────────────────────────────────────────────────
COR_ATIVO    = 0xF5C518  # dourado IMDb
COR_ENCERRADO = 0x2C2F33  # cinza escuro
COR_SUCESSO  = 0x2ECC71  # verde
COR_ERRO     = 0xE74C3C  # vermelho
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

def salvar_painel_id(msg_id: int):
    with open(PAINEL_FILE, "w") as f:
        f.write(str(msg_id))

def carregar_painel_id() -> int | None:
    if not os.path.exists(PAINEL_FILE):
        return None
    with open(PAINEL_FILE, "r") as f:
        try:
            return int(f.read().strip())
        except:
            return None

def tem_cargo_admin(interaction: discord.Interaction) -> bool:
    return any(r.id == ADMIN_ROLE_ID for r in interaction.user.roles)

def formatar_tempo(segundos: int) -> str:
    h = segundos // 3600
    m = (segundos % 3600) // 60
    s = segundos % 60
    return f"{h}h {m:02d}min {s:02d}s"

def tempo_atual(uid: int) -> int:
    d = participantes.get(uid)
    if not d:
        return 0
    total = d["total_seconds"]
    if d["entrou_em"]:
        total += int((datetime.now(timezone.utc) - d["entrou_em"]).total_seconds())
    return total

def barra_progresso(segundos: int, meta: int = REQUIRED_SECONDS, tamanho: int = 10) -> str:
    progresso = min(segundos / meta, 1.0)
    cheios = int(progresso * tamanho)
    vazios = tamanho - cheios
    barra = "█" * cheios + "░" * vazios
    pct = int(progresso * 100)
    return f"`{barra}` {pct}%"

def horario_brasilia() -> str:
    from datetime import timedelta
    brasilia = datetime.now(timezone.utc) - timedelta(hours=3)
    return brasilia.strftime("%H:%M:%S")

def build_painel_embed() -> discord.Embed:
    agora = datetime.now(timezone.utc)

    # ── Sem evento ──────────────────────────────────────────────────────────
    if not evento_ativo and not participantes:
        embed = discord.Embed(
            title="🎬  CineRevo 2026 — Painel de Presença",
            description=(
                "\n"
                "Nenhum evento em andamento no momento.\n"
                "Aguardando início...\n"
            ),
            color=COR_ENCERRADO
        )
        embed.set_footer(text=f"🕐 {horario_brasilia()} (Brasília)")
        return embed

    # ── Snapshot ─────────────────────────────────────────────────────────────
    snapshot = []
    for uid, d in participantes.items():
        total = tempo_atual(uid)
        snapshot.append({
            "nick": d["nick"],
            "total_seconds": total,
            "na_call": d["entrou_em"] is not None,
            "ganhou": total >= REQUIRED_SECONDS
        })
    snapshot.sort(key=lambda x: x["total_seconds"], reverse=True)

    com_emblema   = sum(1 for s in snapshot if s["ganhou"])
    na_call_agora = sum(1 for s in snapshot if s["na_call"])
    total_pessoas = len(snapshot)
    LIMITE_EXPANDIDO = 8  # até 8 pessoas → layout expandido; acima → compacto

    # ── Header ───────────────────────────────────────────────────────────────
    if evento_ativo:
        status_icon  = "🟢"
        status_label = "Em andamento"
        cor          = COR_ATIVO
    else:
        status_icon  = "🔴"
        status_label = "Encerrado"
        cor          = COR_ENCERRADO

    embed = discord.Embed(
        title="🎬  CineRevo 2026 — Painel de Presença",
        color=cor
    )

    # ── Estatísticas (linha de resumo) ───────────────────────────────────────
    embed.add_field(
        name="Status",
        value=f"{status_icon}  {status_label}",
        inline=True
    )
    embed.add_field(
        name="🎙️  Na call agora",
        value=f"**{na_call_agora}**",
        inline=True
    )
    embed.add_field(
        name="🏅  Ganharam Emblema",
        value=f"**{com_emblema}** / {total_pessoas}",
        inline=True
    )

    # ── Separador visual ─────────────────────────────────────────────────────
    embed.add_field(name="\u200b", value="─" * 36, inline=False)

    # ── Lista de participantes — EXPANDIDO (≤ 8 pessoas) ────────────────────
    if snapshot and total_pessoas <= LIMITE_EXPANDIDO:
        for s in snapshot:
            if s["ganhou"]:
                icone  = "🏅"
                estado = "Ganhou o Emblema!"
            elif s["na_call"]:
                icone  = "🎙️"
                estado = "Na call agora"
            else:
                icone  = "⏸️"
                estado = "Fora da call"

            h = s["total_seconds"] // 3600
            m = (s["total_seconds"] % 3600) // 60
            tempo_fmt = f"{h}h {m:02d}min"

            # Barra de progresso
            prog  = min(s["total_seconds"] / REQUIRED_SECONDS, 1.0)
            cheios = int(prog * 8)
            barra = "█" * cheios + "░" * (8 - cheios)
            pct   = int(prog * 100)

            embed.add_field(
                name=f"{icone}  {s['nick']}",
                value=f"`{barra}` {pct}%  •  **{tempo_fmt}**\n{estado}",
                inline=True
            )

        # Padding para alinhar grid de 2 colunas se número ímpar
        if total_pessoas % 2 != 0:
            embed.add_field(name="\u200b", value="\u200b", inline=True)

    # ── Lista de participantes — COMPACTO (> 8 pessoas) ──────────────────────
    elif snapshot:
        MAX_COMPACTO = 25
        linhas = []
        for s in snapshot[:MAX_COMPACTO]:
            if s["ganhou"]:
                icone = "🏅"
            elif s["na_call"]:
                icone = "🎙️"
            else:
                icone = "⏸️"
            h = s["total_seconds"] // 3600
            m = (s["total_seconds"] % 3600) // 60
            linhas.append(f"{icone} **{s['nick']}** — {h}h {m:02d}min")

        if total_pessoas > MAX_COMPACTO:
            linhas.append(f"*...e mais {total_pessoas - MAX_COMPACTO} participantes*")

        embed.add_field(
            name=f"👥  Participantes ({total_pessoas})",
            value="\n".join(linhas),
            inline=False
        )

    # ── Legenda ──────────────────────────────────────────────────────────────
    embed.add_field(
        name="\u200b",
        value="🏅 Ganhou o Emblema  ·  🎙️ Na call  ·  ⏸️ Saiu",
        inline=False
    )

    embed.set_footer(text=f"🔄 Atualizado às {horario_brasilia()} (Brasília)")
    return embed


async def atualizar_painel():
    global painel_message_id
    canal = bot.get_channel(PAINEL_CHANNEL_ID)
    if not canal:
        return
    embed = build_painel_embed()
    if painel_message_id:
        try:
            msg = await canal.fetch_message(painel_message_id)
            await msg.edit(embed=embed)
            return
        except discord.NotFound:
            painel_message_id = None

    # Cria nova mensagem se não existe
    msg = await canal.send(embed=embed)
    painel_message_id = msg.id
    salvar_painel_id(msg.id)


async def loop_painel():
    await bot.wait_until_ready()
    global painel_message_id
    painel_message_id = carregar_painel_id()
    while not bot.is_closed():
        try:
            await atualizar_painel()
        except Exception as e:
            print(f"[PAINEL ERROR] {e}")
        await asyncio.sleep(INTERVALO_PAINEL)


# ─── EVENTS ───────────────────────────────────────────────────────────────────

@bot.event
async def on_ready():
    carregar_dados()
    guild = discord.Object(id=GUILD_ID)
    tree.copy_global_to(guild=guild)
    await tree.sync(guild=guild)
    bot.loop.create_task(loop_painel())
    print(f"✅ Bot online como {bot.user} | Comandos sincronizados!")

@bot.event
async def on_voice_state_update(member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
    if not evento_ativo:
        return

    entrou = after.channel and after.channel.id == VOICE_CHANNEL_ID
    saiu   = before.channel and before.channel.id == VOICE_CHANNEL_ID and (
        not after.channel or after.channel.id != VOICE_CHANNEL_ID
    )

    agora = datetime.now(timezone.utc)

    if entrou:
        primeira_vez = member.id not in participantes
        if member.id not in participantes:
            participantes[member.id] = {
                "nick": member.display_name,
                "discord_tag": str(member),
                "total_seconds": 0,
                "entrou_em": agora
            }
        else:
            participantes[member.id]["nick"] = member.display_name
            participantes[member.id]["discord_tag"] = str(member)
            participantes[member.id]["entrou_em"] = agora
        salvar_dados()

        # Envia DM apenas uma vez por evento
        if member.id not in dm_enviadas:
            dm_enviadas.add(member.id)
            try:
                texto_extra = carregar_dm_mensagem()
                dm_embed = discord.Embed(
                    title="🎬  Bem-vindo ao CineRevo 2026!",
                    description=texto_extra,
                    color=0xF5C518
                )
                dm_embed.add_field(
                    name="⏱️  Meta de tempo",
                    value="Fique **1 hora** na call para ganhar o emblema.",
                    inline=False
                )
                dm_embed.add_field(
                    name="🔄  Tempo acumulado",
                    value="Pode sair e voltar! O tempo é somado automaticamente.",
                    inline=False
                )
                dm_embed.set_footer(text="CineRevo 2026  •  Boa sessão! 🍿")
                await member.send(embed=dm_embed)
            except discord.Forbidden:
                pass  # Usuário com DMs fechadas, ignora silenciosamente

    elif saiu:
        if member.id in participantes and participantes[member.id]["entrou_em"]:
            sessao = (agora - participantes[member.id]["entrou_em"]).total_seconds()
            participantes[member.id]["total_seconds"] += int(sessao)
            participantes[member.id]["entrou_em"] = None
            salvar_dados()


# ─── COMMANDS ─────────────────────────────────────────────────────────────────

@tree.command(name="iniciar_evento", description="Inicia o CineRevo 2026 (reseta dados anteriores)")
async def iniciar_evento(interaction: discord.Interaction):
    global evento_ativo, participantes, evento_inicio

    if not tem_cargo_admin(interaction):
        embed = discord.Embed(description="❌ Você não tem permissão.", color=COR_ERRO)
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    if evento_ativo:
        embed = discord.Embed(description="⚠️ O evento já está em andamento.", color=COR_ERRO)
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    evento_ativo = True
    evento_inicio = datetime.now(timezone.utc)
    participantes = {}
    dm_enviadas.clear()
    salvar_dados()

    # Registra quem já está na call
    canal_voz = interaction.guild.get_channel(VOICE_CHANNEL_ID)
    agora = datetime.now(timezone.utc)
    if canal_voz:
        for member in canal_voz.members:
            participantes[member.id] = {
                "nick": member.display_name,
                "discord_tag": str(member),
                "total_seconds": 0,
                "entrou_em": agora
            }
        salvar_dados()

    embed = discord.Embed(
        title="🎬 CineRevo 2026 Iniciado!",
        description="A contagem de tempo foi ativada.\nQuem ficar **1 hora** na call ganha o emblema!",
        color=COR_SUCESSO
    )
    embed.add_field(name="🎙️ Já na call", value=f"**{len(participantes)}** pessoas", inline=True)
    embed.set_footer(text=f"Iniciado por {interaction.user.display_name}")
    await interaction.response.send_message(embed=embed, ephemeral=True)
    await atualizar_painel()


@tree.command(name="encerrar_evento", description="Encerra o CineRevo 2026 e preserva os dados para o relatório")
async def encerrar_evento(interaction: discord.Interaction):
    global evento_ativo

    if not tem_cargo_admin(interaction):
        embed = discord.Embed(description="❌ Você não tem permissão.", color=COR_ERRO)
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    if not evento_ativo:
        embed = discord.Embed(description="⚠️ Nenhum evento em andamento.", color=COR_ERRO)
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    evento_ativo = False
    agora = datetime.now(timezone.utc)

    # Fecha sessões abertas
    for uid, d in participantes.items():
        if d["entrou_em"]:
            sessao = (agora - d["entrou_em"]).total_seconds()
            d["total_seconds"] += int(sessao)
            d["entrou_em"] = None
    salvar_dados()

    com_emblema = sum(1 for d in participantes.values() if d["total_seconds"] >= REQUIRED_SECONDS)
    total = len(participantes)

    embed = discord.Embed(
        title="🛑 CineRevo 2026 Encerrado!",
        description="Contagem de tempo finalizada. Use `/relatorio` para ver o resultado completo.",
        color=COR_ENCERRADO
    )
    embed.add_field(name="✅ Com emblema", value=f"**{com_emblema}**", inline=True)
    embed.add_field(name="👥 Total", value=f"**{total}**", inline=True)
    embed.set_footer(text=f"Encerrado por {interaction.user.display_name}")
    await interaction.response.send_message(embed=embed, ephemeral=True)
    await atualizar_painel()


@tree.command(name="relatorio", description="Gera o relatório CSV completo do CineRevo 2026")
async def relatorio(interaction: discord.Interaction):
    if not tem_cargo_admin(interaction):
        embed = discord.Embed(description="❌ Você não tem permissão.", color=COR_ERRO)
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    if not participantes:
        embed = discord.Embed(description="📭 Nenhum participante registrado ainda.", color=COR_ERRO)
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

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

    com_emblema = [d for d in dados_snapshot.values() if d["total_seconds"] >= REQUIRED_SECONDS]
    sem_emblema = [d for d in dados_snapshot.values() if d["total_seconds"] < REQUIRED_SECONDS]

    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(["Nick do Servidor", "Discord", "Tempo Total", "Emblema"])
    for d in sorted(dados_snapshot.values(), key=lambda x: x["total_seconds"], reverse=True):
        emblema = "SIM" if d["total_seconds"] >= REQUIRED_SECONDS else "NAO"
        writer.writerow([d["nick"], d["discord_tag"], formatar_tempo(d["total_seconds"]), emblema])

    output.seek(0)
    csv_bytes = output.getvalue().encode("utf-8-sig")
    arquivo = discord.File(fp=BytesIO(csv_bytes), filename="cinerevo2026_relatorio.csv")

    embed = discord.Embed(
        title="📊 CineRevo 2026 — Relatório Final",
        color=COR_ATIVO
    )
    embed.add_field(name="✅ Com emblema", value=f"**{len(com_emblema)}** pessoas", inline=True)
    embed.add_field(name="❌ Sem emblema", value=f"**{len(sem_emblema)}** pessoas", inline=True)
    embed.add_field(name="👥 Total", value=f"**{len(dados_snapshot)}** pessoas", inline=True)
    embed.set_footer(text="Arquivo CSV em anexo — abre no Excel ou Google Sheets")

    await interaction.response.send_message(embed=embed, file=arquivo, ephemeral=True)


@tree.command(name="status_evento", description="Mostra o status atual do evento")
async def status_evento(interaction: discord.Interaction):
    if not tem_cargo_admin(interaction):
        embed = discord.Embed(description="❌ Você não tem permissão.", color=COR_ERRO)
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    embed = build_painel_embed()
    await interaction.response.send_message(embed=embed, ephemeral=True)


@tree.command(name="resetar_evento", description="Reseta todos os dados sem encerrar o evento")
async def resetar_evento(interaction: discord.Interaction):
    global participantes

    if not tem_cargo_admin(interaction):
        embed = discord.Embed(description="❌ Você não tem permissão.", color=COR_ERRO)
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    participantes = {}
    salvar_dados()

    embed = discord.Embed(
        title="🔄 Dados resetados!",
        description="Todos os tempos e participantes foram apagados.",
        color=COR_ERRO
    )
    embed.set_footer(text=f"Resetado por {interaction.user.display_name}")
    await interaction.response.send_message(embed=embed, ephemeral=True)
    await atualizar_painel()


@tree.command(name="definir_mensagem", description="Define o texto principal da DM de boas-vindas do evento")
@app_commands.describe(mensagem="Texto que aparece no corpo da DM. Use \\n para quebrar linha.")
async def definir_mensagem(interaction: discord.Interaction, mensagem: str):
    if not tem_cargo_admin(interaction):
        embed = discord.Embed(description="❌ Você não tem permissão.", color=COR_ERRO)
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    texto = mensagem.replace("\\n", "\n")
    salvar_dm_mensagem(texto)

    # Mostra prévia real do embed que será enviado
    preview = discord.Embed(
        title="🎬  Bem-vindo ao CineRevo 2026!",
        description=texto,
        color=0xF5C518
    )
    preview.add_field(name="⏱️  Meta de tempo", value="Fique **1 hora** na call para ganhar o emblema.", inline=False)
    preview.add_field(name="🔄  Tempo acumulado", value="Pode sair e voltar! O tempo é somado automaticamente.", inline=False)
    preview.set_footer(text="CineRevo 2026  •  Boa sessão! 🍿")

    confirmacao = discord.Embed(
        title="✅  Mensagem atualizada!",
        description="Prévia de como vai aparecer na DM:",
        color=COR_SUCESSO
    )
    confirmacao.set_footer(text=f"Alterado por {interaction.user.display_name}")

    await interaction.response.send_message(embeds=[confirmacao, preview], ephemeral=True)


@tree.command(name="ver_mensagem", description="Mostra a prévia da DM atual que será enviada aos participantes")
async def ver_mensagem(interaction: discord.Interaction):
    if not tem_cargo_admin(interaction):
        embed = discord.Embed(description="❌ Você não tem permissão.", color=COR_ERRO)
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    texto = carregar_dm_mensagem()

    preview = discord.Embed(
        title="🎬  Bem-vindo ao CineRevo 2026!",
        description=texto,
        color=0xF5C518
    )
    preview.add_field(name="⏱️  Meta de tempo", value="Fique **1 hora** na call para ganhar o emblema.", inline=False)
    preview.add_field(name="🔄  Tempo acumulado", value="Pode sair e voltar! O tempo é somado automaticamente.", inline=False)
    preview.set_footer(text="CineRevo 2026  •  Boa sessão! 🍿")

    header = discord.Embed(
        title="📨  Prévia da DM atual",
        description="É assim que a mensagem aparece para quem entrar na call:",
        color=COR_ATIVO
    )
    header.set_footer(text="Use /definir_mensagem para alterar o texto")

    await interaction.response.send_message(embeds=[header, preview], ephemeral=True)


# ─── RUN ──────────────────────────────────────────────────────────────────────
TOKEN = os.environ.get("DISCORD_TOKEN")
if not TOKEN:
    raise ValueError("❌ Variável de ambiente DISCORD_TOKEN não definida!")

bot.run(TOKEN)
