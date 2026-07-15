import psycopg2
import psycopg2.pool
import psycopg2.extensions
import threading

from config.settings import settings

_pool: psycopg2.pool.ThreadedConnectionPool | None = None
_pool_lock = threading.Lock()


def _get_pool() -> psycopg2.pool.ThreadedConnectionPool:
    global _pool
    if _pool is None:
        with _pool_lock:
            if _pool is None:
                _pool = psycopg2.pool.ThreadedConnectionPool(
                    minconn=1,
                    maxconn=10,
                    host=settings.POSTGRES_HOST,
                    port=settings.POSTGRES_PORT,
                    dbname=settings.POSTGRES_DB,
                    user=settings.POSTGRES_USER,
                    password=settings.POSTGRES_PASSWORD,
                    options="-c client_encoding=UTF8",
                )
    return _pool


class _PooledConn:
    """Wrapper transparente: conn.close() devuelve la conexión al pool."""

    def __init__(self, conn):
        self._conn = conn
        self._returned = False

    def __getattr__(self, name):
        return getattr(self._conn, name)

    def close(self):
        if self._returned:
            return
        self._returned = True
        try:
            if not self._conn.closed:
                if self._conn.status == psycopg2.extensions.STATUS_IN_TRANSACTION:
                    self._conn.rollback()
        except Exception:
            pass
        _get_pool().putconn(self._conn)


def get_connection() -> _PooledConn:
    return _PooledConn(_get_pool().getconn())
