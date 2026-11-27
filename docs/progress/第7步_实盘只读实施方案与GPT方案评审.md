# 第 7 步实施方案：实盘只读接入（GPT 方案评审 + 落地计划）

> 日期：2026-11-24　｜　基线：`VERSION = 2.5.0.0`
> 评审对象：`docs/plan/OKEworkplace_v2.5下一阶段技术指导方案.docx`（GPT 方案，已归档，SHA256 与附件一致）
> 本轮边界：只做测试版；不写实现代码、不改 `VERSION`、不打包、不动冻结区
> 结论：**采纳 GPT 的 P0 + P1 范围与总体架构，修正 6 处与现状冲突的实现细节，补充 7 处它未掌握的新情况。**

---

## 0. 一句话结论

GPT 方案的**方向与阶段划分正确**（先只读、再风控、后交易），但有几处按当前代码直接落地会出问题：GET 的 token 保护方式、新库未接入备份、30 秒落库的写入量、`margin` 被当成独立端点、签名路径的构造方式、以及 OKX「HTTP 200 + 业务错误码」的校验。下面给出逐条裁决和可直接照做的实施步骤。

---

## 1. 评审方法

逐条对照以下事实源：

| 事实源 | 用途 |
|---|---|
| `backend/app/main.py` | 路由挂载、Host/Origin/token 加固、监听地址 |
| `backend/app/core/config.py` | 配置字段、`.env` 加载顺序、VERSION 读取 |
| `backend/app/services/oke_client.py` | 代理链、certifi、线程内 Session |
| `backend/app/services/backup_service.py` | 备份范围与触发机制 |
| `backend/app/services/maintenance_service.py`、`db_store.py` | 清理范围 |
| `backend/app/services/future_validator.py` | 停机补验与失败重试 |
| `backend/entry_exe.py`、`frontend/index.html` | 本地 token 的生成与前端获取 |
| `backend/app/core/scheduler.py` | 任务注册方式与参数 |

---

## 2. 可直接采纳（无冲突）

| # | GPT 主张 | 判断 | 落地要点 |
|---|---|---|---|
| A1 | 本轮只做 P0 + P1，不碰 P2–P4 | 采纳 | P2 仅做字段预留与需求确认 |
| A2 | 私有客户端与公共 `oke_client.py` 分离 | 采纳 | 新文件 `okx_private_client.py`，独立 Session |
| A3 | P1 只允许固定 GET 白名单，不暴露通用 request | 采纳 | 白名单常量 + 非白名单直接抛错 |
| A4 | 签名 = Base64(HMAC-SHA256(prehash))，prehash = timestamp + 大写 method + requestPath + body | 采纳 | 见 7.1 的精确实现 |
| A5 | timestamp 用 ISO 8601 UTC 毫秒 | 采纳 | 统一 `...SS.mmmZ` |
| A6 | 独立只读 Key、Passphrase、IP 白名单、独立子账户 | 采纳 | 用户侧 P0；不向协作者提供 Key |
| A7 | 独立环境变量命名空间，不复用 `OKE_API_KEY/OKE_SECRET_KEY` | 采纳 | 见 13 节 |
| A8 | 账户摘要/持仓 30 秒、配置低频、成交增量 | 采纳（落库频率修正见 C4） | 内存 30 秒，落库 5 分钟 |
| A9 | GET 只读缓存，不触发 OKX 请求 | 采纳 | 与现有 `/api/v3/mtf` 约定一致 |
| A10 | 失败保留旧数据并标 stale，不得解释为零余额/空仓 | 采纳 | 每个资源独立 `available/stale/reason` |
| A11 | 新增 `live_account.db`，与两张现有库分离 | 采纳（备份需同步接入，见 C3） | 同目录，WAL + busy_timeout |
| A12 | 前端新增「实盘」Tab，与「订单」物理分区 | 采纳 | Tab id `account` |
| A13 | P1 保留原始仓位单位，不做 `ctVal/ctMult` 换算 | 采纳 | `pos_raw` + `pos_unit="contract"` |
| A14 | 错误分类（鉴权/时钟/限频/网络）与有限重试 | 采纳 | 见 7.3 |
| A15 | 不记录 Secret/Passphrase/签名/完整请求头 | 采纳（补充 repr 风险，见 C10） | 只显示 Key 后四位 |
| A16 | 冻结区 diff 必须为空 | 采纳 | 验收命令见 15.3 |

---

## 3. 与现状冲突或技术上需要修正的项

### C1　「account GET 也要 token 校验」与现有全局中间件冲突

