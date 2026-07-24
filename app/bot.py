import logging
import time

from app import config, database
from app.fetcher import fetch_all_news
from app.summarizer import IRRELEVANT_MARKER, format_news_with_llm
from app.telegram_sender import send_message, sync_subscribers

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

SECONDS_BETWEEN_MESSAGES = 1


def build_raw_text(article):
    return (
        f"Título: {article['title']}\n"
        f"Descrição: {article.get('description') or ''}\n"
        f"Fonte: {article.get('source') or ''}\n"
        f"Link: {article['url']}"
    )


def main():
    database.init_db()
    sync_subscribers()

    subscribers = database.get_subscribers()
    logger.info("%d inscritos", len(subscribers))
    if not subscribers:
        logger.warning("Nenhum inscrito, encerrando sem buscar notícias.")
        database.close_pool()
        return

    articles = fetch_all_news()
    logger.info("%d notícias encontradas", len(articles))

    new_articles = [a for a in articles if not database.is_sent(a["url"])]
    new_articles = new_articles[: config.MAX_NEWS_PER_RUN]
    logger.info("%d notícias novas a enviar", len(new_articles))

    for article in new_articles:
        try:
            summary = format_news_with_llm(build_raw_text(article))
            if summary == IRRELEVANT_MARKER:
                database.mark_sent(article["url"])
                logger.info("Descartado (irrelevante): %s", article["url"])
                continue
            for chat_id in subscribers:
                send_message(summary, chat_id=chat_id, image_url=article.get("image_url"))
            database.mark_sent(article["url"])
            logger.info("Enviado a %d inscritos: %s", len(subscribers), article["url"])
        except Exception:
            logger.exception("Falha ao processar notícia: %s", article["url"])
        time.sleep(SECONDS_BETWEEN_MESSAGES)

    database.close_pool()


if __name__ == "__main__":
    main()
