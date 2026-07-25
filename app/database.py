import psycopg2.pool

from app import config
from app.urls import normalize_url

_pool = None


def _get_pool():
    global _pool
    if _pool is None:
        _pool = psycopg2.pool.SimpleConnectionPool(1, 5, config.DATABASE_URL)
    return _pool


class _PooledConnection:
    def __enter__(self):
        self.conn = _get_pool().getconn()
        return self.conn

    def __exit__(self, exc_type, exc, tb):
        if exc_type is None:
            self.conn.commit()
        else:
            self.conn.rollback()
        _get_pool().putconn(self.conn)


def init_db():
    with _PooledConnection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS sent_news (
                url TEXT PRIMARY KEY,
                sent_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS subscribers (
                chat_id BIGINT PRIMARY KEY,
                subscribed_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS bot_state (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        # Coluna adicionada depois da criação original da tabela. ADD COLUMN sem
        # DEFAULT não reescreve a tabela no Postgres, então é instantâneo.
        cur.execute("ALTER TABLE sent_news ADD COLUMN IF NOT EXISTS title TEXT")
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS instagram_queue (
                id SERIAL PRIMARY KEY,
                url TEXT UNIQUE NOT NULL,
                title TEXT NOT NULL,
                summary TEXT NOT NULL,
                image_url TEXT NOT NULL,
                source TEXT,
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                posted_at TIMESTAMP
            )
            """
        )

    if config.TELEGRAM_CHAT_ID:
        add_subscriber(config.TELEGRAM_CHAT_ID)


def add_subscriber(chat_id):
    with _PooledConnection() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO subscribers (chat_id) VALUES (%s) ON CONFLICT (chat_id) DO NOTHING",
            (chat_id,),
        )


def remove_subscriber(chat_id):
    with _PooledConnection() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM subscribers WHERE chat_id = %s", (chat_id,))


def get_subscribers():
    with _PooledConnection() as conn, conn.cursor() as cur:
        cur.execute("SELECT chat_id FROM subscribers")
        return [row[0] for row in cur.fetchall()]


def get_last_update_id():
    with _PooledConnection() as conn, conn.cursor() as cur:
        cur.execute("SELECT value FROM bot_state WHERE key = 'last_update_id'")
        row = cur.fetchone()
        return int(row[0]) if row else None


def set_last_update_id(value):
    with _PooledConnection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO bot_state (key, value) VALUES ('last_update_id', %s)
            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
            """,
            (str(value),),
        )


def is_sent(url):
    with _PooledConnection() as conn, conn.cursor() as cur:
        cur.execute("SELECT 1 FROM sent_news WHERE url = %s", (normalize_url(url),))
        return cur.fetchone() is not None


def mark_sent(url, title=None):
    """Registra a URL como processada, para não reprocessá-la.

    `title` é preenchido **apenas** quando a notícia foi de fato enviada aos
    inscritos. Descarte (irrelevante ou reprovado na curadoria) grava title NULL.
    É essa diferença que permite a recent_sent_titles() listar só o que foi
    publicado de verdade: se um descarte entrasse nessa lista, a curadoria
    trataria o assunto como "já enviado" e bloquearia uma notícia boa sobre o
    mesmo tema mais tarde.
    """
    with _PooledConnection() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO sent_news (url, title) VALUES (%s, %s) ON CONFLICT (url) DO NOTHING",
            (normalize_url(url), title),
        )


def recent_sent_titles(hours=None):
    """Títulos realmente enviados na janela, para a curadoria não repetir assunto."""
    lookback = hours if hours is not None else config.DUPLICATE_LOOKBACK_HOURS
    with _PooledConnection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT title FROM sent_news
            WHERE title IS NOT NULL
              AND sent_at > NOW() - %s * INTERVAL '1 hour'
            ORDER BY sent_at DESC
            LIMIT 60
            """,
            (lookback,),
        )
        return [row[0] for row in cur.fetchall()]


def enqueue_instagram(url, title, summary, image_url, source=None):
    """Guarda o conteúdo já resumido pelo LLM para o bot do Instagram consumir.
    A tabela sent_news só guarda a URL, então sem isso o resumo e a imagem se
    perderiam no fim da execução. A limpeza dessa tabela é feita pelo bot do
    Instagram, não por cleanup_old_news()."""
    with _PooledConnection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO instagram_queue (url, title, summary, image_url, source)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (url) DO NOTHING
            """,
            (normalize_url(url), title, summary, image_url, source),
        )
        return cur.rowcount > 0


def cleanup_old_news(days=None):
    """Remove do sent_news as notícias mais antigas que `days` dias, para
    manter o tamanho do banco sob controle. Retorna quantas linhas caíram."""
    retention_days = days if days is not None else config.RETENTION_DAYS
    with _PooledConnection() as conn, conn.cursor() as cur:
        cur.execute(
            "DELETE FROM sent_news WHERE sent_at < NOW() - %s * INTERVAL '1 day'",
            (retention_days,),
        )
        return cur.rowcount


def close_pool():
    if _pool is not None:
        _pool.closeall()
