/** V2.3 订单管理渲染（含风险管理旁路展示） */
import { fmtNumber, dirIcons } from '../utils/format.js';
import {
  getOrders, getSummary, getLevels, closeOrder,
  getPortfolio, getRiskSettings, getRiskEvents, updateOrderRisk,
} from '../stores/orderStore.js';
import { getPrices } from '../stores/marketStore.js';

let container;

const RISK_STATE = {
  sl_hit: { text: '已触及止损（仅提示）', color: '#ef4444' },
  tp_hit: { text: '已触及止盈（仅提示）', color: '#22c55e' },
  no_stop: { text: '未设置止损', color: '#f59e0b' },
  normal: { text: '风险正常', color: '#64748b' },
};

export function initOrderCard() {
  container = document.querySelector('[data-orders-grid]');
}

function renderRiskSummary(portfolio, riskSettings) {
  const settings = riskSettings || portfolio?.settings || {};
  const equity = portfolio?.equity ?? settings.equity;
  const riskPct = portfolio?.risk_of_equity_pct;
  const net = portfolio?.net_exposure?.net;
  const noStop = (portfolio?.orders || []).filter(o => o.stop_loss === null || o.stop_loss === undefined).length;
  const warnings = portfolio?.warnings || [];

  const warningsHtml = warnings.length
    ? `<div style="margin-top:8px;display:flex;flex-direction:column;gap:2px;">
         ${warnings.map(w => `<span style="font-size:0.78rem;color:#f59e0b;">⚠ ${w}</span>`).join('')}
       </div>`
    : '';

  return `
    <div class="risk-summary" style="padding:12px 16px;background:#111c33;border:1px solid #1e293b;border-radius:8px;margin-bottom:12px;">
      <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px;">
        <strong style="color:#93c5fd;">🛡 组合风险</strong>
        <button onclick="window.__openRiskModal()"
                style="padding:3px 12px;background:#1e293b;color:#93c5fd;border:1px solid #3b82f6;border-radius:4px;cursor:pointer;font-size:0.78rem;">风险设置</button>
      </div>
      <div style="display:flex;gap:20px;flex-wrap:wrap;margin-top:8px;font-size:0.85rem;">
        <span>权益: <strong>${equity ? `${fmtNumber(equity)} USDT` : '未配置'}</strong></span>
        <span>总名义: <strong>${fmtNumber(portfolio?.total_notional || 0)}</strong></span>
        <span>计划风险: <strong>${fmtNumber(portfolio?.planned_risk || 0)}${riskPct !== null && riskPct !== undefined ? `（权益 ${riskPct}%）` : ''}</strong></span>
        <span>净敞口: <strong style="color:${net >= 0 ? '#22c55e' : '#ef4444'}">${net >= 0 ? '+' : ''}${fmtNumber(net || 0)}</strong></span>
        <span>未设止损: <strong style="color:${noStop ? '#f59e0b' : '#22c55e'}">${noStop}</strong></span>
        <span style="color:#64748b;">单笔 ${settings.risk_per_trade_pct ?? '-'}% · 组合 ${settings.max_portfolio_risk_pct ?? '-'}% · 集中度 ${settings.max_symbol_concentration_pct ?? '-'}%</span>
      </div>
      ${warningsHtml}
    </div>`;
}

function renderRiskEvents(events) {
  if (!events || !events.length) return '';
  const lines = events.map(e => {
    const label = e.event_type === 'sl_hit' ? '止损' : '止盈';
    const color = e.event_type === 'sl_hit' ? '#ef4444' : '#22c55e';
    return `<div style="font-size:0.8rem;color:${color};">
      ⚡ ${e.symbol} 订单 #${e.order_id} 触及${label}价 ${fmtNumber(e.level)}（现价 ${fmtNumber(e.price)}）· 仅提示，不自动平仓
    </div>`;
  }).join('');
  return `<div style="padding:8px 12px;background:rgba(239,68,68,0.08);border:1px solid #ef4444;border-radius:6px;margin-bottom:12px;">${lines}</div>`;
}

