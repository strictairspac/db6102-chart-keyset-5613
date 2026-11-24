from src.models import handover, notices  # noqa: F401  # Register the tables.
from src.models.base import metadata


def upgrade(connection):
    # Version 2 adds the live errata book and the snapshot/credential handover flow.
    metadata.create_all(connection, tables=[
        notices.chart_notices,
        handover.handover_batches,
        handover.handover_items,
        handover.handover_turns,
    ])
