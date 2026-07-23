// 市场分析终端前端 - 核心脚本升级
// 解决：1) 实时更新频率问题 2) 显示市场评分 3) 显示资金行为

const apiBase = "http://127.0.0.1:8000";
const realDot = "\u{1F7E2}";
const fallbackDot = "\u{1F7E1}";

// 配置
const CONFIG = {
  refreshInterval: 1000,  // 1 秒刷新一次实时数据（价格、快照）
  analysisInterval: 2000, // 2 秒更新一次分析（评分、信号）
  maxChartPoints: 100,
};

// 全局数据
let globalData = {
  network: null,
  snapshot: null,
  analysis: {},     // 各币种的分析结果
  priceHistory: {}, // 价格历史
  lastAnalysisUpdate: 0,
};

// ============ 中文标签 ============
const labels = {
  bid: "买价",
  ask: "卖价",
  trend: "趋势",
  macd: "MACD",
  oi: "持仓量",
  funding: "资金费率",
  noSignals: "暂无信号",
  noOrderFlow: "暂无订单流",
  buyVol: "买入量",
  sellVol: "卖出量",
  bestAsk: "最优卖价",
  bestBid: "最优买价",
  backendOffline: "后端离线",
  realData: "实时数据 (OKX)",
  fallbackData: "本地数据",
  proxyDisabled: "代理已禁用",
  marketScore: "综合评分",
  directionLong: "做多",
  directionShort: "做空",
  directionNeutral: "中性",
  riskLow: "低风险",
  riskMedium: "中风险",
  riskHigh: "高风险",
  trendComp: "趋势 (30)",
  momentumComp: "动量 (20)",
  volumeComp: "成交量 (20)",
  oiComp: "OI (20)",
  fundingComp: "费率 (10)",
};

