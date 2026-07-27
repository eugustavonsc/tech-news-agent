import logging
import time

import requests

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


def _broadcast(summary, image_url, subscribers):
    """Envia a um inscrito por vez, sem deixar a falha de um derrubar os
    demais nem impedir o mark_sent() de rodar depois.

    Incidente real (2026-07-27): um inscrito bloqueou o bot, o envio pra ele
    devolvia 403, a exceção escapava do loop e cancelava o mark_sent() da
    notícia inteira. O processo roda como dyno `worker` na Heroku (main() faz
    uma passada e sai; não é Scheduler — Heroku trata a saída de um worker, mesmo com status 0,
    como crash e reinicia sozinha. Cada reinício reprocessava a mesma notícia
    (nunca marcada em sent_news) e batia de novo no mesmo inscrito bloqueado.
    "Reenviou 3x" era, na prática, um loop de crash-restart, não reenvio
    intencional.

    403 é o sinal do Telegram para "bot bloqueado" ou "removido do chat" —
    continuar tentando esse inscrito pra sempre não tem propósito, então ele
    é removido automaticamente (auto-cura, mesmo espírito do cleanup_old_news).
    """
    for chat_id in subscribers:
        try:
            send_message(summary, chat_id=chat_id, image_url=image_url)
        except requests.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else None
            logger.warning("Falha ao enviar para %s (HTTP %s)", chat_id, status)
            if status == 403:
                database.remove_subscriber(chat_id)
                logger.warning("Inscrito %s removido (bot bloqueado ou expulso)", chat_id)
        except requests.RequestException:
            logger.exception("Falha de rede ao enviar para %s", chat_id)


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
            _broadcast(summary, article.get("image_url"), subscribers)
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
