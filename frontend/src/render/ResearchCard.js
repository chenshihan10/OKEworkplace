// 「研究」页：绩效质量（置信区间 / 成本门槛 / 品种分类 / 影子评分 / 运行监控）
// 只读渲染，不参与任何评分或判断；数据来自 /api/v3/performance/quality
import { getJson } from '../api/okx.js';

const C = {
  text: '#e2e8f0', sub: '#94a3b8', line: '#1f2937',
  card: '#111827', head: '#0b1220', red: '#f87171', green: '#34d399',
  orange: '#fbbf24', blue: '#60a5fa',
};

function n(v, d = 2, suffix = '') {
  return v === null || v === undefined ? '—' : `${Number(v).toFixed(d)}${suffix}`;
}

function ci(pair, d = 2, suffix = '%') {
  if (!pair || pair[0] === null || pair[1] === null) return '—';
  return `[${Number(pair[0]).toFixed(d)}, ${Number(pair[1]).toFixed(d)}]${suffix}`;
}

function badge(text, ok) {
  const color = ok === true ? C.green : ok === false ? C.red : C.orange;
  return `<span style="display:inline-block;padding:0.1rem 0.45rem;border-radius:999px;font-size:0.72rem;border:1px solid ${color};color:${color};">${text}</span>`;
}

function table(headers, rows) {
  const th = headers.map(h => `<th style="text-align:left;padding:0.35rem 0.5rem;border-bottom:1px solid ${C.line};color:${C.sub};font-weight:500;white-space:nowrap;">${h}</th>`).join('');
  const tr = rows.map(r => `<tr>${r.map(c => `<td style="padding:0.32rem 0.5rem;border-bottom:1px solid ${C.line};white-space:nowrap;">${c}</td>`).join('')}</tr>`).join('');
  return `<div style="overflow-x:auto;"><table style="width:100%;border-collapse:collapse;font-size:0.8rem;color:${C.text};"><thead><tr>${th}</tr></thead><tbody>${tr}</tbody></table></div>`;
}

function card(title, body, extra = '') {
  return `<section style="background:${C.card};border:1px solid ${C.line};border-radius:10px;padding:0.9rem 1rem;margin-bottom:0.9rem;">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:0.55rem;">
      <h3 style="margin:0;font-size:0.92rem;color:${C.text};">${title}</h3>${extra}
    </div>${body}</section>`;
}

function metric(label, value, hint = '') {
  return `<div style="flex:1;min-width:150px;background:${C.head};border:1px solid ${C.line};border-radius:8px;padding:0.6rem 0.75rem;">
    <div style="font-size:0.72rem;color:${C.sub};">${label}</div>
    <div style="font-size:1.15rem;color:${C.text};margin-top:0.15rem;font-family:Consolas,monospace;">${value}</div>
    ${hint ? `<div style="font-size:0.7rem;color:${C.sub};margin-top:0.15rem;">${hint}</div>` : ''}
  </div>`;
}

function sectionOverall(d) {
  const o = d.overall || {};
  const ciObj = (o.ci && o.ci.ci) || {};
  const cards = [
    metric('胜率（含 FLAT 分母）', n(o.win_rate, 1, '%'), `95% 区间 ${ci(ciObj.win_rate)}`),
    metric('方向准确率', n(o.directional_accuracy, 1, '%'), `95% 区间 ${ci(ciObj.directional_accuracy)}`),
    metric('平均净收益', n(o.avg_net_pct, 3, '%'), `95% 区间 ${ci(ciObj.avg_net_pct, 3, '%')}`),
    metric('毛收益中位数 / 成本', `${n(o.median_gross_pct, 3, '%')} / ${n(o.cost_pct, 3, '%')}`,
      `毛收益高于成本占比 ${n(o.gross_cover_rate_pct, 1, '%')}`),
  ].join('');
  const verdict = o.cost_verdict === '毛收益高于成本门槛';
  return card('总体评估（独立样本口径）',
    `<div style="display:flex;gap:0.6rem;flex-wrap:wrap;margin-bottom:0.6rem;">${cards}</div>
     <div style="font-size:0.78rem;color:${C.sub};">样本：预测 ${o.predictions || 0} 条 / 结果 ${o.results || 0} 条 / 已回验 ${o.verified || 0} 条　${badge(o.cost_verdict || '—', verdict)}</div>`);
}

function sectionHorizon(d) {
  const rows = (d.by_horizon || []).map(h => {
    const c = (h.ci && h.ci.ci) || {};
    const ok = h.median_gross_pct !== null && h.median_gross_pct > h.cost_pct;
    return [
      h.horizon,
      h.verified,
      `${n(h.win_rate, 1, '%')} ${ci(c.win_rate, 1)}`,
      `${n(h.directional_accuracy, 1, '%')} ${ci(c.directional_accuracy, 1)}`,
      n(h.median_gross_pct, 3, '%'),
      n(h.avg_net_pct, 3, '%'),
      n(h.cost_pct, 3, '%'),
      n(h.gross_cover_rate_pct, 1, '%'),
      badge(ok ? '可覆盖' : '不够覆盖', ok),
    ];
  });
  return card('分视界：毛收益 vs 净收益 vs 成本',
    table(['视界', '已回验', '胜率 (95% CI)', '方向准确率 (95% CI)', '毛收益中位数', '平均净收益', '成本', '毛收益覆盖率', '结论'], rows));
}

