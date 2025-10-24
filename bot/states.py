from aiogram.fsm.state import State, StatesGroup


class SellNFT(StatesGroup):
    choosing_type = State()
    entering_media = State()
    entering_title = State()
    entering_description = State()
    entering_lottery_price = State()
    entering_lottery_duration = State()
    entering_auction_start_price = State()
    entering_auction_min_step = State()
    entering_auction_duration = State()
    confirming_publication = State()
    waiting_for_deposit = State()


class Bid(StatesGroup):
    entering_amount = State()

class Prize(StatesGroup):
    entering_address = State()