- **GPT 说法**：`/api/v3/account/*` 的读取接口同样执行 token 校验。
- **代码事实**：`main.py` 第 63 行只对非 `GET/HEAD/OPTIONS` 校验 token；前端 `index.html` 第 7–8 行从页面 URL 取 token 存到 `window.__OKE_TOKEN`，但现有所有 `fetch` 都不带 header。
- **为什么冲突**：若直接把全局中间件改成「所有方法都校验」，现有 8 个 Tab 的所有 GET 会立即 403，影响行情、分析、绩效、本地订单。
- **以谁为准**：以「不影响现有功能」为准，采纳 GPT 的**意图**，不采纳其**全局做法**。
- **折中方案**：
  1. 全局中间件保持原样；
  2. 在 `routes/account.py` 增加路由级依赖 `require_local_token`，仅作用于 `/api/v3/account/*`；
  3. 新建 `frontend/src/stores/accountStore.js` 统一带 `x-oke-token: window.__OKE_TOKEN`；
  4. `OKE_LOCAL_TOKEN` 未配置时（直接 uvicorn 调试）跳过校验，与现状一致。

### C2　私有 base URL 与现有 `OKE_BASE_URL` 可能出现两个真源

- **GPT 说法**：新增 `OKE_PRIVATE_READ_BASE_URL`。
- **代码事实**：`config.py` 已有 `oke_base_url`，当前 `.env` 指向 `https://www.okx.com`。
- **风险**：两个变量分别配置时，公共行情与私有账户可能打到不同区域域名，表现为「行情正常、账户 401/签名错误」，很难排查。
- **裁决**：保留新变量，但**默认空字符串时继承 `oke_base_url`**；只有显式设置才覆盖。
- **折中**：`.env.example` 中该变量默认留空并注释「留空 = 继承 OKE_BASE_URL」。

### C3　新增 `live_account.db` 不会被现有备份覆盖

- **GPT 说法**：账户库单独设置备份与保留周期。
- **代码事实**：`backup_service.py` 第 25–26 行硬编码两张库的表清单，第 167–168 行只备份 `signals.db` 与 `user_trades.db`，第 151 行只清理这两个前缀。
- **为什么冲突**：不修改备份服务，账户库永远不会被备份，GPT 的「备份/恢复演练」验收无法成立。
- **裁决**：把 `live_account.db` 接入 `BackupService`，作为第三张库；文件不存在时自动跳过（未启用私有接入时无影响）。
- **折中**：不做通用「数据库清单」重构，避免影响现有备份逻辑；只增加一条显式配置，改动面最小。

### C4　30 秒刷新 + 落库会造成每日 2880 行快照

- **GPT 说法**：余额/持仓 30 秒刷新，并写入 `account_snapshots` / `position_snapshots`。
- **容量估算**：30 秒一条，单币持仓快照按 6 个币种计算约 1.7 万行/天；一个月 50 万行，SQLite 可承受但无意义。
- **裁决**：**内存缓存 30 秒，数据库快照 5 分钟**；`account_snapshots` 保留 30 天，`position_snapshots` 保留 30 天，`account_fills` 保留 365 天。
- **折中**：新增配置 `OKE_ACCOUNT_SNAPSHOT_MINUTES=5`、`OKE_ACCOUNT_RETENTION_DAYS=30`；前端仍看到 30 秒级新鲜度。

### C5　`/api/v3/account/margin` 不是 OKX 的独立端点

- **GPT 说法**：把 margin 列为一个账户接口。
- **事实**：OKX 没有单独的「保证金汇总」私有端点；账户级字段来自 `/account/balance`（`totalEq/imr/mmr/mgnRatio`），逐仓字段来自 `/account/positions`（`mgnRatio/liqPx/margin`）。
- **裁决**：保留本地 `GET /api/v3/account/margin`，但明确定义为**派生聚合**，响应里带 `sources` 字段；任一来源缺失则对应字段为 `null`，不猜测、不补零。
- **折中**：P1 不做「风险状态」判定（安全/预警/危险），只展示交易所原始值与来源，避免自创阈值。

### C6　签名路径的构造方式需要写死，不能手工拼 query

- **GPT 说法**：query 属于 requestPath，参数编码顺序要稳定。
- **补充**：实际实现必须用 `requests.Request(...).prepare().path_url` 取得最终路径（含编码后的 query），再参与签名；否则容易出现「签名串与实际 URL 编码不一致」的 50113。
- **裁决**：采纳并写死为唯一实现方式；禁止手工 `urlencode` 后拼接签名。

### C7　必须校验 OKX 的业务返回码（GPT 未提）

- **事实**：OKX 私有接口可能返回 HTTP 200，但 body 为 `{"code":"50111","msg":"..."}`。
- **裁决**：私有客户端必须检查 `payload.get("code") == "0"`，否则抛 `OKXPrivateError(code, msg)`；服务层据此分类降级，绝不能把错误响应当成空数据。
- **影响**：这是防止「Key 失效却显示 0 余额」的关键。

### C8　监听地址：桌面入口是 127.0.0.1，`python -m app.main` 是 0.0.0.0

- **代码事实**：`entry_exe.py` 的 `HOST = "127.0.0.1"`；`main.py` 第 131 行 `uvicorn.run(..., host="0.0.0.0")`。
- **裁决**：桌面/打包路径已符合 GPT 要求；建议在 P1-A 顺手把 `__main__` 的 host 改为 `127.0.0.1`，降低暴露面（非冻结区，一行改动）。
- **折中**：若暂不改代码，验收必须固定用 `entry_exe.py` 或显式 `--host 127.0.0.1`。

