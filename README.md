# OKEworkplace
![Uploading image.png…]()

> 加密货币量化分析终端 — 独立桌面应用，不依赖浏览器。

[![version](https://img.shields.io/badge/version-2.1.0-blue)](backend/app/main.py)
[![python](https://img.shields.io/badge/python-3.10+-green)](https://www.python.org/)
[![license](https://img.shields.io/badge/license-MIT-brightgreen)](LICENSE)

## 功能

### 实时行情监控
- BTC-USDT-SWAP / ETH-USDT-SWAP / SOL-USDT-SWAP（可扩展）
- 最新价格 / 24h 涨跌幅 / 成交量 / OI / 资金费率 / 标记价格
- 1 秒刷新（WebView 直连 FastAPI 内存缓存）

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
- 资金行为识别（9 种模式）

### 方向 & 风险
- 方向判定：LONG / SHORT / NEUTRAL（四条件多数表决）
- 风险评估：LOW / MEDIUM / HIGH（ATR + 费率 + 关键价位）
- AI 规则解释引擎（27 条规则模板）

### 独立 GUI 窗口
- 基于 pywebview + Windows WebView2，不依赖浏览器
- 关闭确认对话框（退出 / 最小化到托盘）
- 端口自动递增（8000~8019）
- 四级代理回退链（环境变量 → 注册表 → .env → 直连）

## 快速开始

### 一键启动（推荐）

双击根目录下的 `OKEworkplace.exe`。

### 开发模式

```bash
cd backend

# 安装依赖
pip install -r requirements.txt

# 浏览器模式
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
# 打开 http://127.0.0.1:8000/index_v2.html

# 独立窗口模式
python entry_exe.py
```

## 项目结构

```
OKEworkplace/
├── OKEworkplace.exe              # 一键启动（双击即可）
├── _internal/                    # 运行时依赖（自动生成，勿删除）
├── README.md
├── docs/
│   ├── V2.1_方案设计文档.md       # v2.1 设计规格
│   ├── V2.2_需求预案文档.md       # v2.2 需求预案
│   └── 交接文档.md                # 项目交接文档
├── backend/
│   ├── entry_exe.py               # GUI 窗口启动入口
│   ├── OKEworkplace.spec          # PyInstaller 打包配置
│   ├── app/
│   │   ├── main.py                # FastAPI 应用 (v2.1.0)
│   │   ├── core/
│   │   │   ├── config.py          # 配置管理 (.env)
│   │   │   └── scheduler.py       # 5s 定时调度
│   │   ├── model/
│   │   │   ├── market_score.py    # 五维对称评分引擎
│   │   │   └── capital_behavior.py # 资金行为分析
│   │   ├── routes/
│   │   │   ├── analysis.py        # /api/analysis/{symbol}
│   │   │   ├── monitor.py         # /api/monitor/snapshot
│   │   │   └── coins.py           # 币种管理
│   │   ├── services/
│   │   │   ├── signal_engine.py   # 统一信号聚合入口
│   │   │   ├── market_service.py  # 行情服务
│   │   │   ├── indicator_service.py # EMA/RSI/MACD/ATR
│   │   │   ├── oke_client.py      # OKX API 客户端
│   │   │   └── alert_store.py     # 告警去重
│   │   └── strategy/
│   │       └── trading_rules.py   # v2.0 规则 (已降级)
├── frontend/
│   ├── src/
│   │   └── main.js                 # 前端逻辑脚本
│   └── index_v2.html               # 前端监控面板
└── .venv/                         # Python 虚拟环境
```

## API 端点

| 端点 | 说明 |
|------|------|
| `GET /health` | 健康检查 |
| `GET /api/monitor/snapshot` | 全量快照（行情 + 信号 + 告警） |
| `GET /api/analysis/{symbol}` | 单币种完整分析（评分 + 方向 + 风险 + 解释） |
| `GET /api/coins` | 币种列表管理 |

### 分析输出示例

```json
{
  "symbol": "ETH-USDT",
  "price": 1900.35,
  "score": 65,
  "level": "观察",
  "direction": "SHORT",
  "risk": "MEDIUM",
  "components": {
    "trend": 19, "momentum": 14, "volume": 14, "oi": 11, "funding": 7
  },
  "reasons": [
    "MACD 柱线转负，动能减弱",
    "成交量放大至均量 1.5 倍",
    "OI 增加 (+0.06%)",
    "价格接近支撑位 1900.0"
  ],
  "indicators": {
    "ema20": 1905.2, "ema60": 1918.7, "rsi14": 31.06,
    "macd": {"diff": -6.70, "dea": 4.86, "histogram": -11.56},
    "atr14": 12.3
  }
}
```

## 文档

| 文档 | 路径 |
|------|------|
| v2.1 方案设计 | [docs/V2.1_方案设计文档.md](docs/V2.1_方案设计文档.md) |
| v2.2 需求预案 | [docs/V2.2_需求预案文档.md](docs/V2.2_需求预案文档.md) |
| 项目交接文档 | [docs/交接文档.md](docs/交接文档.md) |

## 技术栈

- **后端**: FastAPI + APScheduler + PyWebView
- **数据源**: OKX V5 REST API
- **前端**: HTML/CSS/JS（pywebview WebView2 容器）
- **打包**: PyInstaller (.spec, --windowed)

## 版本历史

| 版本 | 日期 | 主要变更 |
|------|------|------|
| v2.1.0 | 2026-07-23 | 五维对称评分引擎、方向判定、风险评估、独立 GUI 窗口、OI 修复 |
| v2.0.0 | 2026-07-20 | 市场评分系统、资金行为分析、可解释信号 |
| v0.1.0 | 2026-07-07 | 基础骨架、OKX API 接入、行情监控 |

## License

MIT
