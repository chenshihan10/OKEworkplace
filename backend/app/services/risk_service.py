"""风险管理：手工订单的止损/止盈、组合敞口与触达事件。

设计约束：
  - 只使用内存最新价，不额外请求 OKX；
  - 触达事件只代表“价格触及”，不代表成交，也不自动平仓；
  - 结果仅用于展示，不写回五维评分 / 预测方向。
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from app.services.market_service import market_service
from app.services.order_manager import OrderManager, planned_risk, risk_reward

RISK_TRIGGER_COOLDOWN_SECONDS = 30 * 60
ENTRY_PROXIMITY_PCT = 0.5


def _distance_pct(direction: str, entry: float, level: Optional[float], kind: str) -> Optional[float]:
    """止损/止盈距离%（始终为正）：LONG 时 SL 在下方、TP 在上方；SHORT 相反。"""
    if level is None or not entry:
        return None
    if direction == "LONG":
        return round((entry - level) / entry * 100, 3) if kind == "sl" else round((level - entry) / entry * 100, 3)
    return round((level - entry) / entry * 100, 3) if kind == "sl" else round((entry - level) / entry * 100, 3)


def _risk_state(direction: str, price: Optional[float],
                stop_loss: Optional[float], take_profit: Optional[float]) -> str:
    if stop_loss is None and take_profit is None:
        return "no_stop"
    if price is None:
        return "normal"
    if stop_loss is not None:
        if (direction == "LONG" and price <= stop_loss) or (direction == "SHORT" and price >= stop_loss):
            return "sl_hit"
    if take_profit is not None:
        if (direction == "LONG" and price >= take_profit) or (direction == "SHORT" and price <= take_profit):
            return "tp_hit"
    return "normal"


def order_risk_view(order: dict, settings: dict, current_price: Optional[float]) -> dict:
    """单笔订单的风险指标（纯计算，不读写数据库）。"""
    entry = float(order.get("entry_price") or 0)
    direction = order.get("direction") or "LONG"
    quantity = float(order.get("quantity") or 0)
    stop_loss = order.get("stop_loss")
    take_profit = order.get("take_profit")
    equity = settings.get("equity")
    risk_per_trade_pct = settings.get("risk_per_trade_pct") or 1.0

    risk_amount = planned_risk(entry, stop_loss, quantity)
    rr = risk_reward(entry, stop_loss, take_profit)
    risk_of_equity_pct = (
        round(risk_amount / equity * 100, 3)
        if risk_amount is not None and equity else None
    )
    suggested_qty = (
        round(equity * risk_per_trade_pct / 100 / abs(entry - stop_loss), 6)
        if equity and stop_loss is not None and abs(entry - stop_loss) > 0 else None
    )

    return {
        "order_id": order.get("id"),
        "symbol": order.get("symbol"),
        "direction": direction,
        "entry_price": entry,
        "current_price": current_price,
        "quantity": quantity,
        "note": order.get("note") or "",
        "created_at": order.get("created_at"),
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "sl_distance_pct": _distance_pct(direction, entry, stop_loss, "sl"),
        "tp_distance_pct": _distance_pct(direction, entry, take_profit, "tp"),
        "rr": rr,
        "planned_risk": risk_amount,
        "risk_of_equity_pct": risk_of_equity_pct,
        "suggested_qty": suggested_qty,
        "notional": round(entry * quantity, 4) if quantity else 0.0,
        "risk_state": _risk_state(direction, current_price, stop_loss, take_profit),
    }


class RiskService:
    def __init__(self, order_mgr: Optional[OrderManager] = None) -> None:
        self._orders = order_mgr or OrderManager()

    def settings(self) -> dict:
        return self._orders.get_risk_settings()

    def update_settings(self, equity: Optional[float], risk_per_trade_pct: float,
                        max_portfolio_risk_pct: float,
                        max_symbol_concentration_pct: float) -> dict:
        return self._orders.save_risk_settings(
            equity, risk_per_trade_pct, max_portfolio_risk_pct, max_symbol_concentration_pct
        )

    def events(self, symbol: Optional[str] = None, limit: int = 50) -> list:
        return self._orders.list_risk_events(symbol=symbol, limit=limit)

    def _prices(self) -> dict:
        return market_service.snapshot().get("prices", {})

    def portfolio(self) -> dict:
        """组合风险汇总：只读内存价，不触发外部请求。"""
        settings = self._orders.get_risk_settings()
        prices = self._prices()
        orders = self._orders.get_open_orders()
        equity = settings.get("equity")
        max_risk_pct = settings.get("max_portfolio_risk_pct") or 6.0
        max_concentration_pct = settings.get("max_symbol_concentration_pct") or 50.0
        risk_per_trade_pct = settings.get("risk_per_trade_pct") or 1.0

        views = []
        for order in orders:
            price = (prices.get(order["symbol"]) or {}).get("price")
            views.append(order_risk_view(order, settings, price))

        total_notional = round(sum(v["notional"] for v in views), 4)
        planned = round(sum(v["planned_risk"] for v in views if v["planned_risk"] is not None), 4)
        risk_of_equity_pct = round(planned / equity * 100, 3) if equity and planned else None

        long_notional = round(sum(v["notional"] for v in views if v["direction"] == "LONG"), 4)
        short_notional = round(sum(v["notional"] for v in views if v["direction"] == "SHORT"), 4)

        by_symbol: dict = {}
        for view in views:
            item = by_symbol.setdefault(view["symbol"], {
                "symbol": view["symbol"], "notional": 0.0, "planned_risk": 0.0,
            })
            item["notional"] = round(item["notional"] + view["notional"], 4)
            if view["planned_risk"] is not None:
                item["planned_risk"] = round(item["planned_risk"] + view["planned_risk"], 4)
        for item in by_symbol.values():
            item["concentration_pct"] = (
                round(item["notional"] / total_notional * 100, 2) if total_notional else 0.0
            )

        warnings = []
        if equity is None:
            warnings.append("未配置账户权益，无法计算风险占比与建议数量")
        no_stop = [v for v in views if v["stop_loss"] is None]
        if no_stop:
            ids = "、#".join(str(v["order_id"]) for v in no_stop)
            warnings.append(f"订单 #{ids} 未设置止损（共 {len(no_stop)} 笔）")
        for item in by_symbol.values():
            if item["concentration_pct"] > max_concentration_pct:
                warnings.append(
                    f"{item['symbol']} 占名义仓位 {item['concentration_pct']}%，"
                    f"超过 {max_concentration_pct}% 阈值"
                )
        if risk_of_equity_pct is not None and risk_of_equity_pct > max_risk_pct:
            warnings.append(
                f"组合计划风险占权益 {risk_of_equity_pct}%，超过 {max_risk_pct}% 阈值"
            )
        for view in views:
            if (view["risk_of_equity_pct"] is not None
                    and view["risk_of_equity_pct"] > risk_per_trade_pct):
                warnings.append(
                    f"订单 #{view['order_id']} 计划风险占权益 {view['risk_of_equity_pct']}%，"
                    f"超过单笔 {risk_per_trade_pct}% 阈值"
                )

        return {
            "equity": equity,
            "settings": settings,
            "open_orders": len(views),
            "total_notional": total_notional,
            "planned_risk": planned,
            "risk_of_equity_pct": risk_of_equity_pct,
            "net_exposure": {
                "long": long_notional,
                "short": short_notional,
                "net": round(long_notional - short_notional, 4),
            },
            "by_symbol": list(by_symbol.values()),
            "warnings": warnings,
            "orders": views,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

    def check_price_levels(self, symbol: Optional[str] = None,
                           current_price: Optional[float] = None) -> dict:
        """价格触及检测：开仓价 ±0.5% 建议 + 止损/止盈触达事件。

        事件写入 risk_events（同一订单同一事件 30 分钟冷却），只提示，不平仓。
        """
        settings = self._orders.get_risk_settings()
        snapshot = market_service.snapshot()
        prices = snapshot.get("prices", {})
        signals = snapshot.get("signals", {})
        orders = self._orders.get_open_orders(symbol)

        levels = []
        new_events = []

        for order in orders:
            price = current_price
            if price is None:
                ticker = prices.get(order["symbol"], {})
                price = ticker.get("price", ticker.get("last"))

            view = order_risk_view(order, settings, price)

            # 开仓价附近建议（保留 v2.3 行为）
            entry = order["entry_price"]
            distance_pct = round((price - entry) / entry * 100, 2) if price else None
            triggered = distance_pct is not None and abs(distance_pct) <= ENTRY_PROXIMITY_PCT
            level = {
                **view,
                "distance_pct": distance_pct,
                "threshold_pct": ENTRY_PROXIMITY_PCT,
                "triggered": triggered,
                "suggestion": "observe",
                "reason": "价格尚未回到开仓价附近",
                "alert": False,
                "cooldown_remaining": 0,
            }

            if triggered:
                analysis = (signals.get(order["symbol"]) or {}).get("analysis") or {}
                sys_dir = analysis.get("direction")
                sys_score = analysis.get("score")

                if sys_dir and sys_score is not None:
                    level["system_direction"] = sys_dir
                    level["system_score"] = sys_score
                    level["system_confidence"] = analysis.get("confidence")
                    if sys_dir == order["direction"]:
                        level["suggestion"] = "hold"
                        level["reason"] = f"系统方向 {sys_dir}(评分 {sys_score}) 与你持仓方向一致"
                    else:
                        level["suggestion"] = "consider_close"
                        level["reason"] = (
                            f"系统方向 {sys_dir}(评分 {sys_score}) "
                            f"与你持仓方向 {order['direction']} 相反"
                        )
                else:
                    level["signals_ready"] = False
                    level["reason"] = "价格已触及开仓价附近，系统信号尚未就绪"

                level.update(self._orders.level_alert_state(order["id"], level["suggestion"]))

            # 止损/止盈触达：写事件（冷却由数据库判断）
            if price is not None and view["risk_state"] in ("sl_hit", "tp_hit"):
                event_type = view["risk_state"]
                event_level = order["stop_loss"] if event_type == "sl_hit" else order["take_profit"]
                event = self._orders.record_risk_event(
                    order["id"], order["symbol"], event_type, price, event_level,
                    RISK_TRIGGER_COOLDOWN_SECONDS,
                )
                if event:
                    new_events.append(event)

            levels.append(level)

        return {"levels": levels, "risk_events": new_events}


risk_service = RiskService()