// ============ 格式化函数 ============
function fmtNumber(value, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "-";
  return Number(value).toLocaleString(undefined, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

function fmtPct(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "-";
  return `${(Number(value) * 100).toFixed(4)}%`;
}

// ============ API 请求 ============
async function getJson(path) {
  try {
    const res = await fetch(`${apiBase}${path}`, { cache: "no-store" });
    
    // 🟢 核心改动：拦截 503 状态，直接解析出后端返回的数据量及用时评估 JSON
    if (res.status === 503) {
      const errPayload = await res.json();
      try {
        return { isSyncing: true, ...JSON.parse(errPayload.detail) };
      } catch (pErr) {
        return { isSyncing: true, estimated_data_size: "计算中...", estimated_wait_time: "请稍候" };
      }
    }
    
    if (!res.ok) throw new Error(`${path} 返回 ${res.status}`);
    return res.json();
  } catch (error) {
    console.error(`API 错误: ${path}`, error);
    return null;
  }
}

// ============ 主刷新流程 ============
async function refresh() {
  try {
    // 并行获取网络状态和快照
    const [network, snapshot] = await Promise.all([
      getJson("/network/status"),
      getJson("/api/monitor/snapshot"),
    ]);

    if (network) globalData.network = network;
    if (snapshot) {
      globalData.snapshot = snapshot;
      renderNetwork(network);
      renderSnapshot(snapshot);
    }

    // 定期获取分析数据（不用每次都刷新，减少后端压力）
    const now = Date.now();
    if (now - globalData.lastAnalysisUpdate > CONFIG.analysisInterval) {
      await refreshAnalysis(snapshot);
      globalData.lastAnalysisUpdate = now;
    }
  } catch (error) {
    renderOffline(error);
  }
}

// ============ 刷新分析数据 ============
async function refreshAnalysis(snapshot) {
  if (!snapshot) return;

  const items = snapshot.watch_items || [];
  
  for (const item of items) {
    try {
      const analysis = await getJson(`/api/analysis/${item.symbol}`);
      if (analysis) {
        globalData.analysis[item.symbol] = analysis;
      }
    } catch (error) {
      console.error(`分析错误: ${item.symbol}`, error);
    }
  }
}

// ============ 网络状态渲染 ============
function renderNetwork(data) {
  const target = document.querySelector("[data-network-status]");
  if (!target) return;

  const isReal = data.data_source === "REAL";
  target.textContent = isReal ? `${realDot} ${labels.realData}` : `${fallbackDot} ${labels.fallbackData}`;
  target.classList.toggle("real", isReal);
  target.classList.toggle("fallback", !isReal);
  target.title = data.proxy_enabled ? `代理: ${data.proxy}` : labels.proxyDisabled;
}

// ============ 快照渲染 ============
function renderSnapshot(data) {
  const updated = document.querySelector("[data-updated-at]");
  if (updated) updated.textContent = data.updated_at ? new Date(data.updated_at).toLocaleTimeString("zh-CN") : "--";

  const prices = data.prices || {};
  const signals = data.signals || {};
  const items = data.watch_items || [];

  renderMarketCards(items, prices, signals);
  renderMarketScores(items);
  renderCapitalBehaviors(items);
  renderSignals(signals);
  renderOrderFlow(signals);
  renderWatchlist(items, prices, signals);
}

// ============ 行情卡片渲染（升级版） ============
function renderMarketCards(items, prices, signals) {
  const target = document.querySelector("[data-market-grid]");
  if (!target) return;

  target.innerHTML = items.map((item) => {
    const ticker = prices[item.symbol] || {};
    const signal = signals[item.symbol] || {};
    const analysis = globalData.analysis[item.symbol] || {};
    const macd = signal.macd || {};
    const oi = signal.open_interest || {};
    const funding = signal.funding_rate || {};
    const source = (ticker.source || "-").toUpperCase();
    const sourceClass = source === "OKX" ? "source-real" : "source-fallback";

    // 市场状态 / 方向 (v2.1)
    let stateText = "-";
    let scoreText = "-/100";
    const dirIcons = { LONG: "\u{1F7E2}", SHORT: "\u{1F534}", NEUTRAL: "\u{26AA}" };

    if (analysis.isSyncing) {
      stateText = `<span style="color: #f59e0b; font-size: 0.75rem; animation: pulse 1.5s infinite;">⌛ 正在加载数据 (~${analysis.estimated_data_size})</span>`;
      scoreText = `<span style="color: #94a3b8; font-size: 0.75rem;">预计需 ${analysis.estimated_wait_time}</span>`;
    } else if (analysis.score != null) {
      const dir = analysis.direction || "NEUTRAL";
      const icon = dirIcons[dir] || "❓";
      const scoreColor = analysis.score >= 85 ? "#10b981" : analysis.score >= 70 ? "#f59e0b" : analysis.score >= 55 ? "#3b82f6" : "#94a3b8";
      stateText = `${icon} ${dir === "LONG" ? labels.directionLong : dir === "SHORT" ? labels.directionShort : labels.directionNeutral}`;
      scoreText = `<span style="color:${scoreColor};font-weight:bold;">${analysis.score || "-"}/100</span> ${analysis.level || ""}`;
    }

    return `
      <article class="market-card">
        <div class="market-top">
          <div>
            <span class="symbol">${item.symbol}</span>
            <span class="alias">${item.alias || item.timeframe || ""}</span>
          </div>
          <span class="source ${sourceClass}">${source}</span>
        </div>
        
        <div class="market-price-row">
          <div class="price">${fmtNumber(ticker.price)}</div>
          <div class="market-meta">
            <div>方向: <strong>${stateText}</strong></div>
            <div>评分: <strong>${scoreText}</strong></div>
          </div>
        </div>

        <div class="metric-grid">
          <div><label>${labels.bid}</label><strong>${fmtNumber(ticker.bid_px)}</strong></div>
          <div><label>${labels.ask}</label><strong>${fmtNumber(ticker.ask_px)}</strong></div>
          <div><label>${labels.trend}</label><strong>${signal.trend || "-"}</strong></div>
          <div><label>${labels.macd}</label><strong>${fmtNumber(macd.diff)} / ${fmtNumber(macd.dea)}</strong></div>
          <div><label>${labels.oi}</label><strong>${fmtNumber(oi.open_interest, 0)}</strong></div>
          <div><label>${labels.funding}</label><strong>${fmtPct(funding.funding_rate)}</strong></div>
        </div>
      </article>
    `;
  }).join("");
}

// ============ 市场评分组件 ============
function renderMarketScores(items) {
  const target = document.querySelector("[data-market-scores]");
  if (!target) return;

  target.innerHTML = items.map((item) => {
    const analysis = globalData.analysis[item.symbol];
    if (!analysis) return "";

    if (analysis.isSyncing) {
      return `
        <div class="score-card" style="opacity: 0.6;">
          <div class="score-title">${item.symbol}</div>
          <div class="score-main" style="font-size: 1.1rem; color: #f59e0b; padding: 1.5rem 0;">📡 等待高精度指标清洗...</div>
        </div>
      `;
    }

    const score = analysis.score || 0;
    const comps = analysis.components || {};
    
    // v2.1 五维评分条
    const makeBar = (val, max) => {
      const percent = Math.min(100, (val / max) * 100);
      const color = val >= max * 0.7 ? "#10b981" : val >= max * 0.4 ? "#f59e0b" : "#ef4444";
      return `<div class="score-bar" style="width: ${percent}%; background: ${color};"></div>`;
    };

    // 评分颜色
    const scoreColor = score >= 85 ? "#10b981" : score >= 70 ? "#f59e0b" : score >= 55 ? "#3b82f6" : "#94a3b8";
    const dirIcon = { LONG: "\u{1F7E2}", SHORT: "\u{1F534}", NEUTRAL: "\u{26AA}" }[analysis.direction] || "\u{26AA}";
    const riskColors = { LOW: "#10b981", MEDIUM: "#f59e0b", HIGH: "#ef4444" };
    const riskLabel = { LOW: labels.riskLow, MEDIUM: labels.riskMedium, HIGH: labels.riskHigh };

    return `
      <div class="score-card">
        <div class="score-title">${item.symbol} ${dirIcon}</div>
        <div class="score-main" style="color: ${scoreColor};">${score}/100</div>
        <div style="font-size:0.8rem;color:#94a3b8;margin-bottom:0.5rem;">
          ${analysis.level || "-"} | 
          <span style="color:${riskColors[analysis.risk] || '#94a3b8'};">${riskLabel[analysis.risk] || analysis.risk || "-"}</span>
        </div>
        
        <div class="score-components">
          <div class="component">
            <label>${labels.trendComp}</label>
            <div class="bar-container">${makeBar(comps.trend || 0, 30)}</div>
            <span>${comps.trend || 0}</span>
          </div>
          <div class="component">
            <label>${labels.momentumComp}</label>
            <div class="bar-container">${makeBar(comps.momentum || 0, 20)}</div>
            <span>${comps.momentum || 0}</span>
          </div>
          <div class="component">
            <label>${labels.volumeComp}</label>
            <div class="bar-container">${makeBar(comps.volume || 0, 20)}</div>
            <span>${comps.volume || 0}</span>
          </div>
          <div class="component">
            <label>${labels.oiComp}</label>
            <div class="bar-container">${makeBar(comps.oi || 0, 20)}</div>
            <span>${comps.oi || 0}</span>
          </div>
          <div class="component">
            <label>${labels.fundingComp}</label>
            <div class="bar-container">${makeBar(comps.funding || 0, 10)}</div>
            <span>${comps.funding || 0}</span>
          </div>
        </div>
      </div>
    `;
  }).filter(x => x).join("");
}

// ============ 资金行为组件 ============
function renderCapitalBehaviors(items) {
  const target = document.querySelector("[data-capital-behaviors]");
  if (!target) return;

  target.innerHTML = items.map((item) => {
    const analysis = globalData.analysis[item.symbol];
    if (!analysis) return "";
    
    // 🟢 修正：如果是同步中，直接返回等待提示，不执行后面的变量声明
    if (analysis.isSyncing) {
      return `
        <div class="behavior-card" style="opacity: 0.6;">
          <div class="behavior-header"><strong>${item.symbol}</strong></div>
          <div class="behavior-type" style="color: #64748b; font-size:0.9rem; padding: 1rem 0;">⏳ 等待逐笔数据聚合 CVD 中...</div>
        </div>
      `;
    }

    // 只有非同步状态，才会声明并使用这些变量
    const behavior = analysis.capital_behavior;
    const price = analysis.price;

    return `
      <div class="behavior-card">
        <div class="behavior-header">
          <strong>${item.symbol}</strong>
          <span class="confidence">置信度: ${behavior.confidence}%</span>
        </div>
        
        <div class="behavior-type">${behavior.type}</div>
        
        <div class="behavior-signals">
          ${behavior.signals.map(s => `<span class="signal-tag">${s}</span>`).join("")}
        </div>
        
        <div class="behavior-implications">
          <strong>含义:</strong> ${behavior.implications}
        </div>
        
        <div class="behavior-suggestion">
          <strong>建议:</strong> ${behavior.suggestion}
        </div>
      </div>
    `;
  }).filter(x => x).join("");
}

// ============ 信号渲染（升级版） ============
function renderSignals(signalsBySymbol) {
  const target = document.querySelector("[data-signals]");
  const count = document.querySelector("[data-signal-count]");
  if (!target) return;

  const signals = Object.values(signalsBySymbol || {});
  if (count) count.textContent = `${signals.length}`;
  if (!signals.length) {
    target.innerHTML = `<div class="empty">${labels.noSignals}</div>`;
    return;
  }

  target.innerHTML = signals.map((signal) => {
    const analysis = globalData.analysis[signal.symbol];
    if (!analysis || analysis.isSyncing) return "";

    const dir = analysis.direction || "NEUTRAL";
    const dirText = dir === "LONG" ? labels.directionLong : dir === "SHORT" ? labels.directionShort : labels.directionNeutral;
    const dirEmoji = { LONG: "\u{1F7E2}", SHORT: "\u{1F534}", NEUTRAL: "\u{26AA}" };
    const reasons = analysis.reasons || [];
    const scoreColor = (analysis.score || 0) >= 85 ? "#10b981" : (analysis.score || 0) >= 70 ? "#f59e0b" : (analysis.score || 0) >= 55 ? "#3b82f6" : "#94a3b8";

    return `
      <div class="signal-item ${dir.toLowerCase()}">
        <div class="signal-header">
          <strong>${signal.symbol}</strong>
          <span class="recommendation" style="color:${scoreColor};">
            ${dirEmoji[dir] || "❓"} ${dirText} 
          </span>
        </div>
        <div class="signal-reason">
          ${reasons.map(r => `<div>• ${r}</div>`).join("")}
        </div>
        <p class="signal-desc">评分: <strong style="color:${scoreColor};">${analysis.score || 0}/100</strong> (${analysis.level || "-"}) | 风险: ${analysis.risk || "-"}</p>
      </div>
    `;
  }).filter(x => x).join("");
}

// ============ 订单流渲染（升级版） ============
function renderOrderFlow(signalsBySymbol) {
  const target = document.querySelector("[data-flow-grid]");
  if (!target) return;

  const signals = Object.values(signalsBySymbol || {});
  if (!signals.length) {
    target.innerHTML = `<div class="empty">${labels.noOrderFlow}</div>`;
    return;
  }

  target.innerHTML = signals.map((signal) => {
    const trades = signal.trades || [];
    const buyVolume = trades.filter((x) => x.side === "buy").reduce((sum, x) => sum + Number(x.size || 0), 0);
    const sellVolume = trades.filter((x) => x.side === "sell").reduce((sum, x) => sum + Number(x.size || 0), 0);
    const cvd = signal.cvd || 0;
    const totalVol = buyVolume + sellVolume;
    const buyRatio = totalVol > 0 ? (buyVolume / totalVol) * 100 : 50;
    
    const asks = signal.books?.asks || [];
    const bids = signal.books?.bids || [];
    const topAsk = asks[0] ? `${asks[0][0]} / ${fmtNumber(asks[0][1], 2)}` : "-";
    const topBid = bids[0] ? `${bids[0][0]} / ${fmtNumber(bids[0][1], 2)}` : "-";

    // 订单流判断
    let flowJudgment = "均衡";
    if (buyRatio > 65) flowJudgment = "买方占优";
    else if (buyRatio < 35) flowJudgment = "卖方占优";

    return `
      <div class="flow-card">
        <div class="flow-head">
          <strong>${signal.symbol}</strong>
          <span class="${cvd >= 0 ? "positive" : "negative"}">CVD ${fmtNumber(cvd, 2)}</span>
        </div>
        
        <div class="flow-metrics">
          <div><label>${labels.buyVol}</label><strong>${fmtNumber(buyVolume, 2)}</strong></div>
          <div><label>${labels.sellVol}</label><strong>${fmtNumber(sellVolume, 2)}</strong></div>
          <div><label>${labels.bestAsk}</label><strong>${topAsk}</strong></div>
          <div><label>${labels.bestBid}</label><strong>${topBid}</strong></div>
        </div>
        
        <div class="flow-ratio">
          <div>主动买: ${buyRatio.toFixed(1)}%</div>
          <div>主动卖: ${(100 - buyRatio).toFixed(1)}%</div>
          <div class="judgment">${flowJudgment}</div>
        </div>
      </div>
    `;
  }).join("");
}

// ============ 监控列表渲染 ============
function renderWatchlist(items, prices, signals) {
  const target = document.querySelector("[data-watchlist]");
  const count = document.querySelector("[data-watch-count]");
  if (!target) return;

  if (count) count.textContent = `${items.length} 个币种`;
  target.innerHTML = items.map((item) => {
    const ticker = prices[item.symbol] || {};
    const signal = signals[item.symbol] || {};
    const analysis = globalData.analysis[item.symbol] || {};
    const dirIcon = { LONG: "\u{1F7E2}", SHORT: "\u{1F534}", NEUTRAL: "\u{26AA}" }[analysis.direction] || "";

    return `
      <div class="watch-row" data-symbol="${item.symbol}">
        <span>${dirIcon} ${item.symbol}</span>
        <span>${item.timeframe}</span>
        <span>${fmtNumber(ticker.price)}</span>
        <span>${analysis.direction || "-"}</span>
        <span>${(ticker.source || "-").toUpperCase()}</span>
        <span class="score">${analysis.score || "-"}</span>
        <span><button class="del-btn" onclick="removeCoin('${item.symbol}')">删除</button></span>
      </div>
    `;
  }).join("");
}

// ============ 添加/删除币种（可搜索下拉） ============
let availableCoins = [];
let selectedCoin = null;

async function loadAvailableCoins() {
  if (availableCoins.length > 0) { renderDropdown(availableCoins); return; }
  try {
    const resp = await fetch(`${apiBase}/api/coins/available`);
    if (!resp.ok) throw new Error(await resp.text());
    availableCoins = await resp.json();
    renderDropdown(availableCoins);
  } catch (e) {
    console.warn("加载可用币种失败:", e);
  }
}

function filterAvailableCoins(query) {
  const q = query.toUpperCase().trim();
  if (!q) { renderDropdown(availableCoins); return; }
  const filtered = availableCoins.filter(c => c.symbol.includes(q));
  renderDropdown(filtered);
}

function renderDropdown(coins) {
  const dd = document.getElementById("coin-dropdown");
  if (!coins.length) {
    dd.innerHTML = '<div class="coin-dropdown-empty">无匹配币种</div>';
    dd.classList.add("show");
    return;
  }
  dd.innerHTML = coins.slice(0, 50).map(c => `
    <div class="coin-dropdown-item${selectedCoin === c.symbol ? ' selected' : ''}"
         onclick="selectCoin('${c.symbol}')">
      <span class="sym">${c.symbol}</span>
      <span>
        <span class="price">${c.last ? '$' + c.last.toLocaleString() : '-'}</span>
        <span class="vol"> | 24h量: ${(c.vol24h / 1000000).toFixed(1)}M</span>
      </span>
    </div>
  `).join("");
  dd.classList.add("show");
}

function selectCoin(symbol) {
  selectedCoin = symbol;
  document.getElementById("new-coin-search").value = symbol;
  document.getElementById("coin-dropdown").classList.remove("show");
}

// 点击外部关闭下拉框
document.addEventListener("click", function(e) {
  const wrapper = document.querySelector(".coin-search-wrapper");
  if (wrapper && !wrapper.contains(e.target)) {
    const dd = document.getElementById("coin-dropdown");
    if (dd) dd.classList.remove("show");
  }
});

async function addCoinFromSearch() {
  const symbol = selectedCoin || document.getElementById("new-coin-search").value.trim().toUpperCase();
  if (!symbol) { alert("请选择或输入币种"); return; }
  // 移除 -SWAP 后缀（如果用户输入了完整 instId）
  const cleanSymbol = symbol.replace("-SWAP", "");
  try {
    const resp = await fetch(`${apiBase}/api/coins`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ symbol: cleanSymbol, alias: cleanSymbol, timeframe: "15m" }),
    });
    if (!resp.ok) throw new Error(await resp.text());
    document.getElementById("new-coin-search").value = "";
    selectedCoin = null;
    document.getElementById("coin-dropdown").classList.remove("show");
    refresh();
  } catch (e) {
    alert("添加失败: " + e.message);
  }
}

