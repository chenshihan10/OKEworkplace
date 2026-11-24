/** 订单流（REST 采样）状态管理 */
const API_BASE = '/api/v3/orderflow';

const state = { items: [], bySymbol: {}, updatedAt: null };

export async function refreshOrderflow() {
  try {
    const res = await fetch(API_BASE, { cache: 'no-store' });
    if (!res.ok) return;
    const data = await res.json();
    state.items = data.items || [];
    state.updatedAt = data.updated_at || null;
    state.bySymbol = {};
    for (const item of state.items) state.bySymbol[item.symbol] = item;
  } catch (e) {
    // 保留上一次数据
  }
}

export function getOrderflowItems() { return state.items; }
export function getOrderflow(symbol) { return state.bySymbol[symbol] || null; }
