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
