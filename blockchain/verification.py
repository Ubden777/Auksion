from typing import Dict
from database import queries as db
import logging
import aiohttp
from tonsdk.utils import b64str_to_bytes
from tonsdk.boc import Cell

# =====================================================================================
# This module now contains a functional, on-chain verification mechanism.
# It works by calling the `get_nft_data()` method on the provided NFT item's contract address.
# This method returns several pieces of data, including the collection's address.
# This collection address is then checked against the `whitelisted_collections` table.
# =====================================================================================

TON_API_ENDPOINT = "https://toncenter.com/api/v2/runGetMethod"

async def get_collection_address_from_nft(nft_item_address: str) -> str | None:
    """
    Calls the `get_nft_data()` method on an NFT item contract to find its collection address.
    """
    try:
        async with aiohttp.ClientSession() as session:
            payload = {
                "address": nft_item_address,
                "method": "get_nft_data",
                "stack": []
            }
            async with session.post(TON_API_ENDPOINT, json=payload) as response:
                if response.status != 200:
                    logging.error(f"Failed to call get_nft_data for {nft_item_address}. Status: {response.status}")
                    return None

                data = await response.json()
                if not data.get('ok') or data.get('exit_code') != 0:
                    logging.error(f"get_nft_data call failed for {nft_item_address}. Response: {data}")
                    return None

                # The result is in the 'stack' array. According to TEP-62 standard for NFTs,
                # the stack returned by `get_nft_data()` is:
                # (int init, int index, slice collection_address, slice owner_address, cell content)
                # The collection_address is the 3rd element ([2]).
                stack = data['result']['stack']

                # Stack items are tuples: ['tvm.Slice', 'base64_encoded_cell_data']
                if len(stack) >= 3 and stack[2][0] == 'tvm.Slice':
                    b64_slice = stack[2][1]
                    cell_bytes = b64str_to_bytes(b64_slice)
                    cell = Cell.one_from_boc(cell_bytes)

                    # The slice contains the address. We can read it.
                    collection_address_slice = cell.begin_parse()
                    addr = collection_address_slice.read_address()
                    return addr.to_string(True, True, True) # User-friendly, bounceable, with testnet flag

    except Exception as e:
        logging.error(f"Exception while getting collection address for {nft_item_address}: {e}", exc_info=True)
        return None


async def verify_nft(transaction_details: Dict) -> bool:
    """
    Verifies the authenticity of an NFT from a transaction by checking its collection
    against a whitelist. (Functional Implementation)
    """
    logging.info(f"--- Verifying NFT from transaction ---")

    try:
        # The source of the incoming message is the NFT item's contract address.
        nft_item_address = transaction_details.get("in_msg", {}).get("source")

        if not nft_item_address:
            logging.warning("Could not determine NFT item address from transaction.")
            return False

        collection_address = await get_collection_address_from_nft(nft_item_address)

        if not collection_address:
            logging.warning(f"Could not retrieve collection address for NFT item {nft_item_address}.")
            return False

        is_whitelisted = await db.is_collection_whitelisted(collection_address)

        if is_whitelisted:
            logging.info(f"NFT from collection {collection_address} is whitelisted. Verification successful.")
            return True
        else:
            logging.warning(f"NFT from collection {collection_address} is NOT whitelisted. Verification failed.")
            return False

    except Exception as e:
        logging.error(f"An error occurred during NFT verification: {e}", exc_info=True)
        return False
