# 澄锚海道·海图勘误翻页核收

勘误签发和入库顺序可能不同，换页中到达的新单不能让旧单漏领或领两次。

## 业务流程

1. 勘误交班
2. 签发与收录
3. 翻页回放
4. 勘误核收单

MySQL 复合索引按签发日和收录流水号寻址，用固定收录水位隔离后入队的勘误。

澄锚海图发行处用勘误邮件和已经打开的列表交接。相同签发日翻页顺序不固定，前台页发生位移，补录历史签发件又容易混入本轮取件。上游是签发处，发行处核收本轮清单，下游为海图印务台。

08:50 收齐 CN-1124-航标勘误的原始 5 件，09:00 保存收录批，09:02 领首次两件，09:03 新签发 106，09:04 补录 107，09:05 回放三个翻页策略，09:10 核对本轮水位并导出交接。

签发日与流水号均按降序排序，同日按流水号拆开。游标仅读取严格小于最后一条复合键的记录，水位游标再加首屏流水号上界。本次回放用真实 MySQL 表、二级复合索引与分页 SQL，在同一连接中按脚本写入新记录。默认实时 OFFSET 重复 1 件，实时游标混入 1 件，水位游标无异常。模型要求收录流水按追加顺序递增，覆盖插入间歇，不冻结既有记录的编辑或删除。

## 交班取件（开批快照 · 凭据幂等 · 核收时间）

在原有“翻页策略回放”之外，新增可隔天续领的真实交班取件闭环，对应四个验收点：

1. **开批即冻结原文与顺序**：`POST /handover/batches` 把当时有效的勘误簿按 `issue_date DESC, seq DESC` 复制进 `handover_items`（原文、名次、页码一并冻结）。此后对勘误簿改签发日（`PATCH /handover/notices/{seq}`）、撤回原件（`DELETE` 或 `/withdraw`，软撤回）、补录旧件/签发新件（`POST /handover/notices`），都不改变已开批次的任何一页。开批是短事务，翻页期间勘误簿可继续写入，互不等待。
2. **两位交班员各开各批、各记进度**：批次以 `owner` 隔离，登录 JWT、`officer/owner/actor` 字段或 `X-Officer` 头均可标识交班员；另预置 `operator2`（操作员角色，统一演示口令）。`GET /handover/batches?officer=…` 可按人过滤。
3. **原凭据重试，进度不多记一页，重启可续**：开批响应给 `credential`（第一页签名页码凭据）与 `next_credential`。`POST /handover/batches/{id}/claim`（别名 `/turn`、`/pages`、`/next-page` 等；同时支持 `Idempotency-Key` 头、`page_token`、复合 `cursor`、`offset`、`page`）以 `(batch, credential)` 唯一翻页记录固化“凭据 → 那一页”。同一凭据重试原样返回该页（响应头 `X-Credential-Replay: 1`），进度水位只进不退。所有状态在 MySQL 表中，重启后 `GET /batches/{id}` 的 `next_credential` 可继续领。请求体带 `"simulate_failure": true` 会在提交后刻意返回 500，用于演练“服务端已记账、响应丢失”的最难重试。
4. **核收页给出领完时间**：领完最后一页时一次性写入并持久化 `completed_at`（同时给别名 `finished_at`）。“勘误核收单”页（`#evidence`，兼容 `#receipt/{id}`）展示大号“领完时间”、冻结清单、进度与每条凭据的重放次数；“勘误交班”页领完后也有同一时间横幅。

接口同时挂在 `/handover/...`、根路径 `/batches`、`/notices`（别名 `/errata`、`/bulletins`）以及 `/api`、`/api/handover` 前缀下，便于不同调用口径。所有接口允许演示环境匿名/带头调用；带 JWT 时以登录名为默认交班员。

## 启动

```sh
cp -n .env.example .env
docker compose config --quiet
docker compose up -d --build --wait
```

打开 <http://localhost:18251>。OpenAPI 在 <http://localhost:19251/docs>，数据库映射到本机 17751。所有暴露端口只绑定回环地址。Compose 启动 frontend、backend、worker、db、redis，各自通过健康探针检查。数据库、Redis 和共享产物目录各有命名卷；任务状态及导出内容以数据库中的证据为准。

首次启动时幂等载入演示数据。手动载入可运行 `docker compose exec -T backend python -m scripts.seed_demo`。常规停止可用 `docker compose down`。验收环境清理才加 `-v`，它会删除本项目的数据卷。

## 角色与交接

演示账号共用口令 `Demo-DbWorkbench-2026`。

| 登录名 | 角色 | 可执行操作 |
|---|---|---|
| operator | 资料操作员 | 登记业务资料、设置「每页条数」、提交、查看和下载结果 |
| reviewer | 业务复核员 | 查看执行证据、签署单次复核、下载交接单 |
| viewer | 只读观察员 | 查看资料、执行结果及审计，下载证据 |

选用「CN-1124-航标勘误」对应的演示资料，保存一份复演资料，再以默认参数 2 提交。worker 保存结果摘要、业务明细和 SHA-256。复核员登录后在「勘误核收单」签署。

## 开发说明

| 部分 | 实现 |
|---|---|
| 前端 | 原生 HTML、CSS、JavaScript ES Modules、Nginx |
| 后端 | Python 3.11、FastAPI、SQLAlchemy、JWT |
| 数据库 | MySQL 8.0 |
| 后台执行 | Redis 通知、数据库持久任务队列和行锁、Python worker |

从 `backend/src/domain/scenario.py` 修改业务入口和演示口径，运行 `docker compose up -d --build --wait` 查看变更。数据库表结构在 `backend/src/models` 和 `backend/migrations`，输入模型在 `backend/src/schemas`。业务页和请求接口在 `frontend/src/pages`、`frontend/src/api`。资料、执行、复核三个工作流实体各有独立表和 API；场景输入及结果保留在所属资料和批次中。

角色枚举在 `backend/src/constants/roles.py`、`frontend/src/constants/roles.js`，用于服务端访问控制、账号初始化、前端导航与签署。批次状态在 `backend/src/constants/job_state.py`、`frontend/src/constants/states.js`，用于队列、状态 API、状态标记与轮询。登记、提交、完成和签署事件写入审计表。

`COMPOSE_PROJECT_NAME` 设置栈名，`FRONTEND_PORT`、`BACKEND_PORT`、`DB_PORT` 设置端口。通过 `DB_PASSWORD`、`JWT_SECRET`、`DEMO_PASSWORD` 配置本地凭据。设置 `SEED_DEMO=false` 可关闭演示数据载入，此时数据库初始没有演示账号。数据库密码调整后，已有数据卷需在数据库内同步修改用户密码。

## 验收范围

验证插入对翻页的影响，默认样本保留原有记录的排序字段。 当前界面用 JSON 编辑业务资料，以 JSON 下载证据。过程和截图保存在批次的 [验收记录](../../test-artifacts/gb-6102/TESTING.md)。

[MIT License](LICENSE)