### C9　「数据库限制为当前 Windows 用户」不能靠 Python 可移植实现

- **GPT 说法**：数据库与备份应限制为当前 Windows 用户。
- **事实**：需要 `icacls` 或安装器设置 ACL；纯 Python 跨平台做不到。
- **裁决**：不作为代码验收项；写入部署/打包清单，验收时手工执行并记录。示例：
  `icacls "data" /inheritance:r /grant:r "%USERNAME%:(OI)(CI)F"`
- **折中**：P1 至少保证数据目录不在共享盘、`.env` 不入库不出包。

### C10　配置对象的 `repr` 可能泄露新密钥

- **风险**：`Settings` 继承 `pydantic.BaseModel`，直接 `print(settings)` 或日志记录会带出字段值；新增的 Secret/Passphrase 会被打印。
- **裁决**：新字段使用 `pydantic.SecretStr`（或等价屏蔽），并在代码评审中禁止打印整个 settings；现有 `oke_secret_key` 保持不动，避免影响既有逻辑。
- **折中**：状态接口只返回 `key_suffix`（后四位），永不返回 Secret/Passphrase。

### C11　成交增量同步的分页与去重需要具体化

- **GPT 说法**：时间窗口/游标分页，按真实成交 ID 去重。
- **补充**：
  - 端点：`/api/v5/trade/fills-history`，`instType=SWAP`，`limit=100`，用 `begin/end` 毫秒时间窗分页；
  - 首次同步默认回看 7 天（可配置），之后每次从「上次最大 ts − 5 分钟」开始，覆盖边界；
  - 唯一键 `(inst_id, trade_id)`，`INSERT OR IGNORE`；
  - 任一分页失败**不推进游标**，下一轮重试。
- **裁决**：采纳并写死以上细节。

### C12　`account_config_cache` 不需要历史表

- **GPT 说法**：可只保留最新一份，历史按需留档。
- **裁决**：P1 用单行表（`id=1`）即可；不做历史表，避免过度设计。

### C13　P1 不展示「强平距离」等派生风险指标

- **GPT 说法**：P1 风险状态区展示保证金与风险信息。
- **裁决**：P1 只展示交易所原始字段（`mgnRatio/liqPx/lever`）；强平距离、集中度、敞口汇总放到 P2，且必须先完成 `ctVal/ctMult` 归一化。

---

## 4. GPT 未掌握的新情况（2.5.0.0 实际状态）

| # | 事实 | 对方案的影响 |
|---|---|---|
| N1 | `VERSION` 已是 `2.5.0.0` | 本轮不得再改；验收时记录现值即可 |
| N2 | 全局中间件对 GET 不校验 token；前端 token 来自页面 URL | 见 C1，必须用路由级依赖 |
| N3 | 备份是「按运行时长 + 数据签名」触发，不是固定时钟：启动满 5 分钟首跑，之后累计运行满 `backup_runtime_hours`（默认 6）才允许再备份；数据无变化跳过；只保留 3 份 | 新库必须加入签名与清理，否则「备份成功」是假象 |
| N4 | 停机补验已存在：`future_validator.verify_due()` 每轮扫描所有已到期未出结果的预测（每轮上限 200），失败结果超过重试间隔会被清除重验 | 不需要新建「补验回补」逻辑，别重复造 |
| N5 | `order_flow_snapshots` 没有自动清理：`prune_signals()` 只删 `signals` 与 `signal_snapshots` | 应在 P1-D 顺手补保留策略，否则长期运行会膨胀 |
| N6 | `PerformanceCard.js` 已被另一会话重设计；上下文分桶只有后端接口 | 本轮不要动该文件；账户 Tab 独立新建 |
| N7 | 前端 token 注入在 `index.html` 第 7–8 行，`window.__OKE_TOKEN` 可直接读取 | `accountStore.js` 直接复用，无需新增注入机制 |
| N8 | 公共客户端使用线程内 Session 且 `trust_env=False`，代理由 `_build_proxy_attempts()` 显式提供 | 私有客户端应复用代理构建逻辑，但使用**独立 Session**，避免签名头污染公共请求 |
| N9 | 调度任务统一 `max_instances=1`、`coalesce=True`，并设置 `next_run_time` 错峰 | 新任务照此办理，避免启动瞬间并发打满 |
| N10 | `main.py` 已有 Host/Origin 白名单，覆盖所有方法 | 账户 GET 的 Host/Origin 保护已自动生效，只差 token |

---

## 5. 总体架构与阶段

