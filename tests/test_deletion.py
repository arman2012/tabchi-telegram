import asyncio
from types import SimpleNamespace

import pytest

from app.engine import Problem
from tests.test_engine import setup_campaign


async def test_delete_account_removes_session_preserves_history(engine):
    _,cid=setup_campaign(engine,12)
    engine.review(cid)
    first=engine.s.one("SELECT id FROM deliveries ORDER BY id")["id"]
    engine.s.execute("UPDATE deliveries SET status='sent',message_id=42 WHERE id=?",(first,))
    disconnected=[]
    class Client:
        async def disconnect(self):disconnected.append(True)
    engine.clients["alpha"]=Client()
    engine.pending_codes["alpha"]="temporary-code-hash"
    files=[engine.s.root/"sessions"/("alpha.session"+suffix) for suffix in ["","-journal","-wal","-shm"]]
    for file in files:file.write_bytes(b"private session")
    unrelated=engine.s.root/"sessions"/"beta.session"
    unrelated.write_bytes(b"keep")
    await engine.delete_account("alpha")
    assert disconnected==[True] and "alpha" not in engine.clients and "alpha" not in engine.pending_codes
    assert not any(f.exists() for f in files) and unrelated.read_bytes()==b"keep"
    account=engine.s.one("SELECT * FROM accounts WHERE id='alpha'")
    assert account["status"]=="deleted" and account["phone"]=="deleted:alpha"
    assert account["user_id"] is None and account["username"] is None
    assert engine.s.one("SELECT status,message_id FROM deliveries WHERE id=?",(first,))=={"status":"sent","message_id":42}
    campaign=engine.require("campaigns",cid)
    assert campaign["status"]=="draft" and campaign["reviewed_at"] is None
    with pytest.raises(Problem):engine.review(cid)
    with pytest.raises(Problem):await engine.finish_login("alpha",SimpleNamespace(id=9000,username="old"))
    engine.reassign(cid,["beta"]);engine.review(cid)
    assert engine.require("campaigns",cid)["status"]=="ready"


async def test_deleted_phone_and_user_can_be_added_again(engine):
    phone=engine.require("accounts","alpha")["phone"]
    await engine.delete_account("alpha")
    from tests.test_login import AuthClient
    engine.factory=AuthClient
    result=await engine.login("Re-added",phone)
    assert result["id"]!="alpha"
    await engine.finish_login(result["id"],SimpleNamespace(id=9000,username="back"))
    assert engine.require("accounts",result["id"])["phone"]==phone


async def test_cleanup_failure_is_retryable_and_does_not_reopen_account(engine):
    class Client:
        fail=True
        async def disconnect(self):
            if self.fail:raise OSError("disconnect failed")
    client=Client();engine.clients["alpha"]=client
    with pytest.raises(OSError):await engine.delete_account("alpha")
    assert engine.s.one("SELECT status FROM accounts WHERE id='alpha'")["status"]=="deleting"
    with pytest.raises(Problem):await engine.client("alpha")
    client.fail=False
    await engine.delete_account("alpha")
    assert engine.s.one("SELECT status FROM accounts WHERE id='alpha'")["status"]=="deleted"


async def test_late_login_code_cannot_restore_deleted_account(engine):
    from tests.test_login import AuthClient
    requested,released=asyncio.Event(),asyncio.Event()
    class WaitingLogin(AuthClient):
        async def send_code_request(self,phone):
            requested.set();await released.wait()
            return SimpleNamespace(phone_code_hash="late hash")
        async def disconnect(self):pass
    engine.factory=WaitingLogin
    task=asyncio.create_task(engine.login("Pending","+15557778888"))
    await asyncio.wait_for(requested.wait(),3)
    aid=engine.s.one("SELECT id FROM accounts WHERE phone='+15557778888'")["id"]
    await engine.delete_account(aid)
    released.set()
    with pytest.raises(Problem):await task
    assert engine.s.one("SELECT status FROM accounts WHERE id=?",(aid,))["status"]=="deleted"
    assert aid not in engine.pending_codes


async def test_all_deletion_actions_reject_active_jobs(engine):
    lid,cid=setup_campaign(engine,1)
    task=asyncio.create_task(asyncio.Event().wait())
    engine.jobs["active"]=task
    try:
        with pytest.raises(Problem):await engine.delete_account("alpha")
        with pytest.raises(Problem):engine.delete_list(lid)
        with pytest.raises(Problem):engine.delete_campaign(cid)
        with pytest.raises(Problem):engine.cleanup_uploads()
    finally:
        task.cancel();await asyncio.gather(task,return_exceptions=True)
    assert engine.require("campaigns",cid)["status"]=="draft"