function sectionClass(d) {
  const label = { crypto: '加密品种', tokenized_stock: '代币化股票' };
  const rows = Object.entries(d.by_class || {}).map(([k, v]) => [
    label[k] || k, v.predictions, v.results, v.verified,
    n(v.win_rate, 1, '%'), n(v.directional_accuracy, 1, '%'),
    n(v.median_gross_pct, 3, '%'), n(v.avg_net_pct, 3, '%'),
    v.cost_verdict === '毛收益高于成本门槛' ? badge('可覆盖', true) : badge('不够覆盖', false),
  ]);
  return card('品种分类：加密 vs 代币化股票',
    table(['类别', '预测', '结果', '已回验', '胜率', '方向准确率', '毛收益中位数', '平均净收益', '成本门槛'], rows)
    + `<div style="font-size:0.7rem;color:${C.sub};margin-top:0.4rem;">代币化股票清单可用 OKE_TOKENIZED_STOCK_SYMBOLS 覆盖</div>`);
}

function sectionSymbols(d) {
  const rows = (d.by_symbol || []).map(s => [
    s.symbol, s.class === 'tokenized_stock' ? '股票' : '加密', s.predictions, s.verified,
    n(s.win_rate, 1, '%'), n(s.directional_accuracy, 1, '%'),
    n(s.median_gross_pct, 3, '%'), n(s.avg_net_pct, 3, '%'),
  ]);
  return card('分币种明细', table(['币种', '类别', '预测', '已回验', '胜率', '方向准确率', '毛收益中位数', '平均净收益'], rows));
}

function sectionShadow(d) {
  const s = d.shadow || {};
  if (!s.rows) return card('影子评分 vs 正式评分', `<div style="color:${C.sub};font-size:0.8rem;">暂无影子记录</div>`);
  const body = `<div style="font-size:0.8rem;color:${C.text};line-height:1.8;">
      记录 ${s.rows} 条　正式均分 ${n(s.avg_official_score, 2)}　影子均分 ${n(s.avg_shadow_score, 2)}<br>
      平均差 ${n(s.avg_gap, 2)}　差值标准差 ${n(s.gap_std, 2)}　区间 [${n(s.gap_range && s.gap_range[0], 1)}, ${n(s.gap_range && s.gap_range[1], 1)}]<br>
      OI 变化不可用占比 ${n(s.zero_oi_change_share_pct, 1, '%')}
    </div>
    <div style="font-size:0.7rem;color:${C.sub};margin-top:0.35rem;">${s.note || ''}</div>`;
  return card('影子评分 vs 正式评分（OI 输入已对齐口径）', body);
}

function sectionMonitor(d) {
  const m = d.monitor || {};
  const writes = m.current_candle_writes || {};
  const writeRows = Object.entries(writes).map(([k, v]) => [k, v, v > 1 ? badge('同 K 线多条', false) : badge('正常', true)]);
  const flipRows = (m.direction_flips || []).map(f => [
    f.symbol, f.samples_1h, f.raw_flips_1h, f.stable_flips_1h, f.flips_15m,
    f.last_raw_direction, f.last_stable_direction,
  ]);
  const dup = m.duplicate_buckets_24h || [];
  const summary = `<div style="font-size:0.78rem;color:${C.text};line-height:1.8;">
      当前 K 线（${m.current_candle || '—'}）写入：${Object.keys(writes).length ? '' : '无'}<br>
      24h 内同桶重复：${dup.length} 组　结果数 &gt; 3 的预测：${m.results_over_3_per_prediction || 0} 条　无 timeframe 预测：${m.predictions_without_timeframe || 0} 条
    </div>`;
  const parts = [summary];
  if (writeRows.length) parts.push(table(['币种', '本 K 线写入', '状态'], writeRows));
  if (dup.length) parts.push(table(['币种', '桶', '条数'], dup.map(x => [x.symbol, x.bucket, x.count])));
  parts.push(`<div style="font-size:0.72rem;color:${C.sub};margin:0.4rem 0;">方向翻转（内存统计，重启清零；样本每分钟约 12 次刷新）</div>`);
  parts.push(table(['币种', '样本(1h)', '原始翻转', '稳定后翻转', '15m 翻转', '最近原始', '最近稳定'], flipRows.length ? flipRows : [['—', 0, 0, 0, 0, '—', '—']]));
  return card('运行监控：写入异常与方向翻转', parts.join(''));
}

export async function renderResearch() {
  const el = document.querySelector('[data-research-panel]');
  if (!el) return;
  try {
    const d = await getJson('/api/v3/performance/quality');
    el.innerHTML = [
      sectionOverall(d),
      sectionHorizon(d),
      sectionClass(d),
      sectionSymbols(d),
      sectionShadow(d),
      sectionMonitor(d),
      `<div style="font-size:0.7rem;color:${C.sub};">数据生成时间 ${(d.generated_at || '').replace('T', ' ').slice(0, 19)}Z　定义：${Object.values(d.definition || {}).join('；')}</div>`,
    ].join('');
  } catch (err) {
    el.innerHTML = `<div style="color:${C.red};font-size:0.82rem;">绩效质量数据加载失败：${err.message || err}</div>`;
  }
}
