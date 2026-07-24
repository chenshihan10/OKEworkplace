# OKEworkplace

<img width="2727" height="1342" alt="image" src="https://github.com/user-attachments/assets/94ae4f94-7aa3-445d-8893-6492c1f52f2a" />

> 加密货币量化分析终端。

[![version](https://img.shields.io/badge/version-2.2.0-blue)](backend/app/main.py)
[![python](https://img.shields.io/badge/python-3.10+-green)](https://www.python.org/)
[![license](https://img.shields.io/badge/license-MIT-brightgreen)](LICENSE)

## 功能

### 实时行情监控
- BTC-USDT-SWAP / ETH-USDT-SWAP / SOL-USDT-SWAP（可扩展）
- 最新价格 / 24h 涨跌幅 / 成交量 / OI / 资金费率 / 标记价格 / 指数价格
- 1 秒刷新（WebView 直连 FastAPI 内存缓存）

### v2.2 信号方向抖动控制 ✅ 新增
- **三层过滤**：趋势缓冲（12次多数表决）→ 迟滞带（连续确认翻转）→ 冷却期（5分钟）
- **时间衰减加权投票**：越新的信号权重越高
- v2.1 实测：15分钟内方向翻转11次 → v2.2：**0次抖动**

### v2.2 决策追溯与置信度 ✅ 新增
- **Decision Trace**：记录 EMA/RSI/MACD/OI/成交量/费率 各指标贡献分和判定依据
- **Confidence**：基于一致性+评分强度+波动率的三因素加权可信度（0-100%）
- **Trend Phase**：趋势形成中/确认/强化/衰减/结束 实时检测

### v2.1 五维对称评分引擎
| 维度 | 权重 | 内容 |
|------|:--:|------|
| 趋势评分 | 30 | EMA 排列 + RSI 区间 + MACD 状态 + OI 验证 |
| 动量评分 | 20 | K线动量 + 价格位置 + 金叉/死叉检测 |
| 成交量评分 | 20 | 量能对比 + 量价配合 + 放量突破 |
| OI 评分 | 20 | OI 方向 + 价-OI 配合 |
| 资金费率评分 | 10 | 费率健康度（反向指标） |

**评分等级**：强烈关注(85+) → 重点关注(70+) → 观察(55+) → 中性(40+) → 放弃(<40)

### 技术指标
- EMA (20/60/120)、RSI (14)、MACD (12/26/9)、ATR (14)
- EMA 金叉/死叉检测、MACD 金叉/死叉检测
- 资金行为识别（11 种模式）

### 独立 GUI 窗口
- 基于 pywebview + Windows WebView2，不依赖浏览器
- **v2.2 三选项关闭对话框**：退出 / 最小化到系统托盘 / 取消
- 系统托盘图标（右键菜单：显示窗口 / 退出程序）
- 端口自动递增（8000~8019）
- 四级代理回退链（环境变量 → 注册表 → .env → 直连）

### v2.2 历史信号持久化 ✅ 新增
- SQLite 存储所有信号和分析快照
- `GET /api/signals/history/{symbol}` 查询历史记录

## 快速开始

### 一键启动（推荐）

双击 `OKEworkplace_v2.2.exe`（EXE 目录下自动生成 `data/signals.db`）

### 开发模式

```bash
cd backend

# 安装依赖
pip install -r requirements.txt

# 浏览器模式
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
# 打开 http://127.0.0.1:8000/index.html

# 独立窗口模式
python entry_exe.py
```

## 项目结构

```
OKEworkplace/
├── OKEworkplace_v2.2.exe          # 一键启动
├── _internal/                      # 运行时依赖（自动生成）
├── README.md
├── docs/
│   ├── V2.1_方案设计文档.md          # v2.1 设计规格
│   ├── V2.2_需求预案文档.md          # v2.2 需求预案 + 实施报告
│   └── 交接文档.md                    # 项目交接文档
├── backend/
│   ├── entry_exe.py                # GUI 窗口启动 + pystray 托盘
│   ├── OKEworkplace.spec           # PyInstaller 打包配置
│   ├── .env.example                # v2.2 配置模板
│   ├── app/
│   │   ├── main.py                 # FastAPI 应用 (v2.2.0)
│   │   ├── core/
│   │   │   ├── config.py           # 配置管理（含 v2.2 参数）
│   │   │   └── scheduler.py        # 5s 定时调度
│   │   ├── model/
│   │   │   ├── market_score.py     # 五维对称评分引擎
│   │   │   └── capital_behavior.py # 资金行为分析
│   │   ├── routes/
│   │   │   ├── analysis.py         # /api/analysis/{symbol}（含 trace/confidence/phase）
│   │   │   ├── monitor.py          # /api/monitor/snapshot
│   │   │   └── coins.py            # 币种管理
│   │   ├── services/
│   │   │   ├── signal_engine.py    # 统一信号聚合入口
│   │   │   ├── market_service.py   # 行情服务（集成 Tracker/DB/Bus）
│   │   │   ├── direction_tracker.py # v2.2 方向三层过滤
│   │   │   ├── decision_engine.py  # v2.2 决策追溯+置信度+趋势阶段
│   │   │   ├── db_store.py         # v2.2 SQLite 持久化
│   │   │   ├── event_bus.py        # v2.2 事件总线
│   │   │   ├── indicator_service.py # EMA/RSI/MACD/ATR
│   │   │   ├── oke_client.py       # OKX API 客户端（含标记/指数价）
│   │   │   └── alert_store.py      # v2.2 告警去重
│   │   └── strategy/
│   │       └── trading_rules.py    # v2.0 规则（已降级）
├── frontend/
│   ├── index.html                  # 前端监控面板（ES6 module）
│   └── src/                        # v2.2 模块化架构
│       ├── main.js                 # 调度中枢（~200行）
│       ├── api/                    # API 客户端 (3 files)
│       ├── stores/                 # 状态管理 (3 files)
│       ├── render/                 # 渲染模块 (5 files)
│       ├── views/                  # 标签页管理
│       └── utils/                  # 工具函数
└── tests/
    ├── test_smoke.py
    └── monitor_phase2.py           # v2.2 监控验证脚本
```

## API 端点

### v2.2 新增
| 端点 | 说明 |
|------|------|
| `GET /api/signals/history/{symbol}` | 历史信号查询 |
| `GET /api/analysis/{symbol}` | [增强] 含 confidence / decision_trace / trend_phase / mark_price |

### 完整端点
| 端点 | 说明 |
|------|------|
| `GET /health` | 健康检查 |
| `GET /api/monitor/snapshot` | 全量快照（行情 + 信号 + 告警） |
| `GET /api/analysis/{symbol}` | 单币种完整分析 |
| `GET /api/signals/history/{symbol}` | 历史信号 |
| `GET /api/coins` | 币种列表管理 |
| `GET /network/status` | 网络状态 |

## 文档

| 文档 | 路径 |
|------|------|
| v2.2 需求预案 + 实施报告 | [docs/V2.2_需求预案文档.md](docs/V2.2_需求预案文档.md) |
| v2.1 方案设计 | [docs/V2.1_方案设计文档.md](docs/V2.1_方案设计文档.md) |
| 项目交接文档 | [docs/交接文档.md](docs/交接文档.md) |

## 技术栈

- **后端**: FastAPI + APScheduler + PyWebView + SQLite
- **数据源**: OKX V5 REST API
- **前端**: HTML/CSS/JS（ES6 modules + Event Bus 架构）
- **系统托盘**: pystray + Pillow
- **打包**: PyInstaller (.spec, --windowed)

## 版本历史

| 版本 | 日期 | 主要变更 |
|------|------|------|
| v2.2.0 | 2026-07-24 | 方向抖动控制、决策追溯、置信度、趋势阶段、SQLite持久化、pystray托盘、前端模块化 |
| v2.1.0 | 2026-07-23 | 五维对称评分引擎、方向判定、风险评估、独立 GUI 窗口、OI 修复 |
| v2.0.0 | 2026-07-20 | 市场评分系统、资金行为分析、可解释信号 |
| v0.1.0 | 2026-07-07 | 基础骨架、OKX API 接入、行情监控 |

## License

MIT
