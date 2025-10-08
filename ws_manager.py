from __future__ import annotations
import asyncio, json, time
from binance.websocket.um_futures.websocket_client import UMFuturesWebsocketClient

class WSManager:
    def __init__(self, symbols: list[str], intervals: list[str]) -> None:
        self.symbols = [s.lower() for s in symbols]
        self.intervals = intervals
        self.ws = UMFuturesWebsocketClient()
        self.q: asyncio.Queue = asyncio.Queue()

    def _on_msg(self, _, msg: str) -> None:
        try:
            data = json.loads(msg)
            if data.get("e") == "kline":
                k = data["k"]
                if k.get("x"):
                    self.q.put_nowait(k)
        except Exception:
            pass

    async def start(self) -> None:
        for s in self.symbols:
            for tf in self.intervals:
                self.ws.kline(symbol=s, interval=tf, id=int(time.time()*1000), callback=self._on_msg)

    async def get_closed_bar(self) -> dict:
        return await self.q.get()
