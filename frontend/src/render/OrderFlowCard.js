/** 订单流（REST 采样）卡片渲染 */
import { fmtNumber } from '../utils/format.js';
import { getOrderflowItems } from '../stores/flowStore.js';

function biasMeta(bias) {
  if (bias === null || bias === undefined) return { text: '-', color: '#94a3b8' };
  if (bias >= 30) return { text: `偏多 +${bias}`, color: '#22c55e' };
  if (bias <= -30) return { text: `偏空 ${bias}`, color: '#ef4444' };
  return { text: `均衡 ${bias > 0 ? '+' : ''}${bias}`, color: '#94a3b8' };
}

function qualityBadges(quality = {}, available) {
  const badges = [];
  if (!available) badges.push(['无数据', '#f59e0b']);
  if (quality.sampled) badges.push(['采样', '#3b82f6']);
  if (quality.gap_suspected) badges.push(['可能缺口', '#f59e0b']);
  if (quality.stale) badges.push(['数据过期', '#ef4444']);
  return badges.map(([text, color]) =>
    `<span style="font-size:0.7rem;color:${color};border:1px solid ${color};border-radius:3px;padding:0 5px;">${text}</span>`
  ).join('');
}

function dualBar(buy, sell) {
  const total = (buy || 0) + (sell || 0);
  const buyPct = total ? buy / total * 100 : 50;
  return `
    <div style="display:flex;height:8px;border-radius:4px;overflow:hidden;background:#334155;">
      <div style="width:${buyPct}%;background:#22c55e;"></div>
      <div style="width:${100 - buyPct}%;background:#ef4444;"></div>
    </div>
    <div style="display:flex;justify-content:space-between;font-size:0.75rem;margin-top:4px;">
      <span style="color:#22c55e;">买 ${fmtNumber(buy, 2)}</span>
      <span style="color:#ef4444;">卖 ${fmtNumber(sell, 2)}</span>
    </div>`;
}

function bookBar(imbalance) {
  const pct = Math.max(-1, Math.min(1, imbalance || 0));
  const left = 50 + pct * 50;
  return `
    <div style="position:relative;height:8px;border-radius:4px;background:#334155;overflow:hidden;">
      <div style="position:absolute;left:0;top:0;bottom:0;width:${left}%;background:rgba(34,197,94,0.55);"></div>
      <div style="position:absolute;right:0;top:0;bottom:0;width:${100 - left}%;background:rgba(239,68,68,0.55);"></div>
      <div style="position:absolute;left:50%;top:0;bottom:0;width:1px;background:#e2e8f0;"></div>
    </div>
    <div style="display:flex;justify-content:space-between;font-size:0.72rem;color:#94a3b8;margin-top:4px;">
      <span>买盘更厚</span><span>失衡 ${fmtNumber((imbalance || 0) * 100, 1)}%</span><span>卖盘更厚</span>
    </div>`;
}

export function renderOrderflow() {
  const target = document.querySelector('[data-flow-grid]');
  if (!target) return;

  const items = getOrderflowItems();
  if (!items.length) {
    target.innerHTML = `<div class="empty">订单流数据尚未就绪（服务启动后约 15 秒完成首轮采样）</div>`;
    return;
  }

  target.innerHTML = items.map(item => {
    const available = item.available !== false;
    const bias = biasMeta(item.flow_bias);
    const quality = item.quality || {};
    const largeRows = (item.large_trades || []).slice(0, 5).map(t => {
      const color = t.side === 'buy' ? '#22c55e' : '#ef4444';
      return `<tr>
        <td style="padding:2px 4px;color:#64748b;">${(t.ts || '').slice(11, 19)}</td>
        <td style="padding:2px 4px;color:${color};">${t.side === 'buy' ? '买' : '卖'}</td>
        <td style="padding:2px 4px;">${fmtNumber(t.price)}</td>
        <td style="padding:2px 4px;text-align:right;">${fmtNumber(t.notional, 0)}</td>
      </tr>`;
    }).join('');

    return `
      <div class="flow-card">
        <div class="flow-head">
          <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;">
            <strong>${item.symbol}</strong>
            <span style="font-size:0.75rem;color:${bias.color};border:1px solid ${bias.color};border-radius:3px;padding:0 6px;">${bias.text}</span>
            ${qualityBadges(quality, available)}
          </div>
          <span style="font-size:0.72rem;color:#64748b;">窗口 ${item.window || '-'}</span>
        </div>

        ${available ? `
          <div style="font-size:0.75rem;color:#94a3b8;margin-bottom:4px;">主动买卖量（窗口内）</div>
          ${dualBar(item.buy_volume, item.sell_volume)}

          <div class="flow-metrics" style="margin-top:10px;">
            <div><label>主动净额 delta</label><strong style="color:${(item.delta || 0) >= 0 ? '#22c55e' : '#ef4444'}">${fmtNumber(item.delta, 2)}</strong></div>
            <div><label>delta 比率</label><strong>${fmtNumber((item.delta_ratio || 0) * 100, 1)}%</strong></div>
            <div><label>窗口 CVD</label><strong>${fmtNumber(item.window_cvd, 2)}</strong></div>
            <div><label>本次进程 CVD</label><strong>${fmtNumber(item.session_cvd, 2)}</strong></div>
          </div>

          <div style="font-size:0.75rem;color:#94a3b8;margin:6px 0 4px;">盘口深度（±${item.book?.band_pct ?? 0.5}%）</div>
          ${bookBar(item.book?.imbalance)}
          <div style="font-size:0.72rem;color:#64748b;margin-top:2px;">top20 失衡 ${fmtNumber((item.book?.top20_imbalance || 0) * 100, 1)}%</div>

          <div style="font-size:0.75rem;color:#94a3b8;margin:8px 0 4px;">大单（≥ ${fmtNumber(item.large_threshold, 0)} USDT）</div>
          ${largeRows ? `<table style="width:100%;font-size:0.75rem;border-collapse:collapse;">${largeRows}</table>`
                      : `<div style="font-size:0.75rem;color:#64748b;">窗口内暂无大单</div>`}

          <div style="margin-top:8px;font-size:0.7rem;color:#64748b;">
            成交笔数 ${quality.trade_count ?? '-'} · 窗口覆盖 ${((quality.window_coverage_pct || 0) * 100).toFixed(0)}%
            ${item.updated_at ? ` · 更新 ${new Date(item.updated_at).toLocaleTimeString('zh-CN')}` : ''}
          </div>
        ` : `
          <div style="padding:16px 0;font-size:0.8rem;color:#f59e0b;">${item.reason || '暂无可用数据'}</div>
        `}
      </div>`;
  }).join('');
}
