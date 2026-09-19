from __future__ import annotations

import atexit
import os
from collections.abc import Iterator
from contextlib import contextmanager

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

DEFAULT_DATABASE_URL = "postgresql:///rpg_platform"
_pool: ConnectionPool | None = None


def database_url() -> str:
    from core.config import database_url_override as _database_url_override
    return (
        os.environ.get("DATABASE_URL")
        or os.environ.get("POSTGRES_URL")
        or _database_url_override()
        or DEFAULT_DATABASE_URL
    )


@contextmanager
def connect() -> Iterator[psycopg.Connection]:
    with get_pool().connection() as db:
        yield db


def get_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        from core.config import db_pool_max as _db_pool_max
        from core.config import db_pool_min as _db_pool_min
        from core.config import db_pool_timeout as _db_pool_timeout
        _pool = ConnectionPool(
            conninfo=database_url(),
            min_size=_db_pool_min(),
            max_size=_db_pool_max(),
            timeout=_db_pool_timeout(),
            kwargs={
                "row_factory": dict_row,
                # 关掉服务端命名预处理语句(psycopg3 默认第 5 次执行后自动 prepare)。
                # 生产走 PgBouncer transaction 模式(见 deploy/pgbouncer.ini):事务结束即把
                # 后端连接还给池,语句名落在的连接随时换人 → 运行几秒后开始随机报
                # `InvalidSqlStatementName: prepared statement "_pg3_N" does not exist`
                # (或 DuplicatePreparedStatement)。而 current_user() 吞异常返 None → 随机 401
                # → 前端 api-client 401 硬跳 Login.html、登录页又见到有效会话跳回来 =
                # 页面每隔几秒「自动刷新」一次。psycopg 官方对连接池的对策就是这一条。
                # 托管池化 Postgres(Supabase/Neon/RDS Proxy 等)同理,故无条件关闭。
                "prepare_threshold": None,
            },
        )
    return _pool


def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


atexit.register(close_pool)
