import httpx
from .config import settings

async def binance_klines(symbol: str, interval: str, limit: int):
    url = f"{settings.binance_base_url}/api/v3/klines"
    async with httpx.AsyncClient(timeout=12) as client:
        response = await client.get(url, params={"symbol": symbol.upper(), "interval": interval, "limit": limit})
        response.raise_for_status()
        rows = response.json()
    return [{"time": int(r[0]//1000), "open": float(r[1]), "high": float(r[2]),
             "low": float(r[3]), "close": float(r[4]), "volume": float(r[5])} for r in rows]
