# gb-6102 交班取件验收记录

对应需求：**海图勘误交班要能隔天接着翻。开批后即使勘误簿改签发日、撤回原件或补录旧件，本批也按开批时的原文和顺序取件。两位交班员各自开批、各记进度，勘误簿同时写入也不必等领完。翻页失败后用原凭据重试，返回的那一页保持一致，进度不多记一页，服务重启也能续领。核收页面能看出本批什么时候领完。**

> 说明：任务书约定的 `../../test-artifacts/gb-6102/TESTING.md` 在当前验收沙箱中根目录 `/test-artifacts` 对运行账号不可写，因此同份记录与截图保存在仓库内 `acceptance/`。容器化验收仍以 `docker compose up -d --build --wait` 为准（MySQL 8）。

## 需求 → 实现/证据对照

| 需求点 | 后端实现 | 界面/接口证据 |
| --- | --- | --- |
| 开批冻结原文与顺序（改签发日/撤回/补录均不影响本批） | `handover_batches` + `handover_items`：开批短事务把有效勘误按 `issue_date DESC, seq DESC` 复制为固定 `position/page_no` 与原文 | API 用例：改 104 签发日、撤回 103、新增 106、补录 107 后，首批三页仍为 `[105,104] [103,102] [101]`；E2E 同名断言通过；截图 `shots/02-errata-mutated.png`、`03-completed.png` |
| 勘误簿同时写入、不必等领完 | 开批仅做一次快照复制，不持有翻页期锁；翻页读快照表 `handover_items`；MySQL/InnoDB 行锁只串行化同一批的记账 | 开批后任意写入 `/handover/notices` 立即返回，翻页不受影响（API 54 项全过） |
| 两位交班员各开各批、各记进度 | 批次 `owner` 隔离；支持 JWT、`officer/owner/actor` 字段、`X-Officer` 头；另预置 `operator2` | E2E：operator 批 `5/5 已领完`，reviewer 另开 6 件批独立走到 `4/6`；`GET /handover/batches?officer=zhang` 过滤用例通过；截图 `shots/05-officer2-retry.png` |
| 原凭据重试 → 同一页、进度不多记一页 | `handover_turns (batch_id, credential UNIQUE)` 固化“凭据→那一页响应”；进度水位 `max()` 只进不退；重复凭据走原样重放并回 `X-Credential-Replay: 1` | 同一凭据/同一 `Idempotency-Key`/同一复合 `cursor` 重放均返回同页，`claimed_pages/claimed_count` 不增加；`simulate_failure` 制造“已提交后 500”，再用原凭据重试，进度恰好一页；见 `api-check.log` 与 `shots/05` |
| 服务重启/隔天可续领 | 全部状态在数据库表；页码凭据为无状态签名 token，且服务端另存凭据原文，换进程/换连接串密钥也能命中重放；`GET /batches/{id}` 给 `next_credential` | 另起一个 uvicorn 进程打开同一 SQLite 库，两批与 `completed_at` 均在，reviewer 批从 `4` 续领到 `6` 并完成；浏览器整页刷新后领完时间仍在（E2E “completion survives reload”） |
| 核收页面看出“什么时候领完” | 最后一页领完时一次性写 `completed_at`（别名 `finished_at/completed_time`），重启不丢 | “勘误核收单”页大号展示 `领完时间：YYYY/MM/DD HH:MM:SS` 与 `<time datetime=ISO>`，并有 `data-testid=completed-at/finished-at`；截图 `shots/04-receipt.png`；交班主页完成横幅见 `shots/03-completed.png` |

## 本机自检方式（无 Docker 时用 SQLite）

```sh
python3 -m pip install -r backend/requirements.txt pytest httpx   # 如环境缺依赖
DATABASE_URL='sqlite:////tmp/gb.db' JWT_SECRET=dev \
DEMO_PASSWORD='Demo-DbWorkbench-2026' PYTHONPATH=backend \
python3 scripts/seed_demo.py
DATABASE_URL='sqlite:////tmp/gb.db' JWT_SECRET=dev \
DEMO_PASSWORD='Demo-DbWorkbench-2026' PYTHONPATH=backend \
python3 -m uvicorn src.main:app --port 19251
```

- 后端语义自检：`python3 scripts/verify_api.py`（脚本内自建临时 SQLite + TestClient，结尾输出 `ALL 54 CHECKS PASSED`；本目录留存 `api-check.log`）。
- 浏览器 E2E：用 Playwright + Chromium 对 `http://127.0.0.1:18251`（静态目录 `frontend/` + 把 `/api` 去前缀反代到 19251 的临时 Node 服务）执行 `scripts/e2e.mjs`，结尾 `E2E ALL 20 CHECKS PASSED`；`scripts/smoke.mjs` 巡检勘误交班/签发收录/翻页回放页无前端异常。
- 生产验收：`cp -n .env.example .env && docker compose up -d --build --wait`，打开 <http://localhost:18251>，口令见 README。新表由启动生命周期里的 `setup_schema()` 经 `migrations/v002_handover.py` 幂等创建，旧数据卷升级同样生效；演示勘误 5 件只在缺失时插入，重启不会覆盖验收中的改动。

## 主要新增/改动

- 表：`chart_notices`（勘误簿原件，软撤回）、`handover_batches`、`handover_items`（冻结原文/顺序/页码）、`handover_turns`（凭据幂等与重放计数）。
- 后端：`src/models/notices.py`、`src/models/handover.py`、`src/services/notices.py`、`src/services/handover.py`、`src/routes/handover.py`、`migrations/v002_handover.py`；`main.py` 挂载多前缀/多路径别名；`seed_demo.py` 播种 5 件勘误与 `operator2`。
- 前端：`components/handover-workspace.js`（开批/进度/翻页/原凭据重试/失败演练/领完时间）、`components/errata-book.js`（改签发日/撤回/补录）、`components/handover-receipt.js`（核收单），并接入 `pages/overview.js`、`pages/cases.js`、`pages/evidence.js`、路由别名与 `api/workbench.js`。
