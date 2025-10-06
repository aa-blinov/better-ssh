"""Tests for encryption module."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.encryption import (
    decrypt_password,
    derive_encryption_key,
    encrypt_password,
    find_ssh_key_for_encryption,
    get_fernet_cipher,
    is_encrypted,
)


def test_find_ssh_key_no_ssh_dir(temp_ssh_dir: Path):
    """Test key finding when .ssh doesn't exist."""
    temp_ssh_dir.rmdir()
    result = find_ssh_key_for_encryption()
    assert result is None


def test_find_ssh_key_ed25519(temp_ssh_dir: Path):
    """Test that ed25519 key is found and preferred."""
    ed_key = temp_ssh_dir / "id_ed25519"
    rsa_key = temp_ssh_dir / "id_rsa"
    ed_key.write_text("ed25519-key-content")
    rsa_key.write_text("rsa-key-content")

    result = find_ssh_key_for_encryption()
    assert result == ed_key


def test_find_ssh_key_rsa_fallback(temp_ssh_dir: Path):
    """Test that RSA key is found when ed25519 doesn't exist."""
    rsa_key = temp_ssh_dir / "id_rsa"
    rsa_key.write_text("rsa-key-content")

    result = find_ssh_key_for_encryption()
    assert result == rsa_key


def test_find_ssh_key_none_exist(temp_ssh_dir: Path):
    """Test when no known keys exist."""
    result = find_ssh_key_for_encryption()
    assert result is None


def test_derive_encryption_key(mock_ssh_key: Path):
    """Test key derivation from SSH key."""
    key1 = derive_encryption_key(mock_ssh_key)
    key2 = derive_encryption_key(mock_ssh_key)

    # Should be deterministic
    assert key1 == key2
    # Should be 44 bytes (32 bytes base64-encoded)
    assert len(key1) == 44


def test_derive_encryption_key_different_content(temp_ssh_dir: Path):
    """Test that different SSH keys produce different encryption keys."""
    key1_path = temp_ssh_dir / "key1"
    key2_path = temp_ssh_dir / "key2"
    key1_path.write_text("content1")
    key2_path.write_text("content2")

    enc_key1 = derive_encryption_key(key1_path)
    enc_key2 = derive_encryption_key(key2_path)

    assert enc_key1 != enc_key2


def test_get_fernet_cipher_success(mock_ssh_key: Path):
    """Test Fernet cipher creation with valid SSH key."""
    cipher = get_fernet_cipher()
    assert cipher is not None


def test_get_fernet_cipher_no_key(temp_ssh_dir: Path):
    """Test Fernet cipher fails gracefully without SSH key."""
    cipher = get_fernet_cipher()
    assert cipher is None


def test_encrypt_decrypt_password(mock_ssh_key: Path):
    """Test password encryption and decryption roundtrip."""
    original = "my_secret_password_123"

    encrypted = encrypt_password(original)
    decrypted = decrypt_password(encrypted)

    assert decrypted == original
    assert encrypted != original


def test_encrypt_password_different_each_time(mock_ssh_key: Path):
    """Test that encryption includes randomness (IV/nonce)."""
    password = "same_password"

    encrypted1 = encrypt_password(password)
    encrypted2 = encrypt_password(password)

    # Should be different due to random IV
    assert encrypted1 != encrypted2

    # But both should decrypt to same value
    assert decrypt_password(encrypted1) == password
    assert decrypt_password(encrypted2) == password


def test_encrypt_password_unicode(mock_ssh_key: Path):
    """Test encryption with unicode characters."""
    password = "テスト_🔒_مرحبا_ñ"

    encrypted = encrypt_password(password)
    decrypted = decrypt_password(encrypted)

    assert decrypted == password


def test_is_encrypted_plaintext():
    """Test is_encrypted identifies plaintext."""
    assert is_encrypted("plain_password") is False
    assert is_encrypted("short") is False
    assert is_encrypted("") is False


def test_is_encrypted_valid(mock_ssh_key: Path):
    """Test is_encrypted identifies encrypted passwords."""
    password = "secret"
    encrypted = encrypt_password(password)

    assert is_encrypted(encrypted) is True


def test_is_encrypted_heuristic():
    """Test is_encrypted heuristic checks."""
    # Valid Fernet token starts with 'gAAAAA' -> base64 'Z0FBQUFB'
    fake_encrypted = "Z0FBQUFB" + "a" * 40
    assert is_encrypted(fake_encrypted) is True

    # Too short
    assert is_encrypted("Z0FBQUFB") is False

    # Wrong prefix
    assert is_encrypted("X0FBQUFB" + "a" * 40) is False


def test_decrypt_password_invalid(mock_ssh_key: Path):
    """Test decryption fails with invalid data."""
    with pytest.raises(Exception):
        decrypt_password("not_encrypted_data")


def test_encrypt_without_key(temp_ssh_dir: Path):
    """Test encryption fails without SSH key."""
    with pytest.raises(RuntimeError, match="Failed to initialize encryption"):
        encrypt_password("password")


def test_decrypt_without_key(temp_ssh_dir: Path):
    """Test decryption fails without SSH key."""
    with pytest.raises(RuntimeError, match="Failed to initialize encryption"):
        decrypt_password("some_data")
