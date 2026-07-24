// ============ 中文标签 ============
export const labels = {
  bid: "买价",
  ask: "卖价",
  trend: "趋势",
  macd: "MACD",
  oi: "持仓量",
  funding: "资金费率",
  noSignals: "暂无信号",
  noOrderFlow: "暂无订单流",
  buyVol: "买入量",
  sellVol: "卖出量",
  bestAsk: "最优卖价",
  bestBid: "最优买价",
  backendOffline: "后端离线",
  realData: "实时数据 (OKX)",
  fallbackData: "本地数据",
  proxyDisabled: "代理已禁用",
  marketScore: "综合评分",
  directionLong: "做多",
  directionShort: "做空",
  directionNeutral: "中性",
  riskLow: "低风险",
  riskMedium: "中风险",
  riskHigh: "高风险",
  trendComp: "趋势 (30)",
  momentumComp: "动量 (20)",
  volumeComp: "成交量 (20)",
  oiComp: "OI (20)",
  fundingComp: "费率 (10)",
};

// ============ 格式化函数 ============
export function fmtNumber(value, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "-";
  return Number(value).toLocaleString(undefined, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

export function fmtPct(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "-";
  return `${(Number(value) * 100).toFixed(4)}%`;
}

// ============ 方向图标 ============
export const dirIcons = { LONG: "🟢", SHORT: "🔴", NEUTRAL: "⚪" };

// ============ 评分颜色 ============
export function scoreColor(score) {
  if (score >= 85) return "#10b981";
  if (score >= 70) return "#f59e0b";
  if (score >= 55) return "#3b82f6";
  return "#94a3b8";
}

// ============ 风险 ============
export const riskColors = { LOW: "#10b981", MEDIUM: "#f59e0b", HIGH: "#ef4444" };
export const riskLabels = { LOW: labels.riskLow, MEDIUM: labels.riskMedium, HIGH: labels.riskHigh };