```
OKX 私有 REST（只读 GET 白名单）
        ↑ 签名 / 代理 / TLS / 限频
okx_private_client.py
        ↑
account_service.py  ← APScheduler（30s / 120s / 600s / 6h）
        ↓
account_store.py → live_account.db（WAL）
        ↓
routes/account.py → /api/v3/account/*（只读缓存 + 路由级 token）
        ↓
前端「实盘」Tab（accountStore.js + AccountCard.js）
```

阶段：

| 阶段 | 内容 | 退出条件 |
|---|---|---|
| W0 | 基线审查 | `git status` 清晰、冻结区 diff 为空、现有接口可用 |
| P0 | 用户侧 Key 准备 | 只读子账户 + Passphrase + 固定出口 IP + `.env` |
| P1-A | 私有客户端 | 签名单测、白名单、错误映射通过 |
| P1-B | 存储与服务 | 迁移幂等、缓存降级、成交去重通过 |
| P1-C | 路由与前端 | 实盘 Tab 与 OKX 页面抽样一致 |
| P1-D | 备份、清理、验收 | 备份含新库、撤销 Key 回归、安全扫描通过 |

---

## 6. P0：前置依赖（用户操作，0 代码）

1. 在 OKX 创建独立子账户 `oke-readonly`，只授予「读取」权限，**不授予交易与提现**。
2. 创建 API Key 时保存 **Passphrase**；Key/Secret/Passphrase 只放本机。
3. IP 白名单填**代理出口公网 IP**（不是 `127.0.0.1:12334`）；出口不固定时先解决固定出口。
4. 确认账户注册地区对应的 API 域名，写入 `OKE_PRIVATE_READ_BASE_URL`（留空则继承 `OKE_BASE_URL`）。
5. 开发/测试版 `.env` 放 `backend/.env`；打包版优先 exe 同级 `.env`；真实 `.env` 不入库、不出包、不截图。
6. 确认 Windows 时间同步正常（偏差 > 30 秒会触发 `50102`）。

**P0 验收**：OKX 后台能看到 Key 的只读权限、子账户归属、白名单与最近调用；撤销 Key 不影响主账户。

---

## 7. P1-A：私有只读客户端

### 7.1 新增 `backend/app/services/okx_private_client.py`

**必须实现：**

| 项 | 具体做法 |
|---|---|
| 白名单 | `SIGNED_GET_WHITELIST = {"/api/v5/account/balance", "/api/v5/account/positions", "/api/v5/account/config", "/api/v5/trade/fills-history"}`；其他路径直接抛错 |
| 时间戳 | `datetime.now(timezone.utc)` → `YYYY-MM-DDTHH:MM:SS.mmmZ`（毫秒三位） |
| 签名路径 | `requests.Request("GET", url, params=params).prepare().path_url`，含编码后的 query |
| prehash | `timestamp + "GET" + request_path + ""` |
| 签名 | `base64.b64encode(hmac.new(secret.encode(), prehash.encode(), hashlib.sha256).digest()).decode()` |
| 请求头 | `OK-ACCESS-KEY / OK-ACCESS-SIGN / OK-ACCESS-TIMESTAMP / OK-ACCESS-PASSPHRASE`；Demo 另加 `x-simulated-trading: 1`（P3 才用） |
| 代理 | 复用 `oke_client` 的代理构建逻辑（建议把它提升为公开函数 `build_proxy_attempts()`，或新增 `http_utils.py` 统一导出），按顺序尝试 |
| TLS | `verify=CA_BUNDLE`；**禁止 `verify=False`** |
| Session | 私有客户端自己的 `threading.local()` Session，`trust_env=False` |
| 业务码 | `payload.get("code") != "0"` 抛 `OKXPrivateError(code, msg)` |
| 错误映射 | `50111` Key 无效、`50113` 签名无效、`50114` Passphrase/授权无效、`50102` 时间戳过期、`50011` 限频、`50001/50004` 服务不可用/超时（以官方文档为准） |
| 日志 | 不记录 header、Secret、Passphrase、签名；只记录 path、错误码、耗时 |

**明确不做：** 不提供 `request(method, path, body)` 通用方法；不实现 POST/PUT/DELETE。

### 7.2 配置前置（`config.py` + `.env.example`）

见第 13 节。未配置 Key 时 `is_configured()` 返回 False，调度任务直接跳过，不发起请求。

### 7.3 单测（新增 `backend/tests/test_private_client.py`）

- 固定 timestamp / path / query，断言签名与官方示例一致；
- query 编码顺序与签名路径一致性；
- 非白名单 path 被拒；
- `code != "0"` 抛错并带错误码；
- 毫秒时间戳格式；
- 不把 Secret/Passphrase 写进异常文本。

---

## 8. P1-B：存储与服务

### 8.1 新增 `backend/app/services/account_store.py`

- 数据目录：与 `user_trades.db` 相同（`_db_dir()` 逻辑），文件 `live_account.db`。
- 连接：`WAL` + `busy_timeout=5000` + `synchronous=NORMAL`，事务短小。
- 迁移：只用 `CREATE TABLE IF NOT EXISTS` 与 `CREATE INDEX IF NOT EXISTS`。

