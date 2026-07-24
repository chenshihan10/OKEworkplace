import { labels, dirIcons, scoreColor, riskColors, riskLabels } from '../utils/format.js';
import { getAnalysis } from '../stores/analysisStore.js';

function makeBar(val, max) {
  const percent = Math.min(100, (val / max) * 100);
  const color = val >= max * 0.7 ? "#10b981" : val >= max * 0.4 ? "#f59e0b" : "#ef4444";
  return `<div class="score-bar" style="width: ${percent}%; background: ${color};"></div>`;
}

export function renderMarketScores(items) {
  const target = document.querySelector("[data-market-scores]");
  if (!target) return;

  target.innerHTML = items.map((item) => {
    const analysis = getAnalysis(item.symbol);
    if (!analysis) return "";

    if (analysis.isSyncing) {
      return `
        <div class="score-card" style="opacity: 0.6;">
          <div class="score-title">${item.symbol}</div>
          <div class="score-main" style="font-size: 1.1rem; color: #f59e0b; padding: 1.5rem 0;">📡 等待高精度指标清洗...</div>
        </div>
      `;
    }

    const score = analysis.score || 0;
    const comps = analysis.components || {};

    // 评分颜色
    const sc = scoreColor(score);
    const dirIcon = dirIcons[analysis.direction] || "⚪";

    return `
      <div class="score-card">
        <div class="score-title">${item.symbol} ${dirIcon}</div>
        <div class="score-main" style="color: ${sc};">${score}/100</div>
        <div style="font-size:0.8rem;color:#94a3b8;margin-bottom:0.5rem;">
          ${analysis.level || "-"} | 
          <span style="color:${riskColors[analysis.risk] || '#94a3b8'};">${riskLabels[analysis.risk] || analysis.risk || "-"}</span>
          <!-- v2.2：置信度 -->
          ${analysis.confidence != null ? ` | <span style="color:${analysis.confidence >= 70 ? '#10b981' : analysis.confidence >= 40 ? '#f59e0b' : '#ef4444'};">可信度 ${analysis.confidence}%</span>` : ""}
        </div>
        
        <div class="score-components">
          <div class="component">
            <label>${labels.trendComp}</label>
            <div class="bar-container">${makeBar(comps.trend || 0, 30)}</div>
            <span>${comps.trend || 0}</span>
          </div>
          <div class="component">
            <label>${labels.momentumComp}</label>
            <div class="bar-container">${makeBar(comps.momentum || 0, 20)}</div>
            <span>${comps.momentum || 0}</span>
          </div>
          <div class="component">
            <label>${labels.volumeComp}</label>
            <div class="bar-container">${makeBar(comps.volume || 0, 20)}</div>
            <span>${comps.volume || 0}</span>
          </div>
          <div class="component">
            <label>${labels.oiComp}</label>
            <div class="bar-container">${makeBar(comps.oi || 0, 20)}</div>
            <span>${comps.oi || 0}</span>
          </div>
          <div class="component">
            <label>${labels.fundingComp}</label>
            <div class="bar-container">${makeBar(comps.funding || 0, 10)}</div>
            <span>${comps.funding || 0}</span>
          </div>
        </div>
        <!-- v2.2：Decision Trace 决策依据 -->
        ${analysis.decision_trace && analysis.decision_trace.summary ? `
        <div style="margin-top:8px;padding-top:6px;border-top:1px solid #1e293b;font-size:0.7rem;color:#94a3b8;line-height:1.5;">
          <div style="cursor:help;" title="${(analysis.decision_trace.items || []).map(i => i.indicator + ': ' + i.description).join('\\n')}">
            📋 ${analysis.decision_trace.summary.substring(0, 80)}
          </div>
        </div>` : ""}
      </div>
    `;
  }).filter(x => x).join("");
}
