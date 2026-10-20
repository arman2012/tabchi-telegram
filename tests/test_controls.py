import asyncio
import json
import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from telethon import errors, functions

from app.engine import Engine, Problem
from app.store import Store
from app.web import Campaign
from tests.test_engine import FakeClient, attach, finish, setup_campaign
from tests.test_history import HistoryClient, STAMP, message, user


def create(engine, lid, **options):
    return engine.create_campaign('Controls', lid, 'hello', None, ['alpha'], 10, 0, 0, **options)


async def test_cooldown_survives_login_restart_and_shorter_wait(engine):
    deadline = time.time() + 600
    engine.s.execute("UPDATE accounts SET wait_until=? WHERE id='alpha'", (deadline,))
    engine.restrict('alpha', errors.FloodWaitError(None, capture=10))
    assert engine.require('accounts', 'alpha')['wait_until'] == deadline
    engine.s.recover()
    fresh = Engine(Store(engine.s.root))
    for operation in [fresh.client('alpha'), fresh.login('A', '+15550000000'),
                      fresh.finish_login('alpha', SimpleNamespace(id=9000, username='me')),
                      fresh.check_account('alpha')]:
        with pytest.raises(Problem):
            await operation
    assert fresh.require('accounts', 'alpha')['wait_until'] == deadline
    engine.s.execute("UPDATE accounts SET status='connected' WHERE id='alpha'")
    with pytest.raises(Problem):
        engine.validate_accounts(['alpha'])


async def test_slowmode_is_persistent_destination_wait(engine):
    _, cid = setup_campaign(engine, 2)
    sent = attach(engine, fail=errors.SlowModeWaitError(None, capture=40))
    engine.review(cid); engine.start(cid); await finish(engine, cid)
    row = engine.s.one('SELECT * FROM deliveries ORDER BY id')
    assert row['status'] == 'pending' and row['wait_until'] > time.time() + 30
    assert engine.require('accounts', 'alpha')['status'] == 'connected'
    engine.schedule_next(engine.require('campaigns', cid))
    engine.s.recover()
    engine.clients['alpha'].fail = None
    engine.start(cid)
    await asyncio.sleep(.05)
    assert not sent
    engine.stop(cid); await finish(engine, cid)


async def test_scheduled_start_does_not_send_and_can_cancel(engine):
    lid, _ = setup_campaign(engine, 1)
    scheduled = datetime.now(timezone.utc) + timedelta(hours=1)
    cid = create(engine, lid, scheduled_at=scheduled)
    sent = attach(engine)
    engine.review(cid); engine.start(cid)
    await asyncio.sleep(.05)
    assert not sent
    with pytest.raises(Problem):
        engine.start(cid)
    engine.stop(cid, cancel=True); await finish(engine, cid)
    assert engine.require('campaigns', cid)['status'] == 'cancelled'


async def test_overdue_schedule_and_restart_require_manual_resume(engine):
    lid, _ = setup_campaign(engine, 1)
    cid = create(engine, lid, scheduled_at=datetime.now(timezone.utc)-timedelta(hours=1))
    engine.review(cid)
    engine.s.execute("UPDATE campaigns SET status='running' WHERE id=?", (cid,))
    engine.s.recover()
    assert engine.require('campaigns', cid)['status'] == 'paused'
    sent = attach(engine)
    engine.start(cid); await finish(engine, cid)
    assert len(sent) == 1


async def test_activity_observations_merge_and_snapshot(engine, monkeypatch):
    engine.clients = {'alpha': HistoryClient([message(user(1)), message(user(1), STAMP-timedelta(days=8))]),
                      'beta': HistoryClient([message(user(1), STAMP-timedelta(days=2)), message(user(2), STAMP-timedelta(days=40))])}
    lid = engine.collect('history', [{'account_id':'alpha','group_id':-1}, {'account_id':'beta','group_id':-2}], 'history')
    await engine.jobs['collect:'+lid]
    assert engine.s.one('SELECT last_active_at FROM members WHERE user_id=1')['last_active_at'] == STAMP.timestamp()
    engine.s.execute("INSERT INTO members(list_id,name,username) VALUES (?,'unknown','unknownperson')", (lid,))
    monkeypatch.setattr('app.engine.time.time', lambda: STAMP.timestamp()+30*86400)
    cid = create(engine, lid, active_within_days=30)
    c = engine.require('campaigns', cid)
    assert json.loads(c['filter_counts_json']) == {'qualifying':1,'inactive':1,'unknown':1}
    assert engine.s.one('SELECT COUNT(*) n FROM deliveries WHERE campaign_id=?', (cid,))['n'] == 1
    engine.s.execute('UPDATE members SET last_active_at=NULL WHERE list_id=?', (lid,))
    assert engine.s.one('SELECT last_active_at FROM deliveries WHERE campaign_id=?', (cid,))['last_active_at'] == STAMP.timestamp()


class BioClient(FakeClient):
    def __init__(self, sent, fail=None):
        super().__init__('alpha', sent)
        self.about = ''
        self.updates = []
        self.bio_fail = fail

    async def __call__(self, request):
        if isinstance(request, functions.users.GetFullUserRequest):
            return SimpleNamespace(full_user=SimpleNamespace(about=self.about))
        assert isinstance(request, functions.account.UpdateProfileRequest)
        self.about = request.about
        self.updates.append(request.about)
        if self.bio_fail:
            raise self.bio_fail
        return True


