import asyncio

from unicex import Exchange
from app.screener.parsers.liquidations import LiquidationsParser


async def main() -> None:
    """Main entry point for the application."""
    parser = LiquidationsParser()

    asyncio.create_task(parser.start())

    while True:
        await asyncio.sleep(1)
        data = await parser.fetch_collected_data()
        from pprint import pp

        if data:
            pp(data)

if __name__ == "__main__":
    asyncio.run(main())