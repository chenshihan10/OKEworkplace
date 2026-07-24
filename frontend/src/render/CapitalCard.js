import { getAnalysis } from '../stores/analysisStore.js';

export function renderCapitalBehaviors(items) {
  const target = document.querySelector("[data-capital-behaviors]");
  if (!target) return;

  target.innerHTML = items.map((item) => {
    const analysis = getAnalysis(item.symbol);
    if (!analysis) return "";

    // 如果是同步中，直接返回等待提示
    if (analysis.isSyncing) {
      return `
        <div class="behavior-card" style="opacity: 0.6;">
          <div class="behavior-header"><strong>${item.symbol}</strong></div>
          <div class="behavior-type" style="color: #64748b; font-size:0.9rem; padding: 1rem 0;">⏳ 等待逐笔数据聚合 CVD 中...</div>
        </div>
      `;
    }

    // 只有非同步状态，才会声明并使用这些变量
    const behavior = analysis.capital_behavior;
    const price = analysis.price;

    return `
      <div class="behavior-card">
        <div class="behavior-header">
          <strong>${item.symbol}</strong>
          <span class="confidence">置信度: ${behavior.confidence}%</span>
        </div>
        
        <div class="behavior-type">${behavior.type}</div>
        
        <div class="behavior-signals">
          ${behavior.signals.map(s => `<span class="signal-tag">${s}</span>`).join("")}
        </div>
        
        <div class="behavior-implications">
          <strong>含义:</strong> ${behavior.implications}
        </div>
        
        <div class="behavior-suggestion">
          <strong>建议:</strong> ${behavior.suggestion}
        </div>
      </div>
    `;
  }).filter(x => x).join("");
}
