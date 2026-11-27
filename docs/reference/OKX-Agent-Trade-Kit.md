# OKX Agent Trade Kit 官方简介

> **文档类型**：第三方工具官方简介存档  
> **工具名称**：OKX Agent Trade Kit  
> **官方仓库**：github.com/okx/agent-trade-kit  
> **整理日期**：2026-11-20

---

## 简介

OKX Agent Trade Kit 将 AI 助手与您的 OKX 账户直接连接。无需在 AI 和交易所之间来回切换，只需用自然语言描述您的需求，AI 即可自动执行。

它以本地进程的方式运行在您的设备上。您的 API Key 永远不会离开本地。完全开源，遵循 MIT 协议。

OKX 官方 AI 智能交易工具包。让您的 AI Agent 通过自然语言，在 OKX 上交易现货、合约、期权等多种产品。

资源入口：

- GitHub：github.com/okx/agent-trade-kit
- npm：`okx-trade-mcp`
- npm：`okx-trade-cli`

> **版本提示**：本页内容可能未反映最新版本。如需查看最新工具列表、模块说明、配置选项及更新日志，请以 GitHub 仓库为准：github.com/okx/agent-trade-kit

---

## 目录

- [一、支持哪些功能](#一支持哪些功能)
- [二、三种使用方式](#二三种使用方式)
- [三、快速开始](#三快速开始)
  - [3.1 OpenClaw](#31-openclaw)
  - [3.2 MCP 客户端](#32-mcp-客户端)
  - [站点配置](#站点配置)
  - [代理配置](#代理配置)
- [四、MCP 服务器](#四mcp-服务器)
  - [启动选项](#启动选项)
  - [工具列表](#工具列表)
- [五、命令行（CLI）](#五命令行cli)
- [六、Skills](#六skills)
- [七、安全](#七安全)
- [八、常见问题与提示](#八常见问题与提示)

---

## 一、支持哪些功能？

- **行情数据** — 价格、订单簿、K线、资金费率、持仓量
- **现货交易** — 下单、撤单、改单、批量操作、策略委托
- **合约与永续** — 永续合约和交割合约、杠杆、持仓管理
- **期权** — 下单、期权链、希腊字母（IV、Delta、Gamma、Theta、Vega）
- **策略委托** — 条件单、OCO 止盈止损、追踪止损
- **账户** — 余额、账单、手续费率、仓位管理
- **机器人** — 创建、监控和停止网格策略

---

## 二、三种使用方式

1. **MCP 服务器（`okx-trade-mcp`）** — 接入 Claude、Cursor、Codex、OpenCode 或任意支持 MCP 的 AI 客户端，让您的 Agent 通过自然语言调用 OKX 工具。
2. **CLI（`okx-trade-cli`）** — 在终端直接交易，支持管道、定时任务和脚本，无需 AI 客户端。
3. **Skills（`okx-cex-market`、`okx-cex-trade`、`okx-cex-portfolio`、`okx-cex-bot`）** — 即插即用模块，适用于支持 Skills 协议的 AI 客户端（如 OpenClaw）。按需安装，灵活搭配。

---

## 三、快速开始

### 3.1 OpenClaw

> **安全提示**：切勿将您的 API Key、Secret Key 或 Passphrase 粘贴到对话框中。AI 不应也无需直接接触您的凭证，请始终将其保存在配置文件中。由于 AI 在 OpenClaw 中的行为具有不确定性，强烈建议使用子账户的 API Key 而非主账户，并仅开启所需的最小权限。

#### 第一步 — 安装 Skills

打开 OpenClaw，将以下提示语粘贴到对话框中发送——不是命令行：

```text
运行 npx skills add okx/agent-skills，自主解决所有碰到的问题，查询 BTC 价格。
```

#### 第二步 — 配置 API 凭证

打开终端，运行：

```bash
mkdir -p ~/.okx && cat > ~/.okx/config.toml << 'EOF'
default_profile = "demo"

[profiles.live]
api_key    = "your-live-api-key"
secret_key = "your-live-secret-key"
passphrase = "your-live-passphrase"

[profiles.demo]
api_key    = "your-demo-api-key"
secret_key = "your-demo-secret-key"
passphrase = "your-demo-passphrase"
demo       = true
EOF
```

用任意文本编辑器打开 `~/.okx/config.toml`，填入您的 `api_key`、`secret_key` 和 `passphrase`，保存即可。

获取 API Key：API 页面 — 建议先从模拟盘开始。

### 3.2 MCP 客户端

Claude Desktop、Claude Code、Cursor、VS Code、Windsurf，以及所有兼容 MCP 的客户端。

#### 第一步 — 安装

```bash
npm install -g @okx_ai/okx-trade-mcp @okx_ai/okx-trade-cli
```

验证安装：

```bash
okx market ticker BTC-USDT
```

行情数据可立即使用，无需 API Key。

#### 第二步 — 添加 OKX API 凭证

```bash
okx config init
```

交互式向导将引导您完成 `~/.okx/config.toml` 的创建与配置，运行一次即可完成。

获取 API Key：API 页面 — 建议先从模拟盘开始。

或手动配置 — 跳过向导，直接创建 `~/.okx/config.toml`：

```toml
default_profile = "demo"    # 默认加载哪个 Profile

# Profile 名称是您自定义的标签，可随意命名。
# 启动时通过 --profile <名称> 切换不同配置。
# "demo" 和 "live" 只是惯用命名，名称本身没有特殊含义。

[profiles.demo]
api_key    = "your-demo-api-key"
secret_key = "your-demo-secret-key"
passphrase = "your-demo-passphrase"
demo       = true    # demo = true → 模拟盘交易，不涉及真实资金

[profiles.live]
api_key    = "your-live-api-key"
secret_key = "your-live-secret-key"
passphrase = "your-live-passphrase"
             # 无 demo 标志 → 实盘交易，使用真实资金
```

### 站点配置

OKX 在不同地区运营独立站点。请在 Profile 中添加 `site` 字段，与您账号所在站点保持一致：

| 站点 | 网址 | 适用人群 |
|---|---|---|
| `global`（默认） | www.okx.com | 全球大多数用户 |
| `eea` | my.okx.com | EEA / 欧洲用户 |
| `us` | app.okx.com | 美国用户 |

```toml
[profiles.live]
site       = "global"    # global | eea | us（不填则默认为 global）
api_key    = "your-api-key"
secret_key = "your-secret-key"
passphrase = "your-passphrase"
```

### 代理配置

如果您需要通过代理访问网络，可在 Profile 中添加 `proxy_url` 字段。根据代理类型选择以下其中一种配置：

**无需认证：**

```toml
[profiles.demo]
api_key    = "your-api-key"
secret_key = "your-secret-key"
passphrase = "your-passphrase"
demo       = true
proxy_url  = "http://proxy.example.com:8080"
```

**需要用户名和密码：**

```toml
[profiles.demo]
api_key    = "your-api-key"
secret_key = "your-secret-key"
passphrase = "your-passphrase"
demo       = true
proxy_url  = "http://user:password@proxy.example.com:8080"
```

密码含特殊字符时需进行 URL encode（例如 `p@ss` → `p%40ss`）：

```toml
proxy_url = "http://user:p%40ss@proxy.example.com:8080"
```

#### 第三步 — 连接 AI 客户端

```bash
okx-trade-mcp setup --client <client>
```

| 客户端 | `<client>` 值 |
|---|---|
| Claude Desktop | `claude-desktop` |
| Claude Code | `claude-code` |
| Cursor | `cursor` |
| VS Code | `vscode` |
| Windsurf | `windsurf` |

如需手动配置，请参阅 GitHub 上的 Client Setup (Manual)。

#### 第四步 — 试用

打开您的 AI 客户端，输入：

```text
OKX 上 BTC 现在的价格是多少？
查看我的账户余额
在模拟盘用市价单买入 100 USDT 的 BTC
BTC-USDT-SWAP 的资金费率是多少？
```

---

## 四、MCP 服务器

MCP 服务器通过 Model Context Protocol 标准向外暴露 OKX 交易工具。注册一次后，您的 AI Agent 即可进行交易、查询和账户管理。

### 启动选项

| 使用场景 | 命令 |
|---|---|
| 仅行情数据（无需 Key） | `okx-trade-mcp --modules market` |
| 模拟盘，全功能 | `okx-trade-mcp --profile demo --modules all` |
| 实盘，只读监控 | `okx-trade-mcp --profile live --read-only` |
| 实盘，仅现货 | `okx-trade-mcp --profile live --modules market,spot` |
| 实盘，永续 + 期权 | `okx-trade-mcp --profile live --modules market,swap,option` |

对于未列出的 MCP 客户端，可通过以下命令将其注册为 stdio 服务器：

```bash
okx-trade-mcp --profile <demo|live> --modules <all|market|spot|swap|...>
```

### 工具列表

`market` 模块无需 API Key。其他模块均需要**读取**权限；写入操作还需额外开启**交易**权限。

#### market — 行情数据

| 工具 | 说明 |
|---|---|
| `market_get_ticker` | 单币对行情（最新价、24h 量、买一/卖一） |
| `market_get_tickers` | 某类型全部行情（SPOT / SWAP / FUTURES / OPTION） |
| `market_get_orderbook` | 盘口深度 |
| `market_get_candles` | K线（最近 300 根） |
| `market_get_history_candles` | 历史K线（2天前，最多3个月） |
| `market_get_index_ticker` | 指数行情（如 BTC-USD） |
| `market_get_index_candles` | 指数K线 |
| `market_get_price_limit` | 合约涨跌停价 |
| `market_get_funding_rate` | 永续合约当前资金费率 |
| `market_get_funding_rate_history` | 历史资金费率 |
| `market_get_mark_price` | 衍生品标记价格 |
| `market_get_open_interest` | 持仓量 |
| `market_get_trades` | 最新成交记录 |

#### spot — 现货交易

| 工具 | 说明 |
|---|---|
| `spot_place_order` | 下现货单（市价、限价、Post-only、FOK、IOC） |
| `spot_cancel_order` | 撤销挂单 |
| `spot_amend_order` | 改价或改量 |
| `spot_batch_place_orders` | 批量下单（最多20笔） |
| `spot_batch_cancel_orders` | 批量撤单 |
| `spot_get_order` | 查询单笔订单详情 |
| `spot_get_open_orders` | 查询当前挂单 |
| `spot_get_order_history` | 历史订单（7天内） |
| `spot_get_order_history_archive` | 历史订单（7天前，最多3个月） |
| `spot_get_fills` | 最新成交记录 |
| `spot_get_fills_archive` | 较早成交记录（1小时前，最多3个月） |

#### swap — 永续合约

| 工具 | 说明 |
|---|---|
| `swap_place_order` | 下永续合约单 |
| `swap_cancel_order` | 撤销挂单 |
| `swap_amend_order` | 改价或改量 |
| `swap_batch_place_orders` | 批量下单（最多20笔） |
| `swap_batch_cancel_orders` | 批量撤单 |
| `swap_close_position` | 一键平仓（指定合约） |
| `swap_get_order` | 查询单笔订单详情 |
| `swap_get_open_orders` | 查询当前挂单 |
| `swap_get_order_history` | 历史订单（7天内） |
| `swap_get_positions` | 当前持仓 |
| `swap_get_fills` | 最新成交记录 |
| `swap_set_leverage` | 设置杠杆倍数 |
| `swap_get_leverage` | 查询当前杠杆设置 |

#### futures — 交割合约

| 工具 | 说明 |
|---|---|
| `futures_place_order` | 下交割合约单 |
| `futures_cancel_order` | 撤销挂单 |
| `futures_amend_order` | 改价或改量 |
| `futures_get_order` | 查询单笔订单详情 |
| `futures_get_open_orders` | 查询当前挂单 |
| `futures_get_order_history` | 历史订单 |
| `futures_get_positions` | 当前持仓 |
| `futures_get_fills` | 最新成交记录 |

#### option — 期权

| 工具 | 说明 |
|---|---|
| `option_place_order` | 期权下单（买入/卖出 call 或 put） |
| `option_cancel_order` | 撤销挂单 |
| `option_batch_cancel` | 批量撤单（最多 20 条） |
| `option_amend_order` | 改价或改量 |
| `option_get_order` | 查询单笔订单详情 |
| `option_get_orders` | 查询挂单或历史订单 |
| `option_get_positions` | 当前持仓（含 Greeks） |
| `option_get_fills` | 成交记录 |
| `option_get_instruments` | 期权链（可用合约列表） |
| `option_get_greeks` | 每个合约的 IV + Greeks（delta、gamma、theta、vega） |

#### account — 账户管理

| 工具 | 说明 |
|---|---|
| `account_get_balance` | 交易账户余额（指定币种或全部） |
| `account_get_asset_balance` | 资金账户余额 |
| `account_get_positions` | 当前所有持仓 |
| `account_get_positions_history` | 历史持仓记录 |
| `account_get_bills` | 账单流水（7天内） |
| `account_get_bills_archive` | 账单流水（7天前，最多3个月） |
| `account_get_fee_rates` | 交易手续费率 |
| `account_get_config` | 账户配置（仓位模式、账户层级等） |
| `account_set_position_mode` | 切换单向/双向持仓模式 |
| `account_get_max_size` | 指定合约的最大可开仓量 |
| `account_get_max_withdrawal` | 各币种最大可提余额 |
| `account_get_leverage` | 查询杠杆设置 |
| `account_set_leverage` | 设置杠杆（全局） |
| `account_get_audit_log` | 查询本地工具调用审计日志 |

#### bot — 策略机器人

**网格（bot.grid）**

| 工具 | 说明 |
|---|---|
| `grid_get_orders` | 列出运行中或历史网格机器人 |
| `grid_get_order_details` | 查询指定机器人的详情 |
| `grid_get_sub_orders` | 列出机器人子订单 |
| `grid_create_order` | 创建网格机器人（现货、合约或 Moon Grid） |
| `grid_stop_order` | 停止运行中的机器人 |

**DCA（bot.dca）**

| 工具 | 说明 |
|---|---|
| `dca_create_order` | 创建 DCA（马丁格尔）机器人 |
| `dca_stop_order` | 停止 DCA 策略 |
| `dca_get_orders` | 列出运行中或历史 DCA 策略 |
| `dca_get_order_details` | 查询单个 DCA 策略详情 |
| `dca_get_sub_orders` | 列出 DCA 策略生成的子订单 |

---

## 五、命令行（CLI）

命令行工具是独立的终端工具，无需 AI 客户端。

```bash
# 行情数据
okx market ticker BTC-USDT
okx market candles BTC-USDT --bar 1H --limit 10
okx market funding-rate BTC-USDT-SWAP

# 交易
okx spot place --instId BTC-USDT --side buy --ordType market --sz 100
okx swap place --instId BTC-USDT-SWAP --side buy --ordType market --sz 1 --posSide long --tdMode cross

# 账户
okx account balance
okx account positions

# 网格机器人
okx --demo bot grid create --instId BTC-USDT --algoOrdType grid \
  --maxPx 100000 --minPx 80000 --gridNum 10 --quoteSz 100

# 管道与脚本
okx account balance --json | jq '.[] | {ccy: .ccy, eq: .eq}'
okx market candles BTC-USDT --bar 1H --limit 200 --json | python3 analyze.py
```

完整 CLI 参考文档：见 GitHub 仓库 github.com/okx/agent-trade-kit。

---

## 六、Skills

Skills 是即插即用模块，适用于支持 Skills 协议的 AI 客户端。按需安装，支持单一或组合使用。

```bash
npx skills add okx/agent-skills
```

| 模块 | Skill 包 | 说明 | 权限 |
|---|---|---|---|
| 行情数据 | `okx-cex-market` | 实时获取最新行情、盘口深度、K线走势、资金费率、持仓量及指数数据。 | 公开 · 无需 API Key |
| 交易 | `okx-cex-trade` | 支持现货、合约、期权及算法订单。一键下单、撤单、改单及批量操作，更支持 OCO、移动止盈止损及网格策略。 | 需要 API Key |
| 资产组合 | `okx-cex-portfolio` | 追踪账户余额、当前持仓、收益明细、账单历史、费率等级与资金划转。只需一个 Skill，全盘资产尽在掌握。 | 需要 API Key |
| 机器人 | `okx-cex-bot` | 自动化交易策略：现货网格、合约网格和定投（DCA）机器人。 | 需要 API Key |

前往 GitHub 探索全部 Skills：github.com/okx/agent-trade-kit。

---

## 七、安全

OKX Agent Trade Kit 提供四层安全防护：

1. **模拟盘模式（`--demo`）** — 在模拟账户中交易，实盘资金不受影响。建议从这里开始。
2. **只读模式（`--read-only`）** — 仅允许数据查询，不可进行交易操作。
3. **智能注册** — 服务器在启动时检查您的 API Key 权限。如果该 Key 不具备交易权限，下单工具将不会暴露给 AI。
4. **风险标签** — 所有涉及资金操作的工具均标记为 `[CAUTION]`，提示 AI 在执行前进行确认。

此外，内置限流机制，防止对 OKX API 造成过载。

> **凭证安全**：切勿将您的 API Key、Secret Key 或 Passphrase 透露给任何 AI 模型或粘贴到对话框中。所有凭证应仅保存在本地配置文件（`~/.okx/config.toml`）中。由于 AI 行为具有不确定性，强烈建议使用子账户的 API Key 并仅开启所需的最小权限——除非有明确需求，否则不要开启提币权限。

---

## 八、常见问题与提示

以下要点均摘自上文各章节，便于快速自查：

- **不填 API Key 能用吗？** 可以。`market` 模块与行情数据无需 API Key，安装后运行 `okx market ticker BTC-USDT` 即可验证。
- **先用实盘还是模拟盘？** 建议先从模拟盘开始（`--demo` 或 Profile 中 `demo = true`），确认无误后再切到实盘。
- **凭证放在哪里？** 只放在本地 `~/.okx/config.toml`，不要粘贴进对话框或透露给任何 AI 模型。
- **该用主账户还是子账户？** 强烈建议使用子账户的 API Key，并仅开启所需的最小权限；除非有明确需求，不要开启提币权限。
- **文档与最新版本不一致？** 本页可能未反映最新版本，请以 GitHub 仓库 github.com/okx/agent-trade-kit 为准。
