"""
系统集成测试脚本
验证后端 API、市场评分算法、资金行为分析
"""

import requests
import json
import time
from datetime import datetime

# 配置
API_BASE = "http://127.0.0.1:8000"
TIMEOUT = 5

class TestResult:
    def __init__(self, name):
        self.name = name
        self.passed = False
        self.error = None
        self.response = None
        self.response_time = 0
        
    def __str__(self):
        status = "✅ PASS" if self.passed else "❌ FAIL"
        result = f"{status} | {self.name}\n"
        if self.error:
            result += f"  错误: {self.error}\n"
        if self.response_time > 0:
            result += f"  响应时间: {self.response_time:.2f}ms\n"
        return result

def test_backend_health():
    """测试后端健康状态"""
    test = TestResult("后端健康检查")
    try:
        start = time.time()
        response = requests.get(f"{API_BASE}/health", timeout=TIMEOUT)
        test.response_time = (time.time() - start) * 1000
        
        test.response = response.json()
        test.passed = response.status_code == 200
        if not test.passed:
            test.error = f"状态码 {response.status_code}"
    except Exception as e:
        test.error = str(e)
    return test

def test_monitor_snapshot():
    """测试监控快照端点"""
    test = TestResult("监控快照接口")
    try:
        start = time.time()
        response = requests.get(f"{API_BASE}/api/monitor/snapshot", timeout=TIMEOUT)
        test.response_time = (time.time() - start) * 1000
        
        data = response.json()
        test.response = data
        
        # 验证数据格式
        required_fields = ["watch_items", "prices", "signals", "updated_at"]
        test.passed = all(field in data for field in required_fields)
        
        if test.passed:
            items = data.get("watch_items", [])
            if not items:
                test.error = "没有监控币种"
                test.passed = False
        else:
            test.error = f"缺少字段: {set(required_fields) - set(data.keys())}"
    except Exception as e:
        test.error = str(e)
    return test

def test_analysis_endpoint(symbol="BTC-USDT"):
    """测试分析端点"""
    test = TestResult(f"分析接口 (/api/analysis/{symbol})")
    try:
        start = time.time()
        response = requests.get(f"{API_BASE}/api/analysis/{symbol}", timeout=TIMEOUT)
        test.response_time = (time.time() - start) * 1000
        
        data = response.json()
        test.response = data
        
        # 验证必需字段
        required_fields = [
            "symbol", "price", "market_score", "market_state",
            "components", "capital_behavior", "recommendation"
        ]
        test.passed = all(field in data for field in required_fields)
        
        if test.passed:
            # 验证组件字段
            components = data.get("components", {})
            component_fields = ["trend_score", "capital_score", "orderflow_score", "risk_score"]
            components_ok = all(f in components for f in component_fields)
            
            if not components_ok:
                test.passed = False
                test.error = f"components 缺少字段"
            else:
                # 验证市场评分范围
                score = data.get("market_score", -1)
                if not (0 <= score <= 100):
                    test.passed = False
                    test.error = f"市场评分 {score} 超出范围 [0, 100]"
        else:
            missing = set(required_fields) - set(data.keys())
            test.error = f"缺少字段: {missing}"
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 404:
            test.error = f"符号 {symbol} 无数据（正常）"
        else:
            test.error = str(e)
    except Exception as e:
        test.error = str(e)
    return test

def test_api_response_time():
    """测试 API 响应时间"""
    test = TestResult("API 响应时间性能")
    try:
        # 进行 5 次请求，计算平均响应时间
        response_times = []
        
        for i in range(5):
            start = time.time()
            requests.get(f"{API_BASE}/api/monitor/snapshot", timeout=TIMEOUT)
            response_times.append((time.time() - start) * 1000)
            time.sleep(0.1)  # 避免过频繁的请求
        
        avg_time = sum(response_times) / len(response_times)
        test.response_time = avg_time
        
        # 快照应该 < 500ms
        test.passed = avg_time < 500
        
        if not test.passed:
            test.error = f"平均响应时间 {avg_time:.2f}ms > 500ms"
        else:
            min_time = min(response_times)
            max_time = max(response_times)
            print(f"  细节: 最小 {min_time:.2f}ms, 最大 {max_time:.2f}ms, 平均 {avg_time:.2f}ms")
    except Exception as e:
        test.error = str(e)
    return test

