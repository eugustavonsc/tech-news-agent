import os
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

DATABASE_URL = os.getenv("DATABASE_URL")

OPENCODER_API_KEY = os.getenv("OPENCODER_API_KEY")
OPENCODER_BASE_URL = os.getenv("OPENCODER_BASE_URL")
MODEL_ID = os.getenv("MODEL_ID", "deepseek-v4-flash")

# Modelo por tarefa, cada um caindo em MODEL_ID quando não configurado.
#
# A cota do OpenCode Go é por modelo, e o mesmo login é usado para revisão de
# código no dia a dia. Aqui a assimetria é grande: o curador roda uma vez por
# execução (~144 vezes/dia, com até CURATOR_CANDIDATE_LIMIT candidatas no prompt)
# e responde por praticamente todo o consumo do projeto, enquanto o summarizer
# roda só para as aprovadas (~7 vezes/dia).
#
# Consequência prática: o curador deve ficar num modelo barato — subi-lo de
# faixa multiplica o gasto por ~10 e passa a competir com a revisão de código.
# O summarizer é grátis na prática e escreve o texto que os inscritos leem, então
# é ele quem vale mover para um modelo melhor.
CURATOR_MODEL_ID = os.getenv("CURATOR_MODEL_ID") or MODEL_ID
SUMMARIZER_MODEL_ID = os.getenv("SUMMARIZER_MODEL_ID") or MODEL_ID

# ⚠️ Só modelos do endpoint /v1/chat/completions: os Qwen e MiniMax do catálogo
# ficam em /v1/messages (formato Anthropic) e não respondem ao cliente `openai`.
#
# O bot_instagram tem um `llm.py` que despacha entre os dois formatos; aqui a
# decisão foi NÃO ter, e o motivo não é preguiça — é que a barreira protege.
# Medido com test_summarizer.py: o `minimax-m3` reconheceu que a notícia era
# fora de tema ("o tema central é administração esportiva, não tecnologia em si")
# e a resumiu assim mesmo, em vez de devolver IRRELEVANTE. Habilitar essa família
# trocaria um erro barulhento de API por um erro editorial mudo — matéria de
# futebol indo para os inscritos e para a instagram_queue.
_MODELOS_FORMATO_ANTHROPIC = (
    "minimax-m3", "minimax-m2.7", "minimax-m2.5",
    "qwen3.7-max", "qwen3.7-plus", "qwen3.6-plus",
)
for _nome, _valor in (("MODEL_ID", MODEL_ID),
                      ("CURATOR_MODEL_ID", CURATOR_MODEL_ID),
                      ("SUMMARIZER_MODEL_ID", SUMMARIZER_MODEL_ID)):
    if _valor in _MODELOS_FORMATO_ANTHROPIC:
        raise RuntimeError(
            f"{_nome}={_valor!r} usa o endpoint /v1/messages (formato Anthropic) "
            "e este projeto só fala /v1/chat/completions. Compatíveis: "
            "deepseek-v4-flash, deepseek-v4-pro, glm-5.1, glm-5.2, kimi-k2.6, "
            "kimi-k2.7-code, kimi-k3, mimo-v2.5, mimo-v2.5-pro, hy3, grok-4.5."
        )

NEWSAPI_ORG_KEY = os.getenv("NEWSAPI_ORG_KEY")
NEWSDATA_IO_KEY = os.getenv("NEWSDATA_IO_KEY")
# GNEWS_API_KEY removido: o free tier só dava 100 req/dia e a cota esgotava
# no meio da tarde com o job rodando ~144x/dia (confirmado em produção em
# 2026-07-27). Substituído pelos feeds RSS em RSS_FEEDS (fetcher.py), que não
# têm cota diária nem de rajada.

FREENEWSAPI_KEY = os.getenv("FREENEWSAPI_KEY")
# Ao contrário das outras três fontes (1 chamada = lista completa com imagem),
# a FreeNewsApi só devolve imagem no /v1/details, por artigo — este é o teto de
# quantos artigos da listagem viram uma segunda chamada por execução. Com o job
# rodando a cada ~10-12 min (~144x/dia), 15 dá ~144 * 16 = 2304 chamadas/dia,
# dentro do free tier (5000/dia) mesmo sem cache entre execuções.
FREENEWSAPI_MAX_ARTICLES = int(os.getenv("FREENEWSAPI_MAX_ARTICLES", "15"))
# Observado em produção (2026-07-27): sem espaçar as chamadas de /v1/details,
# os últimos itens do lote falhavam sistematicamente. Causa confirmada no
# painel da FreeNewsApi: o plano free tem limite de **2 requisições/segundo**
# (diferente da cota diária de 5000). 0.5s = exatamente 2 req/s; a folga é
# pequena de propósito, dá pra subir se ainda estourar.
FREENEWSAPI_DETAIL_DELAY = float(os.getenv("FREENEWSAPI_DETAIL_DELAY", "0.5"))
# Timeout próprio, maior que o REQUEST_TIMEOUT (10s) do fetcher.py: medido
# direto contra a API em 2026-07-27, latência normal ficou em 6-7s mas um pico
# isolado chegou a 22,6s (e apareceu como ReadTimeoutError real em produção,
# no timeout de 10s compartilhado). Separado das outras três fontes para não
# deixar o ciclo inteiro mais tolerante a lentidão só por causa desta.
FREENEWSAPI_TIMEOUT = float(os.getenv("FREENEWSAPI_TIMEOUT", "20"))

MAX_NEWS_PER_RUN = int(os.getenv("MAX_NEWS_PER_RUN", "10"))
RETENTION_DAYS = int(os.getenv("RETENTION_DAYS", "90"))

# Curadoria por LLM antes de resumir e enviar (app/curator.py).
# CURATION_ENABLED=false volta ao comportamento antigo sem precisar de deploy —
# é o kill switch caso a curadoria fique restritiva ou barulhenta demais.
CURATION_ENABLED = os.getenv("CURATION_ENABLED", "true").lower() not in ("false", "0", "no")

# Teto de notícias aprovadas por execução. Com o job rodando a cada ~10 min,
# 2 por execução já é bem mais que o volume que os inscritos aguentam — na
# prática a maioria das execuções aprova 0 ou 1.
MAX_APPROVED_PER_RUN = int(os.getenv("MAX_APPROVED_PER_RUN", "3"))

# Quantas candidatas a curadoria avalia por execução. As que sobram do lote não
# são tocadas e voltam a ser avaliadas na execução seguinte.
CURATOR_CANDIDATE_LIMIT = int(os.getenv("CURATOR_CANDIDATE_LIMIT", "80"))

# Janela em que um assunto já enviado bloqueia notícias parecidas.
DUPLICATE_LOOKBACK_HOURS = float(os.getenv("DUPLICATE_LOOKBACK_HOURS", "48"))
