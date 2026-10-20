import asyncio
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from telethon import errors, types

from app.engine import Problem
from app.web import Collect

STAMP = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)


class FixedClock(datetime):
    @classmethod
    def now(cls, tz=None):
        return STAMP


def user(number, **kwargs):
    return types.User(id=number, first_name=f"Author {number}", username=f"author{number}",
                      access_hash=number*100, **kwargs)


def message(author, date=STAMP, fallback=None, sender_id=None, **kwargs):
    async def get_sender():
        return fallback
    return SimpleNamespace(date=date, sender=author,
                           sender_id=sender_id if sender_id is not None else getattr(author, "id", None),
                           get_sender=get_sender, action=None, message="NEVER_PERSIST_THIS_MESSAGE", **kwargs)


class HistoryClient:
    def __init__(self, messages, error=None):
        self.messages, self.error = messages, error
        self.requests = []

    def is_connected(self): return True
    async def is_user_authorized(self): return True
    async def get_entity(self, target):
        return types.Chat(id=abs(target),title=f"Group {target}",photo=types.ChatPhotoEmpty(),
                          participants_count=99,date=STAMP,version=1)
    async def get_participants(self, *args, **kwargs):
        raise AssertionError("History must not read the member list")
    async def iter_messages(self, group, **kwargs):
        self.requests.append(kwargs)
        for item in self.messages:
            yield item
        if self.error:
            raise self.error


async def collect(engine, messages, days=None, error=None):
    client = HistoryClient(messages, error)
    engine.clients["alpha"] = client
    lid = engine.collect("History", [{"account_id":"alpha","group_id":-1}], "history", days)
    await asyncio.wait_for(engine.jobs["collect:"+lid], 5)
    return lid, client


async def test_all_history_no_cap_and_no_message_storage(engine, monkeypatch):
    monkeypatch.setattr("app.engine.datetime", FixedClock)
    ancient = STAMP-timedelta(days=3000)
    service=message(user(8));service.action=SimpleNamespace()
    anonymous=message(None,sender_id=-100)
    forwarded=message(user(2), fwd_from=SimpleNamespace(from_id=types.PeerUser(77)))
    messages=[message(user(1)),message(user(1)),forwarded,message(user(3,bot=True)),
              message(user(4,deleted=True)),message(user(9000)),service,anonymous,
              message(None,sender_id=5,fallback=user(5)),message(user(6),ancient)]
    lid, client=await collect(engine,messages)
    rows=engine.s.all("SELECT * FROM members WHERE list_id=? ORDER BY user_id",(lid,))
    assert [r["user_id"] for r in rows]==[1,2,5,6]
    assert client.requests==[{"limit":None,"wait_time":1}]
    assert engine.require("lists",lid)["status"]=="ready"
    assert engine.s.all("SELECT * FROM campaigns")==[]
    with engine.s.db() as db:
        assert "NEVER_PERSIST_THIS_MESSAGE" not in "\n".join(db.iterdump())
    metadata=json.loads(engine.require("lists",lid)["source"])
    assert metadata["method"]=="history" and metadata["cutoff_at"] is None


async def test_days_inclusive_cutoff_and_fixed_upper_boundary(engine,monkeypatch):
    monkeypatch.setattr("app.engine.datetime",FixedClock)
    cutoff=STAMP-timedelta(days=7)
    messages=[message(user(10),STAMP+timedelta(seconds=1)),message(user(1),STAMP),
              message(user(2),cutoff),message(user(3),cutoff-timedelta(seconds=1)),
              message(user(4),cutoff-timedelta(days=1))]
    lid,_=await collect(engine,messages,7)
    assert [r["user_id"] for r in engine.s.all("SELECT user_id FROM members ORDER BY id")]==[1,2]
    metadata=json.loads(engine.require("lists",lid)["source"])
    assert metadata["started_at"]==STAMP.isoformat()
    assert metadata["cutoff_at"]==cutoff.isoformat()
    assert "4 پیام" in engine.require("lists",lid)["note"]


