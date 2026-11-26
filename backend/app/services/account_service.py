"""V2.6 实盘只读服务：拉取账户摘要 / 持仓 / 配置 / 成交，缓存并提供给路由层。

降级原则（与实施方案第 8.2 节一致）：
- 未启用或未配置 Key：不发起任何请求，`available=false` 且带原因；
- 网络/代理失败：保留上一轮内存与库数据，标 `stale=true`，绝不解释为 0 余额或空仓；
- 鉴权/时钟错误：退避 5 分钟，避免高频重试触发风控；
- 单资源失败不影响其他资源；所有外部请求都收敛在后台调度里，GET 接口只读缓存。
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from app.core.config import settings
from app.services.account_store import AccountStore
from app.services.okx_private_client import OKXPrivateClient, OKXPrivateError

logger = logging.getLogger(__name__)

FILLS_OVERLAP_MS = 60 * 1000      # 增量拉取向前重叠 1 分钟，主键去重
FILLS_MAX_PAGES = 20              # 单轮最多 2000 条，防止首次回看拖住调度
AUTH_BACKOFF_SECONDS = 300
FAILURE_BACKOFF_THRESHOLD = 3


def _to_float(value) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _now() -> datetime:
    return datetime.now(timezone.utc)


class AccountService:
    RESOURCES = ("summary", "positions", "config", "fills")

    def __init__(self, store: Optional[AccountStore] = None,
                 client: Optional[OKXPrivateClient] = None,
                 orders_provider=None) -> None:
        self._store = store
        self._orders_provider = orders_provider
        self._client = client or OKXPrivateClient(
            settings.private_read_base_url or settings.oke_base_url,
            settings.private_read_api_key,
            settings.private_read_secret_key.get_secret_value(),
            settings.private_read_passphrase.get_secret_value(),
        )
        self._resources: Dict[str, Dict] = {
            name: self._blank_resource() for name in self.RESOURCES
        }
        self._cache: Dict[str, object] = {
            "summary": None,
            "positions": None,   # None=尚未刷新；[]=确实空仓
            "config": None,
        }
        self._cursor: Optional[int] = None
        self._snapshot_at: Dict[str, Optional[datetime]] = {
            "summary": None, "positions": None,
        }
        self._last_prune: Optional[Dict] = None
        self._last_refresh_at: Optional[datetime] = None
        if store is not None:
            self._load_persisted()

    @property
    def store(self) -> AccountStore:
        """延迟建库：未启用/未配置时首页轮询也不会落下空的 live_account.db。"""
        if self._store is None:
            self._store = AccountStore()
            self._load_persisted()
        return self._store

    def _load_persisted(self) -> None:
        self._cursor = self._load_cursor()
        self._cache["config"] = self.store.get_config()

    # ─── 状态工具 ──────────────────────────────────────
    @staticmethod
    def _blank_resource() -> Dict:
        return {
            "available": False, "stale": False,
            "updated_at": None, "error": None, "error_code": None,
            "failures": 0, "next_attempt_at": None,
        }

    def _load_cursor(self) -> Optional[int]:
        raw = self.store.get_state("fills_cursor")
        try:
            return int(raw) if raw else None
        except (TypeError, ValueError):
            return None

    @property
    def enabled(self) -> bool:
        return bool(settings.private_read_enabled)

    @property
    def configured(self) -> bool:
        return self._client.is_configured()

    def _gate_reason(self) -> Optional[str]:
        if not self.enabled:
            return "未启用实盘只读"
        if not self.configured:
            return "未配置只读 API Key"
        return None

    def _blocked(self, resource: str) -> bool:
        next_attempt = self._resources[resource]["next_attempt_at"]
        if not next_attempt:
            return False
        try:
            return datetime.fromisoformat(next_attempt) > _now()
        except ValueError:
            return False

    def _mark_ok(self, resource: str) -> None:
        info = self._resources[resource]
        info.update({
            "available": True, "stale": False, "updated_at": _now().isoformat(),
            "error": None, "error_code": None, "failures": 0, "next_attempt_at": None,
        })

    def _mark_failure(self, resource: str, exc: Exception, has_data: bool) -> None:
        info = self._resources[resource]
        info["failures"] += 1
        info["error"] = str(exc)
        info["error_code"] = getattr(exc, "code", "") or None
        info["stale"] = bool(has_data)
        info["available"] = bool(has_data)

        delay = 0
        if getattr(exc, "is_auth_error", False) or getattr(exc, "needs_clock_check", False):
            delay = AUTH_BACKOFF_SECONDS
        elif info["failures"] >= FAILURE_BACKOFF_THRESHOLD:
            delay = min(300, 30 * 2 ** (info["failures"] - FAILURE_BACKOFF_THRESHOLD))
        info["next_attempt_at"] = (
            (_now() + timedelta(seconds=delay)).isoformat() if delay else None
        )
        logger.warning("account %s failed (attempt %d): %s",
                       resource, info["failures"], exc)

    # ─── 摘要 ──────────────────────────────────────────
    def refresh_summary(self) -> Dict:
        reason = self._gate_reason()
        if reason:
            self._resources["summary"]["error"] = reason
            return self._resources["summary"]
        if self._blocked("summary"):
            return self._resources["summary"]

        try:
            payload = self._client.get("/api/v5/account/balance")
            row = (payload.get("data") or [{}])[0]
            data = {
                "total_eq": _to_float(row.get("totalEq")),
                "avail_eq": _to_float(row.get("availEq")),
                "upl": _to_float(row.get("upl")),
                "imr": _to_float(row.get("imr")),
                "mmr": _to_float(row.get("mmr")),
                "mgn_ratio": _to_float(row.get("mgnRatio")),
                "ord_frozen": _to_float(row.get("ordFrozen")),
                "details": [
                    {
                        "ccy": item.get("ccy"),
                        "eq": _to_float(item.get("eq")),
                        "avail_bal": _to_float(item.get("availBal")),
                        "frozen_bal": _to_float(item.get("frozenBal")),
                        "upl": _to_float(item.get("upl")),
                        "eq_usd": _to_float(item.get("eqUsd")),
                    }
                    for item in (row.get("details") or [])
                ],
            }
            self._cache["summary"] = data
            self._mark_ok("summary")
            self._maybe_snapshot("summary", data)
        except OKXPrivateError as exc:
            self._mark_failure("summary", exc, self._cache["summary"] is not None)
        except Exception as exc:  # 解析异常也不能打断其他资源
            self._mark_failure("summary", exc, self._cache["summary"] is not None)
        return self._resources["summary"]

    # ─── 持仓 ──────────────────────────────────────────
    def refresh_positions(self) -> Dict:
        reason = self._gate_reason()
        if reason:
            self._resources["positions"]["error"] = reason
            return self._resources["positions"]
        if self._blocked("positions"):
            return self._resources["positions"]

        try:
            payload = self._client.get("/api/v5/account/positions", {"instType": "SWAP"})
            rows: List[Dict] = []
            for item in payload.get("data") or []:
                pos_raw = _to_float(item.get("pos"))
                if pos_raw is None or pos_raw == 0:
                    continue
                rows.append({
                    "inst_id": item.get("instId"),
                    "pos_side": item.get("posSide"),
                    "pos_raw": pos_raw,
                    "pos_unit": "contract",
                    "avg_px": _to_float(item.get("avgPx")),
                    "mark_px": _to_float(item.get("markPx")),
                    "upl": _to_float(item.get("upl")),
                    "upl_ratio": _to_float(item.get("uplRatio")),
                    "lever": _to_float(item.get("lever")),
                    "liq_px": _to_float(item.get("liqPx")),
                    "mgn_ratio": _to_float(item.get("mgnRatio")),
                    "mgn_mode": item.get("mgnMode"),
                    # P2：交易所已给出 USD 名义价值，无需 ctVal 换算
                    "notional_usd": _to_float(item.get("notionalUsd")),
                    "raw": item,
                })
            self._cache["positions"] = rows
            self._mark_ok("positions")
            self._maybe_snapshot("positions", rows)
        except OKXPrivateError as exc:
            self._mark_failure("positions", exc, self._cache["positions"] is not None)
        except Exception as exc:
            self._mark_failure("positions", exc, self._cache["positions"] is not None)
        return self._resources["positions"]

    # ─── 账户配置 ──────────────────────────────────────
    def refresh_config(self) -> Dict:
        reason = self._gate_reason()
        if reason:
            self._resources["config"]["error"] = reason
            return self._resources["config"]
        if self._blocked("config"):
            return self._resources["config"]

        try:
            payload = self._client.get("/api/v5/account/config")
            row = (payload.get("data") or [{}])[0]
            data = {
                "acct_lv": row.get("acctLv"),
                "pos_mode": row.get("posMode"),
                # account/config 不返回 mgnMode，实际字段为 mgnIsoMode
                "mgn_mode": row.get("mgnMode") or row.get("mgnIsoMode"),
                "fee_taker": _to_float(row.get("feeTaker")),
                "fee_maker": _to_float(row.get("feeMaker")),
                "updated_at": _now().isoformat(),
                "raw": row,
            }
            self._cache["config"] = {k: v for k, v in data.items() if k != "raw"}
            self.store.save_config(data)
            self._mark_ok("config")
        except OKXPrivateError as exc:
            self._mark_failure("config", exc, self._cache["config"] is not None)
        except Exception as exc:
            self._mark_failure("config", exc, self._cache["config"] is not None)
        return self._resources["config"]

    # ─── 成交增量 ──────────────────────────────────────
    def sync_fills(self) -> Dict:
        reason = self._gate_reason()
        if reason:
            self._resources["fills"]["error"] = reason
            return self._resources["fills"]
        if self._blocked("fills"):
            return self._resources["fills"]

        now_ms = int(time.time() * 1000)
        begin = (self._cursor - FILLS_OVERLAP_MS) if self._cursor else (
            now_ms - settings.account_fills_initial_days * 86400 * 1000
        )
        collected: Dict[tuple, Dict] = {}
        after: Optional[int] = None

        try:
            for _ in range(FILLS_MAX_PAGES):
                params = {
                    "instType": "SWAP",
                    "begin": str(begin),
                    "end": str(now_ms),
                    "limit": "100",
                }
                if after:
                    params["after"] = str(after)
                payload = self._client.get("/api/v5/trade/fills-history", params)
                rows = payload.get("data") or []
                if not rows:
                    break

                page_ts: List[int] = []
                for item in rows:
                    ts = int(item.get("ts") or 0)
                    inst_id = item.get("instId")
                    trade_id = item.get("tradeId")
                    if not ts or not inst_id or trade_id is None:
                        continue
                    page_ts.append(ts)
                    collected[(inst_id, str(trade_id))] = {
                        "inst_id": inst_id,
                        "trade_id": str(trade_id),
                        "ord_id": item.get("ordId"),
                        "side": item.get("side"),
                        "pos_side": item.get("posSide"),
                        # fills-history 实际字段为 fillPx / fillSz；px/sz 仅作旧数据兼容
                        "px": _to_float(item.get("fillPx", item.get("px"))),
                        "sz": _to_float(item.get("fillSz", item.get("sz"))),
                        "fee": _to_float(item.get("fee")),
                        "fee_ccy": item.get("feeCcy"),
                        "ts": ts,
                        "raw": item,
                    }
                if len(rows) < 100 or not page_ts:
                    break
                oldest = min(page_ts)
                if oldest <= begin or oldest == after:
                    break
                after = oldest

            inserted = self.store.upsert_fills(list(collected.values()))
            latest = max((row["ts"] for row in collected.values()), default=0)
            if latest > (self._cursor or 0):
                self._cursor = latest
                self.store.set_state("fills_cursor", str(latest))
            self._mark_ok("fills")
            self._resources["fills"]["inserted"] = inserted
        except OKXPrivateError as exc:
            self._mark_failure("fills", exc, self._cursor is not None)
        except Exception as exc:
            self._mark_failure("fills", exc, self._cursor is not None)
        return self._resources["fills"]

    # ─── 组合刷新 ──────────────────────────────────────
    def refresh_all(self) -> Dict:
        """摘要 + 持仓（30 秒一轮）；配置与成交由各自的低频任务刷新。"""
        self.refresh_summary()
        self.refresh_positions()
        self._last_refresh_at = _now()
        return self.status()

    def prune(self) -> Dict:
        result = self.store.prune(
            settings.account_retention_days, settings.account_fills_retention_days
        )
        self._last_prune = {**result, "at": _now().isoformat()}
        return self._last_prune

    def _maybe_snapshot(self, kind: str, data) -> None:
        now = _now()
        last = self._snapshot_at.get(kind)
        if last and (now - last).total_seconds() < settings.account_snapshot_minutes * 60:
            return
        if kind == "summary":
            self.store.save_account_snapshot({**data, "created_at": now.isoformat()})
        else:
            self.store.save_position_snapshots(data)
        self._snapshot_at[kind] = now

    # ─── 只读视图 ──────────────────────────────────────
    def status(self) -> Dict:
        gate = self._gate_reason()
        resources = {
            name: {
                "available": info["available"],
                "stale": info["stale"],
                "updated_at": info["updated_at"],
                "error": info["error"],
                "error_code": info["error_code"],
            }
            for name, info in self._resources.items()
        }
        resources["fills"]["last_sync_ts"] = self._cursor
        if gate:
            for item in resources.values():
                item["error"] = item["error"] or gate
        available = bool(
            not gate and any(info["available"] for info in self._resources.values())
        )
        return {
            "available": available,
            "enabled": self.enabled,
            "configured": self.configured,
            "key_suffix": self._client.key_suffix,
            "reason": gate,
            "resources": resources,
            "updated_at": _now().isoformat() if available else None,
            "last_refresh_at": self._last_refresh_at.isoformat() if self._last_refresh_at else None,
        }

    def _view(self, resource: str, data) -> Dict:
        info = self._resources[resource]
        reason = info["error"] or self._gate_reason()
        return {
            "available": bool(info["available"] and data is not None),
            "stale": info["stale"],
            "reason": reason,
            "updated_at": info["updated_at"],
            "data": data,
        }

    def summary_view(self) -> Dict:
        return self._view("summary", self._cache["summary"])

    def positions_view(self) -> Dict:
        return self._view("positions", self._cache["positions"])

    def config_view(self) -> Dict:
        return self._view("config", self._cache["config"])

    def fills_view(self, limit: int = 50, offset: int = 0,
                   inst_id: Optional[str] = None) -> Dict:
        info = self._resources["fills"]
        result = self.store.get_fills(limit=limit, offset=offset, inst_id=inst_id)
        reason = info["error"] or self._gate_reason()
        return {
            "available": bool(not self._gate_reason()),
            "pending": self._cursor is None,
            "stale": info["stale"],
            "reason": reason,
            "updated_at": info["updated_at"],
            "total": result["total"],
            "items": result["items"],
        }

    def margin_view(self) -> Dict:
        """派生聚合，仅用于展示；不与订单页的手工记账数字合并。"""
        summary = self._cache["summary"]
        positions = self._cache["positions"] or []
        reason = self._resources["summary"]["error"] or self._gate_reason()
        if summary is None:
            return {
                "available": False, "stale": False, "reason": reason,
                "data": None,
                "sources": ["/api/v5/account/balance", "/api/v5/account/positions"],
                "display_only": True,
            }
        return {
            "available": True,
            "stale": bool(
                self._resources["summary"]["stale"] or self._resources["positions"]["stale"]
            ),
            "reason": reason,
            "updated_at": self._resources["summary"]["updated_at"],
            "data": {
                "account": {
                    "total_eq": summary.get("total_eq"),
                    "imr": summary.get("imr"),
                    "mmr": summary.get("mmr"),
                    "mgn_ratio": summary.get("mgn_ratio"),
                },
                "positions": [
                    {
                        "inst_id": row.get("inst_id"),
                        "mgn_ratio": row.get("mgn_ratio"),
                        "liq_px": row.get("liq_px"),
                    }
                    for row in positions
                ],
            },
            "sources": ["/api/v5/account/balance", "/api/v5/account/positions"],
            "display_only": True,
        }

    def stats(self) -> Dict:
        return {
            "store": self.store.stats(),
            "last_prune": self._last_prune,
            "cursor": self._cursor,
        }

    # ─── P2：账户级真实风险与本地/实盘对账 ─────────────
    def _risk_settings(self) -> Dict:
        try:
            return self._orders().get_risk_settings() or {}
        except Exception:  # 本地订单库读取失败不影响账户展示
            return {}

    @staticmethod
    def _side_of(row: Dict) -> str:
        side = (row.get("pos_side") or "").lower()
        if side in ("long", "short"):
            return side
        return "long" if (row.get("pos_raw") or 0) > 0 else "short"

    def risk_view(self) -> Dict:
        """真实风险：保证金、强平距离、按币种名义敞口与集中度（只展示，不处置）。"""
        gate = self._gate_reason()
        summary = self._cache["summary"]
        positions = self._cache["positions"]
        sources = ["/api/v5/account/balance", "/api/v5/account/positions"]
        if summary is None and positions is None:
            return {
                "available": False, "stale": False, "reason": gate,
                "data": None, "sources": sources, "display_only": True,
            }

        rows: List[Dict] = []
        long_notional = short_notional = 0.0
        for pos in positions or []:
            side = self._side_of(pos)
            notional = abs(pos.get("notional_usd") or 0.0)
            if side == "long":
                long_notional += notional
            else:
                short_notional += notional
            mark, liq = pos.get("mark_px"), pos.get("liq_px")
            liq_distance = None
            if mark and liq:
                liq_distance = ((mark - liq) if side == "long" else (liq - mark)) / mark
            rows.append({
                "inst_id": pos.get("inst_id"),
                "side": side,
                "pos_raw": pos.get("pos_raw"),
                "notional_usd": notional,
                "mark_px": mark,
                "liq_px": liq,
                "liq_distance_pct": liq_distance,
                "mgn_ratio": pos.get("mgn_ratio"),
                "upl": pos.get("upl"),
                "lever": pos.get("lever"),
            })

        total_notional = long_notional + short_notional
        top = max(rows, key=lambda item: item["notional_usd"], default=None)
        threshold_pct = self._risk_settings().get("max_symbol_concentration_pct") or 50.0
        concentration_pct = (top["notional_usd"] / total_notional) if top and total_notional else None
        warnings: List[Dict] = []
        if concentration_pct is not None and concentration_pct * 100 > float(threshold_pct):
            warnings.append({
                "type": "concentration",
                "message": f"{top['inst_id']} 占比 {concentration_pct * 100:.1f}%，"
                           f"超过阈值 {threshold_pct:.0f}%",
            })
        risky = [row for row in rows if row["liq_distance_pct"] is not None]
        nearest = min(risky, key=lambda r: r["liq_distance_pct"], default=None)
        if nearest is not None and 0 <= nearest["liq_distance_pct"] < 0.1:
            warnings.append({
                "type": "liquidation",
                "message": f"{nearest['inst_id']} 距强平仅 {nearest['liq_distance_pct'] * 100:.1f}%",
            })

        return {
            "available": True,
            "stale": bool(
                self._resources["summary"]["stale"] or self._resources["positions"]["stale"]
            ),
            "reason": gate or self._resources["positions"]["error"],
            "updated_at": self._resources["positions"]["updated_at"],
            "data": {
                "account": None if summary is None else {
                    "total_eq": summary.get("total_eq"),
                    "avail_eq": summary.get("avail_eq"),
                    "upl": summary.get("upl"),
                    "imr": summary.get("imr"),
                    "mmr": summary.get("mmr"),
                    "mgn_ratio": summary.get("mgn_ratio"),
                },
                "exposure": {
                    "long_notional": long_notional,
                    "short_notional": short_notional,
                    "net_notional": long_notional - short_notional,
                    "total_notional": total_notional,
                },
                "concentration": {
                    "inst_id": top["inst_id"] if top else None,
                    "pct": concentration_pct,
                    "threshold_pct": float(threshold_pct) / 100,
                    "exceeded": bool(
                        concentration_pct is not None
                        and concentration_pct * 100 > float(threshold_pct)
                    ),
                },
                "nearest_liquidation": None if nearest is None else {
                    "inst_id": nearest["inst_id"],
                    "distance_pct": nearest["liq_distance_pct"],
                },
                "positions": rows,
                "warnings": warnings,
                "units": {"notional": "USD", "liq_distance": "ratio"},
            },
            "sources": sources,
            "display_only": True,
        }

    def reconciliation_view(self) -> Dict:
        """本地手工订单与实盘持仓对账：只并列展示，绝不写回 orders 表。"""
        gate = self._gate_reason()
        sources = ["/api/v5/account/positions", "orders(本地手工记账)"]
        positions = self._cache["positions"]
        if positions is None:
            return {
                "available": False, "stale": False, "reason": gate or "持仓尚未刷新",
                "data": None, "sources": sources, "display_only": True,
            }

        local_rows = self._orders().get_open_orders()
        local: Dict[str, Dict] = {}
        for order in local_rows:
            symbol = (order.get("symbol") or "").upper().replace("-SWAP", "")
            if not symbol:
                continue
            bucket = local.setdefault(symbol, {
                "symbol": symbol, "qty_long": 0.0, "qty_short": 0.0,
                "notional_long": 0.0, "notional_short": 0.0, "orders": 0,
            })
            qty = float(order.get("quantity") or 0)
            price = float(order.get("entry_price") or 0)
            bucket["orders"] += 1
            if (order.get("direction") or "").upper() == "SHORT":
                bucket["qty_short"] += qty
                bucket["notional_short"] += qty * price
            else:
                bucket["qty_long"] += qty
                bucket["notional_long"] += qty * price

        live: Dict[str, Dict] = {}
        for pos in positions:
            symbol = (pos.get("inst_id") or "").upper().replace("-SWAP", "")
            if not symbol:
                continue
            bucket = live.setdefault(symbol, {
                "symbol": symbol, "contracts_long": 0.0, "contracts_short": 0.0,
                "notional": 0.0, "inst_id": pos.get("inst_id"),
            })
            side = self._side_of(pos)
            qty = abs(pos.get("pos_raw") or 0.0)
            if side == "long":
                bucket["contracts_long"] += qty
            else:
                bucket["contracts_short"] += qty
            bucket["notional"] += abs(pos.get("notional_usd") or 0.0)

        tolerance = float(settings.account_reconcile_tolerance_pct) / 100
        rows: List[Dict] = []
        counts = {"matched": 0, "local_only": 0, "live_only": 0,
                  "side_mismatch": 0, "qty_mismatch": 0}
        for symbol in sorted(set(local) | set(live)):
            local_item = local.get(symbol)
            live_item = live.get(symbol)
            local_notional = None
            if local_item:
                local_notional = local_item["notional_long"] + local_item["notional_short"]
            live_notional = live_item["notional"] if live_item else None

            if live_item and local_item:
                local_dir = "long" if local_item["notional_long"] >= local_item["notional_short"] else "short"
                live_dir = "long" if live_item["contracts_long"] >= live_item["contracts_short"] else "short"
                if local_dir != live_dir:
                    status = "side_mismatch"
                elif live_notional is not None and local_notional is not None:
                    diff_ratio = abs(local_notional - live_notional) / max(live_notional, 1e-9)
                    status = "qty_mismatch" if diff_ratio > tolerance else "matched"
                else:
                    status = "matched"
            elif local_item:
                status = "local_only"
            else:
                status = "live_only"
            counts[status] += 1

            rows.append({
                "symbol": symbol,
                "inst_id": (live_item or {}).get("inst_id") or f"{symbol}-SWAP",
                "local": None if local_item is None else {
                    "orders": local_item["orders"],
                    "qty_long": local_item["qty_long"],
                    "qty_short": local_item["qty_short"],
                    "notional_usd": local_notional,
                },
                "live": None if live_item is None else {
                    "contracts_long": live_item["contracts_long"],
                    "contracts_short": live_item["contracts_short"],
                    "notional_usd": live_item["notional"],
                },
                "status": status,
            })

        return {
            "available": True,
            "stale": bool(self._resources["positions"]["stale"]),
            "reason": gate or self._resources["positions"]["error"],
            "updated_at": self._resources["positions"]["updated_at"],
            "data": {
                "tolerance_pct": tolerance,
                "counts": counts,
                "rows": rows,
                "notes": [
                    "本地数量为下单时的手工记账单位，实盘为合约张数，两者单位不同。",
                    "状态按方向与 USD 名义价值对比得出，不写回本地 orders 表。",
                ],
            },
            "sources": sources,
            "display_only": True,
        }

    def _orders(self):
        if self._orders_provider is not None:
            return self._orders_provider()
        global _order_manager
        if _order_manager is None:
            from app.services.order_manager import OrderManager
            _order_manager = OrderManager()
        return _order_manager


_instance: Optional[AccountService] = None
_order_manager = None


def get_account_service() -> AccountService:
    """延迟初始化：功能关闭时连 live_account.db 都不创建。"""
    global _instance
    if _instance is None:
        _instance = AccountService()
    return _instance
