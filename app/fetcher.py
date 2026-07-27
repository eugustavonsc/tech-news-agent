import difflib
import logging
import re
import unicodedata

import requests

from app import config
from app.urls import normalize_url

logger = logging.getLogger(__name__)

TITLE_SIMILARITY_THRESHOLD = 0.85

REQUEST_TIMEOUT = 10

TECH_KEYWORDS = (
    "tecnologia", "tech", "techs", "inteligencia artificial", "software",
    "hardware", "aplicativo", "app", "smartphone", "celular", "internet",
    "digital", "robo", "robotica", "startup", "chip", "semicondutor", "5g",
    "nuvem", "cloud", "ciberseguranca", "cripto", "blockchain",
    "programacao", "algoritmo", "telecomunicacoes", "gadget", "wearable",
    "realidade virtual", "realidade aumentada", "drone", "satelite", "gpu",
    "npu", "wi-fi", "wifi", "computador", "notebook", "quantico",
    "redes neurais", "codigo aberto", "open source", "automacao",
    "humanoide",

    "ia", "llm", "prompt", "chatgpt", "copilot", "gemini", "midjourney",
    "anthropic", "claude", "hugging face",

    "google", "apple", "microsoft", "meta", "amazon", "openai", "deepseek",
    "nasa", "spacex", "elon musk", "nvidia", "samsung", "intel", "amd",
    "tsmc", "tesla", "xiaomi",

    "hacker", "malware", "ransomware", "phishing", "vazamento de dados",
    "data center", "servidor", "linux", "android", "ios", "api",

    "streaming", "smartwatch", "fintech", "deeptech", "e-commerce",
    "big tech",
)


def _strip_accents(text):
    return "".join(
        c for c in unicodedata.normalize("NFD", text)
        if unicodedata.category(c) != "Mn"
    )


_TECH_PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(_strip_accents(k)) for k in TECH_KEYWORDS) + r")\b",
    re.IGNORECASE,
)


def is_tech_related(article):
    haystack = _strip_accents(f"{article.get('title') or ''} {article.get('description') or ''}")
    return bool(_TECH_PATTERN.search(haystack))


def _normalize_title(title):
    text = _strip_accents((title or "").lower())
    text = re.sub(r"[^\w\s]", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _dedupe_similar_titles(articles):
    """Descarta notícias cujo título é quase idêntico ao de outra já
    mantida (conteúdo sindicalizado publicado por fontes diferentes)."""
    kept = []
    kept_norm_titles = []
    for article in articles:
        norm_title = _normalize_title(article.get("title"))
        is_duplicate = any(
            difflib.SequenceMatcher(None, norm_title, kept_title).ratio() >= TITLE_SIMILARITY_THRESHOLD
            for kept_title in kept_norm_titles
        )
        if is_duplicate:
            continue
        kept.append(article)
        kept_norm_titles.append(norm_title)
    return kept


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
            "image_url": a.get("urlToImage"),
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
            "image_url": a.get("image_url"),
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
            "image_url": a.get("image"),
        }
        for a in articles
        if a.get("url")
    ]


FREENEWSAPI_BASE = "https://api.freenewsapi.io/v1"


def fetch_freenewsapi():
    """FreeNewsApi.io: testada no bot_instagram antes de entrar aqui (ver
    CLAUDE.md). Duas pegadinhas que a doc não deixa claro e só apareceram
    testando contra a API real:

    - O código de idioma é `pt-419` (português latino-americano no formato
      IETF), não `pt` puro — este último devolve 400 "Invalid language".
    - A imagem só vem no endpoint `/v1/details`, por UUID; a listagem em
      `/v1/news` só tem título e metadado. Por isso esta função faz uma
      chamada extra por artigo (FREENEWSAPI_MAX_ARTICLES por execução), ao
      contrário das outras três fontes, que trazem tudo numa chamada só.
    """
    if not config.FREENEWSAPI_KEY:
        logger.warning("FREENEWSAPI_KEY não configurada, pulando FreeNewsApi")
        return []

    headers = {"x-api-key": config.FREENEWSAPI_KEY}

    try:
        response = requests.get(
            f"{FREENEWSAPI_BASE}/news",
            headers=headers,
            params={
                "language": "pt-419",
                "country": "BR",
                "topic": "technology",
                "limit": config.FREENEWSAPI_MAX_ARTICLES,
            },
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
    except requests.RequestException:
        logger.exception("Falha ao listar notícias na FreeNewsApi")
        return []

    listagem = response.json().get("data") or []

    articles = []
    for item in listagem:
        uuid = item.get("uuid")
        if not uuid:
            continue

        try:
            detalhe = requests.get(
                f"{FREENEWSAPI_BASE}/details",
                headers=headers,
                params={"uuid": uuid},
                timeout=REQUEST_TIMEOUT,
            )
            detalhe.raise_for_status()
        except requests.RequestException:
            # Uma falha pontual (rate limit, artigo removido) não deve
            # derrubar o lote inteiro — só essa notícia fica de fora.
            logger.warning("Falha ao buscar detalhes do artigo %s na FreeNewsApi", uuid)
            continue

        dados = detalhe.json().get("data") or {}
        url = dados.get("original_url")
        if not url:
            continue

        articles.append({
            "title": dados.get("title") or item.get("title"),
            "description": dados.get("incipit"),
            "url": url,
            "source": dados.get("publisher") or "FreeNewsApi",
            "published_at": dados.get("published_at") or item.get("published_at"),
            "image_url": dados.get("thumbnail"),
        })

    return articles


def fetch_all_news():
    """Busca notícias nas quatro fontes configuradas e retorna uma lista
    deduplicada por URL, ordenada da mais recente para a mais antiga."""
    sources = (fetch_newsapi, fetch_newsdata, fetch_gnews, fetch_freenewsapi)

    articles = []
    for fetch in sources:
        try:
            articles.extend(fetch())
        except requests.RequestException:
            logger.exception("Falha ao buscar notícias em %s", fetch.__name__)

    seen_urls = set()
    unique_articles = []
    for article in articles:
        key = normalize_url(article["url"])
        if key in seen_urls:
            continue
        seen_urls.add(key)
        unique_articles.append(article)

    tech_articles = [a for a in unique_articles if is_tech_related(a)]
    tech_articles.sort(key=lambda a: a.get("published_at") or "", reverse=True)
    return _dedupe_similar_titles(tech_articles)