async def test_bio_interruption_reconciled_without_repeat(engine):
    lid, _ = setup_campaign(engine, 2)
    cid = create(engine, lid, bio_texts=['Profile one', 'Profile two'])
    sent = []
    client = BioClient(sent, TimeoutError())
    engine.clients['alpha'] = client
    engine.review(cid); engine.start(cid); await finish(engine, cid)
    selected = engine.s.one('SELECT * FROM campaign_bios WHERE campaign_id=?', (cid,))
    assert selected['status'] == 'uncertain' and not sent
    engine.s.recover()
    client.bio_fail = None
    engine.start(cid); await finish(engine, cid)
    assert len(client.updates) == 1 and len(sent) == 2
    assert client.about == selected['text']
    assert engine.s.one('SELECT status FROM campaign_bios WHERE campaign_id=?', (cid,))['status'] == 'done'
    engine.delete_campaign(cid)
    assert engine.s.all('SELECT * FROM campaign_bios WHERE campaign_id=?', (cid,)) == []


async def test_bio_flood_pauses_without_send(engine):
    lid, _ = setup_campaign(engine, 1)
    cid = create(engine, lid, bio_texts=['profile'])
    sent = []
    engine.clients['alpha'] = BioClient(sent, errors.FloodWaitError(None, capture=60))
    engine.review(cid); engine.start(cid); await finish(engine, cid)
    assert not sent and engine.require('accounts','alpha')['wait_until'] > time.time()+50
    assert engine.s.one('SELECT status FROM deliveries WHERE campaign_id=?', (cid,))['status'] == 'pending'


async def test_posting_permission_pauses_instead_of_continuing(engine):
    _, cid = setup_campaign(engine, 2)
    sent = attach(engine, fail=errors.ChatWriteForbiddenError(None))
    engine.review(cid); engine.start(cid); await finish(engine, cid)
    assert not sent and engine.require('campaigns',cid)['status'] == 'paused'
    assert [r['status'] for r in engine.s.all('SELECT status FROM deliveries ORDER BY id')] == ['failed','pending']


@pytest.mark.parametrize('options', [
    {'scheduled_at':'2026-10-20T12:00:00'}, {'active_within_days':0}, {'active_within_days':366},
    {'bio_texts':[' ']}, {'bio_texts':['a'*71]}, {'bio_texts':['a']*21},
])
def test_option_validation(options):
    with pytest.raises(ValidationError):
        Campaign(title='x', list_id='x', account_ids=['alpha'], **options)


def test_timezone_conversion():
    model = Campaign(title='x', list_id='x', account_ids=['alpha'], scheduled_at='2026-10-20T10:00:00+03:30')
    assert model.scheduled_at.astimezone(timezone.utc).hour == 6
    assert model.scheduled_at.astimezone(timezone.utc).minute == 30


def test_legacy_database_migration_is_idempotent(store):
    with store.db() as db:
        db.execute('DROP TABLE campaign_bios')
        for table, names in {'members':['last_active_at'],
                             'campaigns':['scheduled_at','server_wait_until','active_within_days','filter_counts_json','bio_texts_json'],
                             'deliveries':['last_active_at','wait_until']}.items():
            for name in names:
                db.execute(f'ALTER TABLE {table} DROP COLUMN {name}')
    migrated = Store(store.root)
    Store(store.root)
    with migrated.db() as db:
        assert 'last_active_at' in {r['name'] for r in db.execute('PRAGMA table_info(members)')}
        assert 'server_wait_until' in {r['name'] for r in db.execute('PRAGMA table_info(campaigns)')}


async def test_flood_during_resolution_keeps_pending(engine):
    _, cid = setup_campaign(engine, 2)
    sent = attach(engine)
    async def fail_resolution(target):
        raise errors.FloodWaitError(None, capture=80)
    engine.clients['alpha'].get_entity = fail_resolution
    engine.review(cid); engine.start(cid); await finish(engine, cid)
    assert not sent
    assert engine.require('accounts','alpha')['wait_until'] > time.time()+70
    assert engine.s.one('SELECT COUNT(*) n FROM deliveries WHERE status=\'pending\'')['n'] == 2


def test_options_api_and_report(data_dir):
    from tests.test_web import session
    client = session(data_dir)
    try:
        store = client.app.state.store
        store.execute("INSERT INTO accounts(id,label,phone,status) VALUES ('a','A','+12345678','connected')")
        lid = client.post('/api/lists/import', files={'file':('x.csv',b'username\npersonone')}).json()['id']
        response = client.post('/api/campaigns', json={'title':'x','text':'x','list_id':lid,'account_ids':['a'],
                                                     'scheduled_at':'2026-10-20T10:00:00+03:30','bio_texts':['profile']})
        assert response.status_code == 200
        cid = response.json()['id']
        detail = client.get(f'/api/campaigns/{cid}').json()['campaign']
        assert detail['bios'][0]['text'] == 'profile'
        assert detail['filter_counts']['unknown'] == 1
        assert 'last_active_at,wait_until' in client.get(f'/api/campaigns/{cid}/report').text
        assert client.get('/api/state').json()['campaigns'][0]['bios'] == detail['bios']
    finally:
        client.__exit__(None,None,None)
