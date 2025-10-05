from __future__ import annotations

import base64
from pathlib import Path

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from rich.console import Console

console = Console()

# Fixed salt for deterministic key derivation from SSH key
SALT = b"better-ssh-v1-salt-do-not-change"


def find_ssh_key_for_encryption() -> Path | None:
    """Find SSH key to use as encryption source."""
    ssh_dir = Path.home() / ".ssh"
    if not ssh_dir.exists():
        return None

    # Priority: ed25519 > rsa
    for key_name in ["id_ed25519", "id_rsa"]:
        key_path = ssh_dir / key_name
        if key_path.exists():
            return key_path
    return None


def derive_encryption_key(ssh_key_path: Path) -> bytes:
    """Derive encryption key from SSH key content."""
    try:
        key_data = ssh_key_path.read_bytes()
    except Exception as e:
        console.print(f"[red]SSH key read error: {e}[/red]")
        raise

    # Use PBKDF2 to derive fixed-length key
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=SALT,
        iterations=100000,
    )
    derived_key = kdf.derive(key_data)
    return base64.urlsafe_b64encode(derived_key)


def get_fernet_cipher() -> Fernet | None:
    """Return Fernet cipher for encryption/decryption."""
    ssh_key = find_ssh_key_for_encryption()
    if not ssh_key:
        return None

    try:
        encryption_key = derive_encryption_key(ssh_key)
        return Fernet(encryption_key)
    except Exception as e:
        console.print(f"[red]Encryption initialization error: {e}[/red]")
        return None


def encrypt_password(password: str) -> str:
    """Encrypt password. Returns base64-encoded encrypted string."""
    cipher = get_fernet_cipher()
    if not cipher:
        raise RuntimeError("Failed to initialize encryption")

    encrypted = cipher.encrypt(password.encode("utf-8"))
    return base64.b64encode(encrypted).decode("ascii")


def decrypt_password(encrypted_password: str) -> str:
    """Decrypt password."""
    cipher = get_fernet_cipher()
    if not cipher:
        raise RuntimeError("Failed to initialize encryption")

    try:
        encrypted_bytes = base64.b64decode(encrypted_password.encode("ascii"))
        decrypted = cipher.decrypt(encrypted_bytes)
        return decrypted.decode("utf-8")
    except Exception as e:
        console.print(f"[red]Decryption error: {e}[/red]")
        raise


def is_encrypted(password: str) -> bool:
    """Check if string is encrypted (heuristic based on format)."""
    if not password:
        return False
    # Encrypted passwords are base64 strings of specific length
    # Simple heuristic: check if it looks like a Fernet token
    try:
        base64.b64decode(password.encode("ascii"))
        # Check if it looks like Fernet token (starts with gAAAAA)
        # base64('gAAAAA') = 'Z0FBQUFB'
        return len(password) > 40 and password.startswith("Z0FBQUFB")
    except Exception:
        return False
