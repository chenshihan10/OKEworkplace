from .coins import router as coins_router
from .monitor import router as monitor_router
from .network import router as network_router
from .analysis import router as analysis_router

# 显式暴露给 main.py 导入
__all__ = ["coins", "monitor", "network", "analysis"]

# 桥接命名空间，确保 main.py 里的导入语句不发生破坏
class MockModule:
    def __init__(self, router):
        self.router = router

coins = MockModule(coins_router)
monitor = MockModule(monitor_router)
network = MockModule(network_router)
analysis = MockModule(analysis_router)