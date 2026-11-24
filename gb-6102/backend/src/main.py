import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from scripts.seed_demo import seed, setup_schema
from src.config.settings import SEED_DEMO
from src.domain.scenario import CONFIG
from src.middlewares.errors import catch_errors
from src.middlewares.request_id import request_id
from src.routes import cases, handover, runs, session, system


@asynccontextmanager
async def lifespan(_app):
    setup_schema()
    if SEED_DEMO:
        try:
            seed()
        except Exception:
            logging.getLogger(__name__).exception("Demo seed failed")
    yield


app = FastAPI(title=CONFIG["title"], lifespan=lifespan)
app.middleware("http")(catch_errors)
app.middleware("http")(request_id)
# 最后注册 => 位于最外层：跨源验收脚本/浏览器直连 19251 也可调用，并放行翻页响应头。
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=[
        "X-Credential-Replay", "X-Progress-Pages", "X-Credential",
        "X-Next-Credential", "X-Page-No", "X-Retry-Credential",
    ],
)
for group in (system, session, cases, runs):
    app.include_router(group.router)

# 交班取件接口：主路径为 /handover/batches 与 /batches，
# 同时兼容直接访问后端时带 /api 前缀、以及经 nginx 转发的各种调用口径。
for prefix in ("", "/handover", "/api", "/api/handover"):
    app.include_router(handover.router, prefix=prefix)
