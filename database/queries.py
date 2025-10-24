from typing import Dict, Any
from . import pool
from datetime import datetime

async def add_or_update_user(user_id: int, username: str, full_name: str):
    """Adds a new user or updates their details if they already exist."""
    db_pool = pool.get_pool()
    async with db_pool.acquire() as connection:
        await connection.execute("""
            INSERT INTO users (user_id, username, full_name)
            VALUES ($1, $2, $3)
            ON CONFLICT (user_id) DO UPDATE SET
                username = EXCLUDED.username,
                full_name = EXCLUDED.full_name;
        """, user_id, username, full_name)

async def create_lot(seller_id: int, lot_data: Dict[str, Any]) -> int:
    """
    Creates a new lot in the database with 'pending_deposit' status.
    Returns the ID of the newly created lot.
    """
    db_pool = pool.get_pool()
    query = """
        INSERT INTO lots (
            seller_id, lot_type, title, description, media_file_id, media_type,
            status, end_time, start_price, min_step, ticket_price
        )
        VALUES (
            $1, $2, $3, $4, $5, $6, 'pending_deposit',
            -- End time calculation will be added later based on duration
            NULL, $7, $8, $9
        ) RETURNING lot_id;
    """
    async with db_pool.acquire() as connection:
        lot_id = await connection.fetchval(
            query,
            seller_id,
            lot_data.get("sell_type"),
            lot_data.get("title"),
            lot_data.get("description"),
            lot_data.get("media_file_id"),
            lot_data.get("media_type"),
            lot_data.get("start_price"),
            lot_data.get("min_step"),
            lot_data.get("ticket_price")
        )
    return lot_id

async def save_escrow_wallet(lot_id: int, address: str, public_key: str, encrypted_private_key: str, mnemonic: str):
    """Saves the details of a new escrow wallet to the database."""
    db_pool = pool.get_pool()
    query = """
        INSERT INTO escrow_wallets (lot_id, address, public_key, encrypted_private_key, mnemonic_phrase)
        VALUES ($1, $2, $3, $4, $5);
    """
    async with db_pool.acquire() as connection:
        await connection.execute(query, lot_id, address, public_key, encrypted_private_key, mnemonic)

async def set_lot_end_time(lot_id: int, end_time: datetime):
    """Sets the end time for a lot."""
    db_pool = pool.get_pool()
    query = "UPDATE lots SET end_time = $1 WHERE lot_id = $2;"
    async with db_pool.acquire() as connection:
        await connection.execute(query, end_time, lot_id)

async def get_lot_type_and_duration(lot_id: int) -> dict | None:
    """Fetches the lot type and duration for a given lot."""
    db_pool = pool.get_pool()
    query = "SELECT lot_type, duration_hours FROM lots WHERE lot_id = $1;"
    async with db_pool.acquire() as connection:
        row = await connection.fetchrow(query, lot_id)
        return dict(row) if row else None

async def get_pending_lot_addresses() -> list[dict]:
    """Fetches all escrow addresses for lots that are pending deposit."""
    db_pool = pool.get_pool()
    query = """
        SELECT w.address, w.lot_id
        FROM escrow_wallets w
        JOIN lots l ON w.lot_id = l.lot_id
        WHERE l.status = 'pending_deposit';
    """
    async with db_pool.acquire() as connection:
        rows = await connection.fetch(query)
        return [dict(row) for row in rows]

async def activate_lot(lot_id: int):
    """Activates a lot by setting its status to 'active'."""
    db_pool = pool.get_pool()
    query = "UPDATE lots SET status = 'active' WHERE lot_id = $1;"
    async with db_pool.acquire() as connection:
        await connection.execute(query, lot_id)

async def save_ticket(lot_id: int, user_id: int):
    """Saves a lottery ticket purchase to the database."""
    db_pool = pool.get_pool()
    query = "INSERT INTO tickets (lot_id, owner_id) VALUES ($1, $2);"
    async with db_pool.acquire() as connection:
        await connection.execute(query, lot_id, user_id)

async def get_lottery_participants(lot_id: int) -> list[int]:
    """Gets a list of user_ids for all participants in a lottery."""
    db_pool = pool.get_pool()
    query = "SELECT owner_id FROM tickets WHERE lot_id = $1;"
    async with db_pool.acquire() as connection:
        rows = await connection.fetch(query, lot_id)
        return [row['owner_id'] for row in rows]

async def finish_lot(lot_id: int, winner_id: int | None):
    """Marks a lot as finished and records the winner."""
    db_pool = pool.get_pool()
    status = 'finished_sold' if winner_id else 'finished_unsold'
    query = "UPDATE lots SET status = $1, winner_id = $2 WHERE lot_id = $3;"
    async with db_pool.acquire() as connection:
        await connection.execute(query, status, winner_id, lot_id)

async def get_lot_details_for_update(lot_id: int) -> dict | None:
    """Fetches all necessary details for updating a lot post after finishing."""
    db_pool = pool.get_pool()
    query = """
        SELECT l.title, l.lot_type, l.current_price, l.winner_id, u.username as winner_username, l.media_file_id, l.description, l.start_price, l.min_step, l.ticket_price
        FROM lots l
        LEFT JOIN users u ON l.winner_id = u.user_id
        WHERE l.lot_id = $1;
    """
    async with db_pool.acquire() as connection:
        row = await connection.fetchrow(query, lot_id)
        return dict(row) if row else None

async def save_channel_post_id(lot_id: int, post_id: int):
    """Saves the message_id of the published post in the channel."""
    db_pool = pool.get_pool()
    query = "UPDATE lots SET channel_post_id = $1 WHERE lot_id = $2;"
    async with db_pool.acquire() as connection:
        await connection.execute(query, post_id, lot_id)

async def get_escrow_wallet_details(lot_id: int) -> dict | None:
    """Fetches the encrypted private key and address for a lot's escrow wallet."""
    db_pool = pool.get_pool()
    query = "SELECT address, encrypted_private_key FROM escrow_wallets WHERE lot_id = $1;"
    async with db_pool.acquire() as connection:
        row = await connection.fetchrow(query, lot_id)
        return dict(row) if row else None

async def is_collection_whitelisted(collection_address: str) -> bool:
    """Checks if a given NFT collection address is in the whitelist."""
    db_pool = pool.get_pool()
    query = "SELECT EXISTS(SELECT 1 FROM whitelisted_collections WHERE address = $1);"
    async with db_pool.acquire() as connection:
        is_whitelisted = await connection.fetchval(query, collection_address)
        return is_whitelisted

async def get_previous_bid_leader(lot_id: int) -> int | None:
    """Gets the user_id of the current highest bidder."""
    db_pool = pool.get_pool()
    query = "SELECT bidder_id FROM bids WHERE lot_id = $1 ORDER BY amount DESC LIMIT 1;"
    async with db_pool.acquire() as connection:
        leader_id = await connection.fetchval(query, lot_id)
        return leader_id

async def save_bid(lot_id: int, user_id: int, amount: int):
    """Saves an auction bid to the database."""
    db_pool = pool.get_pool()
    # Using a transaction to ensure both operations succeed or fail together
    async with db_pool.acquire() as connection:
        async with connection.transaction():
            await connection.execute(
                "INSERT INTO bids (lot_id, bidder_id, amount) VALUES ($1, $2, $3);",
                lot_id, user_id, amount
            )
            await connection.execute(
                "UPDATE lots SET current_price = $1 WHERE lot_id = $2;",
                amount, lot_id
            )
