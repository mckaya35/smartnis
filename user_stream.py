from __future__ import annotations
import asyncio, json
from binance.um_futures import UMFutures
from binance.websocket.um_futures.websocket_client import UMFuturesWebsocketClient

class UserStream:
    def __init__(self, api_key: str, api_secret: str) -> None:
        self.rest = UMFutures(key=api_key, secret=api_secret)
        self.ws = UMFuturesWebsocketClient()
        self.q: asyncio.Queue = asyncio.Queue()

    async def start(self) -> None:
        lk = self.rest.new_listen_key()["listenKey"]
        def cb(_, msg: str):
            try:
                self.q.put_nowait(json.loads(msg))
            except Exception:
                pass
        self.ws.user_data(listen_key=lk, callback=cb)

    async def get_event(self) -> dict:
        return await self.q.get()
