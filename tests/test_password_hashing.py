"""Tests for PBKDF2 password hashing and legacy SHA-256 migration."""

import hashlib
import hmac

from server import _hash_password, _verify_password


class TestHashPassword:
    def test_pbkdf2_format(self):
        result = _hash_password("secret")
        assert result.startswith("pbkdf2:")
        parts = result.split(":")[1].split("$")
        assert len(parts) == 3
        iterations, salt, digest = parts
        assert iterations == "600000"
        assert len(salt) == 32  # 16 bytes hex
        assert len(digest) == 64  # SHA-256 hex

    def test_unique_salt_per_call(self):
        a = _hash_password("same")
        b = _hash_password("same")
        assert a != b

    def test_verify_matches(self):
        hashed = _hash_password("hunter2")
        assert _verify_password("hunter2", hashed) is True

    def test_verify_wrong_password(self):
        hashed = _hash_password("hunter2")
        assert _verify_password("wrong", hashed) is False

    def test_verify_corrupted_hash(self):
        hashed = _hash_password("test")
        assert _verify_password("test", "pbkdf2:bad$format") is False
        assert _verify_password("test", "pbkdf2:") is False


class TestLegacySHA256Fallback:
    def test_legacy_sha256_verifies(self):
        legacy = hashlib.sha256("oldpassword".encode("utf-8")).hexdigest()
        assert _verify_password("oldpassword", legacy) is True

    def test_legacy_sha256_wrong_password(self):
        legacy = hashlib.sha256("oldpassword".encode("utf-8")).hexdigest()
        assert _verify_password("wrong", legacy) is False

    def test_pbkdf2_takes_precedence(self):
        hashed = _hash_password("modern")
        # Should NOT match via SHA-256 fallback
        assert _verify_password("modern", hashed) is True
        # Verify the hash is not a plain SHA-256
        sha256 = hashlib.sha256("modern".encode("utf-8")).hexdigest()
        assert hashed != sha256

    def test_hmac_compare_digest_used(self, monkeypatch):
        """Verify that hmac.compare_digest is used for timing-safe comparison."""
        calls = []
        original = hmac.compare_digest

        def tracking_compare(a, b):
            calls.append((a, b))
            return original(a, b)

        monkeypatch.setattr(hmac, "compare_digest", tracking_compare)
        hashed = _hash_password("test")
        _verify_password("test", hashed)
        assert len(calls) == 1
