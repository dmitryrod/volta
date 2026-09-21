import asyncio

from unicex import Exchange, MarketType
from app.screener.parsers.agg_trades import AggTradesParser


async def main() -> None:
    """Main entry point for the application."""
    parser = AggTradesParser(Exchange.BINANCE, MarketType.FUTURES)
    
    asyncio.create_task(parser.start())
    
    while True:
        await asyncio.sleep(1)
        data = await parser.fetch_collected_data()

        if data:
            klines = data["BTCUSDT"]

        if len(klines) > 20:
            for k in klines:
                from datetime import datetime
        
                print(datetime.fromtimestamp(k["t"] / 1000), k["c"])
            return



if __name__ == "__main__":
    asyncio.run(main())