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
import { renderPerformance } from './render/PerformanceCard.js';
import { refreshMtf, getMtfItems } from './stores/mtfStore.js';
import { renderMtf } from './render/MtfCard.js';
import { refreshOrderflow } from './stores/flowStore.js';
import { renderOrderflow } from './render/OrderFlowCard.js';
import { refreshOrders, getRiskSettings, fetchRiskSettings, saveRiskSettings } from './stores/orderStore.js';
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

    // 数据可用性提示：启动判定一次 + 长时间停更判定
    if (network) checkDataAvailability(network, snapshot || globalData.snapshot);

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

  renderMarketCards(items, prices, signals, getMtfItems());
  renderMarketScores(items);
  renderSignals(signals);
  renderWatchlist(items, prices, signals);
}

// 顶部轻提示：5 秒自动消失，不打断操作
let toastTimer = null;
// 提示策略：启动检查一次；之后仅在数据长时间停更时提示一次
const toastState = { startupChecked: false, staleNotified: false, pageStartedAt: Date.now() };

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

  // 中间态直接体现在 title 上：仍显示实时数据，但能看到最近一次更新距今多久
  const ageNote = typeof data.data_age_seconds === 'number' ? ` · 最近数据 ${data.data_age_seconds}s 前` : '';
  target.title = data.proxy_enabled ? `代理: ${data.proxy}${ageNote}` : labels.proxyDisabled;
}

/** 提示里只展示 host:port，不要把完整代理 URL 抛给用户 */
function proxyHostPort(data) {
  return (data.proxy || '').replace(/^https?:\/\//, '') || '未配置';
}

/**
 * 提示策略（替换原先的“每次轮询重新触发”）：
 * 1. 进入界面后判断一次，数据不可用才提示（带代理端口）；
 * 2. 之后只在数据超过 stale_seconds 无更新时提示一次，恢复后自动复位；
 * 3. 单次失败/抖动完全静默，状态不翻转，界面继续用上一次数据。
 */
function checkDataAvailability(network, snapshot) {
  const isReal = network.data_source === 'REAL';
  const bootCheck = network.boot_check_seconds || 10;
  const staleAfter = network.stale_seconds || 60;
  const lastSuccessAt = snapshot?.last_success_at || network.last_success_at || null;
  const age = lastSuccessAt ? (Date.now() - new Date(lastSuccessAt).getTime()) / 1000 : null;

  if (!toastState.startupChecked) {
    if (isReal) {
      toastState.startupChecked = true;
    } else if (age === null && (Date.now() - toastState.pageStartedAt) / 1000 < bootCheck) {
      return; // 刚启动，首笔数据还没到，先不判定
    } else {
      toastState.startupChecked = true;
      showToast(network.proxy_enabled
        ? `代理未启动，行情暂不可用（${proxyHostPort(network)}）`
        : '行情暂不可用：网络不可达');
    }
  }

  // 从未成功取数时，启动提示已经覆盖，不再重复提示
  if (age === null) return;

  if (age > staleAfter) {
    if (!toastState.staleNotified) {
      toastState.staleNotified = true;
      showToast(`数据已停止更新（已 ${Math.floor(age)} 秒）`);
    }
  } else {
    toastState.staleNotified = false;
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
  document.getElementById('modal-stop-loss').value = '';
  document.getElementById('modal-take-profit').value = '';
  _modalDirection = 'LONG';
  _updateModalDirectionBtn();
  _updateSuggestedQty();
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
  _updateSuggestedQty();
}

// 建议数量 = 权益 × 单笔风险% / |开仓价 - 止损价|（仅提示，不自动填数量）
function _updateSuggestedQty() {
  const target = document.getElementById('modal-suggested');
  if (!target) return;
  const settings = getRiskSettings() || {};
  const equity = Number(settings.equity);
  const riskPct = Number(settings.risk_per_trade_pct || 1);
  const entry = parseFloat(document.getElementById('modal-price')?.value);
  const sl = parseFloat(document.getElementById('modal-stop-loss')?.value);

  if (!equity || !entry || !sl || entry <= 0 || entry === sl) {
    target.textContent = settings.equity
      ? '建议数量：填写开仓价与止损价后显示'
      : '建议数量：请先在「风险设置」配置账户权益';
    return;
  }
  const qty = equity * riskPct / 100 / Math.abs(entry - sl);
  target.textContent = `建议数量：${qty.toFixed(6)}（按单笔风险 ${riskPct}%，仅提示）`;
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
  } else if (e.target.id === 'risk-confirm') {
    _saveRiskModal();
  }
});

