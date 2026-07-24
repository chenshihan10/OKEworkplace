import { fmtNumber, dirIcons } from '../utils/format.js';
import { getAnalysis } from '../stores/analysisStore.js';

export function renderWatchlist(items, prices, signals) {
  const target = document.querySelector("[data-watchlist]");
  const count = document.querySelector("[data-watch-count]");
  if (!target) return;

  if (count) count.textContent = `${items.length} 个币种`;
  target.innerHTML = items.map((item) => {
    const ticker = prices[item.symbol] || {};
    const signal = signals[item.symbol] || {};
    const analysis = getAnalysis(item.symbol) || {};
    const dirIcon = dirIcons[analysis.direction] || "";

    return `
      <tr data-symbol="${item.symbol}">
        <td>${dirIcon} ${item.symbol}</td>
        <td>${item.timeframe}</td>
        <td>${fmtNumber(ticker.price)}</td>
        <td>${analysis.direction || "-"}</td>
        <td>${(ticker.source || "-").toUpperCase()}</td>
        <td class="score">${analysis.score || "-"}</td>
        <td><button class="del-btn" onclick="removeCoin('${item.symbol}')">删除</button>
            <button class="order-btn" onclick="window.__openOrderModal('${item.symbol}', ${ticker.price || 0})" style="margin-left:4px;padding:4px 8px;background:#2563eb;color:#fff;border:none;border-radius:4px;cursor:pointer;font-size:0.75rem;">📝 开单</button></td>
      </tr>
    `;
  }).join("");
}
