/** V3.0 预测绩效：汇总 + 分组统计 + 回验明细（仅视觉与信息组织） */

const API = '/api/v3/performance';
const STYLE_ID = 'perf-tab-style';

const STATUS_META = {
  verified: { label: '已回验', tone: 'ok' },
  insufficient_data: { label: '数据不足', tone: 'warn' },
  invalid: { label: '数据无效', tone: 'bad' },
  failed: { label: '取数失败', tone: 'bad' },
};

const fmtPct = (v) => (v === null || v === undefined ? '—' : `${v >= 0 ? '+' : ''}${Number(v).toFixed(2)}%`);
const fmtRate = (v) => (v === null || v === undefined ? '—' : `${Number(v).toFixed(1)}%`);
const fmtNum = (v) => (v === null || v === undefined ? '—' : Number(v).toFixed(2));
const toneOf = (v) => (v === null || v === undefined ? 'flat' : v > 0 ? 'up' : v < 0 ? 'down' : 'flat');
const clampPct = (v) => Math.max(0, Math.min(100, Number(v) || 0));

const MTF_LABELS = {
  LONG: '多头共振',
  SHORT: '空头共振',
  MIXED: '多空分歧',
  unavailable: '无上下文',
};
const FLOW_LABELS = {
  bullish: '买盘偏强',
  bearish: '卖盘偏强',
  neutral: '中性',
  unavailable: '无上下文',
};

function ensureStyle() {
  if (document.getElementById(STYLE_ID)) return;
  const style = document.createElement('style');
  style.id = STYLE_ID;
  style.textContent = `
    .perf { display: flex; flex-direction: column; gap: 14px; }
    .perf-head { display: flex; align-items: flex-end; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
    .perf-title { font-size: 1.05rem; font-weight: 700; color: #e2e8f0; margin: 0 0 4px; }
    .perf-def { font-size: 0.74rem; color: #64748b; line-height: 1.6; max-width: 760px; }
    .perf-meta { font-size: 0.74rem; color: #94a3b8; border: 1px solid #334155; background: rgba(30, 41, 59, 0.5); border-radius: 999px; padding: 4px 12px; white-space: nowrap; }

    .perf-kpis { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; }
    .perf-kpi { background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%); border: 1px solid #334155; border-left: 3px solid #3b82f6; border-radius: 10px; padding: 14px 16px; }
    .perf-kpi.dir { border-left-color: #8b5cf6; }
    .perf-kpi.ret.up { border-left-color: #22c55e; }
    .perf-kpi.ret.down { border-left-color: #ef4444; }
    .perf-kpi.ret.flat { border-left-color: #64748b; }
    .perf-kpi-label { font-size: 0.78rem; color: #94a3b8; }
    .perf-kpi-value { font-size: 1.85rem; font-weight: 700; line-height: 1.2; margin: 8px 0 2px; color: #e2e8f0; font-variant-numeric: tabular-nums; }
    .perf-kpi-value.up { color: #22c55e; }
    .perf-kpi-value.down { color: #ef4444; }
    .perf-kpi-value.flat { color: #94a3b8; }
    .perf-kpi-foot { font-size: 0.73rem; color: #64748b; }
    .perf-meter { height: 5px; background: #1e293b; border-radius: 999px; overflow: hidden; margin-top: 10px; }
    .perf-meter > i { display: block; height: 100%; border-radius: 999px; background: #3b82f6; }
    .perf-meter > i.dir { background: #8b5cf6; }

    .perf-stats { display: flex; flex-wrap: wrap; gap: 8px 26px; background: rgba(30, 41, 59, 0.32); border: 1px solid #1e293b; border-radius: 10px; padding: 11px 16px; }
    .perf-stat { font-size: 0.75rem; color: #94a3b8; display: inline-flex; align-items: baseline; gap: 6px; }
    .perf-stat b { font-size: 0.92rem; font-weight: 600; color: #e2e8f0; font-variant-numeric: tabular-nums; }
    .perf-stat b.warn { color: #f59e0b; }
    .perf-stat b.muted { color: #64748b; }

    .perf-notice { display: flex; gap: 10px; align-items: flex-start; background: rgba(245, 158, 11, 0.07); border: 1px solid rgba(245, 158, 11, 0.3); border-left: 3px solid #f59e0b; border-radius: 8px; padding: 10px 14px; font-size: 0.79rem; color: #fbbf24; line-height: 1.6; }
    .perf-notice i { font-style: normal; }

    .perf-panels { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
    .perf-panel { background: rgba(15, 23, 42, 0.6); border: 1px solid #1e293b; border-radius: 10px; padding: 14px 16px; overflow-x: auto; }
    .perf-panel-head { display: flex; align-items: baseline; justify-content: space-between; gap: 8px; margin-bottom: 8px; }
    .perf-panel-title { font-size: 0.88rem; font-weight: 600; color: #cbd5e1; }
    .perf-panel-sub { font-size: 0.71rem; color: #64748b; }

    .perf-table { width: 100%; border-collapse: collapse; font-size: 0.8rem; font-variant-numeric: tabular-nums; }
    .perf-table th { padding: 6px 8px; font-size: 0.71rem; font-weight: 500; color: #64748b; text-align: right; border-bottom: 1px solid #334155; white-space: nowrap; }
    .perf-table th:first-child, .perf-table td:first-child { text-align: left; }
    .perf-table td { padding: 7px 8px; text-align: right; color: #cbd5e1; border-bottom: 1px solid rgba(30, 41, 59, 0.7); white-space: nowrap; }
    .perf-table tbody tr:hover { background: rgba(59, 130, 246, 0.07); }
    .perf-table .dim { color: #94a3b8; }
    .perf-table .strong { color: #e2e8f0; font-weight: 600; }
    .perf-table .up { color: #22c55e; font-weight: 600; }
    .perf-table .down { color: #ef4444; font-weight: 600; }
    .perf-table .flat { color: #94a3b8; }
    .perf-table tbody tr.group-start td { border-top: 1px solid #334155; }

    .perf-rate { display: inline-flex; align-items: center; justify-content: flex-end; gap: 8px; }
    .perf-rate i { width: 52px; height: 4px; background: #1e293b; border-radius: 999px; overflow: hidden; }
    .perf-rate b { display: block; height: 100%; border-radius: 999px; background: #3b82f6; }
    .perf-wlf .w { color: #22c55e; }
    .perf-wlf .l { color: #ef4444; }
    .perf-wlf .f { color: #64748b; }
    .perf-wlf i { color: #334155; font-style: normal; }

    .perf-chip { display: inline-block; padding: 1px 7px; border-radius: 999px; font-size: 0.7rem; line-height: 1.5; border: 1px solid #334155; color: #94a3b8; background: rgba(148, 163, 184, 0.06); }
    .perf-chip.ok { color: #22c55e; border-color: rgba(34, 197, 94, 0.4); background: rgba(34, 197, 94, 0.08); }
    .perf-chip.warn { color: #f59e0b; border-color: rgba(245, 158, 11, 0.4); background: rgba(245, 158, 11, 0.08); }
    .perf-chip.bad { color: #ef4444; border-color: rgba(239, 68, 68, 0.4); background: rgba(239, 68, 68, 0.08); }
    .perf-chip.long { color: #22c55e; border-color: rgba(34, 197, 94, 0.35); }
    .perf-chip.short { color: #ef4444; border-color: rgba(239, 68, 68, 0.35); }

    .perf-empty { color: #64748b; font-size: 0.8rem; text-align: center; padding: 26px 0; }
    .perf-detail-panel { overflow-x: auto; }

    @media (max-width: 1100px) {
      .perf-panels { grid-template-columns: 1fr; }
    }
    @media (max-width: 760px) {
      .perf-kpis { grid-template-columns: 1fr; }
    }
  `;
  document.head.appendChild(style);
}

