# 🤖 Tech News Agent

Bot que busca notícias de tecnologia, faz curadoria editorial com um LLM (DeepSeek via OpenCoderGo), resume e posta automaticamente no Telegram para todos os chats inscritos, evitando reenviar notícias já publicadas.

## Como funciona

Execução única por invocação (sem loop contínuo), pensada para rodar via **Heroku Scheduler**:

1. Verifica mensagens novas recebidas pelo bot (`getUpdates`): quem mandou `/start` é registrado como inscrito no Postgres. O `TELEGRAM_CHAT_ID` do `.env` é sempre inscrito automaticamente.
2. Busca notícias em três fontes: [NewsAPI.org](https://newsapi.org), [NewsData.io](https://newsdata.io) e [GNews](https://gnews.io) (filtradas por `pt`/tecnologia).
3. Remove duplicatas: por URL normalizada (ignora `http`/`https`, barra final e parâmetros de tracking como `utm_*`) e por título quase idêntico (conteúdo sindicalizado publicado por fontes diferentes com o mesmo texto). Depois aplica um filtro de palavras-chave (busca por palavra inteira, ignorando acentos) para descartar ruído óbvio antes de gastar chamada de LLM.
4. **Curadoria editorial** (`app/curator.py`): o lote de notícias novas vai *inteiro* para o LLM, que compara as candidatas entre si e aprova no máximo `MAX_APPROVED_PER_RUN`. Ver [Curadoria](#curadoria).
5. Para cada notícia **aprovada**: pede ao LLM um resumo formatado. O gate `IRRELEVANTE` do summarizer segue ativo como segunda rede de segurança.
6. Envia o resumo para todos os chats inscritos — como foto (com a imagem da notícia, quando disponível) ou como texto puro, caso não haja imagem ou a legenda seja longa demais — e marca a URL como enviada no banco.
7. Enfileira a notícia na tabela `instagram_queue`, consumida por um projeto separado. Ver [Integração com o Instagram](#integração-com-o-instagram).
8. Remove do banco os registros de notícias enviadas há mais de `RETENTION_DAYS` dias, para manter o tamanho do Postgres sob controle.

> O dedupe do passo 3 é por string e só pega textos quase idênticos; a mesma notícia contada com palavras diferentes por dois veículos passa. Quem resolve isso é a curadoria do passo 4, que compara semanticamente.

## Curadoria

A curadoria roda **antes** de resumir, usando só o título e a descrição que o fetcher já trouxe. Isso não é detalhe de ordem: resumir uma notícia que vai ser descartada é pagar por trabalho jogado no lixo. Uma chamada de curadoria por execução substitui dezenas de chamadas de resumo, então o custo total de LLM **cai**.

Ela existe porque o filtro de palavras-chave é generoso ("digital", "app", "streaming") e o gate `IRRELEVANTE` deixa passar muito ruído. Numa amostra de 25 notícias realmente enviadas: metade não era tecnologia (reembolso de aéreas, política internacional, futebol, saúde bucal), havia publieditorial e listicle de afiliado, e um único teste do Starship apareceu **6 vezes** vindo de 6 veículos diferentes.

O LLM recebe as candidatas numeradas e a lista de títulos já enviados nas últimas `DUPLICATE_LOOKBACK_HOURS`, e rejeita:

- o que não é genuinamente tecnologia;
- publieditorial, propaganda, cupom, lista de ofertas e review de afiliado;
- opinião, coluna, entrevista e análise (em vez de fato novo);
- nicho corporativo sem interesse geral (resultado financeiro, fusão, troca de executivo);
- texto vago, que só faz sentido para quem abre o link;
- assunto repetido — tanto dentro do lote quanto contra o que já foi enviado.

Medido no lote real de 23 notícias: **23 → 2 (91% cortado)**. Com os dois assuntos aprovados marcados como já enviados, a curadoria migrou para outras duas pautas em vez de repeti-los.

As reprovadas são marcadas como processadas para não voltarem na execução seguinte. **Em caso de falha do LLM, nada é enviado e nada é marcado** — as notícias voltam a ser avaliadas na próxima execução, sem perda.

> **Kill switch:** `CURATION_ENABLED=false` volta ao comportamento anterior (enviar até `MAX_NEWS_PER_RUN` sem curadoria) sem precisar de deploy.

## Integração com o Instagram

A tabela `instagram_queue` guarda título, resumo e URL da imagem das notícias enviadas, para um projeto separado publicá-las no Instagram via API do Buffer. Ela existe porque `sent_news` só guarda a URL: o resumo e a imagem viviam apenas na memória do processo e se perdiam ao fim do job.

Só entram notícias **com imagem** (o Instagram exige uma) e **já aprovadas e entregues** ao Telegram — a curadoria daqui é, portanto, o primeiro filtro do Instagram também. Falha ao enfileirar nunca interrompe o fluxo do Telegram: é registrada no log e o job segue.

A limpeza dessa tabela é feita pelo projeto consumidor, não por `cleanup_old_news()`.

### Inscrições

Qualquer pessoa pode receber as notícias mandando `/start` para o bot no Telegram, e cancelar mandando `/stop` — o efeito só é aplicado na próxima execução do job (não é instantâneo, já que o bot não fica ouvindo em tempo real).

## Estrutura

```
app/
  config.py           # leitura centralizada das variáveis de ambiente
  urls.py              # normalização de URL para deduplicação
  fetcher.py          # busca e agrega notícias das 3 APIs, dedupe (URL e título) e filtro por palavra-chave
  curator.py           # curadoria editorial: escolhe o que merece ser enviado
  summarizer.py        # resume via DeepSeek (OpenCoderGo); marca notícias irrelevantes
  telegram_sender.py   # envia mensagens e sincroniza inscritos via Telegram Bot API
  database.py          # Postgres (pool de conexões): notícias enviadas, inscritos e fila do Instagram
  bot.py                # orquestra o fluxo completo (ponto de entrada)
```

### Tabelas

| Tabela | Conteúdo |
| :--- | :--- |
| `sent_news` | URLs já processadas, para dedupe. A coluna `title` é preenchida **apenas** quando a notícia foi de fato entregue; descarte grava `NULL`. É essa diferença que permite a curadoria listar só o que foi publicado — se um descarte entrasse nessa lista, ela trataria o assunto como "já enviado" e bloquearia uma notícia boa sobre o mesmo tema depois. |
| `subscribers` | Chats inscritos via `/start`. |
| `bot_state` | Offset do `getUpdates`, para não reprocessar mensagens. |
| `instagram_queue` | Fila para o projeto do Instagram (ver seção acima). |

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
| `MAX_NEWS_PER_RUN` | Máximo de notícias por execução quando a curadoria está desligada (padrão: `10`) |
| `RETENTION_DAYS` | Dias de histórico mantidos no `sent_news` antes de ser limpo (padrão: `90`) |
| `CURATION_ENABLED` | Liga a curadoria editorial. `false` volta ao comportamento anterior sem deploy (padrão: `true`) |
| `MAX_APPROVED_PER_RUN` | Máximo de notícias aprovadas pela curadoria por execução (padrão: `2`) |
| `CURATOR_CANDIDATE_LIMIT` | Quantas candidatas a curadoria avalia por execução; as demais ficam para a próxima (padrão: `40`) |
| `DUPLICATE_LOOKBACK_HOURS` | Janela em que um assunto já enviado bloqueia notícias parecidas (padrão: `48`) |

⚠️ **Importante:** o bot só consegue enviar mensagens para chats que já iniciaram contato com ele — o dono precisa mandar `/start` para o bot no Telegram antes da primeira execução (veja [Inscrições](#inscrições)).

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
3. Agende a execução via **Heroku Scheduler** rodando `python -m app.bot`.

O `init_db()` é idempotente (`CREATE TABLE IF NOT EXISTS` e `ADD COLUMN IF NOT EXISTS`), então não há passo manual de migração: basta o deploy.

⚠️ Um deploy reinicia o dyno e pode interromper uma execução em andamento. Se isso acontecer no meio do envio, uma notícia já entregue ao Telegram mas ainda sem `mark_sent` será reenviada na execução seguinte. Prefira fazer o deploy logo depois de uma execução terminar.
