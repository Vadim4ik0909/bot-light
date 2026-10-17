import asyncio
import logging
import sys
from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.types import BotCommand

from config import config
from database import db
from api_client import ToeApiClient
from notifier import NotifierService
from handlers import router, api_client

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("bot-light")

async def set_commands(bot: Bot):
    commands = [
        BotCommand(command="status", description="💡 Поточний стан світла"),
        BotCommand(command="today", description="📅 Графік на сьогодні"),
        BotCommand(command="tomorrow", description="📆 Графік на завтра"),
        BotCommand(command="accidents", description="🚨 Аварійні та ремонтні роботи"),
        BotCommand(command="settings", description="⚙️ Налаштування сповіщень"),
        BotCommand(command="help", description="ℹ️ Довідка та допомога"),
    ]
    await bot.set_my_commands(commands)

async def main():
    if not config.BOT_TOKEN or config.BOT_TOKEN == "YOUR_TELEGRAM_BOT_TOKEN_HERE":
        logger.error(
            "CRITICAL: TELEGRAM_BOT_TOKEN is not set!\n"
            "Please create a .env file and set BOT_TOKEN=your_token from @BotFather.\n"
            "Example file is available at .env.example"
        )
        sys.exit(1)

    logger.info("Initializing database...")
    await db.init()

    bot = Bot(
        token=config.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )
    dp = Dispatcher()
    dp.include_router(router)

    notifier_service = NotifierService(bot=bot, api_client=api_client)

    await set_commands(bot)
    logger.info("Bot commands registered.")

    # Start lightweight health check HTTP server (for Render / cloud healthchecks)
    import os
    from aiohttp import web

    health_app = web.Application()
    health_app.router.add_get("/", lambda r: web.Response(text="Bot is running!"))
    health_app.router.add_get("/health", lambda r: web.Response(text="OK"))
    runner = web.AppRunner(health_app)
    await runner.setup()
    port = int(os.getenv("PORT", "10000"))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info(f"Health check server listening on port {port}")

    # Start notifier background task
    notifier_task = asyncio.create_task(notifier_service.start())

    # Keep-alive background task: pings itself every 10 min to prevent Render Free Tier from sleeping
    async def keep_alive():
        service_url = os.getenv("RENDER_EXTERNAL_URL", "https://bot-light-44ib.onrender.com").rstrip("/")
        health_url = f"{service_url}/health"
        logger.info(f"Keep-alive self-ping configured for: {health_url}")
        await asyncio.sleep(60)  # Wait 1 minute after initial boot
        import aiohttp
        async with aiohttp.ClientSession() as session:
            while True:
                try:
                    async with session.get(health_url, timeout=15) as resp:
                        logger.info(f"Keep-alive ping to {health_url}: status {resp.status}")
                except Exception as e:
                    logger.warning(f"Keep-alive ping error: {e}")
                await asyncio.sleep(600)  # 10 minutes (Render timeout is 15 min)

    keep_alive_task = asyncio.create_task(keep_alive())

    try:
        logger.info(
            f"Starting bot for address: {config.CITY_NAME}, {config.STREET_NAME}, {config.BUILDING_NAME} (queue {config.CHER_GPV})"
        )
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        logger.info("Stopping bot and services...")
        notifier_service.stop()
        notifier_task.cancel()
        keep_alive_task.cancel()
        await api_client.close()
        await bot.session.close()
        logger.info("Bot successfully stopped.")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Application terminated.")
