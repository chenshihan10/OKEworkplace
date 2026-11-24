/** 多周期（MTF）矩阵渲染 */
import { dirIcons } from '../utils/format.js';
import { getMtfItems, getMtfTimeframes } from '../stores/mtfStore.js';

const RESONANCE = {
  STRONG_LONG: { text: '强共振做多', color: '#16a34a' },
  LONG: { text: '偏多共振', color: '#22c55e' },
  SHORT: { text: '偏空共振', color: '#ef4444' },
  STRONG_SHORT: { text: '强共振做空', color: '#dc2626' },
  MIXED: { text: '周期分歧', color: '#f59e0b' },
  NEUTRAL: { text: '中性', color: '#94a3b8' },
};

const DIR_LABEL = { LONG: '多', SHORT: '空', NEUTRAL: '中性' };
const EMA_STACK = { bull: '多头排列', bear: '空头排列', mixed: '均线纠缠', unknown: '-' };

function cell(row) {
  const dir = row.direction || 'NEUTRAL';
  const color = dir === 'LONG' ? '#22c55e' : dir === 'SHORT' ? '#ef4444' : '#94a3b8';
  const staleBadge = row.stale
    ? `<span style="font-size:0.7rem;color:#f59e0b;border:1px solid #f59e0b;border-radius:3px;padding:0 4px;">stale</span>`
    : '';
  return `
    <div style="background:#0f172a;border:1px solid #1e293b;border-radius:6px;padding:10px;">
      <div style="display:flex;justify-content:space-between;align-items:center;">
        <strong style="color:#93c5fd;">${row.timeframe}</strong>
        ${staleBadge}
      </div>
      <div style="margin-top:6px;font-size:1.05rem;font-weight:700;color:${color};">
        ${dirIcons[dir] || '⚪'} ${DIR_LABEL[dir] || dir}
        <span style="font-size:0.85rem;color:#cbd5e1;margin-left:6px;">${row.score ?? '-'} 分</span>
      </div>
      <div style="margin-top:6px;font-size:0.78rem;color:#94a3b8;display:flex;flex-direction:column;gap:2px;">
        <span>${row.level || '-'} · ${row.regime_label || row.regime || '-'}</span>
        <span>均线: ${EMA_STACK[row.ema_stack] || row.ema_stack || '-'}</span>
        <span>RSI: ${row.rsi14 ?? '-'} · MACD: ${row.macd_histogram ?? '-'}</span>
        <span>ATR: ${row.atr_pct != null ? row.atr_pct + '%' : '-'}</span>
      </div>
    </div>`;
}

export function renderMtf() {
  const target = document.querySelector('[data-mtf-grid]');
  if (!target) return;

  const items = getMtfItems();
  const timeframes = getMtfTimeframes();

  if (!items.length) {
    target.innerHTML = `<div class="empty">多周期数据尚未就绪（服务启动后约 60 秒完成首轮刷新）</div>`;
    return;
  }

  target.innerHTML = items.map(item => {
    const meta = RESONANCE[item.resonance] || RESONANCE.NEUTRAL;
    const counter = item.counter_trend
      ? `<span style="font-size:0.75rem;color:#f87171;border:1px solid #ef4444;border-radius:3px;padding:1px 6px;">⚠ 逆大周期</span>`
      : '';
    const staleNote = item.stale
      ? `<span style="font-size:0.75rem;color:#f59e0b;">取数失败，展示上一轮缓存</span>`
      : '';
    const reasons = (item.reasons || []).map(r => `<div style="font-size:0.78rem;color:#94a3b8;">· ${r}</div>`).join('');
    const cells = (item.timeframes || []).length
      ? item.timeframes.map(cell).join('')
      : timeframes.map(tf => cell({ timeframe: tf, direction: 'NEUTRAL', stale: true })).join('');

    return `
      <div style="background:linear-gradient(135deg,#1e293b 0%,#0f172a 100%);border:1px solid #334155;border-radius:8px;padding:14px;margin-bottom:12px;">
        <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px;">
          <div style="display:flex;align-items:center;gap:10px;">
            <strong style="font-size:1.05rem;">${item.symbol}</strong>
            <span style="background:${meta.color};color:#0f172a;font-weight:700;border-radius:4px;padding:1px 8px;font-size:0.8rem;">${meta.text}</span>
            <span style="font-size:0.78rem;color:#94a3b8;">主周期 ${item.primary_timeframe || '-'}</span>
            ${counter}
            ${staleNote}
          </div>
          <span style="font-size:0.75rem;color:#64748b;">更新: ${item.updated_at ? new Date(item.updated_at).toLocaleTimeString('zh-CN') : '--'}</span>
        </div>
        <div style="display:grid;grid-template-columns:repeat(3, minmax(180px, 1fr));gap:10px;margin-top:12px;">
          ${cells}
        </div>
        <div style="margin-top:8px;">${reasons}</div>
      </div>`;
  }).join('');
}
