"""Phase 1 监控脚本：验证方向稳定性和告警去重"""
import urllib.request, json, time, sys
from datetime import datetime

BASE = 'http://127.0.0.1:8000'
SAMPLES = 10
INTERVAL = 30  # seconds


def get_json(path):
    try:
        resp = urllib.request.urlopen(f'{BASE}{path}', timeout=5)
        return json.loads(resp.read())
    except Exception as e:
        return {'error': str(e)}


print(f'Phase 1 监控开始: {datetime.now().strftime("%H:%M:%S")}')
print(f'共 {SAMPLES} 次采样, 每次间隔 {INTERVAL}s, 预计 {SAMPLES*INTERVAL//60} 分钟')
print('=' * 70)
header = f'{"采样":>4}  {"时间":>8}  {"币种":>8}  {"原始方向":>6}  {"稳定方向":>6}  {"评分":>4}  {"方向变":>5}  {"告警数":>5}'
print(header)
print('=' * 70)

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
            rd = data.get('raw_direction', '?')
            sc = data.get('score', 0)
            dc = 'Y' if data.get('direction_changed') else 'N'
            line = f'{i+1:>4}  {ts:>8}  {sym:>8}  {rd:>6}  {d:>6}  {sc:>4}  {dc:>5}  {len(alerts):>5}'
            print(line)
            all_samples.append({
                'sample': i + 1, 'time': ts, 'symbol': sym,
                'raw': rd, 'published': d, 'score': sc,
                'changed': dc, 'alerts': len(alerts)
            })
        elif isinstance(data, dict) and 'error' in data:
            print(f'{i+1:>4}  {ts:>8}  {sym:>8}  ERROR: {data["error"][:40]}')
        else:
            status = data.get('isSyncing', False) if isinstance(data, dict) else False
            label = 'SYNCING' if status else 'NODATA'
            print(f'{i+1:>4}  {ts:>8}  {sym:>8}  {label:>12}')

    if i < SAMPLES - 1:
        time.sleep(INTERVAL)

print('=' * 70)
print(f'监控结束: {datetime.now().strftime("%H:%M:%S")}')
print()

# 分析结果
if all_samples:
    changes = sum(1 for s in all_samples if s['changed'] == 'Y')
    total = len(all_samples)
    mismatches = sum(1 for s in all_samples if s['raw'] != s['published'])
    print()
    print('=== 监控报告 ===')
    print(f'总采样数: {total}')
    print(f'方向变更通知: {changes} 次')
    print(f'原始不等于稳定方向: {mismatches} 次 (DirectionTracker 正在过滤的抖动)')
    print(f'当前告警数: {all_samples[-1]["alerts"] if all_samples else 0}')
    print('================')
