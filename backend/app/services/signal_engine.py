from app.strategy.trading_rules import trading_rules


class SignalEngine:
    def evaluate(self, symbol, candles, latest_price, timeframe, open_interest=None, funding_rate=None):
        return trading_rules.evaluate(
            symbol=symbol,
            candles=candles,
            latest_price=latest_price,
            timeframe=timeframe,
            open_interest=open_interest,
            funding_rate=funding_rate,
        )


signal_engine = SignalEngine()

