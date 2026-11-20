import os
import sys
from pathlib import Path

from pydantic import BaseModel, Field
from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parents[2]
load_dotenv(BASE_DIR / ".env")

# 版本单一真源：仓库根目录 VERSION 文件
# 开发模式 backend/app/core/config.py → BASE_DIR=backend，向上一级取仓库根
# 打包后 _internal/app/core/config.py → BASE_DIR=_internal，VERSION 随包放在此处
if getattr(sys, "frozen", False):
    VERSION_FILE = BASE_DIR / "VERSION"
else:
    VERSION_FILE = BASE_DIR.parent / "VERSION"


def read_version() -> str:
    try:
        return VERSION_FILE.read_text(encoding="utf-8").strip()
    except Exception:
        return "0.0.0.0"


APP_VERSION = read_version()


class Settings(BaseModel):
    oke_base_url: str = Field(default="https://api.example.com")
    oke_api_key: str = Field(default="")
    oke_secret_key: str = Field(default="")
    http_proxy: str = Field(default="")
    https_proxy: str = Field(default="")
    poll_interval_seconds: int = Field(default=5)
    default_timeframes: list = Field(default_factory=lambda: ["5m", "15m", "1h", "4h"])
    signal_cooldown_minutes: int = Field(default=30)
    btc_levels: list = Field(default_factory=lambda: [59000, 60000, 62000, 63000])
    eth_levels: list = Field(default_factory=lambda: [1700, 1730, 1750, 1780, 1800, 1830])
    rsi_enabled: bool = Field(default=False)
    data_storage_strategy: str = Field(default="memory")  # memory | aggregated | persistent
    keep_history_records: int = Field(default=100)  # 保留最近 N 条数据记录
    # v2.2：方向抖动控制参数
    signal_buffer_size: int = Field(default=12)
    signal_hysteresis_low: int = Field(default=35)
    signal_hysteresis_high: int = Field(default=55)
    signal_confirm_count: int = Field(default=3)
    signal_flip_count: int = Field(default=4)
    signal_cooldown_minutes_v2: int = Field(default=5)
    # v2.3：网络状态判定（以行情数据新鲜度为准，避免单次探测失败导致状态抖动）
    data_grace_seconds: int = Field(default=15)      # 数据年龄在此范围内仍视为可用
    data_stale_seconds: int = Field(default=60)      # 超过此秒数无更新才提示“停止更新”
    data_boot_check_seconds: int = Field(default=10)  # 启动后等待首笔数据的宽限时间


def build_settings() -> Settings:
    return Settings(
        oke_base_url=os.getenv("OKE_BASE_URL", "https://api.example.com"),
        oke_api_key=os.getenv("OKE_API_KEY", ""),
        oke_secret_key=os.getenv("OKE_SECRET_KEY", ""),
        http_proxy=os.getenv("HTTP_PROXY", ""),
        https_proxy=os.getenv("HTTPS_PROXY", ""),
        poll_interval_seconds=int(os.getenv("POLL_INTERVAL_SECONDS", "5")),
        default_timeframes=os.getenv("MONITOR_TIMEFRAMES", "5m,15m,1h,4h").split(","),
        signal_cooldown_minutes=int(os.getenv("SIGNAL_COOLDOWN_MINUTES", "30")),
        btc_levels=[float(x) for x in os.getenv("BTC_LEVELS", "59000,60000,62000,63000").split(",")],
        eth_levels=[float(x) for x in os.getenv("ETH_LEVELS", "1700,1730,1750,1780,1800,1830").split(",")],
        rsi_enabled=os.getenv("RSI_ENABLED", "false").lower() == "true",
        data_storage_strategy=os.getenv("DATA_STORAGE_STRATEGY", "memory"),
        keep_history_records=int(os.getenv("KEEP_HISTORY_RECORDS", "100")),
        # v2.2 方向抖动控制
        signal_buffer_size=int(os.getenv("SIGNAL_BUFFER_SIZE", "12")),
        signal_hysteresis_low=int(os.getenv("SIGNAL_HYSTERESIS_LOW", "35")),
        signal_hysteresis_high=int(os.getenv("SIGNAL_HYSTERESIS_HIGH", "55")),
        signal_confirm_count=int(os.getenv("SIGNAL_CONFIRM_COUNT", "3")),
        signal_flip_count=int(os.getenv("SIGNAL_FLIP_COUNT", "4")),
        signal_cooldown_minutes_v2=int(os.getenv("SIGNAL_COOLDOWN_MINUTES", "5")),
        # v2.3 网络状态判定阈值
        data_grace_seconds=int(os.getenv("OKE_DATA_GRACE_SECONDS", "15")),
        data_stale_seconds=int(os.getenv("OKE_DATA_STALE_SECONDS", "60")),
        data_boot_check_seconds=int(os.getenv("OKE_DATA_BOOT_CHECK_SECONDS", "10")),
    )


settings = build_settings()


def requests_proxies() -> dict:
    proxies = {}
    if settings.http_proxy:
        proxies["http"] = settings.http_proxy
    if settings.https_proxy:
        proxies["https"] = settings.https_proxy
    return proxies
