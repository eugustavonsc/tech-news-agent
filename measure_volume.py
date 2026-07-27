"""Sonda pra medir, com dado real, se CURATOR_CANDIDATE_LIMIT e RETENTION_DAYS
ainda fazem sentido depois do RSS ter multiplicado o volume de candidatas
("GNews substituído por feeds RSS").

Só lê — não publica, não marca nada como enviado, não altera o banco.
Rode em horários diferentes ao longo de alguns dias pra ter amostra real
antes de decidir mudar os dois parâmetros (mesma lição de "observar antes de
confiar" já aplicada ao MAX_APPROVED_PER_RUN).

    python measure_volume.py
"""

import sys

import psycopg2

from app import config, database
from app.fetcher import fetch_all_news

_reconfigure = getattr(sys.stdout, "reconfigure", None)
if _reconfigure:
    _reconfigure(encoding="utf-8", errors="replace")


def _linhas_desde(cur, horas):
    cur.execute(
        "SELECT COUNT(*) FROM sent_news WHERE sent_at > NOW() - %s * INTERVAL '1 hour'",
        (horas,),
    )
    return cur.fetchone()[0]


def main():
    conn = psycopg2.connect(config.DATABASE_URL)
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM sent_news")
    total = cur.fetchone()[0]
    ultima_1h = _linhas_desde(cur, 1)
    ultimas_24h = _linhas_desde(cur, 24)
    conn.close()

    print("=== sent_news (crescimento da tabela) ===")
    print(f"total de linhas hoje: {total}")
    print(f"novas na última 1h: {ultima_1h}  (~{ultima_1h * 24} projetado/dia nesse ritmo)")
    print(f"novas nas últimas 24h: {ultimas_24h}")
    print(f"RETENTION_DAYS atual: {config.RETENTION_DAYS} dias -> "
          f"~{ultimas_24h * config.RETENTION_DAYS} linhas acumuladas nesse ritmo")

    print("\n=== candidatas por ciclo (agora, snapshot único) ===")
    artigos = fetch_all_news()
    print(f"total buscado (fetch_all_news, todas as fontes): {len(artigos)}")

    novas = [a for a in artigos if not database.is_sent(a["url"])]
    database.close_pool()

    print(f"genuinamente novas (ainda não em sent_news): {len(novas)}")
    print(f"CURATOR_CANDIDATE_LIMIT atual: {config.CURATOR_CANDIDATE_LIMIT}")
    if len(novas) > config.CURATOR_CANDIDATE_LIMIT:
        sobra = len(novas) - config.CURATOR_CANDIDATE_LIMIT
        print(f"⚠️  {sobra} candidata(s) ficariam de fora deste ciclo "
              "(avaliadas só no(s) próximo(s))")
    else:
        print("dentro do limite — o curador veria todas as novas neste ciclo")


if __name__ == "__main__":
    main()
