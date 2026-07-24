"""Phase 2 监控脚本：验证方向稳定 + 标记价 + 置信度 + 决策追溯"""
import urllib.request, json, time
from datetime import datetime

BASE = 'http://127.0.0.1:8000'
SAMPLES = 10
INTERVAL = 30


def get_json(path):
    try:
        resp = urllib.request.urlopen(f'{BASE}{path}', timeout=5)
        return json.loads(resp.read())
    except Exception as e:
        return {'error': str(e)}


print(f'Phase 2 监控开始: {datetime.now().strftime("%H:%M:%S")}')
print(f'共 {SAMPLES} 次采样, 每次间隔 {INTERVAL}s, 预计 {SAMPLES*INTERVAL//60} 分钟')
print()

header = (
    f'{"采样":>4}  {"时间":>8}  {"币种":>8}  '
    f'{"方向":>6}  {"置信度":>5}  {"标记价":>8}  {"指数价":>8}  {"价差":>6}  '
    f'{"Trace数":>6}  {"方向变":>5}  {"告警":>4}'
)
print(header)
print('=' * len(header))

all_samples = []

for i in range(SAMPLES):
    ts = datetime.now().strftime('%H:%M:%S')
    btc = get_json('/api/analysis/BTC-USDT')
    eth = get_json('/api/analysis/ETH-USDT')
    snap = get_json('/api/monitor/snapshot')
    alerts = snap.get('alerts', []) if isinstance(snap, dict) else []

    for sym, data in [('BTC', btc), ('ETH', eth)]:
        if isinstance(data, dict) and 'direction' in data:
            d = data.get('direction', '?')
            cf = data.get('confidence', -1)
            mp = data.get('mark_price', 0)
            ip = data.get('index_price', 0)
            sp = data.get('mark_index_spread', 0)
            tc = len(data.get('decision_trace', {}).get('items', []))
            dc = 'Y' if data.get('direction_changed') else 'N'

            line = f'{i+1:>4}  {ts:>8}  {sym:>8}  {d:>6}  {cf:>5}%  {mp:>8.0f}  {ip:>8.0f}  {sp:>6.2f}  {tc:>6}  {dc:>5}  {len(alerts):>4}'
            print(line)
            all_samples.append({
                'sample': i + 1, 'symbol': sym, 'direction': d,
                'confidence': cf, 'mark_price': mp, 'index_price': ip,
                'spread': sp, 'trace_count': tc, 'changed': dc, 'alerts': len(alerts)
            })
        elif isinstance(data, dict) and 'isSyncing' in data:
            print(f'{i+1:>4}  {ts:>8}  {sym:>8}  {"SYNCING":>6}')
        else:
            err = data.get('error', 'NODATA')[:20]
            print(f'{i+1:>4}  {ts:>8}  {sym:>8}  {"ERROR":>6}  {err}')

    if i < SAMPLES - 1:
        time.sleep(INTERVAL)

print('=' * len(header))
print(f'监控结束: {datetime.now().strftime("%H:%M:%S")}')
print()

if all_samples:
    # 分析
    changes = sum(1 for s in all_samples if s['changed'] == 'Y')
    avg_conf = sum(s['confidence'] for s in all_samples if s['confidence'] >= 0) / max(1, sum(1 for s in all_samples if s['confidence'] >= 0))
    with_mark = sum(1 for s in all_samples if s['mark_price'] > 0)
    with_index = sum(1 for s in all_samples if s['index_price'] > 0)
    with_trace = sum(1 for s in all_samples if s['trace_count'] > 0)
    final_alerts = all_samples[-1]['alerts'] if all_samples else 0

    print()
    print('=== Phase 2 监控报告 ===')
    print(f'总采样: {len(all_samples)}')
    print(f'方向变更通知: {changes} 次')
    print(f'平均置信度: {avg_conf:.0f}%')
    print(f'标记价有效: {with_mark}/{len(all_samples)}')
    print(f'指数价有效: {with_index}/{len(all_samples)}')
    print(f'Trace生成: {with_trace}/{len(all_samples)}')
    print(f'当前告警: {final_alerts}')
    print('======================')
