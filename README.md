# 🤖 Tech News Agent

Bot que busca notícias de tecnologia, resume com um LLM (DeepSeek via OpenCoderGo) e posta automaticamente em um chat do Telegram, evitando reenviar notícias já publicadas.

## Como funciona

Execução única por invocação (sem loop contínuo), pensada para rodar via **Heroku Scheduler** algumas vezes ao dia:

1. Busca notícias em três fontes: [NewsAPI.org](https://newsapi.org), [NewsData.io](https://newsdata.io) e [GNews](https://gnews.io) (filtradas por `pt`/tecnologia).
2. Remove duplicatas por URL e aplica um filtro de palavras-chave para descartar ruído óbvio.
3. Para cada notícia nova (ainda não enviada, conforme o Postgres): pede ao LLM um resumo formatado; se o LLM concluir que não é genuinamente sobre tecnologia, a notícia é descartada.
4. Envia o resumo para o Telegram e marca a URL como enviada no banco.

## Estrutura

```
app/
  config.py           # leitura centralizada das variáveis de ambiente
  fetcher.py          # busca e agrega notícias das 3 APIs, dedupe e filtro por palavra-chave
  summarizer.py        # resume via DeepSeek (OpenCoderGo); marca notícias irrelevantes
  telegram_sender.py   # envia mensagens via Telegram Bot API
  database.py          # Postgres (pool de conexões) para controle de notícias já enviadas
  bot.py                # orquestra o fluxo completo (ponto de entrada)
```

## Variáveis de ambiente

Copie `.env.example` para `.env` e preencha:

| Variável | Descrição |
| :--- | :--- |
| `TELEGRAM_BOT_TOKEN` | Token do bot, gerado pelo @BotFather |
| `TELEGRAM_CHAT_ID` | ID do chat/canal de destino |
| `OPENCODER_API_KEY` | Chave de API da OpenCoderGo |
| `OPENCODER_BASE_URL` | Base URL da API OpenCoderGo |
| `MODEL_ID` | Modelo a ser chamado (ex: `deepseek-v4-flash`) |
| `DATABASE_URL` | URL do PostgreSQL |
| `NEWSAPI_ORG_KEY` | Chave da API NewsAPI.org |
| `NEWSDATA_IO_KEY` | Chave da API NewsData.io |
| `GNEWS_API_KEY` | Chave da API GNews |
| `MAX_NEWS_PER_RUN` | Máximo de notícias enviadas por execução (padrão: `10`) |

⚠️ **Importante:** o bot só consegue enviar mensagens para um chat que já iniciou contato com ele — mande `/start` para o bot no Telegram antes do primeiro envio.

## Rodando localmente

```bash
python -m venv venv
source venv/bin/activate  # Linux/Mac
# venv\Scripts\activate   # Windows

pip install -r requirements.txt
python -m app.bot
```

## Deploy no Heroku

1. Configure as variáveis de ambiente (veja `heroku.txt` para os comandos `heroku config:set`).
2. Adicione o add-on Heroku Postgres.
3. Agende a execução via **Heroku Scheduler** (ex: 3x ao dia) rodando `python -m app.bot`.
