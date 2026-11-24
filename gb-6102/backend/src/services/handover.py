"""交班取件领域服务。

三条核心口径：

1. 开批即快照：把勘误簿当前有效记录按 ``issue_date DESC, seq DESC`` 的复合顺序
   复制进 handover_items，原文与名次一并冻结；之后勘误簿增删改与本批无关，
   开批事务很短，翻页期间勘误簿可继续写入。
2. 一批一进度：handover_batches 上的水位只进不退，且用 (batch, credential)
   唯一翻页记录做幂等；同一凭据重试返回第一次那一页，进度不会多记一页。
3. 全部状态落在 MySQL（测试可用 SQLite 文件），进程/服务重启后凭 next_credential
   继续领取；领完时一次性写入 completed_at，核收页据此展示领完时间。
"""

import json
from math import ceil
from time import time
from uuid import uuid4

import jwt
from fastapi import HTTPException
from sqlalchemy import select

from src.config.settings import JWT_SECRET
from src.models.handover import handover_batches, handover_items, handover_turns
from src.services.audit import record

OPEN = "open"
COMPLETED = "completed"
_TOKEN_TTL_SECONDS = 10 * 365 * 24 * 3600


# ---------------------------------------------------------------- credentials

def issue_credential(batch_id, page_no):
    return jwt.encode(
        {"typ": "handover-page", "hb": batch_id, "pg": page_no, "exp": int(time()) + _TOKEN_TTL_SECONDS},
        JWT_SECRET, algorithm="HS256",
    )


def parse_credential(token, batch_id):
    """识别本服务签发的页码凭据；客户端自定义幂等键返回 None。"""
    if not isinstance(token, str) or token.count(".") != 2:
        return None
    try:
        claims = jwt.decode(token, JWT_SECRET, algorithms=["HS256"], options={"require": ["hb", "pg"]})
    except jwt.InvalidTokenError:
        return None
    if claims.get("typ") != "handover-page" or claims.get("hb") != batch_id:
        return None
    page_no = claims.get("pg")
    return page_no if type(page_no) is int and page_no >= 1 else None


# ---------------------------------------------------------------- serialization

def _iso(seconds):
    if not seconds:
        return None
    from datetime import datetime, timezone

    return datetime.fromtimestamp(int(seconds), tz=timezone.utc).isoformat()


def serialize_batch(row):
    b = dict(row)
    total_pages = b["total_pages"]
    claimed_pages = b["claimed_pages"]
    next_credential = (
        issue_credential(b["id"], claimed_pages + 1)
        if claimed_pages < total_pages and b["status"] != COMPLETED
        else None
    )
    first_credential = issue_credential(b["id"], 1) if total_pages > 0 else None
    return {
        "id": b["id"],
        "batch_id": b["id"],
        "code": b["code"],
        "owner": b["owner"],
        "officer": b["owner"],
        "actor": b["owner"],
        "page_size": b["page_size"],
        "size": b["page_size"],
        "per_page": b["page_size"],
        # 开批后即可用“原凭据”领取第一页。
        "credential": first_credential,
        "first_credential": first_credential,
        "first_page_token": first_credential,
        "page_token": next_credential if claimed_pages > 0 else first_credential,
        "total": b["total"],
        "total_count": b["total"],
        "total_pages": total_pages,
        "pages": total_pages,
        "claimed_pages": claimed_pages,
        "claimed_count": b["claimed_count"],
        "received_count": b["claimed_count"],
        "received": b["claimed_count"],
        "claimed": b["claimed_count"],
        "status": b["status"],
        "state": b["status"],
        "completed": b["status"] == COMPLETED,
        "finished": b["status"] == COMPLETED,
        "done": b["status"] == COMPLETED,
        "source": b.get("source"),
        "created_at": b["created_at"],
        "opened_at": b["created_at"],
        "updated_at": b["updated_at"],
        "completed_at": b["completed_at"],
        "finished_at": b["completed_at"],
        "completed_time": b["completed_at"],
        "finished_time": b["completed_at"],
        "created_at_iso": _iso(b["created_at"]),
        "completed_at_iso": _iso(b["completed_at"]),
        "finished_at_iso": _iso(b["completed_at"]),
        "next_credential": next_credential,
        "next_page_token": next_credential,
        "progress": {
            "claimed_pages": claimed_pages,
            "claimed_count": b["claimed_count"],
            "total": b["total"],
            "total_pages": total_pages,
            "percent": round(100.0 * b["claimed_count"] / b["total"], 1) if b["total"] else 100.0,
        },
    }


