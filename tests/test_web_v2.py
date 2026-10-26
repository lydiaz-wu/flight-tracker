import os
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setenv('TRACKER_DB',str(tmp_path/'v2.db'))
    monkeypatch.setenv('TRACKER_ALLOW_SIGNUP','1')
    import importlib,webapp
    importlib.reload(webapp)
    return TestClient(webapp.app)

def register(client,email):
    r=client.post('/api/register',json={'email':email,'password':'A_Strong_Password_123'})
    assert r.status_code==200,r.text
    return {'X-CSRF-Token':r.json()['csrf']}

def monitor():
    return {'origin':'TPE','destination':'NRT','depart_start':'2027-03-01','depart_end':'2027-03-04','return_start':None,'return_end':None,'airlines':['JL','CI'],'cabin':'economy'}

def test_auth_crud_and_cross_user(client):
    h=register(client,'first@example.com')
    assert client.post('/api/monitors',json=monitor()).status_code==403
    r=client.post('/api/monitors',json=monitor(),headers=h);assert r.status_code==201,r.text
    mid=r.json()['id'];assert len(client.get('/api/monitors').json())==1
    assert client.put(f'/api/monitors/{mid}',json={**monitor(),'enabled':False},headers=h).status_code==200
    h2=register(client,'second@example.com')
    assert client.get(f'/api/monitors/{mid}/history').status_code==404
    assert client.delete(f'/api/monitors/{mid}',headers=h2).status_code==404
    assert client.get('/api/monitors').json()==[]
    assert client.post('/api/logout',headers=h2).status_code==200
    assert client.get('/api/me').status_code==401

def test_invalid_date_and_static(client):
    h=register(client,'third@example.com')
    r=client.post('/api/monitors',json={**monitor(),'depart_end':'2027-02-28'},headers=h)
    assert r.status_code==422
    for path in ['/','/app.js','/styles.css','/manifest.webmanifest','/service-worker.js','/icon.svg']:
        assert client.get(path).status_code==200,path

def test_price_differences_and_history(client):
    h=register(client,'fourth@example.com')
    m=client.post('/api/monitors',json={**monitor(),'down_threshold':500,'up_threshold':500,'target_price':8000},headers=h).json()
    import fare_engine
    id=m['id'];owner=m['owner_id']
    def push(price,n):return fare_engine.ingest(owner,id,[{'airline':'JL','departure':'2027-03-01','price':price}],now=f'2026-11-01T00:00:0{n}+00:00')
    assert push(10000,1)==[]
    assert push(9800,2)==[]
    assert len(push(9000,3))==1
    alerts=push(7900,4);assert len(alerts)==1 and alerts[0]['kind']=='target'
    assert push(7900,5)==[]
    assert len(client.get(f'/api/monitors/{id}/history').json())==5
    assert len(client.get('/api/alerts').json())==2
