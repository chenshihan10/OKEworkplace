/** 多周期（MTF）状态管理 */
const API_BASE = '/api/v3/mtf';

const state = {
  items: [],
  bySymbol: {},
  timeframes: ['15m', '1H', '4H'],
  updatedAt: null,
};

export async function refreshMtf() {
  try {
    const res = await fetch(API_BASE, { cache: 'no-store' });
    if (!res.ok) return;
    const data = await res.json();
    state.items = data.items || [];
    state.timeframes = data.timeframes || state.timeframes;
    state.updatedAt = data.updated_at || null;
    state.bySymbol = {};
    for (const item of state.items) state.bySymbol[item.symbol] = item;
  } catch (e) {
    // 后端未就绪时保留上一次数据
  }
}

export function getMtfItems() { return state.items; }
export function getMtf(symbol) { return state.bySymbol[symbol] || null; }
export function getMtfTimeframes() { return state.timeframes; }
