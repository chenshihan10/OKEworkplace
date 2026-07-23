# OKEworkplace

可扩展的加密币盯盘工作空间。

## 目标

## 🚀 最新升级：v0.2.0 - 量化分析终端

**从行情展示页面升级到量化分析终端**，解决交易中最致命的延迟问题！

### ⚡ 核心改进
- **2 秒快速刷新**（从 15 秒优化，7.5x 性能提升）
- **市场评分系统**：0-100 分量化市场强度（趋势+资金+订单流-风险）
- **资金行为识别**：9 种资金操作模式自动分类
- **可解释信号**：BUY/SELL 附带详细分析理由（而非简单输出）

### 📊 新增功能
| 功能 | 说明 |
|------|------|
| 市场评分 | 0-100 分数评估市场强度，自动判定强势/震荡/弱势 |
| 资金行为分析 | 识别新增资金、头寸平仓、资金撤离等 9 种模式 |
| 新 API 端点 | `GET /api/analysis/{symbol}` 返回完整分析结果 |
| 新前端界面 | 6 标签页面：概览/评分分析/资金行为/交易信号/订单流/监控列表 |
| 快速更新 | 前端 2 秒刷新（从 15 秒），消除交易延迟 |

### 📖 查看更多
- [升级指南](./docs/UPGRADE_GUIDE_v0.2.0.md) - 详尽的功能说明和配置指南
- [升级摘要](./docs/PHASE4_SUMMARY.md) - 技术实现细节和测试清单
- [新前端预览](./frontend/index_v2.html) - 打开即可看到新界面（需要后端运行）

---


- 后端通过 OKE API 定时拉取行情数据
- 对价格、K 线和技术指标做统一处理
- 根据规则输出开单/平仓提醒
- 前端提供关注币种管理、实时价格、K 线和信号展示

## 结构

- `backend/`: API 服务、数据采集、信号引擎、任务调度
- `frontend/`: Google 风格监控面板
- `docs/`: 接口说明和后续扩展文档

## 当前规则

- 监控周期: `5m`, `15m`, `1h`, `4h`
- 一级价格监控: BTC、ETH 关键价格突破/跌破
- 二级: `MA20`, `MA60`, `MA120`
- 三级: `MACD`, `DIFF`, `DEA`
- 四级: 成交量放大
- 五级: `OI` 变化
- 六级: 资金费率
- 同一信号 30 分钟内只推送一次
- 仅提供信号提醒，不执行自动下单/平仓/加仓

## 接入点

你只需要补充 OKE API 的真实地址、鉴权方式、返回字段映射，就可以把 `backend/app/services/oke_client.py` 接到真实行情源。

## 快速开始

### 功能特性

本项目已配置为：
- ✅ **自动启动后端**：打开前端网页时，后端自动启动并在 `http://127.0.0.1:8000` 运行
- ✅ **自动停止后端**：关闭网页或 Streamlit 会话时，后端自动终止
- ✅ **本地代理支持**：支持通过本地代理（如 `http://127.0.0.1:12334`）访问 OKX API，同时也支持直连
- ✅ **VPN 和非 VPN 环境**：无论是否使用 VPN，都可以运行
- ✅ **中文界面**：完整的中文化用户界面
- ✅ **快速数据更新**：可配置的轮询间隔（默认 5 秒）

### 安装依赖

#### 1. 后端依赖
```bash
cd backend
pip install -r requirements.txt
```

#### 2. 前端依赖
```bash
cd frontend
pip install -r requirements.txt
```

### 运行方式

#### Windows 用户（推荐）
双击运行启动脚本：
```
run.bat
```

或在 PowerShell/CMD 中运行：
```powershell
python run.py
```

#### macOS/Linux 用户
```bash
chmod +x run.sh
./run.sh
```

或使用 Python：
```bash
python run.py
```

### 工作流程

1. **启动前端**：运行上述任一命令
   - 自动从 `backend/.env` 加载代理配置
   - 启动 Streamlit 前端应用
   
2. **自动启动后端**：
   - 首次打开网页时，系统自动启动后端服务
   - 后端在 `http://127.0.0.1:8000` 运行
   - 自动应用 `.env` 中的代理设置

3. **使用应用**：
   - 访问 Streamlit 仪表板查看实时数据
   - 使用侧边栏的"后端控制"面板管理后端
   
4. **自动清理**：
   - 关闭浏览器或 Streamlit 会话时，后端自动停止
   - 释放端口资源

### 代理配置