async def test_dedup_across_groups_accounts_preserves_hashes(engine,monkeypatch):
    monkeypatch.setattr("app.engine.datetime",FixedClock)
    alpha,beta=user(1),user(1)
    beta.access_hash=222
    engine.clients={"alpha":HistoryClient([message(alpha)]),"beta":HistoryClient([message(beta)])}
    sources=[{"account_id":"alpha","group_id":-1},{"account_id":"alpha","group_id":-2},
             {"account_id":"beta","group_id":-2}]
    lid=engine.collect("Combined",sources,"history",30)
    await engine.jobs["collect:"+lid]
    rows=engine.s.all("SELECT * FROM members WHERE list_id=?",(lid,))
    assert len(rows)==1 and json.loads(rows[0]["access_json"])=={"alpha":"100","beta":"222"}


async def test_minimal_hash_and_unresolved_authors(engine,monkeypatch):
    monkeypatch.setattr("app.engine.datetime",FixedClock)
    lid,_=await collect(engine,[message(user(1,min=True)),message(None,sender_id=2)])
    assert engine.require("lists",lid)["status"]=="partial"
    assert engine.s.one("SELECT access_json FROM members WHERE user_id=1")["access_json"]=="{}"
    assert "1 نویسنده نامشخص" in engine.require("lists",lid)["note"]


async def test_flood_keeps_partial_and_stops_other_accounts(engine,monkeypatch):
    monkeypatch.setattr("app.engine.datetime",FixedClock)
    engine.clients={"alpha":HistoryClient([message(user(1))],errors.FloodWaitError(None,capture=30)),
                    "beta":HistoryClient([message(user(2))])}
    lid=engine.collect("Flood",[{"account_id":"alpha","group_id":-1},{"account_id":"beta","group_id":-2}],"history")
    await engine.jobs["collect:"+lid]
    assert engine.require("lists",lid)["status"]=="partial"
    assert "FloodWaitError" in engine.require("lists",lid)["note"]
    assert engine.require("accounts","alpha")["status"]=="restricted"
    assert engine.clients["beta"].requests==[]
    assert engine.s.one("SELECT COUNT(*) n FROM members")["n"]==1


async def test_cancel_retains_progress(engine,monkeypatch):
    monkeypatch.setattr("app.engine.datetime",FixedClock)
    waiting=asyncio.Event()
    class WaitingClient(HistoryClient):
        async def iter_messages(self,*args,**kwargs):
            yield message(user(1))
            waiting.set()
            await asyncio.Event().wait()
    engine.clients["alpha"]=WaitingClient([])
    lid=engine.collect("Stopped",[{"account_id":"alpha","group_id":-1}],"history",30)
    await asyncio.wait_for(waiting.wait(),3)
    engine.jobs["collect:"+lid].cancel()
    await asyncio.gather(engine.jobs["collect:"+lid],return_exceptions=True)
    source=engine.require("lists",lid)
    assert source["status"]=="partial" and "1 پیام" in source["note"]
    assert engine.s.one("SELECT COUNT(*) n FROM members")["n"]==1


def test_history_request_validation_and_legacy_defaults():
    from pydantic import ValidationError
    base={"title":"History","sources":[{"account_id":"alpha","group_id":-1}]}
    assert Collect(**base).method=="members"
    assert Collect(**base,method="history").days_back is None
    assert Collect(**base,method="history",days_back=36500).days_back==36500
    for value in [0,-1,36501,1.5,True,"30"]:
        with pytest.raises(ValidationError): Collect(**base,method="history",days_back=value)
    with pytest.raises(ValidationError): Collect(**base,method="members",days_back=30)
    with pytest.raises(ValidationError): Collect(**base,method="unknown")


def test_history_api_passes_method_and_days(data_dir):
    from tests.test_web import session
    client=session(data_dir)
    try:
        captured=[]
        client.app.state.engine.collect=lambda *args: captured.append(args) or "test-id"
        base={"title":"History","sources":[{"account_id":"alpha","group_id":-1}]}
        assert client.post('/api/lists/collect',json={**base,"method":"history","days_back":7}).json()=={"id":"test-id"}
        assert captured[-1][2:]==("history",7)
        assert client.post('/api/lists/collect',json=base).status_code==200
        assert captured[-1][2:]==("members",None)
    finally:
        client.__exit__(None,None,None)
