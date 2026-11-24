from sqlalchemy import BigInteger, Column, Date, Integer, String, Table

from .base import metadata

# 海图勘误簿（在线原件）。开批时把当时的原文与排序复制进 handover_items，
# 此后本表改签发日、撤回原件、补录旧件都不影响已经开出的批次。
chart_notices = Table(
    "chart_notices", metadata,
    Column("seq", Integer, primary_key=True, autoincrement=False),
    Column("issue_date", Date, nullable=False, index=True),
    Column("chart", String(24), nullable=False),
    Column("notice", String(140), nullable=False),
    # 撤回采用软删除：列表默认不返回，审计与恢复仍有凭据。
    Column("withdrawn_at", BigInteger, nullable=True),
    Column("created_at", BigInteger, nullable=False),
    Column("updated_at", BigInteger, nullable=False),
)