export function renderOrders() {
  if (!container) initOrderCard();
  if (!container) return;

  const orders = getOrders();
  const summary = getSummary();
  const prices = getPrices();
  const levels = getLevels();
  const portfolio = getPortfolio();
  const riskSettings = getRiskSettings();
  const riskEvents = getRiskEvents();
  const riskMap = {};
  for (const view of (portfolio?.orders || [])) riskMap[view.order_id] = view;
  const levelMap = {};
  for (const level of levels) levelMap[level.order_id] = level;

  const suggestionLabels = { hold: "建议持有", consider_close: "考虑平仓" };

  let html = '';

  // ── 组合风险汇总（仅后端可用时展示） ──
  if (portfolio) html += renderRiskSummary(portfolio, riskSettings);
  html += renderRiskEvents(riskEvents);

  // ── 统计概览 ──
  html += `
    <div class="order-summary" style="display:flex;gap:20px;padding:12px 16px;background:#0f172a;border-radius:8px;margin-bottom:12px;flex-wrap:wrap;">
      <span>持有中: <strong>${summary.open_orders}</strong></span>
      <span>今日平仓: <strong>${summary.today_closed}</strong></span>
      <span>总盈亏: <strong style="color:${summary.total_pnl >= 0 ? '#22c55e' : '#ef4444'}">${summary.total_pnl >= 0 ? '+' : ''}${summary.total_pnl} USDT</strong></span>
      <span>胜率: <strong>${summary.win_rate}%</strong></span>
    </div>`;

  if (orders.length === 0) {
    html += `<div style="color:#64748b;text-align:center;padding:40px;">暂无持仓订单。在概览页点击 <strong>[📝 开单]</strong> 记录你的交易。</div>`;
  } else {
    for (const order of orders) {
      const currentPrice = prices[order.symbol]?.price || 0;
      const pnlPct = order.direction === 'LONG'
        ? (currentPrice - order.entry_price) / order.entry_price * 100
        : (order.entry_price - currentPrice) / order.entry_price * 100;
      const pnlColor = pnlPct >= 0 ? '#22c55e' : '#ef4444';
      const icon = dirIcons[order.direction] || '📊';
      const level = levelMap[order.id];
      const label = level ? suggestionLabels[level.suggestion] : '';
      const risk = riskMap[order.id];

      let levelHtml = '';
      if (level && level.triggered && label) {
        const levelColor = level.suggestion === 'consider_close' ? '#f59e0b' : '#22c55e';
        const sign = level.distance_pct > 0 ? '+' : '';
        const cooldownNote = level.cooldown_remaining > 0
          ? `（${Math.ceil(level.cooldown_remaining / 60)} 分钟内已提示过）`
          : '';
        levelHtml = `<div style="margin-top:6px;font-size:0.8rem;color:${levelColor};">⚡ 价格触及开仓价（${sign}${level.distance_pct}%）· ${label}：${level.reason}${cooldownNote}</div>`;
      }

      const stateMeta = RISK_STATE[risk?.risk_state || 'normal'];
      const sl = order.stop_loss ?? null;
      const tp = order.take_profit ?? null;
      let riskLine = `
        <div style="display:flex;gap:16px;flex-wrap:wrap;margin-top:6px;font-size:0.82rem;color:#94a3b8;">
          <span>止损: <strong style="color:${sl !== null ? '#ef4444' : '#64748b'}">${sl !== null ? fmtNumber(sl) : '未设'}${risk?.sl_distance_pct !== null && risk?.sl_distance_pct !== undefined ? `（-${risk.sl_distance_pct}%）` : ''}</strong></span>
          <span>止盈: <strong style="color:${tp !== null ? '#22c55e' : '#64748b'}">${tp !== null ? fmtNumber(tp) : '未设'}${risk?.tp_distance_pct !== null && risk?.tp_distance_pct !== undefined ? `（+${risk.tp_distance_pct}%）` : ''}</strong></span>
          <span>盈亏比 R: <strong>${risk?.rr ?? '-'}</strong></span>
          <span>计划风险: <strong>${risk?.planned_risk !== null && risk?.planned_risk !== undefined ? `${fmtNumber(risk.planned_risk)} USDT` : '-'}</strong></span>
          <span>占权益: <strong>${risk?.risk_of_equity_pct !== null && risk?.risk_of_equity_pct !== undefined ? `${risk.risk_of_equity_pct}%` : '未配置权益'}</strong></span>
          <span style="color:${stateMeta.color};">● ${stateMeta.text}</span>
        </div>`;

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
          ${riskLine}
          ${levelHtml}
          <div style="margin-top:8px;display:flex;gap:8px;justify-content:flex-end;">
            <button onclick="window.__editOrderRisk(${order.id}, ${sl === null ? 'null' : sl}, ${tp === null ? 'null' : tp})"
                    style="padding:4px 12px;background:#1e293b;color:#93c5fd;border:1px solid #3b82f6;border-radius:4px;cursor:pointer;font-size:0.8rem;">设置止损/止盈</button>
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

// 设置/清除止损止盈：留空表示清除该侧
window.__editOrderRisk = async (orderId, stopLoss, takeProfit) => {
  const slInput = prompt(`止损价 #${orderId}（留空清除）`, stopLoss === null ? '' : String(stopLoss));
  if (slInput === null) return;
  const tpInput = prompt(`止盈价 #${orderId}（留空清除）`, takeProfit === null ? '' : String(takeProfit));
  if (tpInput === null) return;

  const toValue = (raw) => {
    const text = (raw || '').trim();
    if (!text) return null;
    const num = Number(text);
    return Number.isFinite(num) ? num : NaN;
  };
  const sl = toValue(slInput);
  const tp = toValue(tpInput);
  if (Number.isNaN(sl) || Number.isNaN(tp)) {
    alert('请输入有效价格');
    return;
  }
  try {
    await updateOrderRisk(orderId, sl, tp);
    renderOrders();
  } catch (e) {
    alert(`设置失败: ${e.message}`);
  }
};
