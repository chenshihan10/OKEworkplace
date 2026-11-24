/** V3.0 预测绩效：汇总 + 明细（最小可用版，不含图表） */

const API = '/api/v3/performance';
const STATUS_LABELS = {
  verified: '已回验',
  insufficient_data: '数据不足',
  invalid: '数据无效',
  failed: '取数失败',
};

const fmtPct = (v) => (v === null || v === undefined ? '—' : `${v >= 0 ? '+' : ''}${v.toFixed(2)}%`);
const colorOf = (v) => (v === null || v === undefined ? '#94a3b8' : v >= 0 ? '#22c55e' : '#ef4444');
const fmtNum = (v) => (v === null || v === undefined ? '—' : Number(v).toFixed(2));

function summaryCard(label, value, color = '#e2e8f0') {
  return `<div style="background:#0f172a;border:1px solid #1e293b;border-radius:8px;padding:12px 16px;min-width:130px;">
    <div style="font-size:0.78rem;color:#64748b;margin-bottom:4px;">${label}</div>
    <div style="font-size:1.25rem;font-weight:600;color:${color};">${value}</div>
  </div>`;
}

function groupTable(title, rows) {
  if (!rows.length) return '';
  const body = rows.map(r => `
    <tr>
      <td>${r.symbol || r.horizon || '—'}</td>
      <td>${r.predictions}</td>
      <td>${r.verified}</td>
      <td style="color:#22c55e;">${r.wins}</td>
      <td style="color:#ef4444;">${r.losses}</td>
      <td>${r.flats}</td>
      <td>${r.win_rate === null ? '—' : r.win_rate + '%'}</td>
      <td style="color:${colorOf(r.avg_net_return)};">${fmtPct(r.avg_net_return)}</td>
    </tr>`).join('');
  return `
    <div style="margin-top:16px;">
      <div style="font-size:0.9rem;color:#94a3b8;margin-bottom:6px;">${title}</div>
      <table style="width:100%;border-collapse:collapse;font-size:0.82rem;">
        <thead><tr style="color:#64748b;text-align:left;">
          <th style="padding:6px 8px;">${title.includes('周期') ? '周期' : '币种'}</th>
          <th style="padding:6px 8px;">预测</th><th style="padding:6px 8px;">已回验</th>
          <th style="padding:6px 8px;">胜</th><th style="padding:6px 8px;">负</th>
          <th style="padding:6px 8px;">平</th><th style="padding:6px 8px;">胜率</th>
          <th style="padding:6px 8px;">平均净收益</th>
        </tr></thead>
        <tbody>${body}</tbody>
      </table>
    </div>`;
}

function detailTable(items) {
  if (!items.length) {
    return `<div style="color:#64748b;text-align:center;padding:32px;">暂无回验数据，等待预测到期。</div>`;
  }
  const rows = items.map(it => {
    const status = it.verify_status ? (STATUS_LABELS[it.verify_status] || it.verify_status) : '待回验';
    const statusColor = it.verify_status === 'verified' ? '#22c55e'
      : it.verify_status === 'failed' ? '#ef4444'
      : it.verify_status ? '#f59e0b' : '#64748b';
    const outcome = it.outcome || '—';
    const outcomeColor = it.outcome === 'WIN' ? '#22c55e' : it.outcome === 'LOSS' ? '#ef4444' : '#94a3b8';
    return `<tr style="border-top:1px solid #1e293b;">
      <td style="padding:6px 8px;color:#94a3b8;">${(it.created_at || '').replace('T', ' ').slice(0, 16)}</td>
      <td style="padding:6px 8px;">${it.symbol}</td>
      <td style="padding:6px 8px;">${it.direction}</td>
      <td style="padding:6px 8px;">${it.horizon || '—'}</td>
      <td style="padding:6px 8px;color:${statusColor};">${status}</td>
      <td style="padding:6px 8px;color:${outcomeColor};">${outcome}</td>
      <td style="padding:6px 8px;">${fmtNum(it.entry_price)} → ${fmtNum(it.exit_price)}</td>
      <td style="padding:6px 8px;color:${colorOf(it.net_return)};">${fmtPct(it.net_return)}</td>
    </tr>`;
  }).join('');
  return `
    <div style="margin-top:20px;">
      <div style="font-size:0.9rem;color:#94a3b8;margin-bottom:6px;">回验明细（最近 30 条）</div>
      <table style="width:100%;border-collapse:collapse;font-size:0.8rem;">
        <thead><tr style="color:#64748b;text-align:left;">
          <th style="padding:6px 8px;">时间(UTC)</th><th style="padding:6px 8px;">币种</th>
          <th style="padding:6px 8px;">方向</th><th style="padding:6px 8px;">周期</th>
          <th style="padding:6px 8px;">状态</th><th style="padding:6px 8px;">结果</th>
          <th style="padding:6px 8px;">入场→出场</th><th style="padding:6px 8px;">净收益</th>
        </tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </div>`;
}

export async function renderPerformance() {
  const container = document.querySelector('[data-performance]');
  if (!container) return;
  try {
    const [sumRes, detailRes] = await Promise.all([
      fetch(`${API}/summary`, { cache: 'no-store' }),
      fetch(`${API}/detail?limit=30`, { cache: 'no-store' }),
    ]);
    const summary = await sumRes.json();
    const detail = await detailRes.json();
    const o = summary.overall || {};

    container.innerHTML = `
      <div style="display:flex;gap:12px;flex-wrap:wrap;margin-bottom:8px;">
        ${summaryCard('预测总数', o.predictions ?? 0)}
        ${summaryCard('已回验', o.verified ?? 0)}
        ${summaryCard('待回验', o.pending_predictions ?? 0, '#f59e0b')}
        ${summaryCard('胜率', o.win_rate === null ? '—' : `${o.win_rate}%`)}
        ${summaryCard('方向准确率', o.directional_accuracy === null ? '—' : `${o.directional_accuracy}%`)}
        ${summaryCard('平均净收益', fmtPct(o.avg_net_return), colorOf(o.avg_net_return))}
      </div>
      <div style="font-size:0.75rem;color:#475569;margin-bottom:4px;">${summary.definition || ''}</div>
      ${(o.verified ?? 0) < 30 ? `<div style="font-size:0.78rem;color:#f59e0b;margin-bottom:8px;">
        当前有效样本 ${o.verified || 0} 条，暂不足以判断策略有效性，仅作过程观察。</div>` : ''}
      ${groupTable('按币种', summary.by_symbol || [])}
      ${groupTable('按周期', summary.by_horizon || [])}
      ${detailTable(detail.items || [])}
    `;
  } catch (error) {
    container.innerHTML = `<div style="color:#ef4444;padding:20px;">绩效数据加载失败：${error.message}</div>`;
  }
}

// 供 Tab 切换时立即刷新
window.__okeRefreshPerformance = renderPerformance;
