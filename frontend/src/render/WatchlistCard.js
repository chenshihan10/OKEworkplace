export function renderWatchlist(items, prices, signals) {
  const target = document.querySelector("[data-watchlist]");
  const count = document.querySelector("[data-watch-count]");
  if (!target) return;

  if (count) count.textContent = `${items.length} 个币种`;
  target.innerHTML = items.map((item) => {
    return `
      <tr data-symbol="${item.symbol}">
        <td>${item.symbol}</td>
        <td><button class="del-btn" onclick="removeCoin('${item.symbol}')">删除</button></td>
      </tr>
    `;
  }).join("");
}
