// 简单的发布订阅模式
export function createBus() {
  const handlers = new Map();

  function on(event, callback) {
    if (!handlers.has(event)) {
      handlers.set(event, []);
    }
    handlers.get(event).push(callback);
  }

  function off(event, callback) {
    const cbs = handlers.get(event);
    if (!cbs) return;
    const idx = cbs.indexOf(callback);
    if (idx !== -1) cbs.splice(idx, 1);
  }

  function emit(event, data) {
    const cbs = handlers.get(event);
    if (!cbs) return;
    for (const cb of cbs) {
      cb(data);
    }
  }

  return { on, off, emit };
}
