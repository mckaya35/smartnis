from __future__ import annotations

try:
    from binance.um_futures import UMFutures  # type: ignore
except Exception:
    UMFutures = None  # type: ignore

# Eski/yenı sürüm farkını köprüle: position_risk yoksa, position_information/account ile emüle et
if UMFutures is not None and not hasattr(UMFutures, "position_risk"):
    def position_risk(self, symbol: str | None = None):
        if hasattr(self, "position_information"):
            return self.position_information(symbol=symbol)
        acc = self.account()
        positions = acc.get("positions", [])
        if symbol:
            positions = [p for p in positions if p.get("symbol") == symbol]
        return positions
    setattr(UMFutures, "position_risk", position_risk)