function kpiCard({ label, value, tone = '', valueTone = '', foot = '', meter = null, meterTone = '', extraClass = '' }) {
  return `<div class="perf-kpi ${extraClass}">
    <div class="perf-kpi-label">${label}</div>
    <div class="perf-kpi-value ${valueTone}">${value}</div>
    <div class="perf-kpi-foot">${foot}</div>
    ${meter === null ? '' : `<div class="perf-meter"><i class="${meterTone}" style="width:${clampPct(meter)}%"></i></div>`}
  </div>`;
}

function statItem(label, value, tone = '') {
  return `<span class="perf-stat">${label}<b class="${tone}">${value}</b></span>`;
}

/** 分组统计表：币种 / 周期，胜率带进度条，胜/负/平合并展示 */
function groupPanel(title, subLabel, firstCol, rows) {
  if (!rows || !rows.length) {
    return `<div class="perf-panel"><div class="perf-panel-head"><span class="perf-panel-title">${title}</span></div>
      <div class="perf-empty">暂无分组数据</div></div>`;
  }
  const body = rows.map((r) => `
    <tr>
      <td class="strong">${r.symbol || r.horizon || '—'}</td>
      <td class="dim">${r.predictions ?? 0}</td>
      <td>${r.verified ?? 0}</td>
      <td class="perf-wlf"><span class="w">${r.wins ?? 0}</span><i> / </i><span class="l">${r.losses ?? 0}</span><i> / </i><span class="f">${r.flats ?? 0}</span></td>
      <td>
        <span class="perf-rate">
          <span class="${r.win_rate === null ? 'flat' : 'strong'}">${fmtRate(r.win_rate)}</span>
          <i><b style="width:${clampPct(r.win_rate)}%"></b></i>
        </span>
      </td>
      <td class="${toneOf(r.avg_net_return)}">${fmtPct(r.avg_net_return)}</td>
    </tr>`).join('');
  return `<div class="perf-panel">
    <div class="perf-panel-head">
      <span class="perf-panel-title">${title}</span>
      <span class="perf-panel-sub">${subLabel}</span>
    </div>
    <table class="perf-table">
      <thead><tr>
        <th>${firstCol}</th>
        <th>预测</th>
        <th>已回验</th>
        <th>胜 / 负 / 平</th>
        <th>胜率</th>
        <th>平均净收益</th>
      </tr></thead>
      <tbody>${body}</tbody>
    </table>
  </div>`;
}

