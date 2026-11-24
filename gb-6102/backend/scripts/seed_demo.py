import json
from datetime import date
from time import time

from sqlalchemy import func, select

from migrations.v001_workbench import upgrade as upgrade_v1
from migrations.v002_handover import upgrade as upgrade_v2
from src.config.resources import engine
from src.config.settings import DEMO_PASSWORD
from src.constants.roles import Role
from src.domain.scenario import BULLETIN, FIXTURES
from src.models.cases import cases
from src.models.notices import chart_notices
from src.models.users import users
from src.utils.passwords import hash_password


def insert_new(db, table, key, values):
    # Portable insert-if-absent: startup seeding must never overwrite mutations,
    # including across service restarts (handover progress lives in the database).
    exists = db.execute(select(table.c[key]).where(table.c[key] == values[key])).first()
    if exists is None:
        db.execute(table.insert().values(**values))


def setup_schema():
    with engine.begin() as db:
        upgrade_v1(db)
        upgrade_v2(db)


def seed_notices(db):
    now = int(time())
    for row in BULLETIN:
        insert_new(db, chart_notices, "seq", {
            "seq": row["seq"],
            "issue_date": date.fromisoformat(row["issue_date"]),
            "chart": row["chart"],
            "notice": row["notice"],
            "withdrawn_at": None,
            "created_at": now,
            "updated_at": now,
        })


def seed():
    with engine.begin() as db:
        existing = set(db.execute(select(users.c.username)).scalars())
        for role in Role:
            if role.value not in existing:
                insert_new(db, users, "username", {
                    "username": role.value, "role": role.value, "password_hash": hash_password(DEMO_PASSWORD),
                })
        # 两位交班员场景的第二个操作员账号（口令仍为演示统一口令）。
        if "operator2" not in existing:
            insert_new(db, users, "username", {
                "username": "operator2", "role": Role.OPERATOR.value,
                "password_hash": hash_password(DEMO_PASSWORD),
            })
        for fixture in FIXTURES:
            insert_new(db, cases, "code", {**fixture, "created_by": "seed"})
        seed_notices(db)
        return {table.name: db.scalar(select(func.count()).select_from(table)) for table in (users, cases, chart_notices)}


if __name__ == "__main__":
    setup_schema()
    print(json.dumps(seed(), sort_keys=True))
