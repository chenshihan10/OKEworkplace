/** V2.6 实盘只读状态：账户接口要求本机 token，GET 也不例外 */
import { eventBus } from './systemStore.js';

const API_BASE = '/api/v3/account';

let state = {
  status: null,
  summary: null,
  positions: null,
  margin: null,
  fills: null,
  config: null,
  error: null,
  loading: false,
  updatedAt: null,
};

function authHeaders() {
  const token = window.__OKE_TOKEN || '';
  return token ? { 'x-oke-token': token } : {};
}

async function get(path) {
  const res = await fetch(`${API_BASE}${path}`, {
    cache: 'no-store',
    headers: authHeaders(),
  });
  if (res.status === 403) {
    throw new Error('本机 token 校验失败，请从桌面壳重新打开页面');
  }
  if (!res.ok) throw new Error(`${path} 返回 ${res.status}`);
  return res.json();
}

/** 先看配置状态：未启用/未配置时不再拉明细，页面只展示原因占位 */
export async function refreshAccount() {
  state.loading = true;
  try {
    state.status = await get('/status');
    if (state.status.enabled && state.status.configured) {
      const [summary, positions, margin, fills, config] = await Promise.all([
        get('/summary'),
        get('/positions'),
        get('/margin'),
        get('/fills?limit=20'),
        get('/config'),
      ]);
      state.summary = summary;
      state.positions = positions;
      state.margin = margin;
      state.fills = fills;
      state.config = config;
    } else {
      state.summary = null;
      state.positions = null;
      state.margin = null;
      state.fills = null;
      state.config = null;
    }
    state.error = null;
    state.updatedAt = new Date().toISOString();
    eventBus.emit('account:updated');
  } catch (e) {
    state.error = e.message || '账户数据获取失败';
  } finally {
    state.loading = false;
  }
  return state;
}

export function getAccountState() {
  return state;
}
