"""End-to-end semantics check for the handover feature on SQLite."""
import os
import sys
import tempfile

_tmp = tempfile.mkdtemp(prefix="gb6102-verify-")
db_path = os.path.join(_tmp, "verify.db")
os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"
os.environ["JWT_SECRET"] = "verify-secret"
os.environ["DEMO_PASSWORD"] = "Demo-DbWorkbench-2026"
os.environ["SEED_DEMO"] = "false"
os.environ["REDIS_URL"] = "redis://127.0.0.1:6399/0"

BACKEND = "/workspace/gb-6102/backend"
sys.path.insert(0, BACKEND)
os.chdir(BACKEND)

from fastapi.testclient import TestClient  # noqa: E402

from scripts.seed_demo import seed, setup_schema  # noqa: E402
setup_schema()
seed()

from src.main import app  # noqa: E402

client = TestClient(app)
PASS = []


def check(name, cond, extra=""):
    if not cond:
        print(f"FAIL: {name} {extra}")
        sys.exit(1)
    PASS.append(name)
    print(f"ok: {name}")


def login(u):
    r = client.post("/auth/login", json={"username": u, "password": "Demo-DbWorkbench-2026"})
    check(f"login {u}", r.status_code == 200, r.text)
    return r.json()["token"]


op = login("operator")
rv = login("reviewer")
H_OP = {"Authorization": f"Bearer {op}"}
H_RV = {"Authorization": f"Bearer {rv}"}

# 1. seeded ledger order
r = client.get("/notices")
seqs = [n["seq"] for n in r.json()]
check("ledger seeded 101-105 in desc composite order", seqs == [105, 104, 103, 102, 101], str(seqs))

# 2. operator opens batch size 2
r = client.post("/handover/batches", json={"page_size": 2}, headers=H_OP)
check("open batch 200", r.status_code == 200, r.text)
b = r.json()
bid = b["id"]
check("open snapshot total=5 pages=3 progress0",
      b["total"] == 5 and b["total_pages"] == 3 and b["claimed_count"] == 0 and b["completed_at"] is None, str(b))
c1 = b["next_credential"]
check("open gives page1 credential", isinstance(c1, str) and c1.count(".") == 2)
check("owner is operator", b["owner"] == "operator")

# 3. claim page 1
r = client.post(f"/handover/batches/{bid}/claim", json={"credential": c1}, headers=H_OP)
p1 = r.json()
check("claim c1 -> page1 [105,104]", [i["seq"] for i in p1["items"]] == [105, 104], r.text)
check("progress after p1 =2 / pages1", p1["claimed_count"] == 2 and p1["claimed_pages"] == 1)
c2 = p1["next_credential"]
check("replay header 0", r.headers.get("X-Credential-Replay") == "0")

# 4. mutate the live errata book: change date, withdraw, backfill + new issue
r = client.patch("/notices/104", json={"issue_date": "2020-01-01"}, headers=H_OP)
check("patch issue date", r.status_code == 200 and r.json()["issue_date"] == "2020-01-01", r.text)
r = client.delete("/notices/103", headers=H_OP)
check("withdraw 103", r.status_code == 200 and r.json()["withdrawn"] is True)
r = client.post("/notices", json={"seq": 106, "issue_date": "2026-11-24", "chart": "CN-12311",
                                  "notice": "新增通航浮标"}, headers=H_OP)
check("new issue 106", r.status_code == 200)
r = client.post("/notices", json={"seq": 107, "issue_date": "2026-11-21", "chart": "CN-12311",
                                  "notice": "补录北港灯塔弧区"}, headers=H_OP)
check("backfill old 107", r.status_code == 200)
live_seqs = [n["seq"] for n in client.get("/notices").json()]
check("live book now has 106,107 and hides 103/104 moved", live_seqs == [106, 105, 107, 102, 101, 104], str(live_seqs))

# 5. retry original credential c1 -> identical page, no extra progress
r = client.post(f"/handover/batches/{bid}/claim", json={"credential": c1}, headers=H_OP)
p1r = r.json()
check("retry c1 same items", [i["seq"] for i in p1r["items"]] == [105, 104])
check("retry c1 same original text", p1r["items"][1]["issue_date"] == "2026-11-23"
      and p1r["items"][1]["notice"] == "东锚地界线北移")
check("retry header replay=1", r.headers.get("X-Credential-Replay") == "1")
check("retry does not add progress", p1r["claimed_count"] == 2 and p1r["claimed_pages"] == 1,
      f"{p1r['claimed_count']}/{p1r['claimed_pages']}")
check("replay_count incremented", p1r.get("replay_count") == 1, str(p1r.get("replay_count")))

# 6. continue with c2: frozen page2 must still contain withdrawn 103 and 102
r = client.post(f"/handover/batches/{bid}/claim", json={"credential": c2}, headers=H_OP)
p2 = r.json()
check("page2 frozen [103,102] even after withdraw", [i["seq"] for i in p2["items"]] == [103, 102], r.text)
check("progress 4", p2["claimed_count"] == 4 and p2["claimed_pages"] == 2)
c3 = p2["next_credential"]

# retry c2 immediately
p2r = client.post(f"/handover/batches/{bid}/claim", json={"credential": c2}, headers=H_OP).json()
check("retry c2 same page", [i["seq"] for i in p2r["items"]] == [103, 102])
check("retry c2 progress still 4", p2r["claimed_count"] == 4 and p2r["claimed_pages"] == 2)

