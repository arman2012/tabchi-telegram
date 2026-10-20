from types import SimpleNamespace

import pytest
from telethon import errors

from app.engine import Problem


class AuthClient:
    def __init__(self, *args, **kwargs):
        self.authorized = False
        self.calls = []
        self.user = SimpleNamespace(id=8000, username="login_test")

    def is_connected(self): return True
    async def is_user_authorized(self): return self.authorized
    async def send_code_request(self, phone): return SimpleNamespace(phone_code_hash="temporary-hash")
    async def get_me(self): return self.user
    async def sign_in(self, **kwargs):
        self.calls.append(kwargs)
        if kwargs.get("code") == "bad": raise errors.PhoneCodeInvalidError(None)
        if not kwargs.get("password"): raise errors.SessionPasswordNeededError(None)
        self.authorized = True
        return self.user


async def test_code_password_and_session_reuse(engine):
    engine.factory = AuthClient
    out = await engine.login("Test", "+15551234567")
    aid = out["id"]
    assert out["step"] == "code"
    with pytest.raises(errors.PhoneCodeInvalidError):
        await engine.verify_login(aid, code="bad")
    assert (await engine.verify_login(aid, code="12345"))["step"] == "password"
    assert (await engine.verify_login(aid, password="test-password"))["step"] == "done"
    assert aid not in engine.pending_codes
    row = engine.require("accounts", aid)
    assert row["status"] == "connected" and row["user_id"] == 8000
    assert not {"password", "code", "phone_code_hash"}.intersection(row)
    assert "test-password" not in row.values() and "12345" not in row.values()
    assert (await engine.login("Test", "+15551234567"))["step"] == "done"


async def test_credentials_and_phone_validation(engine):
    with pytest.raises(Problem): await engine.login("Test", "invalid")
    with pytest.raises(Problem): await engine.verify_login("alpha", code="12345")


async def test_failed_login_records_error_without_secrets(engine):
    class Broken(AuthClient):
        async def send_code_request(self, phone):
            raise errors.PhoneNumberBannedError(None)
    engine.factory = Broken
    with pytest.raises(errors.PhoneNumberBannedError):
        await engine.login("Test", "+15551234567")
    row = engine.s.one("SELECT * FROM accounts WHERE phone='+15551234567'")
    assert row["status"] == "restricted"
    assert row["error"] == "PhoneNumberBannedError"
