from typing import Dict, List, Union

from tonsdk.contract.wallet import WalletV3R2, Wallets
from tonsdk.crypto import mnemonic_new


def create_wallet() -> Dict[str, Union[str, List[str]]]:
    """
    Generates a new TON wallet.

    :return: A dictionary containing the wallet's mnemonic, address, public key, and private key.
    """
    mnemonic = mnemonic_new()

    # The Wallets.from_mnemonics function expects a list of mnemonics
    mnemonics, pub_keys, priv_keys, wallet = Wallets.from_mnemonics(
        mnemonics=mnemonic,
        version=WalletV3R2,
        workchain=0
    )

    return {
        "mnemonic": " ".join(mnemonic),
        "address": wallet.address.to_string(True, True, True),
        "public_key": pub_keys[0].hex(),
        "private_key": priv_keys[0].hex()
    }
