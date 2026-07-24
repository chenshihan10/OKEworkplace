import os
from pathlib import Path

from pydantic import BaseModel, Field
from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parents[2]
load_dotenv(BASE_DIR / ".env")


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
    )


settings = build_settings()


def requests_proxies() -> dict:
    proxies = {}
    if settings.http_proxy:
        proxies["http"] = settings.http_proxy
    if settings.https_proxy:
        proxies["https"] = settings.https_proxy
    return proxies
