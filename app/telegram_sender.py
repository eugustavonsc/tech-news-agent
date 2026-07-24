import logging

import requests

from app import config, database

logger = logging.getLogger(__name__)


def send_message(text, chat_id=None):
    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"
    response = requests.post(
        url,
        json={
            "chat_id": chat_id or config.TELEGRAM_CHAT_ID,
            "text": text,
            "parse_mode": "Markdown",
            "disable_web_page_preview": False,
        },
        timeout=10,
    )
    response.raise_for_status()
    return response.json()


def get_updates(offset=None):
    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/getUpdates"
    params = {"offset": offset} if offset is not None else {}
    response = requests.get(url, params=params, timeout=10)
    response.raise_for_status()
    return response.json().get("result", [])


def sync_subscribers():
    """Consulta mensagens novas recebidas pelo bot e atualiza inscrições:
    /start inscreve, /stop cancela. Avança o offset para não reprocessar."""
    last_update_id = database.get_last_update_id()
    offset = last_update_id + 1 if last_update_id is not None else None
    updates = get_updates(offset)

    max_update_id = last_update_id
    for update in updates:
        update_id = update["update_id"]
        max_update_id = update_id if max_update_id is None else max(max_update_id, update_id)

        message = update.get("message") or {}
        chat_id = (message.get("chat") or {}).get("id")
        text = (message.get("text") or "").strip()

        if not chat_id:
            continue

        if text == "/start":
            database.add_subscriber(chat_id)
            logger.info("Novo inscrito: %s", chat_id)
        elif text == "/stop":
            database.remove_subscriber(chat_id)
            logger.info("Inscrição cancelada: %s", chat_id)

    if max_update_id is not None:
        database.set_last_update_id(max_update_id)
