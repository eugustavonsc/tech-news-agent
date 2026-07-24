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
