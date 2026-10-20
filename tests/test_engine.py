import asyncio
import json
import time
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from telethon import errors, types

from app.engine import Problem


class FakeClient:
    def __init__(self, label, sent, fail=None, hold=None):
        self.label, self.sent, self.fail, self.hold = label, sent, fail, hold
        self.targets = []

    def is_connected(self): return True
    async def is_user_authorized(self): return True
    async def disconnect(self): pass

    async def get_entity(self, target):
        self.targets.append(target)
        number = target.user_id if isinstance(target, types.InputPeerUser) else int(str(target).removeprefix("person"))
        return types.User(id=number, first_name="Person", username=f"person{number}", access_hash=number*10)

    async def send_message(self, user, text, **kwargs):
        if self.hold:
            self.hold[0].set()
            await self.hold[1].wait()
        if self.fail:
            raise self.fail
        self.sent.append((self.label, user.id, text))
        return SimpleNamespace(id=len(self.sent))

    async def send_file(self, user, path, caption, **kwargs):
        return await self.send_message(user, caption, **kwargs)


def setup_campaign(engine, count=23, delay=0):
    csv = "username\n" + "\n".join(f"person{i}" for i in range(1, count+1))
    list_id = engine.import_csv("List", csv.encode())
    cid = engine.create_campaign("Campaign", list_id, "سلام", None, ["alpha", "beta"], 10, delay, delay)
    return list_id, cid


def attach(engine, fail=None, hold=None):
    sent = []
    engine.clients = {"alpha": FakeClient("alpha", sent, fail, hold), "beta": FakeClient("beta", sent)}
    return sent


async def finish(engine, cid):
    task = engine.jobs.get("send:" + cid)
    if task:
        await asyncio.wait_for(task, 5)


def test_import_dedup_validation_and_exclusions(engine):
    lid = engine.import_csv("CSV", b"username\n@PersonOne\npersonone\ninvalid link\nhttps://t.me/PersonTwo\n")
    rows = engine.s.all("SELECT * FROM members WHERE list_id=?", (lid,))
    assert [r["username"] for r in rows] == ["personone", "persontwo"]
    assert "Duplicate rows: 1; invalid rows: 1" in engine.require("lists", lid)["note"]
    with pytest.raises(Problem): engine.import_csv("bad", b"name\nabc")
    with pytest.raises(Problem): engine.import_csv("bad", b"username\n@@bad space")


def test_snapshot_and_collection_gate(engine):
    lid, cid = setup_campaign(engine)
    engine.s.execute("UPDATE members SET excluded=1 WHERE list_id=?", (lid,))
    assert engine.s.one("SELECT COUNT(*) n FROM deliveries WHERE campaign_id=?", (cid,))["n"] == 23
    engine.s.execute("UPDATE lists SET status='collecting' WHERE id=?", (lid,))
    with pytest.raises(Problem): engine.create_campaign("x", lid, "x", None, ["alpha"], 10, 30, 60)
    with pytest.raises(Problem): engine.start(cid)


async def test_batches_rotation_completion_and_no_resend(engine):
    _, cid = setup_campaign(engine)
    sent = attach(engine)
    engine.review(cid)
    engine.start(cid)
    await finish(engine, cid)
    assert [x[0] for x in sent] == ["alpha"]*10 + ["beta"]*10 + ["alpha"]*3
    assert len({x[1] for x in sent}) == 23
    assert engine.require("campaigns", cid)["status"] == "completed"
    with pytest.raises(Problem): engine.start(cid)
    engine.s.recover()
    assert len(engine.s.all("SELECT * FROM deliveries WHERE status='sent'")) == 23


async def test_flood_pauses_all_accounts_and_respects_wait(engine):
    _, cid = setup_campaign(engine)
    sent = attach(engine, fail=errors.FloodWaitError(None, capture=40))
    engine.review(cid); engine.start(cid); await finish(engine, cid)
    assert sent == []
    assert engine.require("accounts", "alpha")["status"] == "restricted"
    assert engine.require("campaigns", cid)["status"] == "paused"
    assert engine.require("campaigns", cid)["next_attempt_at"] > time.time()+30
    assert engine.s.one("SELECT COUNT(*) n FROM deliveries WHERE status='pending'")["n"] == 23
    with pytest.raises(Problem): await engine.check_account("alpha")
    with pytest.raises(Problem): engine.start(cid)


async def test_uncertain_delivery_requires_review(engine):
    _, cid = setup_campaign(engine, 2)
    attach(engine, fail=TimeoutError())
    engine.review(cid); engine.start(cid); await finish(engine, cid)
    row = engine.s.one("SELECT * FROM deliveries WHERE campaign_id=? ORDER BY id", (cid,))
    assert row["status"] == "uncertain"
    with pytest.raises(Problem): engine.start(cid)
    engine.resolve_uncertain(cid, row["id"], "sent")
    sent = attach(engine)
    engine.start(cid); await finish(engine, cid)
    assert [x[1] for x in sent] == [2]


