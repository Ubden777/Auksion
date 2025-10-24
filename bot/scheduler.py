from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.jobstores.redis import RedisJobStore
from aiogram import Bot, Dispatcher
from config import Config
from datetime import datetime, timedelta
from database import queries as db

# Global scheduler instance
scheduler = None

def init_scheduler(config: Config):
    """Initializes and starts the scheduler."""
    global scheduler
    if scheduler is None:
        redis_url = f"redis://{config.redis.host}:{config.redis.port}/2" # Use a different DB for jobs
        jobstores = {
            'default': RedisJobStore(url=redis_url)
        }
        scheduler = AsyncIOScheduler(jobstores=jobstores)
        scheduler.start()
        print("Scheduler initialized and started.")

def get_scheduler() -> AsyncIOScheduler:
    """Returns the existing scheduler instance."""
    if scheduler is None:
        raise RuntimeError("Scheduler has not been initialized. Call init_scheduler() first.")
    return scheduler

async def schedule_lottery_end(lot_id: int, hours: int):
    """Schedules a job to end a lottery after a set number of hours."""
    end_time = datetime.now() + timedelta(hours=hours)
    await db.set_lot_end_time(lot_id, end_time)

    scheduler = get_scheduler()
    bot = scheduler.get_job("bot_instance").retval
    scheduler.add_job("bot.scheduler.end_lottery", "date", run_date=end_time, args=[lot_id, bot], id=f"lottery_end_{lot_id}")
    print(f"Scheduled lottery {lot_id} to end at {end_time}")

async def reschedule_auction_end(lot_id: int):
    """Schedules or reschedules a job to end an auction 1 hour from now."""
    end_time = datetime.now() + timedelta(hours=1)
    await db.set_lot_end_time(lot_id, end_time)

    job_id = f"auction_end_{lot_id}"
    scheduler = get_scheduler()
    bot = scheduler.get_job("bot_instance").retval
    # `add_job` with `replace_existing=True` acts as a reschedule
    scheduler.add_job("bot.scheduler.end_auction", "date", run_date=end_time, args=[lot_id, bot], id=job_id, replace_existing=True)
    print(f"Rescheduled auction {lot_id} to end at {end_time}")


async def notify_and_update_on_lot_end(lot_id: int, bot: Bot):
    """Handles notifications and post updates when a lot ends."""
    lot = await db.get_lot_details_for_update(lot_id)
    if not lot:
        return

    seller_id = lot['seller_id']
    winner_id = lot.get('winner_id')

    if winner_id:
        from aiogram.fsm.context import FSMContext
        from bot.states import Prize
        from bot.main import dp

        # We need to create a temporary FSM context to set the state for the winner
        storage = dp.storage
        fsm_context = FSMContext(storage=storage, key={"bot_id": bot.id, "chat_id": winner_id, "user_id": winner_id})
        await fsm_context.set_state(Prize.entering_address)
        await fsm_context.update_data(lot_id=lot_id)

        # Notify winner
        await bot.send_message(winner_id, f"Поздравляем! Вы выиграли лот '{lot['title']}'! Пожалуйста, пришлите ваш TON-адрес для получения приза.")
        # Notify seller
        final_price = lot.get('current_price') or lot['ticket_price']
        await bot.send_message(seller_id, f"Ваш лот '{lot['title']}' продан за {final_price} Stars.")
    else:
        # Notify seller of no sale
        await bot.send_message(seller_id, f"К сожалению, ваш лот '{lot['title']}' не был продан.")

    # --- Update Channel Post ---
    # We need to re-format the post with the winner's info.
    from bot.sell_handlers import format_lot_post

    new_text = await format_lot_post(lot) # The formatting function needs to handle finished lots

    if lot.get('channel_post_id'):
        try:
            # We need to get channel_id from config
            from config import load_config
            config = load_config()

            # We don't need buttons on a finished lot, so remove reply_markup
            await bot.edit_message_caption(
                chat_id=config.bot.channel_id,
                message_id=lot['channel_post_id'],
                caption=new_text,
                reply_markup=None
            )
        except Exception as e:
            logging.error(f"Failed to edit post for lot {lot_id}: {e}")


# --- Job Functions ---
# These functions are executed by the scheduler when a job is due.

async def end_lottery(lot_id: int, bot: Bot):
    """Logic to end a lottery, select a winner, and finalize the lot."""
    print(f"Executing job: end_lottery for lot_id {lot_id}")
    import random

    participants = await db.get_lottery_participants(lot_id)
    winner_id = None

    if participants:
        winner_id = random.choice(participants)
        print(f"Lottery {lot_id} finished. Winner is user_id: {winner_id}")
    else:
        print(f"Lottery {lot_id} finished with no participants.")

    await db.finish_lot(lot_id, winner_id)
    await notify_and_update_on_lot_end(lot_id, bot)

async def end_auction(lot_id: int, bot: Bot):
    """Logic to end an auction, determine the winner, and finalize the lot."""
    print(f"Executing job: end_auction for lot_id {lot_id}")

    winner_id = await db.get_previous_bid_leader(lot_id)

    if winner_id:
        print(f"Auction {lot_id} finished. Winner is user_id: {winner_id}")
    else:
        print(f"Auction {lot_id} finished with no bids.")

    await db.finish_lot(lot_id, winner_id)
    await notify_and_update_on_lot_end(lot_id, bot)
