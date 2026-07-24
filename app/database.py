import psycopg2.pool

from app import config

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
        cur.execute("SELECT 1 FROM sent_news WHERE url = %s", (url,))
        return cur.fetchone() is not None


def mark_sent(url):
    with _PooledConnection() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO sent_news (url) VALUES (%s) ON CONFLICT (url) DO NOTHING",
            (url,),
        )


def close_pool():
    if _pool is not None:
        _pool.closeall()
