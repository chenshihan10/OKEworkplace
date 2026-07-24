let _analysis = {}; // { symbol: analysisResult }

export function updateAnalysis(symbol, data) {
  _analysis[symbol] = data;
}

export function getAnalysis(symbol) {
  return _analysis[symbol] || null;
}

export function getAllAnalysis() {
  return { ..._analysis };
}

export function clearAnalysis() {
  _analysis = {};
}
