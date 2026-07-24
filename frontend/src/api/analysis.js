import { getJson, apiBase } from './okx.js';

export async function fetchSnapshot() {
  return getJson('/api/monitor/snapshot');
}

export async function fetchAnalysis(symbol) {
  return getJson(`/api/analysis/${symbol}`);
}

// ============ 添加/删除币种（可搜索下拉） ============
let availableCoins = [];
let selectedCoin = null;

export async function loadAvailableCoins() {
  if (availableCoins.length > 0) { renderDropdown(availableCoins); return; }
  try {
    const resp = await fetch(`${apiBase}/api/coins/available`);
    if (!resp.ok) throw new Error(await resp.text());
    availableCoins = await resp.json();
    renderDropdown(availableCoins);
  } catch (e) {
    console.warn("加载可用币种失败:", e);
  }
}

export function filterAvailableCoins(query) {
  const q = query.toUpperCase().trim();
  if (!q) { renderDropdown(availableCoins); return; }
  const filtered = availableCoins.filter(c => c.symbol.includes(q));
  renderDropdown(filtered);
}

function renderDropdown(coins) {
  const dd = document.getElementById("coin-dropdown");
  if (!dd) return;
  if (!coins.length) {
    dd.innerHTML = '<div class="coin-dropdown-empty">无匹配币种</div>';
    dd.classList.add("show");
    return;
  }
  dd.innerHTML = coins.slice(0, 50).map(c => `
    <div class="coin-dropdown-item${selectedCoin === c.symbol ? ' selected' : ''}"
         onclick="selectCoin('${c.symbol}')">
      <span class="sym">${c.symbol}</span>
      <span>
        <span class="price">${c.last ? '$' + c.last.toLocaleString() : '-'}</span>
        <span class="vol"> | 24h量: ${(c.vol24h / 1000000).toFixed(1)}M</span>
      </span>
    </div>
  `).join("");
  dd.classList.add("show");
}

export function selectCoin(symbol) {
  selectedCoin = symbol;
  document.getElementById("new-coin-search").value = symbol;
  const dd = document.getElementById("coin-dropdown");
  if (dd) dd.classList.remove("show");
}

export async function addCoinFromSearch() {
  const symbol = selectedCoin || document.getElementById("new-coin-search").value.trim().toUpperCase();
  if (!symbol) { alert("请选择或输入币种"); return; }
  // 移除 -SWAP 后缀（如果用户输入了完整 instId）
  const cleanSymbol = symbol.replace("-SWAP", "");
  try {
    const resp = await fetch(`${apiBase}/api/coins`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ symbol: cleanSymbol, alias: cleanSymbol, timeframe: "15m" }),
    });
    if (!resp.ok) throw new Error(await resp.text());
    document.getElementById("new-coin-search").value = "";
    selectedCoin = null;
    const dd = document.getElementById("coin-dropdown");
    if (dd) dd.classList.remove("show");
    // 触发页面刷新（依赖全局 refresh）
    if (typeof refresh === "function") refresh();
  } catch (e) {
    alert("添加失败: " + e.message);
  }
}

export async function removeCoin(symbol) {
  if (!confirm(`确定删除 ${symbol}？`)) return;
  try {
    const resp = await fetch(`${apiBase}/api/coins/${symbol}`, { method: "DELETE" });
    if (!resp.ok) throw new Error(await resp.text());
    if (typeof refresh === "function") refresh();
  } catch (e) {
    alert("删除失败: " + e.message);
  }
}

// 挂载到 window 以供 HTML onclick 调用
window.loadAvailableCoins = loadAvailableCoins;
window.filterAvailableCoins = filterAvailableCoins;
window.addCoinFromSearch = addCoinFromSearch;
window.removeCoin = removeCoin;
window.selectCoin = selectCoin;
