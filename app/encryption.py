from __future__ import annotations

import base64
from pathlib import Path

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC


def find_ssh_key(key_names: list[str] | None = None) -> Path | None:
    """Find the first available SSH key in ~/.ssh/ by priority order."""
    if key_names is None:
        key_names = ["id_ed25519", "id_rsa", "id_ecdsa", "id_dsa"]
    ssh_dir = Path.home() / ".ssh"
    if not ssh_dir.exists():
        return None
    for key_name in key_names:
        key_path = ssh_dir / key_name
        if key_path.exists():
            return key_path
    return None


def find_ssh_key_for_encryption() -> Path | None:
    """Find SSH key to use as encryption source (prefers modern key types)."""
    return find_ssh_key(["id_ed25519", "id_rsa"])


def derive_encryption_key(ssh_key_path: Path, salt: bytes) -> bytes:
    """Derive encryption key from SSH key content using the provided salt."""
    key_data = ssh_key_path.read_bytes()

    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=100000,
    )
    derived_key = kdf.derive(key_data)
    return base64.urlsafe_b64encode(derived_key)


def get_fernet_cipher(salt: bytes) -> Fernet | None:
    """Return Fernet cipher for encryption/decryption, or None if no SSH key found."""
    ssh_key = find_ssh_key_for_encryption()
    if not ssh_key:
        return None
    encryption_key = derive_encryption_key(ssh_key, salt)
    return Fernet(encryption_key)


def encrypt_password(password: str, salt: bytes) -> str:
    """Encrypt password. Returns base64-encoded encrypted string."""
    cipher = get_fernet_cipher(salt)
    if not cipher:
        raise RuntimeError("Failed to initialize encryption")

    encrypted = cipher.encrypt(password.encode("utf-8"))
    return base64.b64encode(encrypted).decode("ascii")


def decrypt_password(encrypted_password: str, salt: bytes) -> str:
    """Decrypt password."""
    cipher = get_fernet_cipher(salt)
    if not cipher:
        raise RuntimeError("Failed to initialize encryption")

    encrypted_bytes = base64.b64decode(encrypted_password.encode("ascii"))
    decrypted = cipher.decrypt(encrypted_bytes)
    return decrypted.decode("utf-8")


def is_encrypted(password: str) -> bool:
    """Check if string looks like a Fernet-encrypted token.

    Fernet tokens are double-base64 encoded (encrypt() returns bytes, we encode
    those to base64 ascii for storage). A valid token, when decoded, starts with
    version byte 0x80 followed by a timestamp.
    """
    if not password:
        return False
    try:
        # Our storage format: base64(fernet_token_bytes)
        outer = base64.b64decode(password.encode("ascii"))
        # Fernet token itself is also base64url-encoded; decode it
        inner = base64.urlsafe_b64decode(outer + b"==")  # pad to avoid errors
        # Fernet version byte is always 0x80
        return len(inner) >= 9 and inner[0] == 0x80
    except Exception:
        return False