def test_market_score_logic(analysis_response):
    """测试市场评分逻辑"""
    test = TestResult("市场评分算法逻辑")
    try:
        data = analysis_response.get("response", {})
        
        components = data.get("components", {})
        trend = components.get("trend_score", 0)
        capital = components.get("capital_score", 0)
        orderflow = components.get("orderflow_score", 0)
        risk = components.get("risk_score", 0)
        
        # 检查分量范围
        test.passed = all(
            0 <= trend <= 25,
            0 <= capital <= 25,
            0 <= orderflow <= 25,
            -25 <= risk <= 0
        )
        
        if test.passed:
            # 计算综合评分
            calculated_score = trend + capital + orderflow + risk
            actual_score = data.get("market_score", 0)
            
            # 应该在计算值的 ±2 范围内（由于取整）
            test.passed = abs(calculated_score - actual_score) <= 2
            
            if not test.passed:
                test.error = f"评分计算不匹配: {trend}+{capital}+{orderflow}+{risk}={calculated_score}, 实际={actual_score}"
        else:
            test.error = f"分量超出范围: trend={trend}, capital={capital}, orderflow={orderflow}, risk={risk}"
    except Exception as e:
        test.error = str(e)
    return test

def test_capital_behavior(analysis_response):
    """测试资金行为分析"""
    test = TestResult("资金行为分析")
    try:
        data = analysis_response.get("response", {})
        behavior = data.get("capital_behavior", {})
        
        required_fields = ["type", "confidence", "signals", "implications", "suggestion"]
        test.passed = all(field in behavior for field in required_fields)
        
        if test.passed:
            # 验证置信度范围
            confidence = behavior.get("confidence", -1)
            test.passed = 0 <= confidence <= 100
            
            if not test.passed:
                test.error = f"置信度 {confidence} 超出范围 [0, 100]"
        else:
            missing = set(required_fields) - set(behavior.keys())
            test.error = f"缺少字段: {missing}"
    except Exception as e:
        test.error = str(e)
    return test

def test_recommendation_logic(analysis_response):
    """测试建议逻辑"""
    test = TestResult("交易建议逻辑")
    try:
        data = analysis_response.get("response", {})
        recommendation = data.get("recommendation", {})
        
        required_fields = ["signal", "reason", "confidence"]
        test.passed = all(field in recommendation for field in required_fields)
        
        if test.passed:
            # 验证信号值
            valid_signals = ["BUY", "SELL", "AVOID", "MONITOR", "WAIT"]
            signal = recommendation.get("signal", "")
            test.passed = signal in valid_signals
            
            if not test.passed:
                test.error = f"无效的信号 '{signal}'"
        else:
            missing = set(required_fields) - set(recommendation.keys())
            test.error = f"缺少字段: {missing}"
    except Exception as e:
        test.error = str(e)
    return test

def run_all_tests():
    """运行所有测试"""
    print("=" * 60)
    print("🧪 OKEworkplace 系统集成测试")
    print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"API: {API_BASE}")
    print("=" * 60)
    print()
    
    results = []
    
    # 1. 健康检查
    health = test_backend_health()
    results.append(health)
    print(health)
    
    if not health.passed:
        print("❌ 后端未运行，无法继续测试")
        return results
    
    # 2. 快照接口
    snapshot = test_monitor_snapshot()
    results.append(snapshot)
    print(snapshot)
    
    # 3. 分析接口
    if snapshot.passed and snapshot.response:
        items = snapshot.response.get("watch_items", [])
        if items:
            symbol = items[0].get("symbol", "BTC-USDT")
            analysis = test_analysis_endpoint(symbol)
            results.append(analysis)
            print(analysis)
            
            # 分析相关测试
            if analysis.passed:
                score_logic = test_market_score_logic(analysis)
                results.append(score_logic)
                print(score_logic)
                
                behavior = test_capital_behavior(analysis)
                results.append(behavior)
                print(behavior)
                
                recommendation = test_recommendation_logic(analysis)
                results.append(recommendation)
                print(recommendation)
    
    # 4. 性能测试
    performance = test_api_response_time()
    results.append(performance)
    print(performance)
    
    # 总结
    print("=" * 60)
    passed = sum(1 for r in results if r.passed)
    total = len(results)
    print(f"测试结果: {passed}/{total} 通过")
    print("=" * 60)
    
    # 详细报告（JSON 格式）
    print("\n📋 详细结果（JSON）:")
    report = {
        "timestamp": datetime.now().isoformat(),
        "api_base": API_BASE,
        "passed": passed,
        "total": total,
        "tests": [
            {
                "name": r.name,
                "passed": r.passed,
                "error": r.error,
                "response_time_ms": r.response_time
            }
            for r in results
        ]
    }
    print(json.dumps(report, indent=2, ensure_ascii=False))
    
    return results

if __name__ == "__main__":
    run_all_tests()
