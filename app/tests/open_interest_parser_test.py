import asyncio

from unicex import Exchange, start_exchanges_info
from app.screener.parsers.open_interest import OpenInterestParser


e = Exchange.GATE


async def main() -> None:
    """Main entry point for the application."""
    await start_exchanges_info()

    await asyncio.sleep(1.5)

    parser = OpenInterestParser(e)

    asyncio.create_task(parser.start())

    while True:
        await asyncio.sleep(10 if e in [Exchange.BINANCE, Exchange.GATE] else 2)
        data = await parser.fetch_collected_data()
        from pprint import pp

        pp(data.get("ETH_USDT"))


if __name__ == "__main__":
    asyncio.run(main())