from sqlalchemy import (
    JSON,
    BigInteger,
    Column,
    Date,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    Table,
)

from .base import metadata

# 交班批：两位交班员各开各的批，owner 隔离进度。
handover_batches = Table(
    "handover_batches", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("code", String(48), unique=True, nullable=False),
    Column("owner", String(48), nullable=False, index=True),
    Column("page_size", Integer, nullable=False),
    Column("total", Integer, nullable=False, default=0),
    Column("total_pages", Integer, nullable=False, default=0),
    # 顺序领取的水位：已领到第几页 / 共领多少件（重试同一凭据不会重复推进）。
    Column("claimed_pages", Integer, nullable=False, default=0),
    Column("claimed_count", Integer, nullable=False, default=0),
    Column("status", String(16), nullable=False, default="open", index=True),
    Column("source", String(64), nullable=True),
    # 开批请求本身的幂等凭据（可选）。
    Column("open_key", String(255), nullable=True, unique=True),
    Column("created_at", BigInteger, nullable=False),
    Column("updated_at", BigInteger, nullable=False),
    Column("completed_at", BigInteger, nullable=True),
)

# 开批瞬间冻结的勘误原文与固定顺序（position 即开批时的复合排序名次）。
handover_items = Table(
    "handover_items", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("batch_id", ForeignKey("handover_batches.id"), nullable=False, index=True),
    Column("position", Integer, nullable=False),
    Column("page_no", Integer, nullable=False, index=True),
    Column("seq", Integer, nullable=False),
    Column("issue_date", Date, nullable=False),
    Column("chart", String(24), nullable=False),
    Column("notice", String(140), nullable=False),
    UniqueConstraint("batch_id", "position", name="uq_handover_item_position"),
)

# 翻页凭据 -> 该凭据第一次返回的那一页（原样重放，保证重试结果一致、进度不重复）。
handover_turns = Table(
    "handover_turns", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("batch_id", ForeignKey("handover_batches.id"), nullable=False, index=True),
    Column("credential", String(512), nullable=False),
    Column("page_no", Integer, nullable=True),
    Column("start_position", Integer, nullable=False),
    Column("end_position", Integer, nullable=False),
    Column("response", JSON(none_as_null=True), nullable=False),
    Column("replay_count", Integer, nullable=False, default=0),
    Column("created_at", BigInteger, nullable=False),
    Column("last_at", BigInteger, nullable=False),
    UniqueConstraint("batch_id", "credential", name="uq_handover_turn_credential"),
)
