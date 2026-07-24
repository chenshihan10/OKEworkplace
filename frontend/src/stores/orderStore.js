/** V2.3 订单状态管理 */
import { eventBus } from './systemStore.js';

const API_BASE = '/api/v2.3';

let state = {
  orders: [],
  summary: { open_orders: 0, today_closed: 0, total_pnl: 0, total_closed: 0, win_rate: 0 },
  history: [],
};

/** 刷新订单列表 */
export async function refreshOrders() {
  try {
    const res = await fetch(`${API_BASE}/orders`);
    const data = await res.json();
    state.orders = data.orders || [];

    const sumRes = await fetch(`${API_BASE}/orders/summary`);
    state.summary = await sumRes.json();

    eventBus.emit('orders:updated');
  } catch (e) {
    console.error('刷新订单失败', e);
  }
}

/** 开单 */
export async function createOrder(symbol, direction, entryPrice, quantity, note) {
  const res = await fetch(`${API_BASE}/orders`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      symbol,
      direction,
      entry_price: entryPrice,
      quantity: quantity || 0,
      note: note || '',
    }),
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

/** 获取状态 */
export function getOrders() { return state.orders; }
export function getSummary() { return state.summary; }
