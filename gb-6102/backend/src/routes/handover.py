import json
from typing import Optional

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPBearer
from fastapi.responses import JSONResponse

from src.config.resources import engine
from src.config.settings import JWT_SECRET
from src.domain.scenario import BULLETIN
from src.services import handover, notices

router = APIRouter(tags=["Handover"])
bearer = HTTPBearer(auto_error=False)

CREDENTIAL_KEYS = (
    "credential", "page_credential", "pageCredential", "claim_credential",
    "idempotency_key", "idempotencyKey", "idempotency-key",
    "token", "page_token", "pageToken", "key",
)
CREDENTIAL_HEADERS = ("idempotency-key", "x-idempotency-key", "x-credential", "x-page-credential")
PAGE_KEYS = ("page", "page_no", "pageNo", "page_number", "pageNumber", "number")
OFFSET_KEYS = ("offset", "skip")
SIZE_KEYS = ("page_size", "pageSize", "size", "per_page", "perPage", "limit", "parameter")
OFFICER_KEYS = ("owner", "officer", "actor", "username", "operator", "handover_officer", "name")
FAULT_KEYS = ("simulate_failure", "simulateFailure", "fail", "fault", "response_lost")
SOURCE_KEYS = ("source", "case_code", "caseCode", "fixture", "case_id", "caseId")


# ---------------------------------------------------------------- helpers

async def _body(request: Request):
    try:
        raw = await request.body()
        if not raw:
            return {}
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {}


def _pick(body, query, request, names, header_names=()):
    for name in names:
        if name in body and body[name] is not None:
            return body[name]
    for name in names:
        if name in query:
            return query[name]
    for header in header_names:
        value = request.headers.get(header)
        if value:
            return value
    return None


def _as_int(value):
    if value is None or isinstance(value, bool):
        return value if value is None else int(value)
    if isinstance(value, int):
        return value
    text = str(value).strip()
    if text == "":
        return None
    try:
        return int(text)
    except ValueError:
        return value  # 留给服务层报 422


def _truthy(value):
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on", "failed"}


def principal_name(request, credentials, body=None):
    # 显式交班员姓名优先：便于两位交班员用 officer/owner 字段各自开批；
    # 没有显式身份时回退到登录 JWT，再到 x-officer 头与访客。
    if body:
        for key in OFFICER_KEYS:
            value = body.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    header_name = request.headers.get("x-officer") or request.headers.get("x-actor") or request.headers.get("x-user")
    if header_name:
        return header_name.strip()
    if credentials is not None:
        try:
            claims = jwt.decode(
                credentials.credentials, JWT_SECRET, algorithms=["HS256"],
                options={"require": ["sub"]},
            )
            return claims["sub"]
        except jwt.InvalidTokenError:
            pass
    return "guest"


def claim_params(request, body):
    query = request.query_params
    credential = _pick(body, query, request, CREDENTIAL_KEYS, CREDENTIAL_HEADERS)
    cursor = _pick(body, query, request, ("cursor", "page_cursor", "pageCursor", "before"))
    if isinstance(cursor, str):
        text = cursor.strip()
        if text.startswith("{"):
            try:
                cursor = json.loads(text)
            except json.JSONDecodeError:
                pass
    return {
        "credential": credential,
        "page": _as_int(_pick(body, query, request, PAGE_KEYS)),
        "offset": _as_int(_pick(body, query, request, OFFSET_KEYS)),
        "cursor": cursor,
    }


def wants_fault(request, body):
    value = _pick(body, request.query_params, request, FAULT_KEYS, ("x-simulate-failure", "x-fail"))
    return _truthy(value)


# ---------------------------------------------------------------- 勘误簿

@router.get("/notices")
@router.get("/errata")
@router.get("/bulletins")
def list_notices(include_withdrawn: bool = False):
    with engine.connect() as db:
        return notices.list_entries(db, include_withdrawn=include_withdrawn)


@router.post("/notices")
@router.post("/errata")
@router.post("/bulletins")
async def create_notice(request: Request, credentials=Depends(bearer)):
    body = await _body(request)
    actor = principal_name(request, credentials, body)
    with engine.begin() as db:
        return notices.upsert(db, body, actor)


@router.post("/notices/reset-demo")
async def reset_notices(request: Request, credentials=Depends(bearer)):
    body = await _body(request)
    actor = principal_name(request, credentials, body)
    with engine.begin() as db:
        return notices.reset_demo(db, actor, BULLETIN)


@router.get("/notices/{seq}")
@router.get("/errata/{seq}")
def get_notice(seq: int):
    with engine.connect() as db:
        return notices.get(db, seq)


@router.patch("/notices/{seq}")
@router.put("/notices/{seq}")
async def edit_notice(seq: int, request: Request, credentials=Depends(bearer)):
    body = await _body(request)
    actor = principal_name(request, credentials, body)
    with engine.begin() as db:
        return notices.update(db, seq, body, actor)


@router.delete("/notices/{seq}")
async def delete_notice(seq: int, request: Request, credentials=Depends(bearer)):
    actor = principal_name(request, credentials)
    with engine.begin() as db:
        return notices.set_withdrawn(db, seq, True, actor)