def serialize_item(row):
    item = dict(row)
    issue = item.get("issue_date")
    if hasattr(issue, "isoformat"):
        issue = issue.isoformat()
    return {
        "seq": item["seq"],
        "issue_date": issue,
        "chart": item["chart"],
        "notice": item["notice"],
        "position": item["position"],
        "page_no": item["page_no"],
    }


# ---------------------------------------------------------------- queries

def _get_row(db, batch_id, lock=False):
    stmt = select(handover_batches).where(handover_batches.c.id == batch_id)
    if lock:
        stmt = stmt.with_for_update()
    row = db.execute(stmt).mappings().first()
    if row is None:
        raise HTTPException(404, "交班批不存在，可能尚未开批")
    return row


def get_batch(db, batch_id):
    return serialize_batch(_get_row(db, batch_id))


def list_batches(db, owner=None, limit=100):
    stmt = select(handover_batches).order_by(handover_batches.c.id.desc()).limit(limit)
    rows = [serialize_batch(r) for r in db.execute(stmt).mappings()]
    if owner:
        rows = [r for r in rows if r["owner"] == owner]
    return rows


def _items(db, batch_id):
    rows = db.execute(
        select(handover_items)
        .where(handover_items.c.batch_id == batch_id)
        .order_by(handover_items.c.position)
    ).mappings()
    return [serialize_item(r) for r in rows]


def receipt(db, batch_id):
    batch = get_batch(db, batch_id)
    items = _items(db, batch_id)
    turns = db.execute(
        select(handover_turns)
        .where(handover_turns.c.batch_id == batch_id)
        .order_by(handover_turns.c.id)
    ).mappings().all()
    pages = []
    for page_no in range(1, batch["total_pages"] + 1):
        pages.append({
            "page_no": page_no,
            "items": [item for item in items if item["page_no"] == page_no],
        })
    return {
        **batch,
        "items": items,
        "rows": items,
        "pages": pages,
        "turns": [{
            "credential": t["credential"],
            "page_no": t["page_no"],
            "start_position": t["start_position"],
            "end_position": t["end_position"],
            "replay_count": t["replay_count"],
            "created_at": t["created_at"],
            "last_at": t["last_at"],
        } for t in turns],
        "frozen_order": [item["seq"] for item in items],
    }


# ---------------------------------------------------------------- open

def _normalize_page_size(value):
    if value is None:
        return 2
    if type(value) is not int or isinstance(value, bool) or not 1 <= value <= 500:
        raise HTTPException(422, "每页条数须为 1–500 的整数")
    return value


def open_batch(db, actor, page_size=None, source=None, open_key=None):
    size = _normalize_page_size(page_size)
    now = int(time())

    if open_key:
        existing = db.execute(
            select(handover_batches).where(handover_batches.c.open_key == open_key)
        ).mappings().first()
        if existing is not None:
            return serialize_batch(existing)

    # 开批瞬间的原文与顺序：有效勘误按签发日、流水号双降序（与索引口径一致）。
    from src.models.notices import chart_notices

    notice_rows = db.execute(
        select(chart_notices)
        .where(chart_notices.c.withdrawn_at.is_(None))
        .order_by(chart_notices.c.issue_date.desc(), chart_notices.c.seq.desc())
    ).mappings().all()

    code = f"HB-{uuid4().hex[:12].upper()}"
    is_empty = not notice_rows
    created = db.execute(handover_batches.insert().values(
        code=code, owner=actor, page_size=size,
        total=len(notice_rows), total_pages=ceil(len(notice_rows) / size) if notice_rows else 0,
        claimed_pages=0, claimed_count=0,
        status=COMPLETED if is_empty else OPEN, source=source,
        open_key=open_key, created_at=now, updated_at=now,
        # 空簿子开批即领完，核收页仍给出明确的领完时间。
        completed_at=now if is_empty else None,
    ))
    batch_id = created.inserted_primary_key[0]

    for position, row in enumerate(notice_rows):
        db.execute(handover_items.insert().values(
            batch_id=batch_id, position=position, page_no=position // size + 1,
            seq=row["seq"], issue_date=row["issue_date"], chart=row["chart"], notice=row["notice"],
        ))

    record(db, "handover_open", actor, "handover_batch", batch_id)
    return get_batch(db, batch_id)


