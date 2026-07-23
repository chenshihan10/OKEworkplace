"""共享关闭信号 - 前端关闭窗口时通知后端停止"""
import threading

shutdown_event = threading.Event()
