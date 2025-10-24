import asyncio
import logging
import sys
import aiohttp
import redis.asyncio as redis

# Add project root to path to allow imports from other modules
sys.path.insert(0, sys.path[0] + "/..")

from config import load_config
from database import pool as db_pool
from database import queries as db
from blockchain.verification import verify_nft

# Using a public TON API endpoint
TON_API_ENDPOINT = "https://toncenter.com/api/v2/getTransactions"
REDIS_CHANNEL = "lot_activation_channel"


class Watcher:
    def __init__(self, redis_client):
        self.redis = redis_client
        self.addresses_to_watch = {}  # In-memory cache: {"EQ...": lot_id}
        logging.info("Watcher service initialized.")

    async def update_watch_list(self):
        """Fetches the latest list of pending addresses from the database."""
        pending_lots = await db.get_pending_lot_addresses()
        self.addresses_to_watch = {
            lot['address']: lot['lot_id'] for lot in pending_lots
        }
        logging.info(f"Updated watch list. Tracking {len(self.addresses_to_watch)} addresses.")

    async def check_transactions(self):
        """
        Main loop to check for incoming transactions on the watched addresses.
        """
        if not self.addresses_to_watch:
            return

        logging.info(f"Checking transactions for {len(self.addresses_to_watch)} addresses...")

        async with aiohttp.ClientSession() as session:
            tasks = [
                self.check_address(session, address, lot_id)
                for address, lot_id in self.addresses_to_watch.items()
            ]
            await asyncio.gather(*tasks)

    async def check_address(self, session, address: str, lot_id: int):
        """Checks a single address for any incoming transactions."""
        try:
            params = {
                "address": address,
                "limit": 10, # Check last 10 transactions
                "to_lt": 0,
                "archival": "false",
            }
            async with session.get(TON_API_ENDPOINT, params=params) as response:
                if response.status == 200:
                    transactions = await response.json()
                    # For MVP, we consider ANY incoming transaction as a deposit.
                    # A real implementation needs to inspect the transaction body
                    # to confirm it's an NFT transfer.
                    if transactions.get("result") and len(transactions["result"]) > 0:
                        # For now, we take the first transaction found
                        tx = transactions["result"][0]

                        is_verified = await verify_nft(tx)

                        if is_verified:
                            logging.info(f"Found deposit for lot {lot_id} at address {address}. Activating...")
                            await db.activate_lot(lot_id)
                            # Notify the main bot about the activation
                            await self.redis.publish(REDIS_CHANNEL, str(lot_id))
                            # Remove from watch list to avoid re-processing
                            self.addresses_to_watch.pop(address, None)
                else:
                    logging.error(f"Error fetching transactions for {address}: HTTP {response.status}")
        except Exception as e:
            logging.error(f"Exception while checking address {address}: {e}")


async def main():
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)

    config = load_config()
    await db_pool.init_pool(config.db.__dict__)

    redis_url = f"redis://{config.redis.host}:{config.redis.port}/1"
    redis_client = redis.Redis.from_url(redis_url, decode_responses=True)

    watcher = Watcher(redis_client)

    try:
        while True:
            await watcher.update_watch_list()
            await watcher.check_transactions()
            logging.info("Transaction check cycle complete. Waiting 15 seconds...")
            await asyncio.sleep(15)
    finally:
        await db_pool.close_pool()
        await redis_client.close()
        logging.info("Watcher service stopped.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Watcher stopped by user.")
