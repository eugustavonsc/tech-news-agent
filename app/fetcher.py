import logging

import requests

from app import config

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 10

TECH_KEYWORDS = (
    "tecnologia", "tech", "inteligência artificial", "software", "hardware",
    "aplicativo", "smartphone", "celular", "internet", "digital", "robô",
    "robótica", "startup", "chip", "semicondutor", "5g", "nuvem",
    "cibersegurança", "cripto", "blockchain", "programação", "algoritmo",
    "telecomunicações", "gadget", "wearable", "realidade virtual",
    "realidade aumentada", "drone", "satélite", "gpu", "nvidia", "wi-fi",
    "wifi", "computador", "notebook", "google", "apple", "microsoft",
    "meta", "amazon", "openai", "deepseek", "nasa", "spacex", "elon musk",
    "quântico",
)


def is_tech_related(article):
    haystack = f"{article.get('title') or ''} {article.get('description') or ''}".lower()
    return any(keyword in haystack for keyword in TECH_KEYWORDS)


def fetch_newsapi():
    if not config.NEWSAPI_ORG_KEY:
        logger.warning("NEWSAPI_ORG_KEY não configurada, pulando NewsAPI.org")
        return []

    response = requests.get(
        "https://newsapi.org/v2/top-headlines",
        params={
            "language": "pt",
            "category": "technology",
            "apiKey": config.NEWSAPI_ORG_KEY,
        },
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    articles = response.json().get("articles", [])

    return [
        {
            "title": a.get("title"),
            "description": a.get("description"),
            "url": a.get("url"),
            "source": (a.get("source") or {}).get("name", "NewsAPI.org"),
            "published_at": a.get("publishedAt"),
        }
        for a in articles
        if a.get("url")
    ]


def fetch_newsdata():
    if not config.NEWSDATA_IO_KEY:
        logger.warning("NEWSDATA_IO_KEY não configurada, pulando NewsData.io")
        return []

    response = requests.get(
        "https://newsdata.io/api/1/news",
        params={
            "language": "pt",
            "category": "technology",
            "apikey": config.NEWSDATA_IO_KEY,
        },
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    articles = response.json().get("results", []) or []

    return [
        {
            "title": a.get("title"),
            "description": a.get("description"),
            "url": a.get("link"),
            "source": a.get("source_id", "NewsData.io"),
            "published_at": a.get("pubDate"),
        }
        for a in articles
        if a.get("link")
    ]


def fetch_gnews():
    if not config.GNEWS_API_KEY:
        logger.warning("GNEWS_API_KEY não configurada, pulando GNews")
        return []

    response = requests.get(
        "https://gnews.io/api/v4/search",
        params={
            "lang": "pt",
            "q": "tecnologia",
            "apikey": config.GNEWS_API_KEY,
        },
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    articles = response.json().get("articles", [])

    return [
        {
            "title": a.get("title"),
            "description": a.get("description"),
            "url": a.get("url"),
            "source": (a.get("source") or {}).get("name", "GNews"),
            "published_at": a.get("publishedAt"),
        }
        for a in articles
        if a.get("url")
    ]


def fetch_all_news():
    """Busca notícias nas três fontes configuradas e retorna uma lista
    deduplicada por URL, ordenada da mais recente para a mais antiga."""
    sources = (fetch_newsapi, fetch_newsdata, fetch_gnews)

    articles = []
    for fetch in sources:
        try:
            articles.extend(fetch())
        except requests.RequestException:
            logger.exception("Falha ao buscar notícias em %s", fetch.__name__)

    seen_urls = set()
    unique_articles = []
    for article in articles:
        if article["url"] in seen_urls:
            continue
        seen_urls.add(article["url"])
        unique_articles.append(article)

    tech_articles = [a for a in unique_articles if is_tech_related(a)]
    tech_articles.sort(key=lambda a: a.get("published_at") or "", reverse=True)
    return tech_articles
