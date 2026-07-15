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
        # _returned primero: si algo falla luego, __del__/__getattr__ no revientan
        self._returned = False
        self._conn = conn

    def __getattr__(self, name):
        # Evita recursion infinita si _conn aun no existe (init a medias)
        if name == "_conn":
            raise AttributeError(name)
        return getattr(self._conn, name)

    def __del__(self):
        # Red de seguridad: si el llamador no llamo a close() -- p.ej. una query
        # que lanzo excepcion antes de llegar a su close() -- devolvemos igual la
        # conexion al pool. Sin esto, cada error de DB fugaba una conexion y a las
        # 10 (maxconn) el chat entero se quedaba sin poder consultar nada.
        try:
            self.close()
        except Exception:
            pass

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