/** 上下文分桶：按 MTF 共振 / 订单流偏向；样本不足只出计数，不给胜率 */
function contextPanel(title, groups, labels, minSample) {
  const rows = groups || [];
  if (!rows.length) {
    return `<div class="perf-panel">
      <div class="perf-panel-head">
        <span class="perf-panel-title">${title}</span>
        <span class="perf-panel-sub">样本 ≥ ${minSample} 才出胜率</span>
      </div>
      <div class="perf-empty">暂无带上下文的回验样本</div>
    </div>`;
  }
  const body = rows.map((r) => {
    const insufficient = r.insufficient_sample || (r.verified ?? 0) < minSample;
    return `<tr>
      <td class="strong">${labels[r.bucket] || r.bucket || '—'}</td>
      <td class="dim">${r.predictions ?? 0}</td>
      <td>${r.verified ?? 0}</td>
      <td class="perf-wlf"><span class="w">${r.wins ?? 0}</span><i> / </i><span class="l">${r.losses ?? 0}</span><i> / </i><span class="f">${r.flats ?? 0}</span></td>
      <td>
        ${insufficient ? '<span class="perf-chip warn">样本不足</span>' : `<span class="perf-rate">
          <span class="strong">${fmtRate(r.win_rate)}</span>
          <i><b style="width:${clampPct(r.win_rate)}%"></b></i>
        </span>`}
      </td>
      <td class="${insufficient ? 'flat' : toneOf(r.avg_net_return)}">${insufficient ? '—' : fmtPct(r.avg_net_return)}</td>
    </tr>`;
  }).join('');
  return `<div class="perf-panel">
    <div class="perf-panel-head">
      <span class="perf-panel-title">${title}</span>
      <span class="perf-panel-sub">样本 ≥ ${minSample} 才出胜率</span>
    </div>
    <table class="perf-table">
      <thead><tr>
        <th>分桶</th>
        <th>预测</th>
        <th>已回验</th>
        <th>胜 / 负 / 平</th>
        <th>胜率</th>
        <th>平均净收益</th>
      </tr></thead>
      <tbody>${body}</tbody>
    </table>
  </div>`;
}

function detailTable(items, total, limit) {
  if (!items || !items.length) {
    return `<div class="perf-panel">
      <div class="perf-panel-head"><span class="perf-panel-title">回验明细</span></div>
      <div class="perf-empty">暂无回验数据，等待预测到期。</div>
    </div>`;
  }

  let prevPredictionId = null;
  const rows = items.map((it) => {
    const meta = it.verify_status ? (STATUS_META[it.verify_status] || { label: it.verify_status, tone: '' }) : { label: '待回验', tone: '' };
    const dirCls = it.direction === 'LONG' ? 'long' : it.direction === 'SHORT' ? 'short' : '';
    const outcomeCls = it.outcome === 'WIN' ? 'up' : it.outcome === 'LOSS' ? 'down' : 'flat';
    const groupStart = prevPredictionId !== null && it.prediction_id !== prevPredictionId ? ' group-start' : '';
    prevPredictionId = it.prediction_id;
    return `<tr class="${groupStart.trim()}">
      <td class="dim">${(it.created_at || '').replace('T', ' ').slice(5, 16)}</td>
      <td class="strong">${it.symbol || '—'}</td>
      <td><span class="perf-chip ${dirCls}">${it.direction || '—'}</span></td>
      <td class="dim">${it.horizon || '—'}</td>
      <td><span class="perf-chip ${meta.tone}">${meta.label}</span></td>
      <td class="${outcomeCls}">${it.outcome || '—'}</td>
      <td class="dim">${fmtNum(it.entry_price)} → ${fmtNum(it.exit_price)}</td>
      <td class="${toneOf(it.net_return)}">${fmtPct(it.net_return)}</td>
    </tr>`;
  }).join('');

  const shown = items.length;
  const sub = total > shown ? `共 ${total} 条，显示最近 ${shown} 条` : `共 ${total} 条`;
  return `<div class="perf-panel perf-detail-panel">
    <div class="perf-panel-head">
      <span class="perf-panel-title">回验明细</span>
      <span class="perf-panel-sub">${sub}</span>
    </div>
    <table class="perf-table">
      <thead><tr>
        <th>时间(UTC)</th>
        <th>币种</th>
        <th>方向</th>
        <th>周期</th>
        <th>状态</th>
        <th>结果</th>
        <th>入场 → 出场</th>
        <th>净收益</th>
      </tr></thead>
      <tbody>${rows}</tbody>
    </table>
  </div>`;
}

