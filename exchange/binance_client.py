from __future__ import annotations
import time
from typing import Any, Dict, List, Tuple, Callable

import requests
from binance.um_futures import UMFutures


class BinanceClient:
    def __init__(self, api_key: str, api_secret: str) -> None:
        # UMFutures resmi Binance Futures (USDⓈ-M) istemcisi
        self.client = UMFutures(key=api_key, secret=api_secret)
        # Geriye dönük uyumluluk: bazı yerlerde `um` alanı kullanılıyor
        # (ör. eski selftest/probe scriptleri). AttributeError'ı önlemek için alias.
        self.um = self.client  # type: ignore[attr-defined]
        self._exchange_info_cache: Dict[str, Any] | None = None
        self._symbol_filters: Dict[str, Dict[str, Any]] = {}

    def server_time(self) -> int:
        return int(self.client.time()["serverTime"])  # type: ignore

    def _retry(self, func: Callable, *args, max_retry: int = 3, backoff_ms: int = 400, **kwargs):
        last_err = None
        for i in range(max_retry):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                last_err = e
                time.sleep((backoff_ms / 1000.0) * (1.5 ** i))
        if last_err:
            raise last_err

    def get_price(self, symbol: str) -> float:
        ticker = self._retry(self.client.ticker_price, symbol=symbol)
        return float(ticker["price"])  # type: ignore

    def mark_price(self, symbol: str) -> Dict[str, Any]:
        """Mark price wrapper (dict döner: { 'markPrice': '...' })"""
        return self._retry(self.client.mark_price, symbol=symbol)

    def get_exchange_info(self) -> Dict[str, Any]:
        if self._exchange_info_cache is None:
            self._exchange_info_cache = self._retry(self.client.exchange_info)
        return self._exchange_info_cache

    def get_klines(self, symbol: str, interval: str, limit: int = 500) -> List[List[Any]]:
        return self._retry(self.client.klines, symbol=symbol, interval=interval, limit=limit)

    def get_klines_range(self, symbol: str, interval: str, start_time_ms: int, end_time_ms: int, limit: int = 1500) -> List[List[Any]]:
        out: List[List[Any]] = []
        start = start_time_ms
        while True:
            batch = self._retry(self.client.klines, symbol=symbol, interval=interval, startTime=start, endTime=end_time_ms, limit=limit)
            if not batch:
                break
            out.extend(batch)
            last_close = int(batch[-1][6])
            if last_close >= end_time_ms:
                break
            start = last_close + 1
            time.sleep(0.1)
        return out

    def set_leverage(self, symbol: str, leverage: int) -> None:
        try:
            self._retry(self.client.change_leverage, symbol=symbol, leverage=leverage)
        except Exception:
            pass

    def place_market_order(self, symbol: str, side: str, quantity: float, reduce_only: bool = False, client_id: str | None = None, max_retry: int = 3, backoff_ms: int = 400) -> Dict[str, Any]:
        params = dict(symbol=symbol, side=side, type="MARKET", quantity=quantity, reduceOnly=reduce_only)
        if client_id:
            params["newClientOrderId"] = client_id
        return self._retry(self.client.new_order, **params, max_retry=max_retry, backoff_ms=backoff_ms)

    def place_stop_market(self, symbol: str, side: str, stop_price: float, close_position: bool = True, reduce_only: bool = True, client_id: str | None = None, max_retry: int = 3, backoff_ms: int = 400) -> Dict[str, Any]:
        params = dict(symbol=symbol, side=side, type="STOP_MARKET", stopPrice=str(stop_price), closePosition=close_position, reduceOnly=reduce_only, timeInForce="GTC", workingType="CONTRACT_PRICE")
        if client_id:
            params["newClientOrderId"] = client_id
        return self._retry(self.client.new_order, **params, max_retry=max_retry, backoff_ms=backoff_ms)

    def place_take_profit_market(self, symbol: str, side: str, stop_price: float, quantity: float | None = None, reduce_only: bool = True, client_id: str | None = None, max_retry: int = 3, backoff_ms: int = 400) -> Dict[str, Any]:
        params: Dict[str, Any] = dict(symbol=symbol, side=side, type="TAKE_PROFIT_MARKET", stopPrice=str(stop_price), reduceOnly=reduce_only, timeInForce="GTC", workingType="CONTRACT_PRICE")
        if quantity is not None:
            params["quantity"] = quantity
        if client_id:
            params["newClientOrderId"] = client_id
        return self._retry(self.client.new_order, **params, max_retry=max_retry, backoff_ms=backoff_ms)

    def cancel_order(self, symbol: str, order_id: int | None = None, orig_client_order_id: str | None = None):
        return self._retry(self.client.cancel_order, symbol=symbol, orderId=order_id, origClientOrderId=orig_client_order_id)

    def cancel_open_orders(self, symbol: str):
        return self._retry(self.client.cancel_open_orders, symbol=symbol)

    def get_open_orders(self, symbol: str) -> List[Dict[str, Any]]:
        return self._retry(self.client.get_open_orders, symbol=symbol)

    def get_position_risk(self, symbol: str | None = None) -> List[Dict[str, Any]]:
        return self._retry(self.client.position_risk, symbol=symbol)

    def income_history(self, start_time_ms: int | None = None, end_time_ms: int | None = None, income_type: str | None = None) -> List[Dict[str, Any]]:
        params: Dict[str, Any] = {}
        if start_time_ms is not None:
            params["startTime"] = start_time_ms
        if end_time_ms is not None:
            params["endTime"] = end_time_ms
        if income_type is not None:
            params["incomeType"] = income_type
        return self._retry(self.client.income, **params)

    def get_24h_tickers(self) -> List[Dict[str, Any]]:
        return self._retry(self.client.ticker_24hr_price_change)

    def get_top_usdt_perp_symbols(self, top_n: int = 30, exclude: Tuple[str, ...] = tuple(), price_max: float = 100.0, prefer_low_price_max: float = 1.0, **kwargs) -> List[str]:
        """
        24h hacme göre USDT vadeli en likit sembolleri döndürür.
        Eski çağrılarla uyum için limit/min_price/low_price_priority_max anahtarlarını da kabul eder.
        """
        # Eski imza uyumluluğu
        if "limit" in kwargs and isinstance(kwargs["limit"], int):
            top_n = kwargs["limit"]
        if "min_price" in kwargs:
            # min_price burada kullanılmıyor; mantık gereği düşük fiyat tercihleri `prefer_low_price_max` ile kontrol ediliyor
            pass
        if "low_price_priority_max" in kwargs:
            prefer_low_price_max = float(kwargs["low_price_priority_max"])  # type: ignore[arg-type]
        tickers = self.get_24h_tickers()
        filtered = [t for t in tickers if t.get("symbol", "").endswith("USDT") and t.get("symbol") not in exclude]
        filtered.sort(key=lambda x: float(x.get("quoteVolume", 0.0)), reverse=True)
        symbols = [t["symbol"] for t in filtered]
        prices: Dict[str, float] = {}
        for s in symbols[:top_n*2]:
            try:
                prices[s] = self.get_price(s)
                time.sleep(0.05)
            except Exception:
                continue
        low = [s for s in symbols if s in prices and prices[s] <= prefer_low_price_max]
        mid = [s for s in symbols if s in prices and prefer_low_price_max < prices[s] <= price_max]
        out = (low + mid)[:top_n]
        return out

    def _load_symbol_filters(self, symbol: str) -> Dict[str, Any]:
        if symbol in self._symbol_filters:
            return self._symbol_filters[symbol]
        info = self.get_exchange_info()
        for s in info.get("symbols", []):
            if s.get("symbol") == symbol:
                filters = {f["filterType"]: f for f in s.get("filters", [])}
                self._symbol_filters[symbol] = filters
                return filters
        return {}

    def get_symbol_precision(self, symbol: str) -> Tuple[int, int]:
        info = self.get_exchange_info()
        for s in info.get("symbols", []):
            if s.get("symbol") == symbol:
                qty_precision = s.get("quantityPrecision", 3)
                price_precision = s.get("pricePrecision", 2)
                return int(qty_precision), int(price_precision)
        return 3, 2

    def format_qty(self, symbol: str, quantity: float) -> float:
        filters = self._load_symbol_filters(symbol)
        step_size = float(filters.get("LOT_SIZE", {}).get("stepSize", 0.0) or 0.0)
        if step_size > 0:
            quantity = quantity - (quantity % step_size)
        qty_precision, _ = self.get_symbol_precision(symbol)
        return float(f"{quantity:.{qty_precision}f}")

    def format_price(self, symbol: str, price: float) -> float:
        filters = self._load_symbol_filters(symbol)
        tick_size = float(filters.get("PRICE_FILTER", {}).get("tickSize", 0.0) or 0.0)
        if tick_size > 0:
            price = round(price / tick_size) * tick_size
        _, price_precision = self.get_symbol_precision(symbol)
        return float(f"{price:.{price_precision}f}")

    def min_notional_ok(self, symbol: str, price: float, qty: float) -> bool:
        filters = self._load_symbol_filters(symbol)
        notional = price * qty
        min_notional = float(filters.get("MIN_NOTIONAL", {}).get("notional", 0.0) or 0.0)
        return notional >= min_notional if min_notional > 0 else True