@router.post("/notices/{seq}/withdraw")
async def withdraw_notice(seq: int, request: Request, credentials=Depends(bearer)):
    body = await _body(request)
    actor = principal_name(request, credentials, body)
    with engine.begin() as db:
        return notices.set_withdrawn(db, seq, True, actor)


@router.post("/notices/{seq}/restore")
async def restore_notice(seq: int, request: Request, credentials=Depends(bearer)):
    body = await _body(request)
    actor = principal_name(request, credentials, body)
    with engine.begin() as db:
        return notices.set_withdrawn(db, seq, False, actor)


# ---------------------------------------------------------------- 开批 / 进度

@router.get("/batches")
@router.get("/handovers")
def list_batches(request: Request, owner: Optional[str] = None, officer: Optional[str] = None,
                 actor: Optional[str] = None, username: Optional[str] = None,
                 mine: bool = False, credentials=Depends(bearer)):
    principal = principal_name(request, credentials)
    filter_owner = owner or officer or actor or username or (principal if mine else None)
    with engine.connect() as db:
        return handover.list_batches(db, owner=filter_owner)


@router.post("/batches")
@router.post("/batches/open")
@router.post("/handovers")
async def open_batch(request: Request, credentials=Depends(bearer)):
    body = await _body(request)
    actor = principal_name(request, credentials, body)
    size = _as_int(_pick(body, request.query_params, request, SIZE_KEYS))
    source = _pick(body, request.query_params, request, SOURCE_KEYS)
    open_key = _pick(body, request.query_params, request,
                     ("open_credential", "open_key", "idempotency_key", "credential", "key"),
                     CREDENTIAL_HEADERS)
    with engine.begin() as db:
        return handover.open_batch(db, actor, page_size=size, source=str(source) if source else None,
                                   open_key=str(open_key) if open_key else None)


@router.get("/batches/{batch_id}")
@router.get("/batches/{batch_id}/progress")
@router.get("/batches/{batch_id}/status")
@router.get("/handovers/{batch_id}")
def batch_detail(batch_id: int):
    with engine.connect() as db:
        return handover.get_batch(db, batch_id)


@router.get("/batches/{batch_id}/receipt")
@router.get("/batches/{batch_id}/acceptance")
@router.get("/handovers/{batch_id}/receipt")
def batch_receipt(batch_id: int):
    with engine.connect() as db:
        return handover.receipt(db, batch_id)


@router.get("/batches/{batch_id}/pages")
async def get_pages(batch_id: int, request: Request, credentials=Depends(bearer)):
    # 带翻页参数的 GET 同样按“领取这一页”幂等处理；不带参数则返回整批分页目录。
    params = claim_params(request, {})
    if params["credential"] is not None or params["page"] is not None or \
            params["offset"] is not None or params["cursor"] is not None:
        actor = principal_name(request, credentials)
        with engine.begin() as db:
            payload, headers = handover.claim(db, batch_id, actor, params)
        return JSONResponse(payload, headers=headers)
    with engine.connect() as db:
        data = handover.receipt(db, batch_id)
    return {"batch": {k: v for k, v in data.items() if k not in {"items", "rows", "pages", "turns"}},
            "pages": data["pages"]}


# 同一个领取动作挂多组路径别名，兼容“翻页 / turn / next-page”等调用口径。
_CLAIM_PATHS = (
    "/batches/{batch_id}/claim",
    "/batches/{batch_id}/turn",
    "/batches/{batch_id}/turns",
    "/batches/{batch_id}/pages",
    "/batches/{batch_id}/page",
    "/batches/{batch_id}/next",
    "/batches/{batch_id}/next-page",
    "/batches/{batch_id}/receive",
    "/batches/{batch_id}/claim-page",
    "/handovers/{batch_id}/claim",
    "/handovers/{batch_id}/turn",
    "/handovers/{batch_id}/pages",
    "/handovers/{batch_id}/next-page",
)


async def _claim(batch_id: int, request: Request, credentials=Depends(bearer)):
    body = await _body(request)
    actor = principal_name(request, credentials, body)
    params = claim_params(request, body)
    fault = wants_fault(request, body)
    with engine.begin() as db:
        payload, headers = handover.claim(db, batch_id, actor, params)
    headers.update({
        "X-Credential": str(payload.get("credential") or ""),
        "X-Next-Credential": str(payload.get("next_credential") or ""),
        "X-Page-No": str(payload.get("page_no") if payload.get("page_no") is not None else ""),
    })
    if fault:
        # 上面的事务已经提交：刻意制造“服务端已记账、响应却失败”的最难重试场景。
        raise HTTPException(
            status_code=500,
            detail="模拟翻页失败：该页可能已经领取并记账，请用原凭据重试，不要换发新凭据。",
            headers={"X-Retry-Credential": str(payload.get("credential") or "")},
        )
    return JSONResponse(payload, headers=headers)


for _path in _CLAIM_PATHS:
    router.add_api_route(_path, _claim, methods=["POST"], tags=["Handover"])
    if _path.endswith("/claim"):
        router.add_api_route(_path, _claim, methods=["GET"], tags=["Handover"])
