import { apiBase, getJson } from './api/okx.js';
import { fetchNetworkStatus } from './api/network.js';
import { fetchSnapshot, fetchAnalysis } from './api/analysis.js';
import { updateSnapshot, getPrices, getSignals, getSnapshot } from './stores/marketStore.js';
import { updateAnalysis, getAllAnalysis } from './stores/analysisStore.js';
import { updateNetwork, setOffline, eventBus } from './stores/systemStore.js';
import { renderMarketCards } from './render/MarketCard.js';
import { renderMarketScores } from './render/ScoreCard.js';
import { renderCapitalBehaviors } from './render/CapitalCard.js';
import { renderSignals } from './render/SignalCard.js';
import { renderWatchlist } from './render/WatchlistCard.js';
import { initTabs } from './views/tabManager.js';

const CONFIG = {
  refreshInterval: 1000,
  analysisInterval: 2000,
};

let globalData = {
  network: null,
  snapshot: null,
  analysis: {},
  lastAnalysisUpdate: 0,
};

async function refresh() {
  try {
    const [network, snapshot] = await Promise.all([
      fetchNetworkStatus(),
      fetchSnapshot(),
    ]);

    if (network) {
      globalData.network = network;
      updateNetwork(network);
      setOffline(false);
      renderNetwork(network);
    }
    
    if (snapshot) {
      globalData.snapshot = snapshot;
      updateSnapshot(snapshot);
      renderSnapshot(snapshot);
    }

    const now = Date.now();
    if (now - globalData.lastAnalysisUpdate > CONFIG.analysisInterval) {
      await refreshAnalysis(snapshot);
      globalData.lastAnalysisUpdate = now;
    }
  } catch (error) {
    setOffline(true);
    renderOffline(error);
  }
}

async function refreshAnalysis(snapshot) {
  if (!snapshot) return;
  const items = snapshot.watch_items || [];
  
  for (const item of items) {
    try {
      const analysis = await fetchAnalysis(item.symbol);
      if (analysis) {
        globalData.analysis[item.symbol] = analysis;
        updateAnalysis(item.symbol, analysis);
      }
    } catch (error) {
      console.error(`分析错误: ${item.symbol}`, error);
    }
  }
}

function renderSnapshot(data) {
  const updated = document.querySelector('[data-updated-at]');
  if (updated) {
    updated.textContent = data.updated_at 
      ? new Date(data.updated_at).toLocaleTimeString('zh-CN') 
      : '--';
  }

  const prices = getPrices();
  const signals = getSignals();
  const items = data.watch_items || [];

  renderMarketCards(items, prices, signals);
  renderMarketScores(items);
  renderCapitalBehaviors(items);
  renderSignals(signals);
  renderOrderFlow(signals);
  renderWatchlist(items, prices, signals);
}

function renderNetwork(data) {
  const target = document.querySelector('[data-network-status]');
  if (!target) return;
  
  const realDot = '\u{1F7E2}';
  const fallbackDot = '\u{1F7E1}';
  const isReal = data.data_source === 'REAL';
  const labels = { realData: '实时数据 (OKX)', fallbackData: '本地数据', proxyDisabled: '代理已禁用' };
  
  target.textContent = isReal ? `${realDot} ${labels.realData}` : `${fallbackDot} ${labels.fallbackData}`;
  target.classList.toggle('real', isReal);
  target.classList.toggle('fallback', !isReal);
  target.title = data.proxy_enabled ? `代理: ${data.proxy}` : labels.proxyDisabled;
}

function renderOrderFlow(signalsBySymbol) {
  const target = document.querySelector('[data-flow-grid]');
  if (!target) return;

  const signals = Object.values(signalsBySymbol || {});
  if (!signals.length) {
    target.innerHTML = '<div class="empty">暂无订单流</div>';
    return;
  }

  target.innerHTML = signals.map((signal) => {
    const trades = signal.trades || [];
    const buyVolume = trades.filter(x => x.side === 'buy').reduce((sum, x) => sum + Number(x.size || 0), 0);
    const sellVolume = trades.filter(x => x.side === 'sell').reduce((sum, x) => sum + Number(x.size || 0), 0);
    const cvd = signal.cvd || 0;
    const totalVol = buyVolume + sellVolume;
    const buyRatio = totalVol > 0 ? (buyVolume / totalVol) * 100 : 50;
    
    const asks = signal.books?.asks || [];
    const bids = signal.books?.bids || [];
    const topAsk = asks[0] ? `${asks[0][0]} / ${fmtNumber(asks[0][1], 2)}` : '-';
    const topBid = bids[0] ? `${bids[0][0]} / ${fmtNumber(bids[0][1], 2)}` : '-';

    let flowJudgment = '均衡';
    if (buyRatio > 65) flowJudgment = '买方占优';
    else if (buyRatio < 35) flowJudgment = '卖方占优';

    return `
      <div class="flow-card">
        <div class="flow-head">
          <strong>${signal.symbol}</strong>
          <span class="${cvd >= 0 ? 'positive' : 'negative'}">CVD ${fmtNumber(cvd, 2)}</span>
        </div>
        <div class="flow-metrics">
          <div><label>买入量</label><strong>${fmtNumber(buyVolume, 2)}</strong></div>
          <div><label>卖出量</label><strong>${fmtNumber(sellVolume, 2)}</strong></div>
          <div><label>最优卖价</label><strong>${topAsk}</strong></div>
          <div><label>最优买价</label><strong>${topBid}</strong></div>
        </div>
        <div class="flow-ratio">
          <div>主动买: ${buyRatio.toFixed(1)}%</div>
          <div>主动卖: ${(100 - buyRatio).toFixed(1)}%</div>
          <div class="judgment">${flowJudgment}</div>
        </div>
      </div>
    `;
  }).join('');
}

function renderOffline(error) {
  const fallbackDot = '\u{1F7E1}';
  const status = document.querySelector('[data-network-status]');
  if (status) {
    status.textContent = `${fallbackDot} 后端离线`;
    status.classList.add('fallback');
  }
  const grid = document.querySelector('[data-market-grid]');
  if (grid) grid.innerHTML = `<article class="market-card skeleton">${error.message}</article>`;
}

// 暴露 refresh 给全局，供 api/analysis.js 等模块调用
window.refresh = refresh;

// 点击外部关闭下拉框
document.addEventListener("click", function(e) {
  const wrapper = document.querySelector(".coin-search-wrapper");
  if (wrapper && !wrapper.contains(e.target)) {
    const dd = document.getElementById("coin-dropdown");
    if (dd) dd.classList.remove("show");
  }
});

// 辅助：fmtNumber（导入或本地）
function fmtNumber(value, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return '-';
  return Number(value).toLocaleString(undefined, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

// 初始化
function init() {
  // 初始化标签页
  initTabs();
  
  // 添加呼吸动画
  const style = document.createElement('style');
  style.innerHTML = '@keyframes pulse { 0% { opacity: 0.6; } 50% { opacity: 1; } 100% { opacity: 0.6; } }';
  document.head.appendChild(style);
  
  // 启动
  refresh();
  setInterval(refresh, CONFIG.refreshInterval);
  
  // 关闭时通知后端
  window.addEventListener('beforeunload', function() {
    navigator.sendBeacon(`${apiBase}/api/shutdown`, '{}');
  });
  
  console.log(`行情终端已启动 [刷新: ${CONFIG.refreshInterval}ms, 分析: ${CONFIG.analysisInterval}ms]`);
}

// 启动
init();
