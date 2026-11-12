// 同源部署：桌面端由 FastAPI 托管，Web 部署亦同源，无需写死后端地址
export const apiBase = "";

export async function getJson(path) {
  const res = await fetch(`${apiBase}${path}`, { cache: "no-store" });

  // 拦截 503 状态，解析出后端返回的同步进度
  if (res.status === 503) {
    const errPayload = await res.json();
    try {
      return { isSyncing: true, ...JSON.parse(errPayload.detail) };
    } catch (pErr) {
      return { isSyncing: true, estimated_data_size: "计算中...", estimated_wait_time: "请稍候" };
    }
  }

  if (!res.ok) throw new Error(`${path} 返回 ${res.status}`);
  return res.json();
}
