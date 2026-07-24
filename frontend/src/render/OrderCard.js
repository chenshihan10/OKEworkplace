/** V2.3 订单管理渲染 */
import { fmtNumber, dirIcons } from '../utils/format.js';
import { getOrders, getSummary, closeOrder } from '../stores/orderStore.js';
import { getPrices } from '../stores/marketStore.js';

let container;

export function initOrderCard() {
  container = document.querySelector('[data-orders-grid]');
}

export function renderOrders() {
  if (!container) initOrderCard();
  if (!container) return;

  const orders = getOrders();
  const summary = getSummary();
  const prices = getPrices();

  let html = '';

  // ── 统计概览 ──
  html += `
    <div class="order-summary" style="display:flex;gap:20px;padding:12px 16px;background:#0f172a;border-radius:8px;margin-bottom:12px;flex-wrap:wrap;">
      <span>持有中: <strong>${summary.open_orders}</strong></span>
      <span>今日平仓: <strong>${summary.today_closed}</strong></span>
      <span>总盈亏: <strong style="color:${summary.total_pnl >= 0 ? '#22c55e' : '#ef4444'}">${summary.total_pnl >= 0 ? '+' : ''}${summary.total_pnl} USDT</strong></span>
      <span>胜率: <strong>${summary.win_rate}%</strong></span>
    </div>`;

  if (orders.length === 0) {
    html += `<div style="color:#64748b;text-align:center;padding:40px;">暂无持仓订单。在监控列表中点击 <strong>[📝 开单]</strong> 记录你的交易。</div>`;
  } else {
    for (const order of orders) {
      const currentPrice = prices[order.symbol]?.price || 0;
      const pnlPct = order.direction === 'LONG'
        ? (currentPrice - order.entry_price) / order.entry_price * 100
        : (order.entry_price - currentPrice) / order.entry_price * 100;
      const pnlColor = pnlPct >= 0 ? '#22c55e' : '#ef4444';
      const icon = dirIcons[order.direction] || '📊';

      html += `
        <div class="order-card" style="background:#0f172a;border:1px solid #1e293b;border-radius:8px;padding:12px 16px;margin-bottom:8px;">
          <div style="display:flex;justify-content:space-between;align-items:center;">
            <div>
              <strong>${order.symbol}</strong>
              <span style="margin-left:8px;">${icon} ${order.direction === 'LONG' ? '多头' : '空头'}</span>
            </div>
            <span style="font-size:0.8rem;color:#64748b;">${order.created_at?.replace('T', ' ') || ''}</span>
          </div>
          <div style="display:flex;gap:24px;margin-top:8px;flex-wrap:wrap;font-size:0.9rem;">
            <span>开仓价: <strong>${fmtNumber(order.entry_price)}</strong></span>
            <span>当前价: <strong>${fmtNumber(currentPrice)}</strong></span>
            <span>盈亏: <strong style="color:${pnlColor}">${pnlPct >= 0 ? '+' : ''}${pnlPct.toFixed(2)}%</strong></span>
            ${order.quantity ? `<span>数量: ${order.quantity}</span>` : ''}
            ${order.note ? `<span style="color:#94a3b8;">📝 ${order.note}</span>` : ''}
          </div>
          <div style="margin-top:8px;display:flex;gap:8px;justify-content:flex-end;">
            <button onclick="window.__closeOrder(${order.id}, '${order.symbol}', ${currentPrice})"
                    style="padding:4px 12px;background:#dc2626;color:#fff;border:none;border-radius:4px;cursor:pointer;font-size:0.8rem;">✕ 平仓</button>
          </div>
        </div>`;
    }
  }

  container.innerHTML = html;
}

// 挂载平仓函数到 window（简化交互）
window.__closeOrder = async (orderId, symbol, price) => {
  if (!confirm(`确定平仓 ${symbol} 订单 #${orderId} 吗？`)) return;
  try {
    await closeOrder(orderId, price);
    renderOrders();
  } catch (e) {
    alert(`平仓失败: ${e.message}`);
  }
};
