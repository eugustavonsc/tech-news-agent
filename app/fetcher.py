import difflib
import logging
import re
import time
import unicodedata

import feedparser
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


_HTML_TAG_RE = re.compile(r"<[^>]+>")

# Substituem o GNews (removido): o free tier dava só 100 req/dia, e com o job
# rodando ~144x/dia a cota esgotava no meio da tarde — confirmado em produção
# em 2026-07-27 (403 "You have reached your request limit for today").
# RSS não tem cota diária nem de rajada.
#
# Testados um a um contra o feed real em 2026-07-27 antes de entrar aqui (ver
# CLAUDE.md): 5 destes 9 vêm com imagem embutida no próprio feed, sem precisar
# de scraper — o article_images.py testado e descartado no bot_instagram só
# conseguiu achar foto extra em 1 de 15 artigos raspando a página do zero.
# Os outros 4 não têm imagem no feed, mas ainda servem o Telegram normalmente
# (send_message aceita image_url=None); só não alimentam a instagram_queue,
# que exige imagem.
RSS_FEEDS = (
    ("Tecnoblog", "https://tecnoblog.net/feed/"),
    ("G1 Tecnologia", "https://g1.globo.com/dynamo/tecnologia/rss2.xml"),
    ("Adrenaline", "https://www.adrenaline.com.br/feed/"),
    ("Mundo Conectado", "https://www.mundoconectado.com.br/feed/"),
    ("GameVicio", "https://www.gamevicio.com/feed/"),
    ("Canaltech", "https://canaltech.com.br/rss/"),
    ("Olhar Digital", "https://olhardigital.com.br/feed/"),
    ("pplware", "https://pplware.sapo.pt/feed/"),
    ("Sapo Tek", "https://tek.sapo.pt/rss"),
)


def _rss_description(entry):
    """Remove marcação HTML do resumo — RSS costuma vir com <p> e afins, e o
    texto vai direto pro prompt do curador/summarizer, que espera texto puro.
    """
    return _HTML_TAG_RE.sub("", entry.get("summary") or "").strip()


def _rss_image(entry):
    """Cada site estrutura a imagem de um jeito diferente no RSS — checa os
    três formatos mais comuns, na ordem de confiabilidade observada testando
    os feeds reais.

    Alguns feeds (visto no Tecnoblog) trazem `media_content` misturando foto
    real, embed de vídeo e ícone de afiliado no mesmo artigo, sem indicar
    qual é qual além do `medium`. Entre os candidatos com `medium="image"`,
    prioriza o de maior largura declarada — o ícone pequeno perde para a foto
    de capa quando o feed informa dimensão; quando não informa, fica na
    ordem em que o site listou (aceitável: o pior caso é a mesma notícia
    sem imagem, não uma imagem errada — o `images.py` do bot_instagram
    rejeita o que for pequeno demais antes de publicar).
    """
    for item in entry.get("media_thumbnail") or ():
        if item.get("url"):
            return item["url"]

    candidatos = [
        m for m in (entry.get("media_content") or ())
        if m.get("medium") == "image" and m.get("url")
    ]
    if candidatos:
        candidatos.sort(key=lambda m: int(m.get("width") or 0), reverse=True)
        return candidatos[0]["url"]

    for enc in entry.get("enclosures") or ():
        if (enc.get("type") or "").startswith("image") and enc.get("href"):
            return enc["href"]

    return None


def _rss_published_iso(entry):
    """ISO 8601, para casar com o formato das outras fontes: fetch_all_news()
    ordena por published_at como string, e RFC 822 puro ("Mon, 27 Jul...")
    não ordena certo comparado a "2026-07-27T..." — o dia da semana na frente
    quebraria a ordenação cronológica."""
    parsed = entry.get("published_parsed")
    if not parsed:
        return entry.get("published")
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", parsed)


def fetch_rss(feed_url, source_name):
    parsed = feedparser.parse(feed_url)
    if parsed.bozo and not parsed.entries:
        logger.warning("Feed RSS inacessível ou malformado: %s (%s)",
                       source_name, feed_url)
        return []

    articles = []
    for entry in parsed.entries:
        url = entry.get("link")
        if not url:
            continue
        articles.append({
            "title": entry.get("title"),
            "description": _rss_description(entry),
            "url": url,
            "source": source_name,
            "published_at": _rss_published_iso(entry),
            "image_url": _rss_image(entry),
        })
    return articles


def fetch_all_rss():
    """Lê todos os feeds de RSS_FEEDS. Falha num feed não derruba os outros —
    mesmo tratamento de isolamento que as outras fontes já têm em
    fetch_all_news(), só que aqui dentro de uma única fonte "lógica"."""
    articles = []
    for source_name, feed_url in RSS_FEEDS:
        try:
            articles.extend(fetch_rss(feed_url, source_name))
        except Exception:
            logger.exception("Falha ao ler feed RSS: %s", source_name)
    return articles


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

    ⚠️ Observado em produção (2026-07-27): as mesmas notícias (sempre as
    últimas da lista) falhavam em toda execução. Causa confirmada no painel
    da FreeNewsApi: o free tier tem **2 requisições/segundo**, separado da
    cota diária de 5000. `FREENEWSAPI_DETAIL_DELAY` espaça as chamadas de
    detalhe pra respeitar isso; sem ele, os últimos itens do lote
    sistematicamente ficavam de fora.
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
            timeout=config.FREENEWSAPI_TIMEOUT,
        )
        response.raise_for_status()
    except requests.RequestException:
        logger.exception("Falha ao listar notícias na FreeNewsApi")
        return []

    listagem = response.json().get("data") or []

    articles = []
    for indice, item in enumerate(listagem):
        uuid = item.get("uuid")
        if not uuid:
            continue

        if indice > 0:
            # Espaça as chamadas pra não estourar rate limit de rajada (ver
            # nota da função) — só entre uma chamada e outra, não antes da
            # primeira.
            time.sleep(config.FREENEWSAPI_DETAIL_DELAY)

        try:
            detalhe = requests.get(
                f"{FREENEWSAPI_BASE}/details",
                headers=headers,
                params={"uuid": uuid},
                timeout=config.FREENEWSAPI_TIMEOUT,
            )
            detalhe.raise_for_status()
        except requests.RequestException as exc:
            # Uma falha pontual (rate limit, artigo removido) não deve
            # derrubar o lote inteiro — só essa notícia fica de fora. O tipo
            # da exceção vai no log porque "falhou" sozinho não diz se foi
            # timeout, 429 ou outra coisa — sem isso, só foi diagnosticável
            # testando a chamada manualmente depois.
            logger.warning("Falha ao buscar detalhes do artigo %s na FreeNewsApi: %s",
                           uuid, exc)
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
    """Busca notícias em NewsAPI, NewsData, os feeds RSS (RSS_FEEDS) e
    FreeNewsApi, e retorna uma lista deduplicada por URL, ordenada da mais
    recente para a mais antiga."""
    sources = (fetch_newsapi, fetch_newsdata, fetch_all_rss, fetch_freenewsapi)

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