# 7. last page completes with timestamp
p3 = client.post(f"/handover/batches/{bid}/claim", json={"credential": c3}, headers=H_OP).json()
check("page3 [101]", [i["seq"] for i in p3["items"]] == [101])
check("completed + completed_at", p3["completed"] is True and isinstance(p3["completed_at"], int), str(p3))
check("no next credential at end", p3["next_credential"] is None)
detail = client.get(f"/handover/batches/{bid}", headers=H_OP).json()
check("detail persisted completed_at", detail["completed_at"] == p3["completed_at"])

# 8. receipt shows completion time and frozen order
rc = client.get(f"/handover/batches/{bid}/receipt", headers=H_OP).json()
check("receipt frozen order", rc["frozen_order"] == [105, 104, 103, 102, 101], str(rc["frozen_order"]))
check("receipt completed_at present", isinstance(rc["completed_at"], int))
check("receipt has 3 turn records", len(rc["turns"]) >= 3, str(len(rc["turns"])))

# 9. second officer has independent batch/progress
r = client.post("/handover/batches", json={"parameter": 2}, headers=H_RV)  # existing param alias
b2 = r.json()
bid2 = b2["id"]
check("reviewer batch owner", b2["owner"] == "reviewer" and bid2 != bid)
p = client.post(f"/handover/batches/{bid2}/claim", json={"credential": b2["next_credential"]}, headers=H_RV).json()
check("officer2 page1", [i["seq"] for i in p["items"]] == [106, 105], str([i["seq"] for i in p["items"]]))
check("officer2 progress independent=2", p["claimed_count"] == 2)
d1 = client.get(f"/handover/batches/{bid}", headers=H_OP).json()
check("officer1 still completed/5", d1["claimed_count"] == 5 and d1["completed"] is True)

# 10. client-chosen idempotency key semantics
b3 = client.post("/batches", json={"page_size": 2}, headers=H_OP).json()
k1 = "fixed-credential-abc"
a = client.post(f"/batches/{b3['id']}/claim", json={"idempotency_key": k1}).json()
a2 = client.post(f"/batches/{b3['id']}/claim", json={"credential": k1}).json()
check("client key first page", [i["seq"] for i in a["items"]] == [106, 105])
check("same client key replays page", [i["seq"] for i in a2["items"]] == [106, 105])
check("client key progress once", a2["claimed_pages"] == 1 and a2["claimed_count"] == 2,
      f"{a2['claimed_pages']} {a2['claimed_count']}")
k2 = "fixed-credential-def"
a3 = client.post(f"/batches/{b3['id']}/claim",
                 headers={"Idempotency-Key": k2}).json()  # header key, no body
check("header idem key advances page2", [i["seq"] for i in a3["items"]] == [107, 102],
      str([i["seq"] for i in a3["items"]]))

# 11. fault after commit + retry with original credential
b4 = client.post("/handover/batches", json={"page_size": 2}).json()
x1 = client.post(f"/handover/batches/{b4['id']}/claim",
                 json={"credential": b4["next_credential"]}).json()
cx2 = x1["next_credential"]
fr = client.post(f"/handover/batches/{b4['id']}/claim",
                 json={"credential": cx2, "simulate_failure": True})
check("fault call returns 500", fr.status_code == 500, str(fr.status_code))
check("fault response carries retry credential header",
      fr.headers.get("X-Retry-Credential") == cx2)
xr = client.post(f"/handover/batches/{b4['id']}/claim", json={"credential": cx2}).json()
check("post-fault retry same page [107,104]", [i["seq"] for i in xr["items"]] == [107, 102],
      str([i["seq"] for i in xr["items"]]))
check("progress counted exactly one page for that credential",
      xr["claimed_pages"] == 2 and xr["claimed_count"] == 4, str(xr))

# 12. composite keyset cursor style
b5 = client.post("/handover/batches", json={"page_size": 2}).json()
k = client.post(f"/handover/batches/{b5['id']}/claim", json={}).json()
check("empty body claims first page", [i["seq"] for i in k["items"]] == [106, 105])
cur = k["next_cursor"]
k2 = client.post(f"/handover/batches/{b5['id']}/claim", json={"cursor": cur}).json()
check("keyset cursor yields next frozen page", [i["seq"] for i in k2["items"]] == [107, 102],
      str([i["seq"] for i in k2["items"]]))
k2r = client.post(f"/handover/batches/{b5['id']}/claim", json={"cursor": cur}).json()
check("same cursor retries same page", [i["seq"] for i in k2r["items"]] == [107, 102])
check("cursor retry no extra progress", k2r["claimed_count"] == 4, str(k2r["claimed_count"]))

# 13. prefix aliases
r = client.post("/api/handover/batches", json={"page_size": 5})
check("/api/handover prefix works", r.status_code == 200, r.text)
r = client.get("/api/batches")
check("/api/batches prefix works", r.status_code == 200)
r = client.get("/errata")
check("/errata noun alias works", r.status_code == 200 and len(r.json()) == 6)

# 14. restart resilience: dispose pool (simulates new process opening same durable DB)
from src.config.resources import engine
engine.dispose()
after = client.get(f"/handover/batches/{bid}/receipt", headers=H_OP).json()
check("after 'restart' batch still completed", after["status"] == "completed")
check("after 'restart' completed_at kept", isinstance(after["completed_at"], int))
resume = client.post(f"/handover/batches/{bid2}/claim", json={}).json()
# bid2 had page1 claimed; default next should be page2
check("after restart officer2 resumes at page2", resume.get("page_no") == 2, str(resume.get("page_no")))

# 15. open idempotency key
r1 = client.post("/handover/batches", json={"page_size": 3, "idempotency_key": "open-once"}).json()
r2 = client.post("/handover/batches", json={"page_size": 9, "credential": "open-once"}).json()
check("open idempotent same batch", r1["id"] == r2["id"])

print(f"\nALL {len(PASS)} CHECKS PASSED; db={db_path}")
