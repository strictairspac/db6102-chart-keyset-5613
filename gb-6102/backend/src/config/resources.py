from redis import Redis
from sqlalchemy import create_engine

from .settings import DATABASE_URL, REDIS_URL

if DATABASE_URL.startswith("sqlite"):
    # 仅本地/验收自测会使用 SQLite 文件库；生产与 compose 仍使用 MySQL。
    engine = create_engine(DATABASE_URL, pool_pre_ping=True, connect_args={"check_same_thread": False})
else:
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)
cache = Redis.from_url(REDIS_URL, socket_connect_timeout=2, socket_timeout=3)
