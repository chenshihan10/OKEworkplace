"""V2.2 最终全量监控：方向稳定 + 置信度 + 趋势阶段 + 告警 + SQLite"""
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


print(f'V2.2 最终监控开始: {datetime.now().strftime("%H:%M:%S")}')
print(f'共 {SAMPLES} 次采样, 每 {INTERVAL}s, 预计 {SAMPLES*INTERVAL//60} 分钟')
print()
header = (
    f'{"#":>3}  {"时间":>8}  {"币种":>6}  '
    f'{"方向":>6}  {"置信":>4}  {"评分":>4}  {"阶段":>8}  {"标记价":>8}  {"告警":>4}'
)
print(header)
print('=' * len(header))

all_samples = []

for i in range(SAMPLES):
    ts = datetime.now().strftime('%H:%M:%S')
    btc = get_json('/api/analysis/BTC-USDT')
    eth = get_json('/api/analysis/ETH-USDT')
    snap = get_json('/api/monitor/snapshot')
    alerts = len(snap.get('alerts', [])) if isinstance(snap, dict) else 0
    history = get_json('/api/signals/history/BTC-USDT')
    db_count = history.get('stats', {}).get('total_signals', 0) if isinstance(history, dict) else 0

    for sym, data in [('BTC', btc), ('ETH', eth)]:
        if isinstance(data, dict) and 'direction' in data:
            d = data.get('direction', '?')
            cf = data.get('confidence', 0)
            sc = data.get('score', 0)
            tp = data.get('trend_phase', {}).get('phase_label', '-')[:8]
            mp = data.get('mark_price', 0)
            line = f'{i+1:>3}  {ts:>8}  {sym:>6}  {d:>6}  {cf:>3}%  {sc:>3}  {tp:>8}  {mp:>8.0f}  {alerts:>4}'
            print(line)
            all_samples.append({
                'sample': i + 1, 'symbol': sym, 'direction': d,
                'confidence': cf, 'score': sc, 'phase': tp,
                'mark_price': mp, 'alerts': alerts, 'db_count': db_count,
            })
        elif isinstance(data, dict) and 'isSyncing' in data:
            print(f'{i+1:>3}  {ts:>8}  {sym:>6}  {"SYNC":>14}')
        else:
            err = data.get('error', 'NODATA')[:15]
            print(f'{i+1:>3}  {ts:>8}  {sym:>6}  {"ERR":>14}  {err}')

    if i < SAMPLES - 1:
        time.sleep(INTERVAL)

print('=' * len(header))
print(f'监控结束: {datetime.now().strftime("%H:%M:%S")}')
print()

if all_samples:
    last = all_samples[-1]
    changes = sum(1 for s in all_samples if s.get('changed') == 'Y')
    avg_conf = sum(s['confidence'] for s in all_samples) / len(all_samples)
    phases = set(s['phase'] for s in all_samples if s['phase'] != '-')

    print()
    print('=' * 50)
    print('   V2.2 最终监控报告')
    print('=' * 50)
    print(f'总采样:          {len(all_samples)}')
    print(f'方向稳定性:       {"✅ 无抖动" if changes == 0 else f"⚠ {changes}次变更"}')
    print(f'平均置信度:      {avg_conf:.0f}%')
    print(f'趋势阶段分布:    {", ".join(phases) if phases else "N/A"}')
    print(f'当前告警数:      {last.get("alerts", 0)}')
    print(f'SQLite 历史记录: {last.get("db_count", 0)} 条')
    print(f'标记价采集:      {"✅ 有效" if last.get("mark_price", 0) > 0 else "⚠ 待配置"}')
    print('=' * 50)
