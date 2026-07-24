import { getJson } from './okx.js';

export async function fetchNetworkStatus() {
  return getJson('/network/status');
}
