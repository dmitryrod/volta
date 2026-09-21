"""Probe unicex Bybit API (run inside docker)."""
import asyncio
import json

from unicex import Exchange, get_uni_client


async def main() -> None:
    client = await get_uni_client(Exchange.BYBIT).create()
    async with client:
        prices = await client.futures_last_price()
        print("BTC price:", prices.get("BTCUSDT"))
        raw = await client.client.tickers(category="option", base_coin="BTC")
        print("option keys:", raw.keys() if isinstance(raw, dict) else type(raw))
        if isinstance(raw, dict) and "result" in raw:
            lst = raw["result"].get("list", [])
            print("option count:", len(lst))
            if lst:
                print("sample:", json.dumps(lst[0], indent=2)[:500])


if __name__ == "__main__":
    asyncio.run(main())
