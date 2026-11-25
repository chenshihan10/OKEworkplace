/** V2.6 实盘（只读）卡片：交易所真实账户，与「订单」页手工记账完全独立 */
import { fmtNumber } from '../utils/format.js';
import { getAccountState } from '../stores/accountStore.js';

const MUTED = '#94a3b8';
const DIM = '#64748b';
const GREEN = '#22c55e';
const RED = '#ef4444';
const AMBER = '#f59e0b';

const ACCT_LV_LABEL = {
  1: '简单交易模式',
  2: '单币种保证金模式',
  3: '跨币种保证金模式',
  4: '组合保证金模式',
};
const POS_MODE_LABEL = {
  long_short_mode: '双向持仓',
  net_mode: '单向持仓',
};

function esc(value) {
  return String(value ?? '').replace(/[&<>"']/g, (ch) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[ch]));
}

function badge(text, color) {
  return `<span style="font-size:0.7rem;color:${color};border:1px solid ${color};border-radius:3px;padding:0 5px;white-space:nowrap;">${esc(text)}</span>`;
}

function metric(label, value, color = '#e2e8f0') {
  return `
    <div style="background:#0f172a;border:1px solid #334155;border-radius:6px;padding:8px 10px;">
      <div style="font-size:0.72rem;color:${MUTED};">${esc(label)}</div>
      <div style="font-size:1rem;font-weight:600;color:${color};margin-top:2px;">${value}</div>
    </div>`;
}

function notice(text, color = AMBER) {
  return `<div style="padding:10px 12px;font-size:0.82rem;color:${color};background:rgba(245,158,11,0.08);border:1px solid rgba(245,158,11,0.35);border-radius:6px;">${esc(text)}</div>`;
}

function pct(value, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return '-';
  return `${(Number(value) * 100).toFixed(digits)}%`;
}

function uplColor(value) {
  if (value === null || value === undefined) return '#e2e8f0';
  return Number(value) >= 0 ? GREEN : RED;
}

function timeText(iso) {
  if (!iso) return '-';
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? '-' : date.toLocaleString('zh-CN');
}

function statusBar(status) {
  if (!status) {
    return `<div style="font-size:0.8rem;color:${MUTED};">正在读取账户配置状态…</div>`;
  }
  if (!status.enabled) {
    return notice('实盘只读未启用。在测试版 .env 设置 OKE_PRIVATE_READ_ENABLED=true 并填写只读子账户 Key 后重启；未启用时后端不注册任务、不发起任何外部请求。');
  }
  if (!status.configured) {
    return notice('实盘只读已启用，但未配置 API Key（OKE_PRIVATE_READ_API_KEY / SECRET_KEY / PASSPHRASE）。配置后无需改代码，下一轮刷新即出真实数据。');
  }
  const stale = Object.values(status.resources || {}).some((item) => item.stale);
  return `
    <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;font-size:0.78rem;color:${MUTED};">
      ${badge('只读连接', GREEN)}
      <span>Key 尾号 ${esc(status.key_suffix || '----')}</span>
      <span>· 后端每 30 秒刷新，页面每 15 秒读取缓存</span>
      ${stale ? badge('部分数据过期，展示上次成功值', AMBER) : ''}
      ${status.updated_at ? `<span style="margin-left:auto;color:${DIM};">更新 ${esc(timeText(status.updated_at))}</span>` : ''}
    </div>`;
}

function summaryBlock(summary) {
  if (!summary) return '';
  if (!summary.available || !summary.data) {
    return `<div style="font-size:0.8rem;color:${AMBER};">账户摘要不可用：${esc(summary.reason || '尚未完成首次刷新')}</div>`;
  }
  const data = summary.data;
  return `
    <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px;">
      <strong style="font-size:0.9rem;">账户摘要</strong>
      ${summary.stale ? badge('数据过期', AMBER) : ''}
      <span style="margin-left:auto;font-size:0.7rem;color:${DIM};">${esc(timeText(summary.updated_at))}</span>
    </div>
    <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:8px;">
      ${metric('总权益 (USD)', fmtNumber(data.total_eq, 2))}
      ${metric('可用保证金', fmtNumber(data.avail_eq, 2))}
      ${metric('未实现盈亏', fmtNumber(data.upl, 2), uplColor(data.upl))}
      ${metric('初始保证金', fmtNumber(data.imr, 2))}
      ${metric('维持保证金', fmtNumber(data.mmr, 2))}
      ${metric('保证金率', fmtNumber(data.mgn_ratio, 2))}
    </div>
    ${(data.details || []).length ? `
      <table style="width:100%;border-collapse:collapse;font-size:0.76rem;margin-top:10px;">
        <thead><tr style="color:${MUTED};text-align:left;">
          <th style="padding:4px 6px;border-bottom:1px solid #334155;">币种</th>
          <th style="padding:4px 6px;border-bottom:1px solid #334155;text-align:right;">权益</th>
          <th style="padding:4px 6px;border-bottom:1px solid #334155;text-align:right;">可用</th>
          <th style="padding:4px 6px;border-bottom:1px solid #334155;text-align:right;">冻结</th>
          <th style="padding:4px 6px;border-bottom:1px solid #334155;text-align:right;">未实现盈亏</th>
        </tr></thead>
        <tbody>
          ${(data.details || []).map((item) => `
            <tr>
              <td style="padding:4px 6px;">${esc(item.ccy)}</td>
              <td style="padding:4px 6px;text-align:right;">${fmtNumber(item.eq, 4)}</td>
              <td style="padding:4px 6px;text-align:right;">${fmtNumber(item.avail_bal, 4)}</td>
              <td style="padding:4px 6px;text-align:right;">${fmtNumber(item.frozen_bal, 4)}</td>
              <td style="padding:4px 6px;text-align:right;color:${uplColor(item.upl)};">${fmtNumber(item.upl, 4)}</td>
            </tr>`).join('')}
        </tbody>
      </table>` : ''}`;
}

function positionsBlock(positions) {
  if (!positions) return '';
  const head = `
    <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px;">
      <strong style="font-size:0.9rem;">真实持仓</strong>
      ${badge('交易所原始单位：张', '#3b82f6')}
      ${positions.stale ? badge('数据过期', AMBER) : ''}
    </div>`;

  if (!positions.available) {
    return `${head}<div style="font-size:0.8rem;color:${AMBER};">持仓不可用：${esc(positions.reason || '尚未完成首次刷新')}</div>`;
  }
  const rows = positions.data || [];
  if (!rows.length) {
    return `${head}<div style="font-size:0.8rem;color:${MUTED};">交易所返回空仓（不是加载失败）</div>`;
  }
  return `
    ${head}
    <table style="width:100%;border-collapse:collapse;font-size:0.76rem;">
      <thead><tr style="color:${MUTED};text-align:left;">
        <th style="padding:4px 6px;border-bottom:1px solid #334155;">合约</th>
        <th style="padding:4px 6px;border-bottom:1px solid #334155;">方向</th>
        <th style="padding:4px 6px;border-bottom:1px solid #334155;text-align:right;">数量（张）</th>
        <th style="padding:4px 6px;border-bottom:1px solid #334155;text-align:right;">开仓均价</th>
        <th style="padding:4px 6px;border-bottom:1px solid #334155;text-align:right;">标记价</th>
        <th style="padding:4px 6px;border-bottom:1px solid #334155;text-align:right;">未实现盈亏</th>
        <th style="padding:4px 6px;border-bottom:1px solid #334155;text-align:right;">杠杆</th>
        <th style="padding:4px 6px;border-bottom:1px solid #334155;text-align:right;">强平价</th>
        <th style="padding:4px 6px;border-bottom:1px solid #334155;text-align:right;">保证金率</th>
      </tr></thead>
      <tbody>
        ${rows.map((row) => {
          const side = row.pos_side === 'short' ? '空' : row.pos_side === 'long' ? '多' : (row.pos_side || '-');
          const sideColor = row.pos_side === 'short' ? RED : row.pos_side === 'long' ? GREEN : MUTED;
          return `<tr>
            <td style="padding:4px 6px;">${esc(row.inst_id)}</td>
            <td style="padding:4px 6px;color:${sideColor};">${esc(side)}</td>
            <td style="padding:4px 6px;text-align:right;">${fmtNumber(row.pos_raw, 2)}</td>
            <td style="padding:4px 6px;text-align:right;">${fmtNumber(row.avg_px)}</td>
            <td style="padding:4px 6px;text-align:right;">${fmtNumber(row.mark_px)}</td>
            <td style="padding:4px 6px;text-align:right;color:${uplColor(row.upl)};">
              ${fmtNumber(row.upl, 2)} <span style="color:${DIM};">(${pct(row.upl_ratio)})</span>
            </td>
            <td style="padding:4px 6px;text-align:right;">${fmtNumber(row.lever, 2)}x</td>
            <td style="padding:4px 6px;text-align:right;color:${AMBER};">${fmtNumber(row.liq_px)}</td>
            <td style="padding:4px 6px;text-align:right;">${fmtNumber(row.mgn_ratio, 2)}</td>
          </tr>`;
        }).join('')}
      </tbody>
    </table>`;
}

function marginBlock(margin) {
  if (!margin) return '';
  const head = `
    <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px;">
      <strong style="font-size:0.9rem;">保证金视图</strong>
      ${badge('派生展示，不参与记账', '#8b5cf6')}
      ${margin.stale ? badge('数据过期', AMBER) : ''}
    </div>`;
  if (!margin.available || !margin.data) {
    return `${head}<div style="font-size:0.8rem;color:${AMBER};">不可用：${esc(margin.reason || '缺少账户摘要或持仓')}</div>`;
  }
  const account = margin.data.account || {};
  return `
    ${head}
    <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:8px;">
      ${metric('总权益', fmtNumber(account.total_eq, 2))}
      ${metric('初始保证金', fmtNumber(account.imr, 2))}
      ${metric('维持保证金', fmtNumber(account.mmr, 2))}
      ${metric('保证金率', fmtNumber(account.mgn_ratio, 2))}
    </div>
    <div style="margin-top:6px;font-size:0.7rem;color:${DIM};">
      来源：${(margin.sources || []).map(esc).join(' + ') || '-'}
    </div>`;
}

function configBlock(config) {
  const head = `<div style="display:flex;align-items:center;gap:8px;margin-bottom:8px;"><strong style="font-size:0.9rem;">账户配置</strong></div>`;
  if (!config || !config.available || !config.data) {
    const reason = config ? config.reason : '尚未刷新';
    return `${head}<div style="font-size:0.8rem;color:${MUTED};">${esc(reason || '尚未刷新')}</div>`;
  }
  const data = config.data;
  const acct = ACCT_LV_LABEL[data.acct_lv] || data.acct_lv || '-';
  const posMode = POS_MODE_LABEL[data.pos_mode] || data.pos_mode || '-';
  return `
    ${head}
    <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:8px;">
      ${metric('账户模式', `${esc(data.acct_lv || '-')} · ${esc(acct)}`)}
      ${metric('持仓模式', esc(posMode))}
      ${metric('吃单费率', data.fee_taker === null || data.fee_taker === undefined ? '-' : pct(data.fee_taker, 4))}
      ${metric('挂单费率', data.fee_maker === null || data.fee_maker === undefined ? '-' : pct(data.fee_maker, 4))}
    </div>`;
}

function fillsBlock(fills) {
  if (!fills) return '';
  const head = `
    <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px;">
      <strong style="font-size:0.9rem;">交易所成交</strong>
      ${fills.stale ? badge('数据过期', AMBER) : ''}
      ${fills.pending ? badge('首次同步中', '#3b82f6') : ''}
      <span style="margin-left:auto;font-size:0.7rem;color:${DIM};">本地累计 ${fills.total ?? 0} 条</span>
    </div>`;
  if (!fills.available) {
    return `${head}<div style="font-size:0.8rem;color:${AMBER};">成交记录不可用：${esc(fills.reason || '未启用')}</div>`;
  }
  const items = fills.items || [];
  if (!items.length) {
    return `${head}<div style="font-size:0.8rem;color:${MUTED};">
      ${fills.pending ? '正在回看历史成交，稍候…' : '本地尚无可展示的成交记录'}
    </div>`;
  }
  return `
    ${head}
    <table style="width:100%;border-collapse:collapse;font-size:0.76rem;">
      <thead><tr style="color:${MUTED};text-align:left;">
        <th style="padding:4px 6px;border-bottom:1px solid #334155;">时间</th>
        <th style="padding:4px 6px;border-bottom:1px solid #334155;">合约</th>
        <th style="padding:4px 6px;border-bottom:1px solid #334155;">方向</th>
        <th style="padding:4px 6px;border-bottom:1px solid #334155;text-align:right;">价格</th>
        <th style="padding:4px 6px;border-bottom:1px solid #334155;text-align:right;">数量（张）</th>
        <th style="padding:4px 6px;border-bottom:1px solid #334155;text-align:right;">手续费</th>
      </tr></thead>
      <tbody>
        ${items.map((item) => {
          const sideColor = item.side === 'sell' ? RED : GREEN;
          const sideText = item.side === 'sell' ? '卖' : '买';
          const posText = item.pos_side === 'short' ? '空' : item.pos_side === 'long' ? '多' : '';
          return `<tr>
            <td style="padding:4px 6px;color:${DIM};">${esc(timeText(item.ts_iso))}</td>
            <td style="padding:4px 6px;">${esc(item.inst_id)}</td>
            <td style="padding:4px 6px;color:${sideColor};">${sideText}${posText ? `（${posText}）` : ''}</td>
            <td style="padding:4px 6px;text-align:right;">${fmtNumber(item.px)}</td>
            <td style="padding:4px 6px;text-align:right;">${fmtNumber(item.sz, 2)}</td>
            <td style="padding:4px 6px;text-align:right;">${fmtNumber(item.fee, 4)} ${esc(item.fee_ccy || '')}</td>
          </tr>`;
        }).join('')}
      </tbody>
    </table>
    <div style="margin-top:6px;font-size:0.7rem;color:${DIM};">数量为交易所原始单位「张」，P1 不做张数与币数量换算。</div>`;
}

export function renderAccount() {
  const target = document.querySelector('[data-account]');
  if (!target) return;

  const state = getAccountState();
  const status = state.status;

  if (state.error && !status) {
    target.innerHTML = `<div class="empty">账户接口不可用：${esc(state.error)}</div>`;
    return;
  }

  const body = !status || !status.enabled || !status.configured
    ? ''
    : `
      <div style="display:grid;gap:12px;">
        <div class="flow-card">${summaryBlock(state.summary)}</div>
        <div class="flow-card">${positionsBlock(state.positions)}</div>
        <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:12px;">
          <div class="flow-card">${marginBlock(state.margin)}</div>
          <div class="flow-card">${configBlock(state.config)}</div>
        </div>
        <div class="flow-card">${fillsBlock(state.fills)}</div>
      </div>`;

  target.innerHTML = `
    <div style="display:grid;gap:12px;">
      <div class="flow-card">
        <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:8px;">
          <strong style="font-size:0.95rem;">实盘账户（只读）</strong>
          <span style="font-size:0.72rem;color:${DIM};">与「订单」页手工记账相互独立，数字不合并</span>
        </div>
        ${statusBar(status)}
        ${state.error ? `<div style="margin-top:8px;font-size:0.78rem;color:${RED};">最近一次读取失败：${esc(state.error)}</div>` : ''}
      </div>
      ${body}
    </div>`;
}
