import { apiBase, getJson } from './api/okx.js';
import { fetchNetworkStatus } from './api/network.js';
import { fetchSnapshot, fetchAnalysis } from './api/analysis.js';
import { updateSnapshot, getPrices, getSignals, getSnapshot } from './stores/marketStore.js';
import { updateAnalysis, getAllAnalysis } from './stores/analysisStore.js';
import { updateNetwork, setOffline, eventBus } from './stores/systemStore.js';
import { renderMarketCards } from './render/MarketCard.js';
import { renderMarketScores } from './render/ScoreCard.js';
import { renderSignals } from './render/SignalCard.js';
import { renderWatchlist } from './render/WatchlistCard.js';
import { initOrderCard, renderOrders } from './render/OrderCard.js';
import { refreshOrders } from './stores/orderStore.js';
import { initTabs } from './views/tabManager.js';

const CONFIG = {
  refreshInterval: 1000,
  analysisInterval: 2000,
};

// 开发模式：仅在 ?dev=1 时启用前端文件变更自动刷新；正式版无该参数，不产生任何请求
const DEV_RELOAD = new URLSearchParams(window.location.search).has('dev');

// 主动刷新（热更新/手动）时不要触发退出信标，否则 reload 会把后端一起关掉
function reloadPage() {
  window.__okeReloading = true;
  window.location.reload();
}

function watchFrontendChanges() {
  if (!DEV_RELOAD) return;
  let baseline = null;
  setInterval(async () => {
    try {
      const res = await fetch(`${apiBase}/dev/frontend-version`, { cache: 'no-store' });
      if (!res.ok) return;
      const data = await res.json();
      if (baseline === null) {
        baseline = data.version;
        return;
      }
      if (data.version !== baseline) {
        reloadPage();
      }
    } catch (error) {
      // 后端未就绪时忽略，下一轮再试
    }
  }, 1500);
}

// 手动刷新兜底：F5 / Ctrl+R
document.addEventListener('keydown', (event) => {
  const isF5 = event.key === 'F5';
  const isReload = (event.ctrlKey || event.metaKey) && (event.key === 'r' || event.key === 'R');
  if (isF5 || isReload) {
    event.preventDefault();
    reloadPage();
  }
});

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

    // 订单刷新（独立轮询，不阻塞行情渲染）
    refreshOrders().then(renderOrders).catch(() => {});

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
  renderSignals(signals);
  renderWatchlist(items, prices, signals);
}

// 顶部轻提示：5 秒自动消失，不打断操作
let toastState = { key: '', at: 0 };
let toastTimer = null;

function showToast(text, duration = 5000) {
  const el = document.getElementById('app-toast');
  if (!el) return;
  el.textContent = text;
  el.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove('show'), duration);
}

