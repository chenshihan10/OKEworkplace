import { createBus } from '../utils/eventBus.js';

// 创建全局事件总线
export const eventBus = createBus();

let _networkStatus = null;
let _activeTab = 'overview';
let _isOffline = false;

export function updateNetwork(status) {
  _networkStatus = status;
  eventBus.emit('network:change', status);
}

export function getNetwork() { return _networkStatus; }

export function setActiveTab(tab) {
  _activeTab = tab;
  eventBus.emit('tab:change', tab);
}

export function getActiveTab() { return _activeTab; }

export function setOffline(val) {
  _isOffline = val;
  eventBus.emit('offline:change', val);
}

export function isOffline() { return _isOffline; }
