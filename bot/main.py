import asyncio
import logging
import os
import sys

from aiogram import Bot, Dispatcher, types
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart
from aiogram.fsm.storage.redis import RedisStorage
from aiogram.types import Message
from redis.asyncio.client import Redis

from bot import sell_handlers, buy_handlers


# Redis client for FSM storage
dp = Dispatcher()


from aiogram.utils.keyboard import ReplyKeyboardBuilder

@dp.message(CommandStart())
async def command_start_handler(message: Message) -> None:
    builder = ReplyKeyboardBuilder()
    builder.add(types.KeyboardButton(text="Продать NFT"))
    # Can add more buttons here later, e.g., "Мои лоты", "Баланс"
    # builder.adjust(2)

    await message.answer(
        f"Здравствуйте, {message.from_user.full_name}!\n\n"
        "Добро пожаловать на NFT-аукцион. Здесь вы можете выставить свои NFT на продажу или принять участие в торгах.",
        reply_markup=builder.as_markup(resize_keyboard=True),
    )


from database.pool import init_pool, close_pool
from config import load_config
from blockchain.encryption import init_encryption
from .scheduler import init_scheduler, get_scheduler

REDIS_CHANNEL = "lot_activation_channel"

async def redis_listener(bot: Bot, config):
    """Listens for messages from the Watcher and triggers lot publication."""
    redis_url = f"redis://{config.redis.host}:{config.redis.port}/1"
    r = Redis.from_url(redis_url, decode_responses=True)
    async with r.pubsub() as pubsub:
        await pubsub.subscribe(REDIS_CHANNEL)
        logging.info("Redis listener started.")
        while True:
            message = await pubsub.get_message(ignore_subscribe_messages=True)
            if message:
                lot_id = int(message['data'])
                logging.info(f"Received notification to publish lot {lot_id}.")
                await sell_handlers.publish_lot(lot_id, bot, config.bot.channel_id)

                # After publishing, schedule its end if it's a lottery
                from database import queries as db
                from bot.scheduler import schedule_lottery_end

                lot_details = await db.get_lot_type_and_duration(lot_id)
                if lot_details and lot_details['lot_type'] == 'lottery':
                    await schedule_lottery_end(lot_id, lot_details['duration_hours'])

            await asyncio.sleep(0.1)

async def main() -> None:
    config = load_config()

    # Setup FSM storage
    redis_url = f"redis://{config.redis.host}:{config.redis.port}/0"
    storage = RedisStorage(Redis.from_url(redis_url))
    dp.storage = storage

    init_encryption(config.security.encryption_key)
    await init_pool(config.db.__dict__)
    init_scheduler(config)

    dp.include_router(sell_handlers.router)
    dp.include_router(buy_handlers.router)

    bot = Bot(config.bot.token, parse_mode=ParseMode.HTML)

    # A bit of a hack to make the bot instance available to scheduler jobs
    get_scheduler().add_job(lambda: bot, id="bot_instance", replace_existing=True)

    listener_task = asyncio.create_task(redis_listener(bot, config))

    try:
        await dp.start_polling(bot)
    finally:
        listener_task.cancel()
        get_scheduler().shutdown()
        await close_pool()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    asyncio.run(main())