表结构见第 11 节。

**方法清单：**

`save_account_snapshot(data)`、`save_position_snapshots(rows)`、`upsert_fills(rows)`、`get_fills(limit, offset, inst_id)`、`save_config(data)`、`get_config()`、`get_state(key)` / `set_state(key, value)`、`last_fill_ts()`、`prune(days)`、`stats()`。

### 8.2 新增 `backend/app/services/account_service.py`

| 方法 | 数据源 | 行为 |
|---|---|---|
| `refresh_summary()` | `/api/v5/account/balance` | 更新内存缓存；每 `snapshot_minutes` 落一条 `account_snapshots` |
| `refresh_positions()` | `/api/v5/account/positions?instType=SWAP` | 更新内存；每 `snapshot_minutes` 落快照 |
| `refresh_config()` | `/api/v5/account/config` | 落单行缓存；失败保留旧值 |
| `sync_fills()` | `/api/v5/trade/fills-history` | 增量拉取 + 去重 + 更新游标 |
| `refresh_all()` | 上述组合 | 供调度调用；单资源失败不影响其他资源 |
| `status()` | 本地 | configured/enabled/key_suffix/各资源 last_success/last_error/stale |
| `prune()` | 本地 | 按保留天数清理快照与成交 |

**降级规则：**

- 未配置 → `available=false, reason="未配置只读 API Key"`，不请求。
- 网络/代理失败 → 保留上一轮内存与库数据，`stale=true`，`reason` 区分「连接失败」。
- 鉴权错误（50111/50113/50114）→ 停止高频重试（退避到 5 分钟），`available=false` 或 `stale=true`，提示检查 Key/Passphrase/时钟。
- 业务错误 → 该资源 `stale=true`，其他资源不受影响。
- 永远不把失败解释为 0 余额或空仓。

### 8.3 调度（`core/scheduler.py`）

仅当 `private_read_enabled` 时注册：

| 任务 | 周期 | 首次运行 | 参数 |
|---|---|---|---|
| `account_refresh` | `account_poll_seconds`（30） | 启动 +15s | `max_instances=1, coalesce=True` |
| `account_fills` | `account_fills_poll_seconds`（120） | 启动 +30s | 同上 |
| `account_config` | `account_config_poll_seconds`（600） | 启动 +20s | 同上 |
| `account_prune` | 6 小时 | 启动 +5min | 同上 |

启动时**不阻塞**：不在 `lifespan` 里同步拉取。

---

## 9. P1-C：路由与前端

### 9.1 新增 `backend/app/routes/account.py`

- 前缀 `/api/v3/account`。
- 路由级依赖 `require_local_token`（见 C1）。
- 六个只读接口，全部只读服务层缓存/本地库：

| 方法 | 路径 | 返回 |
|---|---|---|
| GET | `/status` | 配置状态、各资源新鲜度、错误码、Key 后四位 |
| GET | `/summary` | 权益、可用、占用、未实现盈亏、币种明细 |
| GET | `/positions` | 真实持仓（原始单位）、杠杆、`mgnRatio`、`liqPx` |
| GET | `/margin` | 派生聚合 + `sources`（见 C5） |
| GET | `/fills` | 本地增量成交，支持 `limit/offset/inst_id` |
| GET | `/config` | 账户模式、持仓模式、手续费等级 |

统一响应字段：`available / pending / stale / reason / updated_at / data`。

### 9.2 `main.py`

- `from app.routes import ..., account`；
- `app.include_router(account.router, prefix="", tags=["account"])`；
- 建议把 `__main__` 的 `host` 改为 `127.0.0.1`（C8）。

### 9.3 前端

| 文件 | 改动 |
|---|---|
| `frontend/index.html` | Tab 栏新增 `data-tab="account"`（文案「实盘」）；新增 `#tab-account` 容器 `[data-account]` |
| `frontend/src/main.js` | 初始化 `accountStore` 刷新（15 秒轮询，后端 30 秒）；挂 `window.__okeRefreshAccount` |
| `frontend/src/views/tabManager.js` | 切到 `account` 时立即刷新 |
| `frontend/src/stores/accountStore.js`（新增） | `fetch` 带 `x-oke-token`；状态含 status/summary/positions/margin/fills/config |
| `frontend/src/render/AccountCard.js`（新增） | 状态条、账户摘要、持仓表、保证金区、成交表；stale/未配置/错误提示 |

**界面硬约束：**

- 实盘 Tab 与订单 Tab 并列，**禁止合并持仓数字、盈亏或风险**；
- Key 只显示后四位；
- 原始单位（张）必须展示，标注「交易所原始单位」；
- 未配置/失败时展示原因，不展示 0。

**不改动**：`frontend/src/render/PerformanceCard.js`、`OrderCard.js`。

---

## 10. P1-D：备份、清理与验收

### 10.1 `backup_service.py`

