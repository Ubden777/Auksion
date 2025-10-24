from database import queries as db
from blockchain.encryption import decrypt
import logging
import aiohttp
from async_lru import alru_cache
from tonsdk.utils import Address, to_nano, bytes_to_b64str
from tonsdk.contract.wallet import WalletV3R2
from tonsdk.contract.token.nft import NFTItem
import nacl.signing

# =====================================================================================
# This module now contains a functional, on-chain transfer mechanism.
# It uses the Toncenter HTTP API to get wallet states and to broadcast messages.
# =====================================================================================

TON_API_ENDPOINT = "https://toncenter.com/api/v2/"

@alru_cache(maxsize=128)
async def get_wallet_seqno(address: str) -> int:
    """Gets the current sequence number (seqno) for a wallet address."""
    info = await get_wallet_information(address)
    if info and info['account_state'] == 'active':
        return info['seqno']
    return 0

@alru_cache(maxsize=128)
async def get_wallet_balance(address: str) -> int:
    """Gets the current balance in nanotons for a wallet address."""
    info = await get_wallet_information(address)
    if info:
        return int(info['balance'])
    return 0

async def get_wallet_information(address: str) -> dict | None:
    """Fetches full wallet information from the API."""
    async with aiohttp.ClientSession() as session:
        params = {"address": address}
        async with session.get(f"{TON_API_ENDPOINT}getWalletInformation", params=params) as response:
            if response.status == 200:
                data = await response.json()
                if data.get('ok'):
                    return data['result']
    return None

async def get_nft_item_address_from_owner(owner_address: str) -> str | None:
    """
    Finds the first NFT item address owned by a given wallet.
    NOTE: This is a simplification. It assumes the escrow wallet holds only one NFT.
    """
    async with aiohttp.ClientSession() as session:
        params = {"owner_address": owner_address}
        async with session.get(f"{TON_API_ENDPOINT}getNftItemsByOwnerAddress", params=params) as response:
            if response.status == 200:
                data = await response.json()
                if data.get('result', {}).get('nft_items'):
                    return data['result']['nft_items'][0]['address']
    return None

async def send_boc(boc_b64: str) -> bool:
    """Broadcasts a Bag of Cells (BoC) to the network."""
    async with aiohttp.ClientSession() as session:
        payload = {"boc": boc_b64}
        async with session.post(f"{TON_API_ENDPOINT}sendBoc", json=payload) as response:
            return response.status == 200


async def transfer_nft(lot_id: int, recipient_address: str) -> str | None:
    """
    Transfers the NFT from the escrow wallet to the winner.
    (Functional Implementation)
    """
    logging.info(f"Initiating NFT transfer for lot {lot_id} to {recipient_address}...")

    wallet_details = await db.get_escrow_wallet_details(lot_id)
    if not wallet_details:
        logging.error(f"Could not find escrow wallet details for lot {lot_id}.")
        return None

    try:
        decrypted_pk_hex = decrypt(wallet_details['encrypted_private_key'])
        decrypted_pk_bytes = bytes.fromhex(decrypted_pk_hex)

        # 1. Initialize Wallet from private key
        signing_key = nacl.signing.SigningKey(decrypted_pk_bytes)
        public_key = signing_key.verify_key.encode()

        wallet = WalletV3R2(public_key=public_key, private_key=decrypted_pk_bytes)
        escrow_address = wallet.address.to_string(True, True, True)

        # 2. Check escrow wallet balance for gas fees
        balance = await get_wallet_balance(escrow_address)
        MIN_BALANCE_FOR_TRANSFER = to_nano('0.1', 'ton') # 0.1 TON
        if balance < MIN_BALANCE_FOR_TRANSFER:
            logging.error(f"Insufficient balance on escrow wallet {escrow_address} for lot {lot_id}. Balance: {balance} nanotons.")
            # TODO: Notify admin about the low balance
            return None

        # 3. Find the NFT item address on the escrow wallet
        nft_item_address = await get_nft_item_address_from_owner(wallet.address.to_string(True, True, True))
        if not nft_item_address:
            logging.error(f"Could not find any NFT on the escrow wallet {wallet.address.to_string(True, True, True)} for lot {lot_id}.")
            return None

        # 3. Get the current seqno of the wallet
        seqno = await get_wallet_seqno(wallet.address.to_string(True, True, True))

        # 4. Create the NFT transfer message body
        transfer_body = NFTItem().create_transfer_body(
            new_owner_address=Address(recipient_address),
            response_address=None, # Send excess gas back to the escrow wallet itself
            forward_amount=to_nano('0.02', 'ton') # Forward a small amount of TON to the new owner's wallet
        )

        # 5. Create the full transfer query
        query = wallet.create_transfer_message(
            to_addr=nft_item_address,
            amount=to_nano('0.05', 'ton'), # Amount to send to the NFT item contract for processing
            seqno=seqno,
            payload=transfer_body
        )

        boc_b64 = bytes_to_b64str(query["message"].to_boc(False))

        # 6. Send the BoC to the network
        success = await send_boc(boc_b64)

        if success:
            tx_hash = query["message"].hash.hex()
            logging.info(f"Successfully sent NFT transfer for lot {lot_id}. Tx Hash: {tx_hash}")
            return tx_hash
        else:
            logging.error(f"Failed to send BoC for lot {lot_id} transfer.")
            return None

    except Exception as e:
        logging.error(f"Failed to process NFT transfer for lot {lot_id}: {e}", exc_info=True)
        return None
