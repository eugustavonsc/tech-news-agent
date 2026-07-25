import logging
import time

from app import config, curator, database
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


def _curate(new_articles):
    """Aplica a curadoria ao lote e devolve só as notícias aprovadas.

    As reprovadas são marcadas como processadas (sem título, ver mark_sent) para
    não voltarem na próxima execução, 10 minutos depois. As candidatas além de
    CURATOR_CANDIDATE_LIMIT ficam intactas e são avaliadas depois.
    """
    if not config.CURATION_ENABLED:
        logger.warning("CURATION_ENABLED=false — enviando sem curadoria")
        return new_articles[: config.MAX_NEWS_PER_RUN]

    candidates = new_articles[: config.CURATOR_CANDIDATE_LIMIT]
    if not candidates:
        return []

    approved, rejected, motivo = curator.select(
        candidates, database.recent_sent_titles()
    )
    logger.info(
        "Curadoria: %d aprovada(s), %d reprovada(s) de %d candidatas — %s",
        len(approved), len(rejected), len(candidates), motivo,
    )

    for article in rejected:
        database.mark_sent(article["url"])
        logger.info("Reprovado na curadoria: %s", article["url"])

    return approved


def _enqueue_for_instagram(article, summary):
    """Enfileira a notícia para o bot do Instagram. Nunca deve interromper o
    fluxo do Telegram: notícia sem imagem é ignorada (o Instagram exige imagem)
    e qualquer falha é apenas logada."""
    image_url = article.get("image_url")
    if not image_url:
        return
    try:
        database.enqueue_instagram(
            url=article["url"],
            title=article["title"],
            summary=summary,
            image_url=image_url,
            source=article.get("source"),
        )
    except Exception:
        logger.exception("Falha ao enfileirar para o Instagram: %s", article["url"])


def main():
    database.init_db()
    removed = database.cleanup_old_news()
    if removed:
        logger.info("%d notícias antigas removidas do banco (retenção de %d dias)", removed, config.RETENTION_DAYS)

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
    logger.info("%d notícias novas (ainda não processadas)", len(new_articles))

    new_articles = _curate(new_articles)
    logger.info("%d notícias a enviar", len(new_articles))

    for article in new_articles:
        try:
            summary = format_news_with_llm(build_raw_text(article))
            if summary == IRRELEVANT_MARKER:
                database.mark_sent(article["url"])
                logger.info("Descartado (irrelevante): %s", article["url"])
                continue
            for chat_id in subscribers:
                send_message(summary, chat_id=chat_id, image_url=article.get("image_url"))
            # Só aqui o título é gravado: marca que a notícia foi realmente
            # entregue, e é o que alimenta o dedupe de assunto da curadoria.
            database.mark_sent(article["url"], article.get("title"))
            logger.info("Enviado a %d inscritos: %s", len(subscribers), article["url"])
            _enqueue_for_instagram(article, summary)
        except Exception:
            logger.exception("Falha ao processar notícia: %s", article["url"])
        time.sleep(SECONDS_BETWEEN_MESSAGES)

    database.close_pool()


if __name__ == "__main__":
    main()
