from __future__ import annotations
import asyncio, json
from binance.um_futures import UMFutures
from binance.websocket.um_futures.websocket_client import UMFuturesWebsocketClient

class UserStream:
    def __init__(self, api_key: str, api_secret: str) -> None:
        self.rest = UMFutures(key=api_key, secret=api_secret)
        self.ws = UMFuturesWebsocketClient()
        self.q: asyncio.Queue = asyncio.Queue()
        self._listen_key: str | None = None
        self._started: bool = False

    async def start(self) -> None:
        if self._started:
            return
        lk = self.rest.new_listen_key()["listenKey"]
        self._listen_key = lk
        def cb(_, msg: str):
            try:
                self.q.put_nowait(json.loads(msg))
            except Exception:
                pass
        self.ws.user_data(listen_key=lk, callback=cb)
        self._started = True

    async def stop(self) -> None:
        try:
            await asyncio.to_thread(self.ws.stop)
        except Exception:
            pass
        self._started = False

    async def refresh_listen_key(self) -> None:
        try:
            if self._listen_key:
                await asyncio.to_thread(self.rest.keepalive_listen_key, self._listen_key)
        except Exception:
            # Fallback: restart user stream
            await self.stop()
            await self.start()

    async def get_event(self) -> dict:
        return await self.q.get()
