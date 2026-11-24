/** V2.3 订单状态管理 */
import { eventBus } from './systemStore.js';

const API_BASE = '/api/v2.3';
const RISK_BASE = '/api/v3/risk';

let state = {
  orders: [],
  summary: { open_orders: 0, today_closed: 0, total_pnl: 0, total_closed: 0, win_rate: 0 },
  history: [],
  levels: [],
  riskEvents: [],
  portfolio: null,
  riskSettings: null,
};

// 组合风险数据变化慢，5 秒刷新一次即可；价格触达仍随订单每秒检查
let _lastPortfolioAt = 0;
const PORTFOLIO_INTERVAL_MS = 5000;

/** 刷新订单列表 */
export async function refreshOrders() {
  try {
    const res = await fetch(`${API_BASE}/orders`);
    const data = await res.json();
    state.orders = data.orders || [];

    const sumRes = await fetch(`${API_BASE}/orders/summary`);
    state.summary = await sumRes.json();

    // 价格触及建议（后端已做 30 分钟冷却，同时返回新触发的止损/止盈事件）
    try {
      const levelRes = await fetch(`${API_BASE}/price-levels/check`);
      const levelData = await levelRes.json();
      state.levels = levelData.levels || [];
      state.riskEvents = levelData.risk_events || [];
    } catch (e) {
      state.levels = [];
      state.riskEvents = [];
    }

    if (Date.now() - _lastPortfolioAt > PORTFOLIO_INTERVAL_MS) {
      _lastPortfolioAt = Date.now();
      try {
        const riskRes = await fetch(`${API_BASE}/risk/portfolio`);
        state.portfolio = await riskRes.json();
      } catch (e) {
        // 保留上一份组合数据
      }
      if (!state.riskSettings) {
        try {
          const setRes = await fetch(`${RISK_BASE}/settings`);
          state.riskSettings = await setRes.json();
        } catch (e) {
          state.riskSettings = null;
        }
      }
    }

    eventBus.emit('orders:updated');
  } catch (e) {
    console.error('刷新订单失败', e);
  }
}

/** 开单（可选止损/止盈） */
export async function createOrder(symbol, direction, entryPrice, quantity, note, stopLoss, takeProfit) {
  const payload = {
    symbol,
    direction,
    entry_price: entryPrice,
    quantity: quantity || 0,
    note: note || '',
  };
  if (stopLoss !== null && stopLoss !== undefined && stopLoss !== '') payload.stop_loss = Number(stopLoss);
  if (takeProfit !== null && takeProfit !== undefined && takeProfit !== '') payload.take_profit = Number(takeProfit);

  const res = await fetch(`${API_BASE}/orders`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(await res.text());
  await refreshOrders();
  return res.json();
}

/** 平仓 */
export async function closeOrder(orderId, closePrice) {
  const res = await fetch(`${API_BASE}/orders/${orderId}/close`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ close_price: closePrice }),
  });
  if (!res.ok) throw new Error(await res.text());
  await refreshOrders();
  return res.json();
}

/** 设置/清除止损止盈（传 null 表示清除） */
export async function updateOrderRisk(orderId, stopLoss, takeProfit) {
  const res = await fetch(`${API_BASE}/orders/${orderId}/risk`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ stop_loss: stopLoss, take_profit: takeProfit }),
  });
  if (!res.ok) throw new Error(await res.text());
  await refreshOrders();
  return res.json();
}

/** 读取风险偏好 */
export async function fetchRiskSettings() {
  const res = await fetch(`${RISK_BASE}/settings`);
  if (!res.ok) throw new Error(await res.text());
  state.riskSettings = await res.json();
  return state.riskSettings;
}

/** 保存风险偏好 */
export async function saveRiskSettings(payload) {
  const res = await fetch(`${RISK_BASE}/settings`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(await res.text());
  state.riskSettings = await res.json();
  _lastPortfolioAt = 0;
  await refreshOrders();
  return state.riskSettings;
}

/** 获取状态 */
export function getOrders() { return state.orders; }
export function getSummary() { return state.summary; }
export function getLevels() { return state.levels; }
export function getRiskEvents() { return state.riskEvents; }
export function getPortfolio() { return state.portfolio; }
export function getRiskSettings() { return state.riskSettings; }