#### 本地代理（推荐用于 VPN 环境）
在 `backend/.env` 中配置：
```
HTTP_PROXY=http://127.0.0.1:12334
HTTPS_PROXY=http://127.0.0.1:12334
```

#### 无代理（直连）
在 `backend/.env` 中清空：
```
HTTP_PROXY=
HTTPS_PROXY=
```

#### 动态调整
在 Streamlit 前端的侧边栏中也可以动态修改代理设置。

### 后端控制面板

在 Streamlit 的侧边栏中，你可以：
- 📊 查看后端运行状态
- 🚀 手动启动后端
- 🛑 手动停止后端
- 🌐 修改代理设置

## 技术细节

### 后端进程管理

- 前端通过 `subprocess` 启动后端进程
- 后端进程在前端的生命周期内运行
- 使用 `atexit` 确保 Streamlit 关闭时后端被终止

#### 进程管理流程
```
用户打开网页
  ↓
Streamlit 加载 app.py
  ↓
检查 backend_initialized 状态
  ↓
调用 start_backend()
  ├─ 检查后端是否已运行（HTTP health check）
  ├─ 若未运行，启动 uvicorn 进程
  ├─ 注入 HTTP_PROXY/HTTPS_PROXY 环境变量
  ├─ 等待后端就绪（最多 15 秒）
  └─ 返回成功/失败状态
  ↓
渲染前端界面
  ├─ 侧边栏显示后端状态
  └─ 提供手动控制按钮
  ↓
用户关闭网页或 Streamlit 会话
  ↓
atexit 触发 stop_backend()
  ├─ 发送 SIGTERM 信号
  ├─ 等待进程优雅退出
  └─ 必要时强制杀死进程
```

### 环境变量管理

```
启动流程：
1. run.py/run.bat/run.sh 启动
2. 读取 backend/.env 文件
3. 注入环境变量到进程环境
4. 启动 Streamlit
5. Streamlit 启动后端时传递环境变量

后端获取代理：
1. 后端启动时通过 os.getenv() 读取环境变量
2. core/config.py 中的 Settings 类加载配置
3. services/network_service.py 使用 requests_proxies()
4. 所有 requests 请求都通过 proxies 参数使用配置的代理
```

### 数据抓取和存储优化

#### 抓取间隔配置
- **默认**：`POLL_INTERVAL_SECONDS=5`（每 5 秒抓取一次）
- **可调整**：在 `backend/.env` 中修改此参数

#### 存储策略
可在 `backend/.env` 中配置：
```
DATA_STORAGE_STRATEGY=memory          # 存储策略：memory | aggregated | persistent
KEEP_HISTORY_RECORDS=100              # 保留最近的历史记录数
```

**存储策略对比**：
| 策略 | 内存占用 | 历史数据 | 用途 |
|------|---------|---------|------|
| memory | 极低 | 仅最新 | 实时交易 |
| aggregated | 中等 | 聚合数据 | 平衡方案 |
| persistent | 较高 | 完整历史 | 数据分析 |

详细配置说明请参考 [DATA_OPTIMIZATION.md](DATA_OPTIMIZATION.md)。

## 改进日志

### 2026-07-07 - 自动启动/停止系统

#### 前端应用改进 ([frontend/app.py](frontend/app.py))
- ✅ 添加了后端进程管理器
- ✅ 实现健康检查 `is_backend_running()`
- ✅ 实现启动函数 `start_backend()`
- ✅ 实现停止函数 `stop_backend()`
- ✅ 在 Streamlit 侧边栏添加后端控制面板
- ✅ 支持动态修改代理设置
- ✅ 使用 `atexit` 确保关闭时清理后端进程

#### 启动脚本新增
- ✅ [run.py](run.py) - Python 通用启动脚本（跨平台）
- ✅ [run.bat](run.bat) - Windows 批处理脚本
- ✅ [run.sh](run.sh) - Linux/Mac 启动脚本

#### 配置和数据管理
- ✅ 修改 `backend/.env` 添加轮询间隔和存储策略配置
- ✅ 新增 `backend/app/services/storage_manager.py` - 多层级存储策略
- ✅ 支持数据采样以减少存储压力

#### 前端界面改进
- ✅ 完整中文化界面（HTML、JavaScript、Streamlit）
- ✅ 优化了用户体验和可读性

### 原始 Change Log

