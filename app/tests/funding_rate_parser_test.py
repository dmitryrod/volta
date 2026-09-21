import asyncio

from unicex import Exchange
from app.screener.parsers.funding_rate import FundingRateParser


async def main() -> None:
    """Main entry point for the application."""
    parser = FundingRateParser(Exchange.OKX)

    asyncio.create_task(parser.start())

    while True:
        await asyncio.sleep(1)
        data = await parser.fetch_collected_data()
        from pprint import pp

        pp(data.get("BTC-USDT-SWAP"))

if __name__ == "__main__":
    asyncio.run(main())