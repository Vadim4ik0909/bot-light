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

    # Start notifier background task
    notifier_task = asyncio.create_task(notifier_service.start())

    try:
        logger.info(
            f"Starting bot for address: {config.CITY_NAME}, {config.STREET_NAME}, {config.BUILDING_NAME} (queue {config.CHER_GPV})"
        )
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        logger.info("Stopping bot and services...")
        notifier_service.stop()
        notifier_task.cancel()
        await api_client.close()
        await bot.session.close()
        logger.info("Bot successfully stopped.")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Application terminated.")