- 2026-07-07: 初始化工作空间骨架，完成后端 API、前端面板和基础信号链路。
- 2026-07-07: 将核心判断算法隔离到 `backend/app/strategy/trading_rules.py`，降低后续升级成本。
- 2026-07-07: 增加可运行的烟雾测试，并完成 Python 3.7 兼容处理。
- 2026-07-07: 将 OI、Funding 等扩展指标纳入信号引擎，统一告警去重逻辑。
- 2026-07-07: 引入 `.env` 配置加载，后端与前端依赖拆分，便于独立安装和运行。
- 2026-07-07: 接入 OKX V5 REST 真实接口，行情、K 线、OI、Funding、成交和盘口都改为优先拉取实盘数据，并保留本地兜底。
- 2026-07-07: 修复 Python 3.7 环境下 `urllib3 2.x` 与 OpenSSL 不兼容问题，锁定 `urllib3==1.26.18` 以保证后端可启动。
- 2026-07-07: 实测直连 `www.okx.com` 出现连接超时，当前程序会回退到本地兜底数据；后续需要网络可达性或代理配置后才能确认实盘数据。
- 2026-07-07: 已确认本机代理 `http://127.0.0.1:12334` 可访问 OKX，后端 `.env` 已加入 `HTTP_PROXY` 与 `HTTPS_PROXY`，后续程序默认走代理获取实盘数据。
- 2026-07-07: 所有 OKX REST 请求改为通过配置注入 `requests proxies`，新增 `/network/status` 网络诊断接口，并在首页显示 `REAL DATA (OKX)` 或 `FALLBACK DATA`。
- 2026-07-07: 重构首页为紧凑交易监控台，移除冗长 JSON 日志窗口，新增价格卡、信号摘要、订单流和盘口摘要，并为前端资源加入版本参数避免缓存。
- 2026-07-07: 自动启动/停止后端系统上线，支持多存储策略，数据抓取间隔优化到 5 秒，完整中文化界面。

## 文件结构

```
OKEworkplace/
├── README.md                           # 项目说明（此文件）
├── DATA_OPTIMIZATION.md                # 数据优化详细指南
├── run.py                              # Python 启动脚本
├── run.bat                             # Windows 启动脚本
├── run.sh                              # Linux/Mac 启动脚本
├── backend/
│   ├── .env                            # 后端配置
│   ├── requirements.txt                # Python 依赖
│   ├── app/
│   │   ├── main.py                     # FastAPI 应用
│   │   ├── models.py                   # 数据模型
│   │   ├── core/
│   │   │   ├── config.py               # 配置管理
│   │   │   └── scheduler.py            # 任务调度
│   │   ├── routes/
│   │   │   ├── coins.py                # 币种 API
│   │   │   ├── monitor.py              # 监控 API
│   │   │   └── network.py              # 网络 API
│   │   ├── services/
│   │   │   ├── market_service.py       # 行情服务
│   │   │   ├── oke_client.py           # OKX API 客户端
│   │   │   ├── signal_engine.py        # 信号引擎
│   │   │   ├── storage_manager.py      # 存储管理
│   │   │   └── ...
│   │   └── strategy/
│   │       └── trading_rules.py        # 交易规则
│   └── tests/
│       └── test_smoke.py               # 烟雾测试
├── frontend/
│   ├── app.py                          # Streamlit 应用
│   ├── index.html                      # HTML 前端
│   ├── requirements.txt                # Python 依赖
│   └── src/
│       ├── main.js                     # JavaScript 逻辑
│       └── styles.css                  # 样式表
└── .venv/                              # Python 虚拟环境
```

## 常见问题

### Q: 为什么要自动启动/停止后端？
A: 这样用户只需打开网页即可使用，无需手动启动两个应用。关闭时自动清理，避免后台进程占用资源。

### Q: 支持多实例吗？
A: 不建议同时运行多个 Streamlit 实例。如需多实例，手动启动后端后，更改前端配置中的 `API_BASE` 即可。

### Q: 代理必须是 127.0.0.1:12334 吗？
A: 不是。可在 `backend/.env` 中修改任意代理地址，或在 Streamlit 侧边栏中动态调整。

### Q: 能否同时使用 VPN 和本地代理？
A: 可以。系统会优先使用配置的本地代理。若要使用 VPN，清空代理配置后重启。

### Q: 如何修改数据抓取间隔？
A: 在 `backend/.env` 中修改 `POLL_INTERVAL_SECONDS` 参数，然后重启后端。详见 [DATA_OPTIMIZATION.md](DATA_OPTIMIZATION.md)。

### Q: 后端无法启动怎么办？
A: 
1. 检查 Python 环境是否正确
2. 确保端口 8000 未被占用
3. 查看 Streamlit 侧边栏的错误信息
4. 尝试在侧边栏点击"🚀 启动"手动启动

## 贡献指南

欢迎提交 Issue 和 Pull Request！

## License

MIT