- 表签名增加：`("live_account.db", ("account_snapshots", "position_snapshots", "account_fills", "account_config_cache", "account_sync_state"))`；
- `create_backup()` 增加 `_backup_one("live_account.db", stamp)`（文件不存在返回空串）；
- `_prune()` 增加前缀 `live_account_`；
- 不改「按运行时长 + 数据签名」的现有触发逻辑。

### 10.2 清理

- `account_store.prune()`：快照保留 30 天、成交保留 365 天；
- 顺手补 `order_flow_snapshots` 保留策略（N5）：在 `db_store` 增加 `prune_order_flow(days)`，由现有维护任务或新任务调用，默认 7 天；**这是遗留项，不阻塞 P1，但建议同批完成**。

### 10.3 验收清单

见第 15 节。

---

## 11. 数据表 DDL（`live_account.db`）

```sql
CREATE TABLE IF NOT EXISTS account_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    total_eq REAL, avail_eq REAL, upl REAL,
    imr REAL, mmr REAL, mgn_ratio REAL, ord_frozen REAL,
    details_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_account_snapshots_time ON account_snapshots(created_at);

CREATE TABLE IF NOT EXISTS position_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    inst_id TEXT NOT NULL,
    pos_side TEXT,
    pos_raw REAL,
    pos_unit TEXT NOT NULL DEFAULT 'contract',
    avg_px REAL, mark_px REAL,
    upl REAL, upl_ratio REAL,
    lever REAL, liq_px REAL, mgn_ratio REAL, mgn_mode TEXT,
    raw_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_position_snapshots_inst ON position_snapshots(inst_id, created_at);

CREATE TABLE IF NOT EXISTS account_fills (
    inst_id TEXT NOT NULL,
    trade_id TEXT NOT NULL,
    ord_id TEXT,
    side TEXT, pos_side TEXT,
    px REAL, sz REAL,
    fee REAL, fee_ccy TEXT,
    ts INTEGER NOT NULL,
    raw_json TEXT,
    created_at TEXT NOT NULL,
    PRIMARY KEY (inst_id, trade_id)
);
CREATE INDEX IF NOT EXISTS idx_account_fills_ts ON account_fills(ts);

CREATE TABLE IF NOT EXISTS account_config_cache (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    acct_lv TEXT, pos_mode TEXT, mgn_mode TEXT,
    fee_taker REAL, fee_maker REAL,
    updated_at TEXT NOT NULL,
    raw_json TEXT
);

CREATE TABLE IF NOT EXISTS account_sync_state (
    key TEXT PRIMARY KEY,
    value TEXT,
    updated_at TEXT NOT NULL
);
```

> P2 再通过 `ALTER TABLE position_snapshots ADD COLUMN` 增加 `normalized_base_qty / notional_quote / conversion_status`，不在 P1 预留空列。

---

## 12. 接口契约（示例）

### `/api/v3/account/status`

```json
{
  "available": true,
  "enabled": true,
  "configured": true,
  "key_suffix": "ab12",
  "resources": {
    "summary":   { "available": true,  "stale": false, "updated_at": "2026-11-24T06:00:00+00:00", "error": null },
    "positions": { "available": true,  "stale": false, "updated_at": "2026-11-24T06:00:00+00:00", "error": null },
    "config":    { "available": true,  "stale": false, "updated_at": "2026-11-24T05:50:00+00:00", "error": null },
    "fills":     { "available": true,  "stale": false, "updated_at": "2026-11-24T05:59:00+00:00", "last_sync_ts": 1795500000000, "error": null }
  },
  "updated_at": "2026-11-24T06:00:00+00:00"
}
```

### `/api/v3/account/summary`

```json
{
  "available": true, "stale": false, "reason": null,
  "updated_at": "2026-11-24T06:00:00+00:00",
  "data": {
    "total_eq": 1234.56, "avail_eq": 900.0, "upl": 12.3,
    "imr": 300.0, "mmr": 60.0, "mgn_ratio": 4.2, "ord_frozen": 0.0,
    "details": [
      { "ccy": "USDT", "eq": 1200.0, "avail_bal": 900.0, "frozen_bal": 0.0, "upl": 12.3, "eq_usd": 1200.0 }
    ]
  }
}
```

### `/api/v3/account/positions`

```json
{
  "available": true, "stale": false, "reason": null,
  "updated_at": "2026-11-24T06:00:00+00:00",
  "data": [
    {
      "inst_id": "BTC-USDT-SWAP", "pos_side": "long",
      "pos_raw": 2.0, "pos_unit": "contract",
      "avg_px": 60000.0, "mark_px": 60100.0,
      "upl": 20.0, "upl_ratio": 0.0167,
      "lever": 3.0, "liq_px": 40000.0, "mgn_ratio": 12.5, "mgn_mode": "cross"
    }
  ]
}
```

> `pos_unit="contract"` 是显式声明：P1 不把 `pos_raw` 当币数量；前端标注「张」。

### `/api/v3/account/margin`