async def test_pause_during_request_finishes_only_current(engine):
    _, cid = setup_campaign(engine, 3)
    hold = (asyncio.Event(), asyncio.Event())
    sent = attach(engine, hold=hold)
    engine.review(cid); engine.start(cid)
    await asyncio.wait_for(hold[0].wait(), 3)
    engine.stop(cid)
    with pytest.raises(Problem): engine.start(cid)
    hold[1].set(); await finish(engine, cid)
    assert len(sent) == 1
    assert engine.require("campaigns", cid)["status"] == "paused"
    engine.clients["alpha"].hold = None
    engine.start(cid); await finish(engine, cid)
    assert len(sent) == 3


def test_restart_recovery(store):
    from app.engine import Engine
    engine = Engine(store)
    store.execute("INSERT INTO accounts(id,label,phone,status) VALUES ('a','A','+12345678','pending')")
    lid = engine.make_list("x", "[]")
    store.execute("INSERT INTO campaigns(id,title,list_id,status,text,accounts_json,batch_size,delay_min,delay_max,created) VALUES ('c','c',?,'running','x','[\"a\"]',10,30,60,'now')", (lid,))
    store.execute("INSERT INTO deliveries(campaign_id,name,access_json,account_id,status) VALUES ('c','x','{}','a','sending')")
    store.recover()
    assert engine.require("campaigns", "c")["status"] == "paused"
    assert engine.require("lists", lid)["status"] == "partial"
    assert store.one("SELECT status FROM deliveries")["status"] == "uncertain"
    assert engine.require("accounts", "a")["status"] == "disconnected"


def test_random_interval_and_reassign_remaining_only(engine, monkeypatch):
    _, cid = setup_campaign(engine)
    first = engine.s.one("SELECT id FROM deliveries ORDER BY id")
    engine.s.execute("UPDATE deliveries SET status='sent' WHERE id=?", (first["id"],))
    engine.reassign(cid, ["beta"])
    assert engine.s.one("SELECT account_id FROM deliveries WHERE id=?", (first["id"],))["account_id"] == "alpha"
    assert {r["account_id"] for r in engine.s.all("SELECT account_id FROM deliveries WHERE status='pending'")} == {"beta"}
    assert engine.require("campaigns", cid)["reviewed_at"] is None
    monkeypatch.setattr("app.engine.random.uniform", lambda lo, hi: 42 if (lo,hi)==(30,60) else 0)
    campaign = engine.require("campaigns", cid) | {"delay_min":30,"delay_max":60}
    stamp=time.time();engine.schedule_next(campaign)
    assert stamp+41.9 <= engine.require("campaigns", cid)["next_attempt_at"] <= stamp+42.1


async def test_collect_separate_dedup_hashes_and_partial(engine):
    class Collector(FakeClient):
        async def get_entity(self, target):
            return types.Chat(id=1,title="Group",photo=types.ChatPhotoEmpty(),participants_count=8,date=datetime.now(timezone.utc),version=1)
        async def get_participants(self, group, limit):return SimpleNamespace(total=8)
        async def iter_participants(self, group):
            yield types.User(id=1,first_name="A",username="person1",access_hash=100 if self.label=="alpha" else 200)
            yield types.User(id=2,first_name="Bot",bot=True)
            yield types.User(id=9000,first_name="Me")
    sent=[];engine.clients={id:Collector(id,sent) for id in ["alpha","beta"]}
    lid=engine.collect("Groups",[{"account_id":"alpha","group_id":-1},{"account_id":"beta","group_id":-1}])
    await asyncio.wait_for(engine.jobs["collect:"+lid],5)
    assert sent==[]
    rows=engine.s.all("SELECT * FROM members WHERE list_id=?",(lid,))
    assert len(rows)==1
    assert json.loads(rows[0]["access_json"])=={"alpha":"100","beta":"200"}
    assert engine.require("lists",lid)["status"]=="partial"


async def test_recipient_privacy_skip_and_photo(engine):
    _, cid=setup_campaign(engine,2)
    sent=attach(engine)
    original=engine.clients["alpha"].send_message
    async def privacy(user,text,**kwargs):
        if user.id==1:raise errors.UserPrivacyRestrictedError(None)
        return await original(user,text,**kwargs)
    engine.clients["alpha"].send_message=privacy
    engine.s.execute("INSERT INTO uploads VALUES ('photo','uploads/photo.jpg','image/jpeg')")
    engine.s.execute("UPDATE campaigns SET photo_id='photo' WHERE id=?",(cid,))
    engine.review(cid);engine.start(cid);await finish(engine,cid)
    assert len(sent)==1
    assert engine.s.all("SELECT status FROM deliveries ORDER BY id")==[{"status":"skipped"},{"status":"sent"}]
