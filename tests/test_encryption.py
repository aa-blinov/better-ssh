"""Tests for encryption module."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.encryption import (
    decrypt_password,
    derive_encryption_key,
    encrypt_password,
    find_ssh_key,
    find_ssh_key_for_encryption,
    get_fernet_cipher,
    is_encrypted,
)

TEST_SALT = b"test-salt-for-unit-tests-only-32"


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


def test_find_ssh_key_default_includes_ecdsa_and_dsa(temp_ssh_dir: Path):
    """Test that find_ssh_key() without args finds ecdsa/dsa keys not in the encryption list."""
    ecdsa_key = temp_ssh_dir / "id_ecdsa"
    ecdsa_key.write_text("ecdsa-key-content")

    # find_ssh_key() default covers ed25519, rsa, ecdsa, dsa
    assert find_ssh_key() == ecdsa_key

    # find_ssh_key_for_encryption() only looks for ed25519/rsa — should not find ecdsa
    assert find_ssh_key_for_encryption() is None


def test_derive_encryption_key(mock_ssh_key: Path):
    """Test key derivation from SSH key."""
    key1 = derive_encryption_key(mock_ssh_key, TEST_SALT)
    key2 = derive_encryption_key(mock_ssh_key, TEST_SALT)

    # Should be deterministic for the same salt
    assert key1 == key2
    # Should be 44 bytes (32 bytes base64-encoded)
    assert len(key1) == 44


def test_derive_encryption_key_different_content(temp_ssh_dir: Path):
    """Test that different SSH keys produce different encryption keys."""
    key1_path = temp_ssh_dir / "key1"
    key2_path = temp_ssh_dir / "key2"
    key1_path.write_text("content1")
    key2_path.write_text("content2")

    enc_key1 = derive_encryption_key(key1_path, TEST_SALT)
    enc_key2 = derive_encryption_key(key2_path, TEST_SALT)

    assert enc_key1 != enc_key2


def test_derive_encryption_key_different_salts(mock_ssh_key: Path):
    """Test that different salts produce different encryption keys for the same SSH key."""
    salt1 = b"salt-one-32-bytes-padding-here!!"
    salt2 = b"salt-two-32-bytes-padding-here!!"

    key1 = derive_encryption_key(mock_ssh_key, salt1)
    key2 = derive_encryption_key(mock_ssh_key, salt2)

    assert key1 != key2


def test_get_fernet_cipher_success(mock_ssh_key: Path):
    """Test Fernet cipher creation with valid SSH key."""
    cipher = get_fernet_cipher(TEST_SALT)
    assert cipher is not None


def test_get_fernet_cipher_no_key(temp_ssh_dir: Path):
    """Test Fernet cipher fails gracefully without SSH key."""
    cipher = get_fernet_cipher(TEST_SALT)
    assert cipher is None


def test_encrypt_decrypt_password(mock_ssh_key: Path):
    """Test password encryption and decryption roundtrip."""
    original = "my_secret_password_123"

    encrypted = encrypt_password(original, TEST_SALT)
    decrypted = decrypt_password(encrypted, TEST_SALT)

    assert decrypted == original
    assert encrypted != original


def test_encrypt_password_different_each_time(mock_ssh_key: Path):
    """Test that encryption includes randomness (IV/nonce)."""
    password = "same_password"

    encrypted1 = encrypt_password(password, TEST_SALT)
    encrypted2 = encrypt_password(password, TEST_SALT)

    # Should be different due to random IV
    assert encrypted1 != encrypted2

    # But both should decrypt to same value
    assert decrypt_password(encrypted1, TEST_SALT) == password
    assert decrypt_password(encrypted2, TEST_SALT) == password


def test_encrypt_decrypt_different_salts(mock_ssh_key: Path):
    """Test that a password encrypted with one salt cannot be decrypted with another."""
    salt1 = b"first-salt-32-bytes-padding-!!!!"
    salt2 = b"other-salt-32-bytes-padding-!!!!"
    password = "secret"

    encrypted = encrypt_password(password, salt1)

    with pytest.raises(Exception):
        decrypt_password(encrypted, salt2)


def test_encrypt_password_unicode(mock_ssh_key: Path):
    """Test encryption with unicode characters."""
    password = "テスト_🔒_مرحبا_ñ"

    encrypted = encrypt_password(password, TEST_SALT)
    decrypted = decrypt_password(encrypted, TEST_SALT)

    assert decrypted == password


def test_is_encrypted_plaintext():
    """Test is_encrypted identifies plaintext."""
    assert is_encrypted("plain_password") is False
    assert is_encrypted("short") is False
    assert is_encrypted("") is False


def test_is_encrypted_valid(mock_ssh_key: Path):
    """Test is_encrypted identifies encrypted passwords."""
    password = "secret"
    encrypted = encrypt_password(password, TEST_SALT)

    assert is_encrypted(encrypted) is True


def test_is_encrypted_heuristic():
    """Test is_encrypted structural checks."""
    # Token is too short after decoding
    assert is_encrypted("Z0FBQUFB") is False

    # Valid base64 but wrong first byte after double-decode (not 0x80)
    # 'YAAAA...' outer-decodes to something starting with 0x60, not 0x80
    assert is_encrypted("YAAAAAAA" + "a" * 40) is False

    # Plaintext that happens to be valid base64 but wrong structure
    assert is_encrypted("aGVsbG8=") is False  # base64 of "hello"

    # Not valid base64 at all
    assert is_encrypted("not-base64!!!") is False


def test_decrypt_password_invalid(mock_ssh_key: Path):
    """Test decryption fails with invalid data."""
    with pytest.raises(Exception):
        decrypt_password("not_encrypted_data", TEST_SALT)


def test_encrypt_without_key(temp_ssh_dir: Path):
    """Test encryption fails without SSH key."""
    with pytest.raises(RuntimeError, match="Failed to initialize encryption"):
        encrypt_password("password", TEST_SALT)


def test_decrypt_without_key(temp_ssh_dir: Path):
    """Test decryption fails without SSH key."""
    with pytest.raises(RuntimeError, match="Failed to initialize encryption"):
        decrypt_password("some_data", TEST_SALT)
