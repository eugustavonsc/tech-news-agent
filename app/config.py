import os
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

DATABASE_URL = os.getenv("DATABASE_URL")

OPENCODER_API_KEY = os.getenv("OPENCODER_API_KEY")
OPENCODER_BASE_URL = os.getenv("OPENCODER_BASE_URL")
MODEL_ID = os.getenv("MODEL_ID", "deepseek-v4-flash")

NEWSAPI_ORG_KEY = os.getenv("NEWSAPI_ORG_KEY")
NEWSDATA_IO_KEY = os.getenv("NEWSDATA_IO_KEY")
GNEWS_API_KEY = os.getenv("GNEWS_API_KEY")

MAX_NEWS_PER_RUN = int(os.getenv("MAX_NEWS_PER_RUN", "10"))
RETENTION_DAYS = int(os.getenv("RETENTION_DAYS", "90"))

# Curadoria por LLM antes de resumir e enviar (app/curator.py).
# CURATION_ENABLED=false volta ao comportamento antigo sem precisar de deploy —
# é o kill switch caso a curadoria fique restritiva ou barulhenta demais.
CURATION_ENABLED = os.getenv("CURATION_ENABLED", "true").lower() not in ("false", "0", "no")

# Teto de notícias aprovadas por execução. Com o job rodando a cada ~10 min,
# 2 por execução já é bem mais que o volume que os inscritos aguentam — na
# prática a maioria das execuções aprova 0 ou 1.
MAX_APPROVED_PER_RUN = int(os.getenv("MAX_APPROVED_PER_RUN", "2"))

# Quantas candidatas a curadoria avalia por execução. As que sobram do lote não
# são tocadas e voltam a ser avaliadas na execução seguinte.
CURATOR_CANDIDATE_LIMIT = int(os.getenv("CURATOR_CANDIDATE_LIMIT", "40"))

# Janela em que um assunto já enviado bloqueia notícias parecidas.
DUPLICATE_LOOKBACK_HOURS = float(os.getenv("DUPLICATE_LOOKBACK_HOURS", "48"))
