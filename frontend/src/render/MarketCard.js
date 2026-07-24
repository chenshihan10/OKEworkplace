import { fmtNumber, fmtPct, labels, dirIcons, scoreColor } from '../utils/format.js';
import { getAnalysis } from '../stores/analysisStore.js';

export function renderMarketCards(items, prices, signals) {
  const target = document.querySelector("[data-market-grid]");
  if (!target) return;

  target.innerHTML = items.map((item) => {
    const ticker = prices[item.symbol] || {};
    const signal = signals[item.symbol] || {};
    const analysis = getAnalysis(item.symbol) || {};
    const macd = signal.macd || {};
    const oi = signal.open_interest || {};
    const funding = signal.funding_rate || {};
    const source = (ticker.source || "-").toUpperCase();
    const sourceClass = source === "OKX" ? "source-real" : "source-fallback";

    // 市场状态 / 方向
    let stateText = "-";
    let scoreText = "-/100";

    if (analysis.isSyncing) {
      stateText = `<span style="color: #f59e0b; font-size: 0.75rem; animation: pulse 1.5s infinite;">⌛ 正在加载数据 (~${analysis.estimated_data_size})</span>`;
      scoreText = `<span style="color: #94a3b8; font-size: 0.75rem;">预计需 ${analysis.estimated_wait_time}</span>`;
    } else if (analysis.score != null) {
      const dir = analysis.direction || "NEUTRAL";
      const icon = dirIcons[dir] || "❓";
      const sc = scoreColor(analysis.score);
      stateText = `${icon} ${dir === "LONG" ? labels.directionLong : dir === "SHORT" ? labels.directionShort : labels.directionNeutral}`;
      // v2.2：置信度
      const confidence = analysis.confidence != null ? ` 可信度 ${analysis.confidence}%` : "";
      scoreText = `<span style="color:${sc};font-weight:bold;">${analysis.score || "-"}/100</span> ${analysis.level || ""}<span style="color:#94a3b8;font-size:0.75rem;margin-left:4px;">${confidence}</span>`;
    }

    return `
      <article class="market-card">
        <div class="market-top">
          <div>
            <span class="symbol">${item.symbol}</span>
            <span class="alias">${item.alias || item.timeframe || ""}</span>
          </div>
          <span class="source ${sourceClass}">${source}</span>
        </div>
        
        <div class="market-price-row">
          <div class="price">${fmtNumber(ticker.price)}</div>
          <div class="market-meta">
            <div>方向: <strong>${stateText}</strong></div>
            <div>评分: <strong>${scoreText}</strong></div>
          </div>
        </div>

        <div class="metric-grid">
          <div><label>${labels.bid}</label><strong>${fmtNumber(ticker.bid_px)}</strong></div>
          <div><label>${labels.ask}</label><strong>${fmtNumber(ticker.ask_px)}</strong></div>
          <div><label>${labels.trend}</label><strong>${signal.trend || "-"}</strong></div>
          <div><label>${labels.macd}</label><strong>${fmtNumber(macd.diff)} / ${fmtNumber(macd.dea)}</strong></div>
          <div><label>${labels.oi}</label><strong>${fmtNumber(oi.open_interest, 0)}</strong></div>
          <div><label>${labels.funding}</label><strong>${fmtPct(funding.funding_rate)}</strong></div>
        </div>
        <!-- v2.2：标记价 / 指数价 -->
        <div style="display:flex;gap:12px;margin-top:8px;font-size:0.75rem;color:#94a3b8;border-top:1px solid #1e293b;padding-top:6px;">
          <span>标记价: <strong>${fmtNumber(analysis.mark_price)}</strong></span>
          <span>指数价: <strong>${fmtNumber(analysis.index_price)}</strong></span>
          <span>价差: <strong>${fmtNumber(analysis.mark_index_spread)}</strong></span>
        </div>
      </article>
    `;
  }).join("");
}
