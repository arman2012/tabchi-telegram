import io
import json

from fastapi.testclient import TestClient

import run
from app.web import create_app


def test_dashboard_urls_must_be_local_http():
    assert run.valid_dashboard_url('http://127.0.0.1:12345/')
    for url in ['https://example.com/', 'file:///C:/Windows/system32/cmd.exe',
                'http://127.0.0.1:12345/other', 'http://user@127.0.0.1:12345/',
                'http://127.0.0.1:0/', 'http://127.0.0.1:99999/',
                'http://127.0.0.1:12345/?url=bad', None]:
        assert not run.valid_dashboard_url(url)


def test_duplicate_launch_opens_verified_dashboard(data_dir,monkeypatch,capsys):
    marker=data_dir/'server.json'
    marker.write_text(json.dumps({'url':'http://127.0.0.1:12345/','instance_id':'test'}),encoding='utf-8')
    checked=[];opened=[]
    monkeypatch.delenv('TABCHI_NO_BROWSER',raising=False)
    monkeypatch.setattr(run,'dashboard_responds',lambda url,key:checked.append((url,key)) or True)
    monkeypatch.setattr(run.webbrowser,'open',lambda url:opened.append(url) or True)
    assert run.reopen_existing(marker,attempts=1)
    assert checked==[('http://127.0.0.1:12345/','test')]
    assert opened==['http://127.0.0.1:12345/']
    assert 'Dashboard: http://127.0.0.1:12345/' in capsys.readouterr().out


def test_duplicate_launch_without_browser_and_missing_marker(data_dir,monkeypatch):
    marker=data_dir/'server.json'
    monkeypatch.setenv('TABCHI_NO_BROWSER','1')
    monkeypatch.setattr(run,'dashboard_responds',lambda *args:True)
    monkeypatch.setattr(run.time,'sleep',lambda seconds:None)
    opened=[]
    monkeypatch.setattr(run.webbrowser,'open',lambda url:opened.append(url))
    assert not run.reopen_existing(marker,attempts=1)
    marker.write_text(json.dumps({'url':'http://127.0.0.1:12345/','instance_id':'test'}),encoding='utf-8')
    assert run.reopen_existing(marker,attempts=1)
    assert opened==[]


def test_stale_or_unsafe_marker_is_not_opened(data_dir,monkeypatch):
    marker=data_dir/'server.json'
    opened=[]
    monkeypatch.setattr(run.webbrowser,'open',lambda url:opened.append(url))
    monkeypatch.setattr(run.time,'sleep',lambda seconds:None)
    monkeypatch.setattr(run,'dashboard_responds',lambda *args:False)
    for info in [{'url':'http://127.0.0.1:12345/','instance_id':'stale'},
                 {'url':'https://example.com/','instance_id':'external'}, [], None]:
        marker.write_text(json.dumps(info),encoding='utf-8')
        assert not run.reopen_existing(marker,attempts=1)
    assert opened==[]


def test_health_identity_and_no_cache(data_dir,monkeypatch):
    monkeypatch.setenv('TABCHI_INSTANCE_ID','unit-test-instance')
    with TestClient(create_app(data_dir)) as client:
        response=client.get('/health')
        assert response.json()=={'app':'tabchi','instance_id':'unit-test-instance'}
        assert response.headers['cache-control']=='no-store'
        assert client.get('/health',headers={'host':'evil.example'}).status_code==403


def test_health_probe_checks_instance_id_and_ignores_proxy(monkeypatch):
    captured=[]
    class Opener:
        def open(self,url,timeout):
            captured.append(url)
            return io.BytesIO(b'{"app":"tabchi","instance_id":"right-instance"}')
    def build(handler):
        assert handler.proxies=={}
        return Opener()
    monkeypatch.setattr(run.urllib.request,'build_opener',build)
    assert run.dashboard_responds('http://127.0.0.1:12345/','right-instance')
    assert not run.dashboard_responds('http://127.0.0.1:12345/','wrong-instance')
    assert captured==['http://127.0.0.1:12345/health']*2
