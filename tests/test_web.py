import io

from fastapi.testclient import TestClient
from PIL import Image

from app.web import create_app


def session(data_dir):
    app=create_app(data_dir)
    client=TestClient(app)
    client.__enter__()
    client.get('/')
    token=client.get('/api/bootstrap').json()['token']
    client.headers['X-CSRF-Token']=token
    return client


def test_local_security_and_secrets(data_dir):
    app=create_app(data_dir)
    with TestClient(app) as client:
        assert client.get('/api/state').status_code==403
        assert client.get('/',headers={'host':'evil.example'}).status_code==403
        assert client.get('/',headers={'origin':'https://evil.example'}).status_code==403
        assert client.get('/').status_code==200
        assert client.get('/static/app.js?v=2').headers['cache-control']=='no-store'
        assert client.post('/api/credentials',json={'api_id':1,'api_hash':'a'*32}).status_code==403
        token=client.get('/api/bootstrap').json()['token']
        response=client.post('/api/credentials',json={'api_id':1,'api_hash':'a'*32},headers={'X-CSRF-Token':token})
        assert response.status_code==200
        body=client.get('/api/state').json()
        assert body['configured'] is True
        assert 'api_hash' not in str(body)
        assert client.get('/data/app.sqlite3').status_code==404


def test_csv_photo_and_campaign_validation(data_dir):
    client=session(data_dir)
    try:
        assert client.post('/api/lists/import',files={'file':('bad.csv',b'name\nfoo')}).status_code==400
        good=client.post('/api/lists/import',files={'file':('names.csv',b'username\npersonone\npersontwo')})
        assert good.status_code==200
        lid=good.json()['id']
        assert client.get(f'/api/lists/{lid}/members').json()['total']==2
        assert client.get(f'/api/lists/{lid}/members?offset=-1').status_code==400
        assert client.post('/api/photos',files={'file':('fake.jpg',b'not an image')}).status_code==400
        image=io.BytesIO();Image.new('RGB',(10,10)).save(image,format='PNG')
        photo=client.post('/api/photos',files={'file':('test.png',image.getvalue())})
        assert photo.status_code==200
        assert client.get('/api/photos/'+photo.json()['id']).headers['content-type']=='image/png'
        body={'title':'x','list_id':lid,'text':'x','account_ids':['a'],'delay_min':60,'delay_max':30}
        assert client.post('/api/campaigns',json=body).status_code==422
    finally:
        client.__exit__(None,None,None)


def test_campaign_api_snapshot_review_and_report(data_dir):
    client=session(data_dir)
    try:
        store=client.app.state.store
        store.execute("INSERT INTO accounts(id,label,phone,user_id,status) VALUES ('a','=formula','+12345678',9000,'connected')")
        lid=client.post('/api/lists/import',files={'file':('names.csv',b'username\npersonone')}).json()['id']
        cid=client.post('/api/campaigns',json={'title':'hello','list_id':lid,'text':'سلام','account_ids':['a']}).json()['id']
        assert store.one('SELECT status FROM campaigns')['status']=='draft'
        assert client.post(f'/api/campaigns/{cid}/start',json={}).status_code==400
        member=store.one('SELECT id FROM members')['id']
        client.post(f'/api/lists/{lid}/members/{member}',json={'excluded':True})
        assert client.get(f'/api/campaigns/{cid}').json()['total']==1
        assert client.post(f'/api/campaigns/{cid}/review',json={}).status_code==200
        report=client.get(f'/api/campaigns/{cid}/report').text
        assert "'=formula" in report
        assert client.post(f'/api/campaigns/{cid}/cancel',json={}).status_code==200
        assert client.post(f'/api/campaigns/{cid}/start',json={}).status_code==400
    finally:
        client.__exit__(None,None,None)