function renderNetwork(data) {
  const target = document.querySelector('[data-network-status]');
  if (!target) return;
  
  const realDot = '\u{1F7E2}';
  const fallbackDot = '\u{1F7E1}';
  const isReal = data.data_source === 'REAL';
  const labels = { realData: '实时数据 (OKX)', fallbackData: '数据不可用', proxyDisabled: '代理已禁用' };
  
  target.textContent = isReal ? `${realDot} ${labels.realData}` : `${fallbackDot} ${labels.fallbackData}`;
  target.classList.toggle('real', isReal);
  target.classList.toggle('fallback', !isReal);
  target.title = data.proxy_enabled ? `代理: ${data.proxy}` : labels.proxyDisabled;

  // 行情不可用时给一条轻提示（代理端口来自后端配置，不写死）
  const unavailableKey = isReal ? '' : `${data.proxy_enabled}|${data.proxy}`;
  if (isReal) {
    toastState.key = '';
  } else if (toastState.key !== unavailableKey || Date.now() - toastState.at > 60000) {
    toastState.key = unavailableKey;
    toastState.at = Date.now();
    const text = data.proxy_enabled
      ? `代理未启动，行情暂不可用（${data.proxy}）`
      : '行情暂不可用：网络不可达';
    showToast(text);
  }
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

// ============================================================
// 开单模态框（全局函数，供 onclick 调用）
// ============================================================
let _modalDirection = 'LONG';

window.__openOrderModal = function(symbol, price) {
  document.getElementById('modal-symbol').value = symbol;
  document.getElementById('modal-price').value = price || 0;
  document.getElementById('modal-quantity').value = '';
  document.getElementById('modal-note').value = '';
  _modalDirection = 'LONG';
  _updateModalDirectionBtn();
  document.getElementById('order-modal').style.display = 'flex';
};

function closeOrderModal() {
  document.getElementById('order-modal').style.display = 'none';
}
window.closeOrderModal = closeOrderModal;

function _updateModalDirectionBtn() {
  const longBtn = document.getElementById('modal-direction-long');
  const shortBtn = document.getElementById('modal-direction-short');
  if (_modalDirection === 'LONG') {
    longBtn.style.background = '#22c55e';
    longBtn.style.color = '#fff';
    shortBtn.style.background = '#334155';
    shortBtn.style.color = '#94a3b8';
  } else {
    shortBtn.style.background = '#ef4444';
    shortBtn.style.color = '#fff';
    longBtn.style.background = '#334155';
    longBtn.style.color = '#94a3b8';
  }
}

document.addEventListener('click', function(e) {
  if (e.target.id === 'modal-direction-long') {
    _modalDirection = 'LONG';
    _updateModalDirectionBtn();
  } else if (e.target.id === 'modal-direction-short') {
    _modalDirection = 'SHORT';
    _updateModalDirectionBtn();
  } else if (e.target.id === 'modal-confirm') {
    _submitOrder();
  }
});

async function _submitOrder() {
  const symbol = document.getElementById('modal-symbol').value;
  const price = parseFloat(document.getElementById('modal-price').value);
  const quantity = parseFloat(document.getElementById('modal-quantity').value) || 0;
  const note = document.getElementById('modal-note').value;

  if (!symbol || !price || price <= 0) {
    alert('请输入有效的价格');
    return;
  }

  try {
    const { createOrder } = await import('./stores/orderStore.js');
    await createOrder(symbol, _modalDirection, price, quantity, note);
    closeOrderModal();
    // 通知订单模块刷新
    const { refreshOrders } = await import('./stores/orderStore.js');
    const { renderOrders } = await import('./render/OrderCard.js');
    await refreshOrders();
    renderOrders();
  } catch (e) {
    alert(`开单失败: ${e.message}`);
  }
}

// 版本号来自后端 /health，保证界面与真正运行的进程一致
async function loadVersion() {
  const target = document.querySelector('[data-app-version]');
  if (!target) return;
  try {
    const res = await fetch(`${apiBase}/health`, { cache: 'no-store' });
    const data = await res.json();
    if (data && data.version) target.textContent = `v${data.version}`;
  } catch (error) {
    // 后端未就绪时保留占位，不打断主流程
  }
}

// 初始化
function init() {
  // 初始化订单模块
  initOrderCard();
  
  // 初始化标签页
  initTabs();
  
  // 添加呼吸动画
  const style = document.createElement('style');
  style.innerHTML = '@keyframes pulse { 0% { opacity: 0.6; } 50% { opacity: 1; } 100% { opacity: 0.6; } }';
  document.head.appendChild(style);
  
  // 启动
  loadVersion();
  watchFrontendChanges();
  refresh();
  setInterval(refresh, CONFIG.refreshInterval);
  
  // 关闭时通知后端（热刷新/手动刷新时不通知，否则会把后端一起关掉）
  window.addEventListener('beforeunload', function() {
    if (window.__okeReloading) return;
    navigator.sendBeacon(`${apiBase}/api/shutdown`, '{}');
  });
  
  console.log(`行情终端已启动 [刷新: ${CONFIG.refreshInterval}ms, 分析: ${CONFIG.analysisInterval}ms]`);
}

// 启动
init();