def test_delete_list_keeps_campaign_snapshot_and_purges_after_last_campaign(engine):
    lid,cid=setup_campaign(engine,3)
    engine.delete_list(lid)
    assert engine.s.all("SELECT * FROM members WHERE list_id=?",(lid,))==[]
    with pytest.raises(Problem):engine.require("lists",lid)
    assert engine.s.one("SELECT COUNT(*) n FROM deliveries WHERE campaign_id=?",(cid,))["n"]==3
    engine.review(cid)
    engine.delete_campaign(cid)
    assert engine.s.one("SELECT * FROM lists WHERE id=?",(lid,)) is None
    assert engine.s.all("SELECT * FROM deliveries")==[]
    with pytest.raises(Problem):engine.require("campaigns",cid)
    lid=engine.import_csv("Unreferenced",b"username\npersonone")
    engine.delete_list(lid)
    assert engine.s.one("SELECT * FROM lists WHERE id=?",(lid,)) is None


def test_shared_photos_retained_then_removed_and_orphans_cleaned(engine):
    lid,cid=setup_campaign(engine,1)
    file=engine.s.root/"uploads"/"shared.png";file.write_bytes(b"photo")
    orphan=engine.s.root/"uploads"/"orphan.png";orphan.write_bytes(b"unused")
    engine.s.execute("INSERT INTO uploads VALUES ('shared','uploads/shared.png','image/png')")
    engine.s.execute("INSERT INTO uploads VALUES ('orphan','uploads/orphan.png','image/png')")
    engine.s.execute("UPDATE campaigns SET photo_id='shared' WHERE id=?",(cid,))
    other=engine.create_campaign("Other",lid,"caption","shared",["alpha"],10,30,60)
    engine.delete_campaign(cid)
    assert file.exists()
    assert engine.cleanup_uploads()==1 and not orphan.exists() and file.exists()
    engine.delete_campaign(other)
    assert not file.exists() and engine.s.all("SELECT * FROM uploads")==[]


async def test_session_and_photo_paths_are_contained(engine):
    outside=engine.s.root/"keep.session";outside.write_bytes(b"keep")
    engine.s.execute("INSERT INTO accounts(id,label,phone,status) VALUES ('../keep','x','+15551112222','connected')")
    with pytest.raises(Problem):await engine.delete_account("../keep")
    engine.s.execute("INSERT INTO uploads VALUES ('bad','keep.session','image/png')")
    with pytest.raises(Problem):engine.cleanup_uploads()
    assert outside.read_bytes()==b"keep"


def test_delete_api_security_state_and_preserved_report(data_dir):
    from tests.test_web import session
    client=session(data_dir)
    try:
        store=client.app.state.store
        store.execute("INSERT INTO accounts(id,label,phone,user_id,status) VALUES ('a','History label','+15551234567',9000,'connected')")
        lid=client.post('/api/lists/import',files={'file':('names.csv',b'username\npersonone')}).json()['id']
        cid=client.post('/api/campaigns',json={'title':'x','list_id':lid,'text':'x','account_ids':['a']}).json()['id']
        assert client.delete('/api/accounts/a',headers={'X-CSRF-Token':'invalid'}).status_code==403
        assert client.delete('/api/accounts/a').status_code==200
        state=client.get('/api/state').json()
        assert state['accounts']==[] and state['account_labels']['a']=='History label · حذف‌شده'
        assert 'History label' in client.get(f'/api/campaigns/{cid}/report').text
        assert client.delete(f'/api/lists/{lid}').status_code==200
        assert client.get('/api/state').json()['lists']==[]
        assert client.get(f'/api/lists/{lid}/members').status_code==400
        assert client.get(f'/api/campaigns/{cid}').json()['total']==1
        assert client.delete(f'/api/campaigns/{cid}').status_code==200
        assert client.get('/api/state').json()['campaigns']==[]
        assert client.get(f'/api/campaigns/{cid}/report').status_code==400
        assert client.post('/api/cleanup',json={}).json()['deleted_photos']==0
    finally:
        client.__exit__(None,None,None)
