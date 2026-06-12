# CineRevo 2026 — Bot de Presença

Bot Discord para rastrear tempo de participação no evento CineRevo 2026.

## Comandos

| Comando | Descrição |
|---|---|
| `/iniciar_evento` | Inicia o evento e começa a contar o tempo |
| `/encerrar_evento` | Encerra o evento e para a contagem |
| `/relatorio` | Gera CSV com todos os participantes |
| `/status_evento` | Mostra quantas pessoas estão sendo rastreadas |

> Todos os comandos são **ephemeral** (só o admin que usou o comando vê a resposta).

## Deploy no Railway (gratuito)

1. Cria conta em **railway.app**
2. Clica em **New Project → Deploy from GitHub repo**
3. Sobe esses arquivos no GitHub (bot.py, requirements.txt, Procfile)
4. No Railway, vai em **Variables** e adiciona:
   - `DISCORD_TOKEN` = seu token do bot
5. Clica em **Deploy** — pronto, 24/7!

## Variáveis de ambiente necessárias

| Variável | Valor |
|---|---|
| `DISCORD_TOKEN` | Token do bot (Developer Portal) |

## Estrutura de dados (data.json)

```json
{
  "123456789": {
    "nick": "BryanRX",
    "discord_tag": "bryanrx",
    "total_seconds": 3720,
    "entrou_em": null
  }
}
```