import { labels, dirIcons, scoreColor } from '../utils/format.js';
import { getAnalysis } from '../stores/analysisStore.js';

export function renderSignals(signalsBySymbol) {
  const target = document.querySelector("[data-signals]");
  const count = document.querySelector("[data-signal-count]");
  if (!target) return;

  const signals = Object.values(signalsBySymbol || {});
  if (count) count.textContent = `${signals.length}`;
  if (!signals.length) {
    target.innerHTML = `<div class="empty">${labels.noSignals}</div>`;
    return;
  }

  target.innerHTML = signals.map((signal) => {
    const analysis = getAnalysis(signal.symbol);
    if (!analysis || analysis.isSyncing) return "";

    const dir = analysis.direction || "NEUTRAL";
    const dirText = dir === "LONG" ? labels.directionLong : dir === "SHORT" ? labels.directionShort : labels.directionNeutral;
    const dirEmoji = dirIcons[dir] || "❓";
    const reasons = analysis.reasons || [];
    const sc = scoreColor(analysis.score || 0);

    // v2.2：方向稳定性提示
    const rawDir = analysis.raw_direction;
    const stableDir = analysis.direction;
    const dirChanged = analysis.direction_changed;
    const stabilityBadge = (rawDir && rawDir !== stableDir)
      ? `<span style="font-size:0.7rem;color:#94a3b8;margin-left:4px;" title="原始方向: ${rawDir} → 稳定方向: ${stableDir}">🔄 过滤后稳定</span>`
      : "";
    const changeBadge = dirChanged
      ? `<span style="font-size:0.7rem;color:#f59e0b;margin-left:4px;">🆕 方向变更</span>`
      : "";

    return `
      <div class="signal-item ${dir.toLowerCase()}">
        <div class="signal-header">
          <strong>${signal.symbol}</strong>
          <span class="recommendation" style="color:${sc};">
            ${dirEmoji} ${dirText} ${stabilityBadge} ${changeBadge}
          </span>
        </div>
        <div class="signal-reason">
          ${reasons.map(r => `<div>• ${r}</div>`).join("")}
        </div>
        <p class="signal-desc">评分: <strong style="color:${sc};">${analysis.score || 0}/100</strong> (${analysis.level || "-"}) | 风险: ${analysis.risk || "-"}${analysis.confidence != null ? ` | 可信度: ${analysis.confidence}%` : ""}</p>
      </div>
    `;
  }).filter(x => x).join("");
}
