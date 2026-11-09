"""Binance Spot Testnet adapter. This module intentionally has no live endpoint."""
from __future__ import annotations
import hashlib
import hmac
import time
from decimal import Decimal, InvalidOperation
from urllib.parse import urlencode
import httpx

BINANCE_SPOT_TESTNET_BASE = "https://testnet.binance.vision"

class ExchangeTestnetError(RuntimeError):
    def __init__(self, code: str, message: str, status_code: int = 502):
        self.code, self.message, self.status_code = code, message, status_code
        super().__init__(f"{code}: {message}")

class BinanceSpotTestnet:
    def __init__(self, api_key: str, api_secret: str, *, timeout: float = 12.0,
                 transport: httpx.AsyncBaseTransport | None = None):
        if not api_key or not api_secret:
            raise ValueError("Testnet API credentials are required")
        self.api_key, self.api_secret = api_key, api_secret
        self.timeout, self.transport = timeout, transport

    def _signed_query(self, params: dict) -> str:
        values = dict(params)
        values["timestamp"] = int(time.time() * 1000)
        values["recvWindow"] = 5000
        query = urlencode(values)
        signature = hmac.new(self.api_secret.encode(), query.encode(), hashlib.sha256).hexdigest()
        return query + "&signature=" + signature

    async def _request(self, method: str, path: str, params: dict | None = None):
        query = self._signed_query(params or {})
        url = f"{BINANCE_SPOT_TESTNET_BASE}{path}?{query}"
        try:
            async with httpx.AsyncClient(timeout=self.timeout, transport=self.transport) as client:
                response = await client.request(method, url, headers={"X-MBX-APIKEY": self.api_key})
        except httpx.HTTPError as exc:
            raise ExchangeTestnetError("NETWORK_ERROR", "Testnet request failed", 502) from exc
        try:
            data = response.json()
        except ValueError:
            data = {}
        if response.status_code >= 400:
            code = str(data.get("code", f"HTTP_{response.status_code}")) if isinstance(data, dict) else f"HTTP_{response.status_code}"
            message = str(data.get("msg", "Exchange rejected the request")) if isinstance(data, dict) else "Exchange rejected the request"
            raise ExchangeTestnetError(code, message[:200], 422 if response.status_code < 500 else 502)
        if not isinstance(data, dict):
            raise ExchangeTestnetError("INVALID_RESPONSE", "Unexpected exchange response")
        return data

    async def verify_account(self) -> dict:
        data = await self._request("GET", "/api/v3/account")
        if data.get("canTrade") is not True:
            raise ExchangeTestnetError("TRADING_NOT_ENABLED", "API key does not have trading permission", 403)
        if data.get("canWithdraw") is not False:
            raise ExchangeTestnetError("WITHDRAWAL_PERMISSION_UNVERIFIED", "API must explicitly report withdrawals disabled", 403)
        return {"can_trade": bool(data.get("canTrade")), "can_withdraw": data.get("canWithdraw"),
                "account_type": data.get("accountType"), "balances_count": len(data.get("balances", []))}

    async def place_limit_order(self, *, symbol: str, side: str, quantity: str, price: str,
                                client_order_id: str) -> dict:
        if side not in {"BUY", "SELL"}:
            raise ValueError("side must be BUY or SELL")
        try:
            q, p = Decimal(quantity), Decimal(price)
        except (InvalidOperation, ValueError):
            raise ValueError("quantity and price must be valid decimal strings")
        if not q.is_finite() or not p.is_finite() or q <= 0 or p <= 0:
            raise ValueError("quantity and price must be finite and positive")
        return await self._request("POST", "/api/v3/order", {
            "symbol": symbol, "side": side, "type": "LIMIT", "timeInForce": "GTC",
            "quantity": format(q, "f"), "price": format(p, "f"),
            "newClientOrderId": client_order_id,
        })

    async def cancel_order(self, *, symbol: str, order_id: str | None = None,
                           client_order_id: str | None = None) -> dict:
        params = {"symbol": symbol}
        if order_id: params["orderId"] = order_id
        elif client_order_id: params["origClientOrderId"] = client_order_id
        else: raise ValueError("order_id or client_order_id is required")
        return await self._request("DELETE", "/api/v3/order", params)

    async def get_order(self, *, symbol: str, client_order_id: str) -> dict:
        return await self._request("GET", "/api/v3/order", {
            "symbol": symbol, "origClientOrderId": client_order_id,
        })
