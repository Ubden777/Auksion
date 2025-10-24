from aiogram import F, Router, types
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
import logging

from bot.states import SellNFT
# This part will be triggered by the Watcher service in the future.
from aiogram.client.bot import Bot
from database import queries as db

async def _prompt_for_nft_deposit(message: types.Message, state: FSMContext):
    """
    A helper function to handle the final step of lot creation:
    1.  Create the lot in the database.
    2.  Generate a new escrow wallet.
    3.  Encrypt and save the wallet's private key.
    4.  Ask the user to send their NFT to the new address.
    """
    from blockchain.wallet import create_wallet
    from blockchain.encryption import encrypt
    from aiogram.types import User

    user: User = message.from_user
    await db.add_or_update_user(user.id, user.username, user.full_name)

    user_data = await state.get_data()
    lot_id = await db.create_lot(user.id, user_data)

    escrow_wallet = create_wallet()
    escrow_address = escrow_wallet["address"]

    encrypted_pk = encrypt(escrow_wallet["private_key"])
    encrypted_mnemonic = encrypt(escrow_wallet["mnemonic"])

    await db.save_escrow_wallet(
        lot_id=lot_id,
        address=escrow_address,
        public_key=escrow_wallet["public_key"],
        encrypted_private_key=encrypted_pk,
        mnemonic=encrypted_mnemonic
    )

    await state.update_data(escrow_address=escrow_address, lot_id=lot_id)
    await state.set_state(SellNFT.waiting_for_deposit)

    await message.answer(
        "Все данные собраны! Теперь последний шаг перед публикацией.\n\n"
        "Для гарантии сделки, пожалуйста, переведите ваш NFT на следующий временный кошелек. "
        "Этот адрес действителен только для этой сделки.\n\n"
        f"<code>{escrow_address}</code>\n\n"
        "Как только наш сервис обнаружит поступление NFT, ваш лот будет автоматически опубликован. "
        "Ожидаем поступления..."
    )

router = Router()


@router.message(F.text == "Продать NFT")
async def start_selling(message: types.Message, state: FSMContext):
    """Starts the process of selling an NFT."""
    await state.set_state(SellNFT.choosing_type)

    builder = InlineKeyboardBuilder()
    builder.add(types.InlineKeyboardButton(text="Лотерея", callback_data="sell_type:lottery"))
    builder.add(types.InlineKeyboardButton(text="Классический Аукцион", callback_data="sell_type:auction"))
    builder.adjust(1)

    await message.answer(
        "Отлично! Давайте выставим ваш NFT на продажу.\n\n"
        "Пожалуйста, выберите тип аукциона:",
        reply_markup=builder.as_markup()
    )


@router.callback_query(F.data.startswith("sell_type:"))
async def select_sell_type(callback: types.CallbackQuery, state: FSMContext):
    """Handles the selection of the auction type."""
    sell_type = callback.data.split(":")[1]
    await state.update_data(sell_type=sell_type)
    await state.set_state(SellNFT.entering_media)

    await callback.message.edit_text(
        "Вы выбрали: " + ("Лотерея" if sell_type == "lottery" else "Классический Аукцион") + "\n\n"
        "Теперь, пожалуйста, пришлите изображение или видео вашего NFT."
    )
    await callback.answer()


@router.message(SellNFT.entering_media, F.photo | F.video)
async def enter_media(message: types.Message, state: FSMContext):
    """Handles receiving the media for the lot."""
    if message.photo:
        file_id = message.photo[-1].file_id
        media_type = "photo"
    else:
        file_id = message.video.file_id
        media_type = "video"

    await state.update_data(media_file_id=file_id, media_type=media_type)
    await state.set_state(SellNFT.entering_title)

    await message.answer("Отлично, медиа принято. Теперь введите название лота (до 255 символов).")


@router.message(SellNFT.entering_title, F.text)
async def enter_title(message: types.Message, state: FSMContext):
    """Handles receiving the title for the lot."""
    # Basic validation
    if len(message.text) > 255:
        await message.answer("Название слишком длинное. Пожалуйста, введите название до 255 символов.")
        return

    await state.update_data(title=message.text)
    await state.set_state(SellNFT.entering_description)

    await message.answer("Название сохранено. Теперь введите описание вашего лота.")


@router.message(SellNFT.entering_description, F.text)
async def enter_description(message: types.Message, state: FSMContext):
    """Handles receiving the description and routes to the next step based on lot type."""
    await state.update_data(description=message.text)
    user_data = await state.get_data()
    sell_type = user_data.get("sell_type")

    if sell_type == "lottery":
        await state.set_state(SellNFT.entering_lottery_price)
        await message.answer("Описание сохранено. Теперь укажите цену одного билета в Telegram Stars.")
    elif sell_type == "auction":
        await state.set_state(SellNFT.entering_auction_start_price)
        await message.answer("Описание сохранено. Теперь укажите стартовую цену в Telegram Stars.")
    else:
        # Handle error case, though it's unlikely
        await state.clear()
        await message.answer("Произошла ошибка. Пожалуйста, начните заново, нажав 'Продать NFT'.")