# ---------------------------------------------------------------- claim

def _page_payload(batch, items, page_no, start, end, credential, replayed=False, replay_count=0):
    page_items = items[start:end]
    size = batch["page_size"]
    total_pages = batch["total_pages"]
    next_page_no = page_no + 1 if page_no is not None and page_no < total_pages else None
    last = page_items[-1] if page_items else None
    payload = {
        **batch,
        "page": page_no,
        "page_no": page_no,
        "page_number": page_no,
        "start": start,
        "end": end,
        "items": page_items,
        "rows": page_items,
        "records": page_items,
        "credential": credential,
        "page_credential": credential,
        "idempotency_key": credential,
        "next_credential": issue_credential(batch["id"], next_page_no) if next_page_no else None,
        "next_page_token": issue_credential(batch["id"], next_page_no) if next_page_no else None,
        "next_page": next_page_no,
        "next_offset": end if end < batch["total"] else None,
        "has_more": end < batch["total"],
        "next_cursor": {"issue_date": last["issue_date"], "seq": last["seq"]} if last and end < batch["total"] else None,
        "cursor": {"issue_date": last["issue_date"], "seq": last["seq"]} if last else None,
        "replayed": replayed,
        "replay_count": replay_count,
    }
    return payload


def _find_cursor_position(items, cursor):
    if isinstance(cursor, str):
        # 允许 "YYYY-MM-DD:seq" 或纯 seq 的复合游标写法。
        text = cursor.strip()
        if ":" in text:
            day, _, seq_text = text.rpartition(":")
            try:
                seq = int(seq_text)
            except ValueError:
                seq = None
            if seq is not None:
                for i, item in enumerate(items):
                    if item["seq"] == seq and (not day or item["issue_date"] == day):
                        return i
        elif text.isdigit():
            cursor = {"seq": int(text)}
    if isinstance(cursor, dict):
        seq = cursor.get("seq", cursor.get("sequence", cursor.get("s")))
        day = cursor.get("issue_date", cursor.get("day", cursor.get("issueDate", cursor.get("d"))))
        for i, item in enumerate(items):
            if item["seq"] == seq and (day is None or item["issue_date"] == day):
                return i
    raise HTTPException(422, "游标不属于本批冻结清单，无法在原页之后续领")