```json
{
  "available": true, "stale": false,
  "data": {
    "account": { "total_eq": 1234.56, "imr": 300.0, "mmr": 60.0, "mgn_ratio": 4.2 },
    "positions": [ { "inst_id": "BTC-USDT-SWAP", "mgn_ratio": 12.5, "liq_px": 40000.0 } ]
  },
  "sources": ["/api/v5/account/balance", "/api/v5/account/positions"],
  "display_only": true
}
```

### `/api/v3/account/fills`

```json
{
  "available": true, "stale": false, "total": 1,
  "items": [
    { "inst_id": "BTC-USDT-SWAP", "trade_id": "123", "ord_id": "456",
      "side": "buy", "pos_side": "long", "px": 60000.0, "sz": 1.0,
      "fee": -0.5, "fee_ccy": "USDT", "ts": 1795500000000,
      "ts_iso": "2026-11-24T06:00:00+00:00" }
  ]
}
```

---

## 13. 配置项清单

| 变量 | 默认 | 必填 | 说明 |
|---|---|---|---|
| `OKE_PRIVATE_READ_ENABLED` | `false` | 是 | 关闭时完全不注册任务、不请求 |
| `OKE_PRIVATE_READ_BASE_URL` | 空 | 否 | 空 = 继承 `OKE_BASE_URL` |
| `OKE_PRIVATE_READ_API_KEY` | 空 | 是 | 只读 Key，不复用 `OKE_API_KEY` |
| `OKE_PRIVATE_READ_SECRET_KEY` | 空 | 是 | `SecretStr`，不日志 |
| `OKE_PRIVATE_READ_PASSPHRASE` | 空 | 是 | `SecretStr`，不日志、不回显 |
| `OKE_ACCOUNT_POLL_SECONDS` | `30` | 否 | 摘要/持仓刷新 |
| `OKE_ACCOUNT_FILLS_POLL_SECONDS` | `120` | 否 | 成交增量 |
| `OKE_ACCOUNT_CONFIG_POLL_SECONDS` | `600` | 否 | 账户配置 |
| `OKE_ACCOUNT_SNAPSHOT_MINUTES` | `5` | 否 | 快照落库间隔 |
| `OKE_ACCOUNT_RETENTION_DAYS` | `30` | 否 | 快照保留 |
| `OKE_ACCOUNT_FILLS_RETENTION_DAYS` | `365` | 否 | 成交保留 |
| `OKE_ACCOUNT_FILLS_INITIAL_DAYS` | `7` | 否 | 首次回看窗口 |

同时更新 `backend/.env.example`，真实值只写本机 `.env`。

---

## 14. 调度与线程

- 全部任务 `max_instances=1`、`coalesce=True`；
- 私有客户端内部使用独立 `ThreadPoolExecutor(max_workers=2)` 或直接串行执行（30 秒一轮，两个请求，无需并发）；
- 不挤占行情 5 秒主循环的 16 线程池；
- 账户请求失败退避：连续失败 3 次后指数退避到 5 分钟，恢复后回落。

---

## 15. 测试与验收

### 15.1 自动化

| 测试 | 覆盖 |
|---|---|
| `tests/test_private_client.py` | 签名、query、白名单、业务码、时间格式、错误映射、敏感信息不落异常 |
| `tests/test_account_store.py` | 迁移幂等、成交去重、游标、保留清理 |
| `tests/test_account_service.py` | 部分失败保留旧值、stale、未配置不请求 |
| 路由测试 | token 缺失 403、token 正确 200、GET 不触发外部请求（mock 客户端断言 0 调用） |

### 15.2 手工验收

1. 未配置 Key：启动正常，实盘 Tab 显示「未配置」，行情/订单不受影响。
2. 配置只读 Key：摘要、持仓、保证金、成交与 OKX 网页抽样一致（至少 3 个币种）。
3. 撤销 Key：账户模块降级，其他模块正常。
4. 断网/代理失败：保留旧数据并标 stale，不显示 0。
5. 系统时间调快 60 秒：出现可诊断的时间戳错误提示。
6. 连续刷新本地接口 60 次：后端无新增 OKX 请求（看日志）。
7. 重启两次：迁移幂等，成交不重复。
8. 备份：手动触发一次备份，确认 `live_account_*.db` 存在且可打开。

### 15.3 冻结区与回归

```powershell
git diff --stat -- backend/app/model/market_score.py backend/app/services/signal_engine.py backend/app/services/indicator_service.py backend/app/services/direction_tracker.py backend/app/services/future_validator.py
```

输出必须为空。再回归 8 个 Tab 与 `/api/analysis`、`/api/monitor/snapshot`、`/api/predictions`、`/api/v3/performance/*`。

---

## 16. 实施顺序与取舍理由

