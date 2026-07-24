from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "fbclid", "gclid", "igshid", "ref", "mc_cid", "mc_eid",
}


def normalize_url(url):
    """Normaliza uma URL para fins de deduplicação: força https, remove a
    barra final do path e descarta parâmetros de tracking conhecidos."""
    parts = urlsplit(url)
    netloc = parts.netloc.lower()
    path = parts.path.rstrip("/") or "/"
    query = urlencode(sorted(
        (k, v) for k, v in parse_qsl(parts.query)
        if k.lower() not in TRACKING_PARAMS
    ))
    return urlunsplit(("https", netloc, path, query, ""))
