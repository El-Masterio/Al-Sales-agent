"""
tests/unit/test_security.py
===========================
Tests for password hashing, JWT, and encryption.
"""

from __future__ import annotations

import uuid

import pytest

from app.services.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    decrypt_json,
    decrypt_value,
    encrypt_json,
    encrypt_value,
    hash_password,
    key_preview,
    verify_password,
)

pytestmark = pytest.mark.unit


class TestPasswordHashing:
    def test_hash_and_verify(self):
        hashed = hash_password("mypassword")
        assert hashed != "mypassword"
        assert verify_password("mypassword", hashed) is True

    def test_verify_wrong_password(self):
        hashed = hash_password("mypassword")
        assert verify_password("wrong", hashed) is False


class TestJWT:
    def test_access_token_roundtrip(self):
        user_id = uuid.uuid4()
        token = create_access_token(user_id, "admin")
        payload = decode_token(token, expected_type="access")
        assert payload["sub"] == str(user_id)
        assert payload["role"] == "admin"
        assert payload["type"] == "access"

    def test_refresh_token_roundtrip(self):
        user_id = uuid.uuid4()
        token = create_refresh_token(user_id, "sales_rep")
        payload = decode_token(token, expected_type="refresh")
        assert payload["type"] == "refresh"

    def test_wrong_token_type_raises(self):
        token = create_access_token(uuid.uuid4(), "admin")
        with pytest.raises(ValueError):
            decode_token(token, expected_type="refresh")

    def test_invalid_token_raises(self):
        with pytest.raises(ValueError):
            decode_token("not-a-token")


class TestEncryption:
    def test_value_roundtrip(self):
        encrypted = encrypt_value("secret-api-key")
        assert encrypted != "secret-api-key"
        assert decrypt_value(encrypted) == "secret-api-key"

    def test_json_roundtrip(self):
        data = {"token": "abc", "refresh": "xyz"}
        encrypted = encrypt_json(data)
        assert decrypt_json(encrypted) == data

    def test_key_preview(self):
        assert key_preview("sk-1234567890ab") == "...90ab"
        assert key_preview("ab") == "**"
