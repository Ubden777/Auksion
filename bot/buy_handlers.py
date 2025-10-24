from aiogram import F, Router, types
from aiogram.client.bot import Bot
from aiogram.fsm.context import FSMContext
from .states import Bid

# In a real app, this should be a deep-link to the bot with a start parameter
# For now, we just send a simple message.
BOT_USERNAME = "YourBotsUsernameHere" # Needs to be configured

router = Router()

@router.callback_query(F.data.startswith("buy_ticket:"))
async def handle_buy_ticket_callback(callback: types.CallbackQuery, bot: Bot):
    """Handles the 'Buy Ticket' button press from the channel."""
    lot_id = int(callback.data.split(":")[1])
    user_id = callback.from_user.id

    # Acknowledge the button press in the channel
    await callback.answer("Перенаправляем в личные сообщения для покупки...", show_alert=False)

    # Simulate redirecting to PM and starting the payment process
    # In a real scenario, you'd use a deep link.
    # Here, we fetch lot details to show the price.
    from database import queries as db
    pool = db.pool.get_pool()
    async with pool.acquire() as conn:
        ticket_price = await conn.fetchval("SELECT ticket_price FROM lots WHERE lot_id = $1", lot_id)

    if ticket_price:
        text = (
            f"Вы собираетесь купить 1 билет на лот #{lot_id} за {ticket_price} Stars.\n\n"
            "Нажмите 'Оплатить' для подтверждения."
        )
        # Placeholder for the actual invoice button
        builder = types.InlineKeyboardBuilder()
        builder.add(types.InlineKeyboardButton(text="Оплатить", callback_data=f"confirm_payment:{lot_id}"))

        await bot.send_message(user_id, text, reply_markup=builder.as_markup())
    else:
        await bot.send_message(user_id, f"Не удалось найти информацию о лоте #{lot_id}.")


@router.callback_query(F.data.startswith("confirm_payment:"))
async def handle_confirm_payment(callback: types.CallbackQuery):
    """Handles the ticket payment confirmation."""
    lot_id = int(callback.data.split(":")[1])
    user = callback.from_user

    from database import queries as db
    await db.add_or_update_user(user.id, user.username, user.full_name)
    await db.save_ticket(lot_id, user.id)

    await callback.message.edit_text(
        "Оплата прошла! Ваш билет учтен. Желаем удачи!"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("bid:"))
async def handle_bid_callback(callback: types.CallbackQuery, bot: Bot, state: FSMContext):
    """Handles the 'Make a Bid' button press from the channel."""
    lot_id = int(callback.data.split(":")[1])
    user_id = callback.from_user.id

    await callback.answer("Перенаправляем в личные сообщения для ставки...", show_alert=False)

    # Simulate redirecting and asking for bid amount
    # Here, we'd fetch current price and min_step
    from database import queries as db
    pool = db.pool.get_pool()
    async with pool.acquire() as conn:
        lot_details = await conn.fetchrow(
            "SELECT start_price, current_price, min_step FROM lots WHERE lot_id = $1",
            lot_id
        )

    if lot_details:
        current_price = lot_details.get('current_price') or lot_details.get('start_price', 0)
        min_step = lot_details.get('min_step', 1)
        next_bid_amount = current_price + min_step

        text = (
            f"Вы собираетесь сделать ставку на лот #{lot_id}.\n"
            f"Текущая ставка: {current_price} Stars.\n"
            f"Минимальная следующая ставка: {next_bid_amount} Stars.\n\n"
            "Пожалуйста, введите сумму вашей ставки в ответном сообщении."
        )
        await state.set_state(Bid.entering_amount)
        await state.update_data(lot_id=lot_id, min_bid=next_bid_amount)
        await bot.send_message(user_id, text)
    else:
        await bot.send_message(user_id, f"Не удалось найти информацию о лоте #{lot_id}.")


@router.message(Bid.entering_amount, F.text)
async def enter_bid_amount(message: types.Message, state: FSMContext, bot: Bot):
    """Handles receiving the bid amount from the user."""
    try:
        bid_amount = int(message.text)
        state_data = await state.get_data()
        min_bid = state_data.get("min_bid", 0)
        lot_id = state_data.get("lot_id")

        if bid_amount < min_bid:
            await message.answer(f"Ваша ставка слишком мала. Минимальная ставка: {min_bid} Stars.")
            return

    except (ValueError, TypeError):
        await message.answer("Пожалуйста, введите корректное число.")
        return

    from database import queries as db
    user = message.from_user

    # Get previous leader before saving the new bid
    previous_leader_id = await db.get_previous_bid_leader(lot_id)

    await db.add_or_update_user(user.id, user.username, user.full_name)
    await db.save_bid(lot_id, user.id, bid_amount)

    # Notify the previous leader if there was one and they are not the current bidder
    if previous_leader_id and previous_leader_id != user.id:
        try:
            await bot.send_message(
                previous_leader_id,
                f"Вашу ставку на лот #{lot_id} перебили. Новая ставка: {bid_amount} Stars."
            )
        except Exception as e:
            # This can fail if the user blocked the bot, so we log it and continue.
            logging.warning(f"Failed to notify previous leader {previous_leader_id} for lot {lot_id}: {e}")

    await message.answer(
        f"Ваша ставка в размере {bid_amount} Stars принята! Вы - текущий лидер.\n\n"
        "Мы уведомим вас, если вашу ставку перебьют."
    )

    # After a successful bid, reschedule the auction end time
    from bot.scheduler import reschedule_auction_end
    await reschedule_auction_end(lot_id)

    await state.clear()


from .states import Prize
from blockchain import transfer

@router.message(Prize.entering_address, F.text)
async def enter_prize_address(message: types.Message, state: FSMContext):
    """Handles receiving the winner's TON address and initiating the transfer."""
    address = message.text.strip()
    # Basic address validation: length 48, starts with E or U
    if not (len(address) == 48 and address[0] in ('E', 'U')):
        await message.answer("Кажется, это невалидный TON-адрес. Пожалуйста, проверьте и отправьте еще раз.")
        return

    state_data = await state.get_data()
    lot_id = state_data.get("lot_id")

    await message.answer("Адрес принят! Запускаем процесс перевода вашего NFT. Это может занять несколько минут...")

    tx_hash = await transfer.transfer_nft(lot_id, address)

    if tx_hash:
        # Construct explorer link
        explorer_link = f"https://tonviewer.com/transaction/{tx_hash}"
        await message.answer(
            "Успех! Ваш NFT был отправлен. Вы можете отследить транзакцию здесь:\n"
            f"{explorer_link}"
        )
    else:
        await message.answer(
            "Произошла ошибка во время отправки NFT. Мы уже разбираемся в проблеме. "
            "Пожалуйста, свяжитесь с поддержкой, если проблема не решится."
        )

    await state.clear()
