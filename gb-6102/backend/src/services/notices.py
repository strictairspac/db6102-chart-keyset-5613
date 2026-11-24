from datetime import date
from time import time

from fastapi import HTTPException
from sqlalchemy import select

from src.models.notices import chart_notices
from src.services.audit import record

MAX_NOTICES = 1000


def serialize(row):
    data = dict(row)
    issue = data.get("issue_date")
    if isinstance(issue, date):
        data["issue_date"] = issue.isoformat()
    data["withdrawn"] = data.get("withdrawn_at") is not None
    return data


def list_entries(db, include_withdrawn=False):
    stmt = select(chart_notices).order_by(
        chart_notices.c.issue_date.desc(), chart_notices.c.seq.desc()
    ).limit(MAX_NOTICES)
    rows = [serialize(r) for r in db.execute(stmt).mappings()]
    if not include_withdrawn:
        rows = [r for r in rows if not r["withdrawn"]]
    return rows


def get(db, seq, include_withdrawn=True):
    row = db.execute(
        select(chart_notices).where(chart_notices.c.seq == seq)
    ).mappings().first()
    if row is None or (not include_withdrawn and row["withdrawn_at"] is not None):
        raise HTTPException(404, "勘误簿中没有这条记录")
    return serialize(row)


def _validate_seq(value):
    if type(value) is not int or not 1 <= value <= 2147483647:
        raise HTTPException(422, "收录流水号 seq 须为 1–2147483647 的整数")
    return value


def _validate_issue_date(value):
    try:
        parsed = date.fromisoformat(value)
    except (ValueError, TypeError) as exc:
        raise HTTPException(422, "签发日 issue_date 须为 YYYY-MM-DD") from exc
    if parsed.year < 1970:
        raise HTTPException(422, "签发日不能早于 1970 年")
    return parsed


def _validate_text(field, value, limit, label):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise HTTPException(422, f"{label}须为 1–{limit} 字的非空文本")
    return value


def validate_payload(data, partial=False):
    if not isinstance(data, dict):
        raise HTTPException(422, "请求内容须为 JSON 对象")
    values = {}
    if "seq" in data or not partial:
        values["seq"] = _validate_seq(data.get("seq"))
    if "issue_date" in data or not partial:
        values["issue_date"] = _validate_issue_date(data.get("issue_date"))
    if "chart" in data or not partial:
        values["chart"] = _validate_text("chart", data.get("chart"), 24, "海图编号")
    if "notice" in data or not partial:
        values["notice"] = _validate_text("notice", data.get("notice"), 140, "勘误原文")
    return values


def upsert(db, data, actor):
    """签发新件 / 补录旧件都走这里；同 seq 幂等覆盖并恢复已撤回件。"""
    values = validate_payload(data)
    now = int(time())
    seq = values["seq"]
    existing = db.execute(
        select(chart_notices.c.seq).where(chart_notices.c.seq == seq)
    ).first()
    values.update({"withdrawn_at": None, "updated_at": now})
    if existing is None:
        db.execute(chart_notices.insert().values(**values, created_at=now))
        action = "notice_create"
    else:
        db.execute(chart_notices.update().where(chart_notices.c.seq == seq).values(**values))
        action = "notice_upsert"
    record(db, action, actor, "notice", seq)
    return get(db, seq, include_withdrawn=True)


def update(db, seq, data, actor):
    _validate_seq(seq)
    get(db, seq, include_withdrawn=True)
    values = validate_payload(data, partial=True)
    if "seq" in values and values["seq"] != seq:
        raise HTTPException(422, "不能通过修改路径更改收录流水号")
    values.pop("seq", None)
    if values:
        values["updated_at"] = int(time())
        db.execute(chart_notices.update().where(chart_notices.c.seq == seq).values(**values))
    record(db, "notice_edit", actor, "notice", seq)
    return get(db, seq, include_withdrawn=True)


def set_withdrawn(db, seq, withdrawn, actor):
    get(db, seq, include_withdrawn=True)
    now = int(time())
    db.execute(
        chart_notices.update().where(chart_notices.c.seq == seq).values(
            withdrawn_at=now if withdrawn else None, updated_at=now
        )
    )
    record(db, "notice_withdraw" if withdrawn else "notice_restore", actor, "notice", seq)
    return get(db, seq, include_withdrawn=True)


def reset_demo(db, actor, bulletins):
    """验收辅助：把演示 5 件恢复为开演状态，不触碰交班批。"""
    now = int(time())
    for row in bulletins:
        values = {
            "issue_date": date.fromisoformat(row["issue_date"]),
            "chart": row["chart"],
            "notice": row["notice"],
            "withdrawn_at": None,
            "updated_at": now,
        }
        existing = db.execute(
            select(chart_notices.c.seq).where(chart_notices.c.seq == row["seq"])
        ).first()
        if existing is None:
            db.execute(chart_notices.insert().values(seq=row["seq"], created_at=now, **values))
        else:
            db.execute(chart_notices.update().where(chart_notices.c.seq == row["seq"]).values(**values))
    record(db, "notice_reset", actor, "notice", 0)
    return list_entries(db)