// 开仓价 / 止损价变化时实时更新建议数量
['modal-price', 'modal-stop-loss'].forEach(id => {
  document.getElementById(id)?.addEventListener('input', _updateSuggestedQty);
});

async function _submitOrder() {
  const symbol = document.getElementById('modal-symbol').value;
  const price = parseFloat(document.getElementById('modal-price').value);
  const quantity = parseFloat(document.getElementById('modal-quantity').value) || 0;
  const note = document.getElementById('modal-note').value;
  const stopLoss = document.getElementById('modal-stop-loss').value;
  const takeProfit = document.getElementById('modal-take-profit').value;

  if (!symbol || !price || price <= 0) {
    alert('请输入有效的价格');
    return;
  }

  try {
    const { createOrder } = await import('./stores/orderStore.js');
    await createOrder(symbol, _modalDirection, price, quantity, note, stopLoss, takeProfit);
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

// ============================================================
// 风险设置模态框
// ============================================================
async function _openRiskModal() {
  try {
    const settings = await fetchRiskSettings();
    document.getElementById('risk-equity').value = settings.equity ?? '';
    document.getElementById('risk-per-trade').value = settings.risk_per_trade_pct ?? 1;
    document.getElementById('risk-portfolio').value = settings.max_portfolio_risk_pct ?? 6;
    document.getElementById('risk-concentration').value = settings.max_symbol_concentration_pct ?? 50;
  } catch (e) {
    // 读取失败也允许填写后保存
  }
  document.getElementById('risk-modal').style.display = 'flex';
}
window.__openRiskModal = _openRiskModal;

function closeRiskModal() {
  document.getElementById('risk-modal').style.display = 'none';
}
window.closeRiskModal = closeRiskModal;

async function _saveRiskModal() {
  const equityText = document.getElementById('risk-equity').value.trim();
  const equity = equityText === '' ? null : Number(equityText);
  const payload = {
    equity,
    risk_per_trade_pct: Number(document.getElementById('risk-per-trade').value) || 1,
    max_portfolio_risk_pct: Number(document.getElementById('risk-portfolio').value) || 6,
    max_symbol_concentration_pct: Number(document.getElementById('risk-concentration').value) || 50,
  };
  if (equity !== null && (!Number.isFinite(equity) || equity <= 0)) {
    alert('账户权益必须大于 0，留空表示未配置');
    return;
  }
  try {
    await saveRiskSettings(payload);
    closeRiskModal();
    const { renderOrders } = await import('./render/OrderCard.js');
    renderOrders();
    _updateSuggestedQty();
  } catch (e) {
    alert(`保存失败: ${e.message}`);
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

  // 多周期：后端 60 秒一轮，前端 10 秒轮询只读缓存
  const refreshMtfView = () => refreshMtf().then(() => {
    renderMtf();
    // 概览卡片也带多周期徽标，数据到达后立即重绘一次
    const snap = getSnapshot();
    if (snap) renderSnapshot(snap);
  }).catch(() => {});
  window.__okeRefreshMtf = refreshMtfView;
  refreshMtfView();
  setInterval(refreshMtfView, 10000);

  // 订单流：后端 10 秒采样一轮，前端同步 10 秒轮询
  const refreshOrderflowView = () => refreshOrderflow().then(renderOrderflow).catch(() => {});
  window.__okeRefreshOrderflow = refreshOrderflowView;
  refreshOrderflowView();
  setInterval(refreshOrderflowView, 10000);
  
  // 添加呼吸动画
  const style = document.createElement('style');
  style.innerHTML = '@keyframes pulse { 0% { opacity: 0.6; } 50% { opacity: 1; } 100% { opacity: 0.6; } }';
  document.head.appendChild(style);
  
  // 启动
  loadVersion();
  watchFrontendChanges();
  refresh();
  renderPerformance();
  setInterval(refresh, CONFIG.refreshInterval);
  // 绩效页数据变化慢，30 秒刷新即可
  setInterval(renderPerformance, 30000);
  
  // 关闭时通知后端（热刷新/手动刷新时不通知，否则会把后端一起关掉）
  window.addEventListener('beforeunload', function() {
    if (window.__okeReloading) return;
    const token = window.__OKE_TOKEN || '';
    navigator.sendBeacon(`${apiBase}/api/shutdown?token=${encodeURIComponent(token)}`, '{}');
  });
  
  console.log(`行情终端已启动 [刷新: ${CONFIG.refreshInterval}ms, 分析: ${CONFIG.analysisInterval}ms]`);
}

// 启动
init();