# --- Lottery Path ---
@router.message(SellNFT.entering_lottery_price, F.text)
async def enter_lottery_price(message: types.Message, state: FSMContext):
    """Handles receiving the lottery ticket price."""
    try:
        ticket_price = int(message.text)
        if ticket_price <= 0:
            raise ValueError
    except ValueError:
        await message.answer("Пожалуйста, введите корректное положительное число (например, 10).")
        return

    await state.update_data(ticket_price=ticket_price)
    await state.set_state(SellNFT.entering_lottery_duration)

    await message.answer(
        "Цена билета сохранена. Теперь укажите продолжительность лотереи в часах (например, 48)."
    )


@router.message(SellNFT.entering_lottery_duration, F.text)
async def enter_lottery_duration(message: types.Message, state: FSMContext):
    """Handles receiving the lottery duration."""
    try:
        duration_hours = int(message.text)
        if duration_hours <= 0:
            raise ValueError
    except ValueError:
        await message.answer("Пожалуйста, введите корректное положительное число (например, 48).")
        return

    await state.update_data(duration_hours=duration_hours)
    await _prompt_for_nft_deposit(message, state)


# --- Auction Path ---
@router.message(SellNFT.entering_auction_start_price, F.text)
async def enter_auction_start_price(message: types.Message, state: FSMContext):
    """Handles receiving the auction start price."""
    try:
        start_price = int(message.text)
        if start_price <= 0:
            raise ValueError
    except ValueError:
        await message.answer("Пожалуйста, введите корректное положительное число (например, 100).")
        return

    await state.update_data(start_price=start_price)
    await state.set_state(SellNFT.entering_auction_min_step)

    await message.answer(
        "Стартовая цена сохранена. Теперь укажите минимальный шаг ставки (например, 10)."
    )


@router.message(SellNFT.entering_auction_min_step, F.text)
async def enter_auction_min_step(message: types.Message, state: FSMContext):
    """Handles receiving the auction minimum step."""
    try:
        min_step = int(message.text)
        if min_step <= 0:
            raise ValueError
    except ValueError:
        await message.answer("Пожалуйста, введите корректное положительное число (например, 10).")
        return

    await state.update_data(min_step=min_step)
    await _prompt_for_nft_deposit(message, state)


async def format_lot_post(lot_details: dict) -> str:
    """Formats the text for the lot post in the channel."""
    text = f"<b>{lot_details['title']}</b>\n\n"
    text += f"{lot_details['description']}\n\n"
    if lot_details['lot_type'] == 'auction':
        text += f"<b>Стартовая цена:</b> {lot_details['start_price']} Stars\n"
        text += f"<b>Минимальный шаг:</b> {lot_details['min_step']} Stars\n"
        text += f"<b>Текущая ставка:</b> {lot_details.get('current_price', lot_details['start_price'])} Stars\n"
    elif lot_details['lot_type'] == 'lottery':
        text += f"<b>Цена билета:</b> {lot_details['ticket_price']} Stars\n"

    if lot_details['status'] in ('finished_sold', 'finished_unsold'):
        text += "\n<b>--- Аукцион завершен ---</b>\n"
        if lot_details.get('winner_username'):
            text += f"<b>Победитель:</b> @{lot_details['winner_username']}\n"
            final_price = lot_details.get('current_price') or lot_details['ticket_price']
            text += f"<b>Финальная цена:</b> {final_price} Stars\n"
        else:
            text += "<b>Лот не продан.</b>\n"

    return text


async def publish_lot(lot_id: int, bot: Bot, channel_id: int):
    """
    Fetches lot details, formats, and publishes the post to the target channel.
    """
    # This function replaces the test_publish command.
    # It will be called by the Redis listener.
    db_pool = db.pool.get_pool()
    async with db_pool.acquire() as conn:
        # We need a more comprehensive query to get all details, including seller info if needed
        lot_details = await conn.fetchrow("SELECT * FROM lots WHERE lot_id = $1", lot_id)

    if not lot_details:
        logging.error(f"Attempted to publish lot {lot_id}, but it was not found in the database.")
        return

    post_text = await format_lot_post(dict(lot_details))

    builder = InlineKeyboardBuilder()
    if lot_details['lot_type'] == 'auction':
        builder.add(types.InlineKeyboardButton(text="Сделать ставку", callback_data=f"bid:{lot_id}"))
    else:
        builder.add(types.InlineKeyboardButton(text=f"Купить билет за {lot_details['ticket_price']} Stars", callback_data=f"buy_ticket:{lot_id}"))

    try:
        message = None
        if lot_details['media_type'] == 'photo':
            message = await bot.send_photo(
                chat_id=channel_id,
                photo=lot_details['media_file_id'],
                caption=post_text,
                reply_markup=builder.as_markup()
            )
        elif lot_details['media_type'] == 'video':
            message = await bot.send_video(
                chat_id=channel_id,
                video=lot_details['media_file_id'],
                caption=post_text,
                reply_markup=builder.as_markup()
            )

        if message:
            await db.save_channel_post_id(lot_id, message.message_id)
            logging.info(f"Successfully published lot {lot_id} to channel {channel_id} with message_id {message.message_id}.")

    except Exception as e:
        logging.error(f"Failed to publish lot {lot_id} to channel {channel_id}: {e}")