async function removeCoin(symbol) {
  if (!confirm(`确定删除 ${symbol}？`)) return;
  try {
    const resp = await fetch(`${apiBase}/api/coins/${symbol}`, { method: "DELETE" });
    if (!resp.ok) throw new Error(await resp.text());
    refresh();
  } catch (e) {
    alert("删除失败: " + e.message);
  }
}

// ============ 离线渲染 ============
function renderOffline(error) {
  const status = document.querySelector("[data-network-status]");
  if (status) {
    status.textContent = `${fallbackDot} ${labels.backendOffline}`;
    status.classList.add("fallback");
  }
  const grid = document.querySelector("[data-market-grid]");
  if (grid) grid.innerHTML = `<article class="market-card skeleton">${error.message}</article>`;
}

// ============ 初始化和定时器 ============
refresh();
setInterval(refresh, CONFIG.refreshInterval);
// 🟢 追加呼吸动画样式，让加载文本有闪烁效果
const style = document.createElement('style');
style.innerHTML = `@keyframes pulse { 0% { opacity: 0.6; } 50% { opacity: 1; } 100% { opacity: 0.6; } }`;
document.head.appendChild(style);

console.log(`行情终端已启动 [刷新: ${CONFIG.refreshInterval}ms, 分析: ${CONFIG.analysisInterval}ms]`);

// 🟢 关闭浏览器窗口时通知后端停止
window.addEventListener('beforeunload', function() {
  // sendBeacon 比 fetch 更可靠（浏览器不会在页面关闭时取消该请求）
  navigator.sendBeacon(`${apiBase}/api/shutdown`, '{}');
});