export async function renderPerformance() {
  const container = document.querySelector('[data-performance]');
  if (!container) return;
  ensureStyle();
  try {
    const [sumRes, detailRes, contextRes] = await Promise.all([
      fetch(`${API}/summary`, { cache: 'no-store' }),
      fetch(`${API}/detail?limit=30`, { cache: 'no-store' }),
      fetch(`${API}/context-summary`, { cache: 'no-store' }).catch(() => null),
    ]);
    if (!sumRes.ok || !detailRes.ok) {
      throw new Error(`接口返回 ${sumRes.status} / ${detailRes.status}`);
    }
    const summary = await sumRes.json();
    const detail = await detailRes.json();
    const context = contextRes && contextRes.ok ? await contextRes.json() : null;
    const o = summary.overall || {};
    const verified = o.verified ?? 0;
    const winRate = o.win_rate;
    const dirAcc = o.directional_accuracy;
    const avgNet = o.avg_net_return;

    container.innerHTML = `
      <div class="perf">
        <div class="perf-head">
          <div>
            <div class="perf-title">预测绩效</div>
            <div class="perf-def">${summary.definition || ''}</div>
          </div>
          <div class="perf-meta">有效样本 ${verified} 条 · 每次进入自动刷新</div>
        </div>

        <div class="perf-kpis">
          ${kpiCard({
            label: '胜率',
            value: fmtRate(winRate),
            foot: `${o.wins ?? 0} 胜 / ${o.losses ?? 0} 负 / ${o.flats ?? 0} 平`,
            meter: winRate,
          })}
          ${kpiCard({
            label: '方向准确率',
            value: fmtRate(dirAcc),
            foot: '仅计 WIN 与 LOSS，排除平盘',
            meter: dirAcc,
            meterTone: 'dir',
            extraClass: 'dir',
          })}
          ${kpiCard({
            label: '平均净收益',
            value: fmtPct(avgNet),
            valueTone: toneOf(avgNet),
            foot: `累计 ${fmtPct(o.sum_net_return)} · 已扣双边手续费与滑点`,
            extraClass: `ret ${toneOf(avgNet)}`,
          })}
        </div>

        <div class="perf-stats">
          ${statItem('预测总数', o.predictions ?? 0)}
          ${statItem('回验结果', o.results ?? 0)}
          ${statItem('已回验', verified)}
          ${statItem('待回验', o.pending_predictions ?? 0, 'warn')}
          ${statItem('数据不足', o.insufficient_data ?? 0)}
          ${statItem('数据无效', o.invalid ?? 0, 'muted')}
          ${statItem('取数失败', o.failed ?? 0, 'muted')}
        </div>

        ${verified < 30 ? `<div class="perf-notice"><i>⚠</i><span>当前有效样本仅 ${verified} 条（少于 30 条），统计意义有限，暂不足以判断策略有效性，仅作过程观察。</span></div>` : ''}

        <div class="perf-panels">
          ${groupPanel('按币种', '预测 / 回验分布', '币种', summary.by_symbol || [])}
          ${groupPanel('按周期', '同一预测在不同持有期的表现', '周期', summary.by_horizon || [])}
        </div>

        <div class="perf-panels">
          ${contextPanel('多周期共振', context && context.mtf_resonance, MTF_LABELS, (context && context.min_sample) || 30)}
          ${contextPanel('订单流偏向', context && context.orderflow_bias, FLOW_LABELS, (context && context.min_sample) || 30)}
        </div>

        ${detailTable(detail.items || [], detail.total ?? 0, detail.limit ?? 30)}
      </div>
    `;
  } catch (error) {
    container.innerHTML = `<div class="perf"><div class="perf-notice" style="border-color:rgba(239,68,68,.4);background:rgba(239,68,68,.08);border-left-color:#ef4444;color:#f87171;">
      <i>✕</i><span>绩效数据加载失败：${error.message}</span></div></div>`;
  }
}

// 供 Tab 切换时立即刷新
window.__okeRefreshPerformance = renderPerformance;
