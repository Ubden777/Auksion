import base64
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

_ENCRYPTION_KEY = None

def _derive_key(secret: str) -> bytes:
    """Derives a secure encryption key from the secret."""
    # Using a fixed salt is not ideal, but acceptable for this MVP.
    # In a production system, you might store a unique salt per user/key.
    salt = b'nft_auction_bot_salt'
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=100000,
    )
    return base64.urlsafe_b64encode(kdf.derive(secret.encode()))

def init_encryption(secret_key: str):
    """Initializes the encryption service with a secret key."""
    global _ENCRYPTION_KEY
    if not secret_key:
        raise ValueError("A secret key must be provided for encryption.")
    _ENCRYPTION_KEY = _derive_key(secret_key)

def get_fernet() -> Fernet:
    if _ENCRYPTION_KEY is None:
        raise RuntimeError("Encryption service has not been initialized. Call init_encryption() first.")
    return Fernet(_ENCRYPTION_KEY)

def encrypt(data: str) -> str:
    """Encrypts a string and returns it as a string."""
    f = get_fernet()
    return f.encrypt(data.encode()).decode()

def decrypt(encrypted_data: str) -> str:
    """Decrypts a string and returns it."""
    f = get_fernet()
    return f.decrypt(encrypted_data.encode()).decode()
