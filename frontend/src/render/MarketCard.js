import { fmtNumber, labels, dirIcons, scoreColor } from '../utils/format.js';
import { getAnalysis } from '../stores/analysisStore.js';

export function renderMarketCards(items, prices, signals, mtfItems = []) {
  const target = document.querySelector("[data-market-grid]");
  if (!target) return;

  const mtfMap = {};
  for (const mtf of mtfItems || []) mtfMap[mtf.symbol] = mtf;

  target.innerHTML = items.map((item) => {
    const ticker = prices[item.symbol] || {};
    const signal = signals[item.symbol] || {};
    const analysis = getAnalysis(item.symbol) || {};
    const macd = signal.macd || {};
    const hasData = ticker.price != null;
    const source = hasData ? (ticker.source || "okx").toUpperCase() : "数据不可用";
    const sourceClass = hasData ? "source-real" : "source-fallback";

    // v3.0：市场状态（纯规则），数据缺失时不显示
    const regime = analysis.market_regime || {};
    const regimeLabel = regime.regime && regime.regime !== "UNKNOWN" ? regime.label : "";

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

    // 多周期徽标（旁路展示，不参与评分）
    const mtf = mtfMap[item.symbol];
    let mtfLine = "";
    if (mtf && (mtf.timeframes || []).length) {
      const badges = mtf.timeframes.map(tf => {
        const icon = dirIcons[tf.direction] || "⚪";
        return `<span style="border:1px solid #334155;border-radius:3px;padding:0 5px;">${tf.timeframe} ${icon}${tf.score ?? "-"}</span>`;
      }).join("");
      const counter = mtf.counter_trend
        ? `<span style="color:#f59e0b;">⚠ 逆大周期</span>`
        : "";
      mtfLine = `<div style="display:flex;gap:6px;flex-wrap:wrap;margin-top:8px;font-size:0.72rem;color:#94a3b8;">${badges}${counter}</div>`;
    }

    return `
      <article class="market-card">
        <div class="market-top">
          <div>
            <span class="symbol">${item.symbol}</span>
            <span class="alias">${item.alias || item.timeframe || ""}</span>
          </div>
          <div style="display:flex;align-items:center;gap:8px;">
            ${regimeLabel ? `<span style="font-size:0.72rem;color:#94a3b8;border:1px solid #334155;border-radius:4px;padding:1px 6px;" title="市场状态：${regimeLabel}">${regimeLabel}</span>` : ""}
            <span class="source ${sourceClass}">${source}</span>
          </div>
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
          <div><label>${labels.macd}</label><strong>${fmtNumber(macd.diff)} / ${fmtNumber(macd.dea)}</strong></div>
        </div>
        ${mtfLine}
        <!-- v2.2：标记价 / 指数价 -->
        <div style="display:flex;gap:12px;margin-top:8px;font-size:0.75rem;color:#94a3b8;border-top:1px solid #1e293b;padding-top:6px;">
          <span>标记价: <strong>${fmtNumber(analysis.mark_price)}</strong></span>
          <span>指数价: <strong>${fmtNumber(analysis.index_price)}</strong></span>
          <span>价差: <strong>${fmtNumber(analysis.mark_index_spread)}</strong></span>
        </div>
        <!-- v2.3：开单按钮 -->
        <div style="margin-top:10px;text-align:right;border-top:1px solid #1e293b;padding-top:8px;">
          <button onclick="window.__openOrderModal('${item.symbol}', ${ticker.price || 0})"
                  style="padding:6px 16px;background:#2563eb;color:#fff;border:none;border-radius:6px;cursor:pointer;font-size:0.85rem;font-weight:600;">
            📝 开单
          </button>
        </div>
      </article>
    `;
  }).join("");
}