| 顺序 | 工作 | 为什么先做 |
|---|---|---|
| 1 | W0 基线审查 | 避免覆盖并行会话改动；先确认冻结区干净 |
| 2 | P1-A 签名客户端 + 单测 | 风险最高、最独立；签名错会浪费大量联调时间 |
| 3 | `live_account.db` + store | 先定数据落点，再写服务，避免边写边改表 |
| 4 | account_service + 调度 | 把外部请求收敛到后台；GET 才能只读缓存 |
| 5 | 路由 + 前端 Tab | 数据链路稳定后再做展示，便于逐项对账 |
| 6 | 备份/清理 + 安全验收 | 最后补齐生命周期，避免「能看但不敢长期跑」 |

**关键取舍：**

- 选独立 `live_account.db` 而不是塞进 `user_trades.db`：账户敏感数据与手工记账物理隔离，删库/备份/权限都能独立处理。
- 选 5 分钟落库而不是 30 秒：30 秒的价值在「看」，不在「存」；落库只用于回溯与对账。
- 选路由级 token 而不是全局：不破坏现有 GET，满足敏感数据保护。
- 选「继承 `OKE_BASE_URL`」而不是双域名：减少一处可能配置错的真源。
- 选 P1 不做归一化：在没确认 `ctVal/ctMult` 语义前，任何换算都可能给出错误风险数字。

---

## 17. 风险与回退

| 风险 | 影响 | 回退 |
|---|---|---|
| 签名实现错误 | 账户页不可用 | 客户端与业务解耦；关 `OKE_PRIVATE_READ_ENABLED` 即回到现状 |
| Key 泄露 | 账户信息暴露 | 只读 + 子账户 + IP 白名单；撤销 Key 即失效 |
| 新库损坏 | 账户历史丢失 | 不影响主库；删除 `live_account.db` 可重建 |
| 落库过多 | 磁盘增长 | 5 分钟快照 + 30 天保留 + 手动 VACUUM |
| 新增依赖 | 打包失败 | 仅用 `requests/hmac/hashlib/base64`，无新依赖 |
| 前端 token 未带 | 账户接口 403 | `accountStore` 统一注入；调试模式未配置 token 时跳过 |

---

## 18. 本轮不做

- 不做 P2 的 `ctVal/ctMult` 归一化、敞口汇总、强平距离、本地/实盘对账视图；
- 不做 P3 的下单/撤单/改单/状态机/审计表；
- 不做 P4 的自动交易、熔断执行器、杀开关；
- 不改预测节流、回验状态机、绩效口径；
- 不改 `VERSION`、不打包、不提交/推送、不打印真实 `.env`。

---

## 19. 归档说明

GPT 方案原件已存在于 `docs/plan/OKEworkplace_v2.5下一阶段技术指导方案.docx`，经 SHA256 校验与用户附件完全一致（`A6C89221…52C60`），故不重复复制；本文件即为其评审与实施方案。

---

## 20. 实施状态（2026-11-26）

### 20.1 已完成

| 阶段 | 状态 | 备注 |
|---|---|---|
| P0 前置（只读子账户、白名单） | 用户已完成 | 出口 IP 后续发生变化，导致 401 |
| P1-A 私有只读客户端 | 完成 | HMAC 签名、代理回退、业务码校验、错误映射、单测 |
| P1-B 账户库与服务 | 完成 | `live_account.db`、快照/成交（`tradeId` 去重）、配置缓存、30s 调度、懒建库 |
| P1-C 路由与实盘 Tab | 完成 | 八个只读接口、路由级 token（GET 也校验）、前端 Tab |
| P1-D 备份与清理 | 完成 | 账户库纳入备份签名/创建/清理；订单流快照保留清理（7 天） |
| P2 风险与对账 | **代码完成，未验收** | `/risk`、`/reconciliation`；因 OKX 401（出口 IP 变动）未做真实数据核对 |

### 20.2 当前开关与入口

- `OKE_PRIVATE_READ_ENABLED=false`：不注册账户调度、不创建空库、前端不显示「实盘」Tab。
- 恢复条件：只读 Key 的固定出口 IP 加入白名单，填好三项 Key，把开关置 true 后重启。
- 「实盘」隐藏后，`/api/v3/account/*` 仍保留；未启用时返回 `available=false` 占位。

### 20.3 与本文早期设计的差异

- 接口由六个扩到八个：新增 `risk`（账户级真实风险）与 `reconciliation`（本地手工单 ↔ 实盘持仓）。
- 持仓数量仍为交易所原始单位「张」，未做 `ctVal` 换算；对账用 USD 名义价值比较，容差由
  `OKE_ACCOUNT_RECONCILE_TOLERANCE_PCT`（默认 20）控制。
- token 方案采用 C1 折中：全局中间件不动，账户路由独立依赖，GET 也校验。
- 验收结论：真实只读联调曾成功（余额/持仓/成交均可用），之后因代理出口 IP 变化持续 401；P2 未完成真实验收。

### 20.4 相关文档

- 回测与评分实验：`docs/progress/第8步_回测与评分实验_20261126.md`
- 当前状态汇总：`docs/handover/交接文档.md` 第十一节
- 外部协作者说明：`docs/handover/交接文档_给GPT协作者_20261124.md` 第十二节
