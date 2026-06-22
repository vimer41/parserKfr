import asyncio
import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import database
import parser
import os

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


async def scheduled_parse():
    """Parse all brands and then check for deficit alerts."""
    logger.info("=== Scheduled parser job started ===")
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, parser.run_parser_iteration)

    # Send deficit alerts after every parse
    try:
        import bot as bot_module
        await bot_module.send_deficit_alerts()
        logger.info("Deficit check completed.")
        
        await bot_module.send_analytics_report()
        logger.info("Analytics report sent.")
    except Exception as e:
        logger.error(f"Alerts/Reports error: {e}")


async def main():
    database.init_db()
    logger.info("Database initialized.")

    # Scheduler: parse every 1 hour (was 3h, now more frequent for better data)
    scheduler = AsyncIOScheduler()
    scheduler.add_job(scheduled_parse, 'interval', hours=1)
    scheduler.start()
    logger.info("Scheduler started (every 1 hour).")

    # Run first parse immediately
    asyncio.create_task(scheduled_parse())

    # Start Telegram bot
    from dotenv import load_dotenv
    load_dotenv()
    token = os.getenv("BOT_TOKEN")

    if token:
        logger.info("Starting Telegram Bot...")
        import bot
        await bot.start_bot()
    else:
        logger.warning("BOT_TOKEN not found! Parser runs, but bot is off.")
        while True:
            await asyncio.sleep(3600)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped!")