def _canonical_key(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _replay_turn(db, turn, batch, actor, batch_id, now):
    replay_count = turn["replay_count"] + 1
    db.execute(handover_turns.update().where(handover_turns.c.id == turn["id"]).values(
        replay_count=replay_count, last_at=now
    ))
    record(db, "handover_retry", actor, "handover_batch", batch_id)
    payload = dict(turn["response"])
    # 页内容（items/page/credential）按第一次原样返回；进度状态刷新为当前值，
    # 且本次重试没有写入任何推进值，所以进度不会多记。
    for key in ("status", "state", "completed", "finished", "claimed_pages",
                "claimed_count", "received_count", "progress", "updated_at",
                "completed_at", "finished_at", "completed_at_iso", "finished_at_iso"):
        if key in batch:
            payload[key] = batch[key]
    payload["replayed"] = True
    payload["replay_count"] = replay_count
    return payload, {"X-Credential-Replay": "1", "X-Progress-Pages": str(batch["claimed_pages"])}


def _find_turn(db, batch_id, key):
    if key is None:
        return None
    return db.execute(
        select(handover_turns).where(
            handover_turns.c.batch_id == batch_id,
            handover_turns.c.credential == key,
        )
    ).mappings().first()


def claim(db, batch_id, actor, params):
    """返回 (payload, headers)。调用方负责在事务提交后按 fault 决定是否报 500。"""
    batch_row = _get_row(db, batch_id, lock=True)
    batch = serialize_batch(batch_row)
    items = _items(db, batch_id)
    size = batch["page_size"]
    total = batch["total"]
    now = int(time())

    credential = params.get("credential")
    if credential is not None and not isinstance(credential, str):
        credential = str(credential)
    if credential == "":
        credential = None

    explicit_page = params.get("page")
    offset = params.get("offset")
    cursor = params.get("cursor")

    # 由翻页参数派生稳定的“原凭据”：同一游标/offset/页码重试必须命中同一页。
    derived_key = None
    if credential is None:
        if cursor is not None:
            derived_key = "cursor:" + _canonical_key(cursor)
        elif offset is not None:
            derived_key = f"offset:{offset}"
        elif explicit_page is not None:
            derived_key = f"page:{explicit_page}"

    # 显式页码/页码凭据先解析出来，用于区分“同一页重试”与“同一长期凭据翻到另一页”。
    token_page = parse_credential(credential, batch_id) if credential else None
    requested_page = token_page
    if requested_page is None and explicit_page is not None:
        if type(explicit_page) is not int or isinstance(explicit_page, bool) or explicit_page < 1:
            raise HTTPException(422, "page 须为不小于 1 的整数")
        requested_page = explicit_page

    # 1) 同一凭据（含派生凭据）：原样重放第一次返回的那一页，绝不再次推进进度。
    idem_key = credential or derived_key
    turn = _find_turn(db, batch_id, idem_key)
    if turn is not None:
        same_page = requested_page is None or turn["page_no"] == requested_page
        if same_page:
            return _replay_turn(db, turn, batch, actor, batch_id, now)
        # 同一长期凭据被用于不同显式页码：按页命名空间分别幂等。
        idem_key = f"{idem_key}#page:{requested_page}"
        turn = _find_turn(db, batch_id, idem_key)
        if turn is not None:
            return _replay_turn(db, turn, batch, actor, batch_id, now)

    # 2) 解析本次请求要取的窗口（页码凭据 / 显式页码 / offset / 复合游标 / 默认下一页）。
    target_page = requested_page
    start = None
    end = None

    if target_page is None:
        if offset is not None:
            if type(offset) is not int or isinstance(offset, bool) or offset < 0:
                raise HTTPException(422, "offset 须为不小于 0 的整数")
            start = min(offset, total)
            end = min(start + size, total)
            target_page = start // size + 1 if start < total else batch["total_pages"] or None
        elif cursor is not None:
            pos = _find_cursor_position(items, cursor)
            start = pos + 1
            end = min(start + size, total)
            target_page = (pos + 1) // size + 1 if start < total else batch["total_pages"] or None
        else:
            target_page = batch["claimed_pages"] + 1 if batch["claimed_pages"] < batch["total_pages"] else None

    if total == 0 or target_page is None:
        # 整批已经领完：重放核收终态而不是多造一页。
        terminal_key = idem_key or issue_credential(batch_id, 1)
        payload = _page_payload(batch, items, None, 0, 0, terminal_key, replayed=True)
        payload["message"] = "本批已经领完"
        return payload, {"X-Credential-Replay": "1", "X-Progress-Pages": str(batch["claimed_pages"])}

    if not 1 <= target_page <= batch["total_pages"]:
        raise HTTPException(404, f"本批只有 {batch['total_pages']} 页，没有第 {target_page} 页")

    if start is None:
        start = (target_page - 1) * size
        end = min(target_page * size, total)

    # 3) 推进水位（只进不退；重复/回退页码不重复记账）。
    new_claimed_pages = max(batch["claimed_pages"], target_page)
    new_claimed_count = max(batch["claimed_count"], end)
    completed = new_claimed_count >= total
    completed_at = batch["completed_at"]
    if completed and completed_at is None:
        completed_at = now

    db.execute(handover_batches.update().where(handover_batches.c.id == batch_id).values(
        claimed_pages=new_claimed_pages,
        claimed_count=new_claimed_count,
        status=COMPLETED if completed else OPEN,
        completed_at=completed_at,
        updated_at=now,
    ))
    record(db, "handover_claim", actor, "handover_batch", batch_id)

    updated_row = _get_row(db, batch_id)
    updated_batch = serialize_batch(updated_row)

    # 4) 固化“凭据 -> 这一页”。默认下一页没有入参凭据时，用该页的签名页码凭据，
    #    客户端从响应里拿到它，失败后即可“用原凭据重试”。
    turn_key = idem_key or issue_credential(batch_id, target_page)
    existing = _find_turn(db, batch_id, turn_key)
    if existing is not None:
        return _replay_turn(db, existing, updated_batch, actor, batch_id, now)

    payload = _page_payload(updated_batch, items, target_page, start, end, turn_key)
    db.execute(handover_turns.insert().values(
        batch_id=batch_id, credential=turn_key, page_no=target_page,
        start_position=start, end_position=end, response=payload,
        replay_count=0, created_at=now, last_at=now,
    ))
    return payload, {"X-Credential-Replay": "0", "X-Progress-Pages": str(new_claimed_pages)}
