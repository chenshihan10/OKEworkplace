// 内部状态
let _snapshot = null;
let _prices = {};
let _signals = {};
let _updatedAt = null;

export function updateSnapshot(snapshot) {
  _snapshot = snapshot;
  _prices = snapshot.prices || {};
  _signals = snapshot.signals || {};
  _updatedAt = snapshot.updated_at || null;
}

export function getPrices() { return _prices; }
export function getSignals() { return _signals; }
export function getSnapshot() { return _snapshot; }
export function getUpdatedAt() { return _updatedAt; }
