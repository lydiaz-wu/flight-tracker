"""Flight Tracker 2.0 web API. Start with: uvicorn webapp:app --host 127.0.0.1 --port 8000

Session cookies are signed by an app-specific secret, and only same-origin requests
with CSRF token are allowed for mutations. HTTPS is required outside local development.
"""
from __future__ import annotations
import hashlib, hmac, json, os, secrets, sqlite3, time
from datetime import datetime, timezone
from pathlib import Path
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from monitor_store import MonitorStore, ValidationError, NotFoundError

ROOT=Path(__file__).resolve().parent
DATA=Path(os.environ.get('TRACKER_DB',str(ROOT/'data'/'tracker_v2.sqlite3')))
DATA.parent.mkdir(parents=True,exist_ok=True)
SECRET=os.environ.get('TRACKER_SESSION_SECRET','')
if not SECRET:
    # Development-only: ephemeral sessions; a production server must set this env var
    SECRET=secrets.token_hex(32)
COOKIE_SECURE=os.environ.get('TRACKER_HTTPS','0')=='1'
store=MonitorStore(DATA)
app=FastAPI(title='Flight Tracker 2.0')


def connect():
    db=sqlite3.connect(str(DATA),timeout=20)
    db.row_factory=sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    return db

with connect() as db:
    db.executescript('''
    CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY,email TEXT UNIQUE NOT NULL, salt TEXT NOT NULL, password_hash TEXT NOT NULL,created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS sessions(token_hash TEXT PRIMARY KEY,user_id TEXT NOT NULL,csrf TEXT NOT NULL,expiry INTEGER NOT NULL, FOREIGN KEY(user_id) REFERENCES users(id));
    CREATE TABLE IF NOT EXISTS observations(id INTEGER PRIMARY KEY AUTOINCREMENT,monitor_id TEXT NOT NULL,airline TEXT NOT NULL,departure TEXT NOT NULL,return_date TEXT NOT NULL DEFAULT '',price INTEGER NOT NULL,currency TEXT NOT NULL DEFAULT 'TWD',booking_url TEXT NOT NULL DEFAULT '',checked_at TEXT NOT NULL,UNIQUE(monitor_id,airline,departure,return_date,checked_at));
    CREATE INDEX IF NOT EXISTS idx_observations_monitor ON observations(monitor_id,checked_at);
    CREATE TABLE IF NOT EXISTS alerts(id TEXT PRIMARY KEY,monitor_id TEXT NOT NULL,owner_id TEXT NOT NULL,kind TEXT NOT NULL,airline TEXT NOT NULL,old_price INTEGER,new_price INTEGER,created_at TEXT NOT NULL,read INTEGER NOT NULL DEFAULT 0);
    CREATE INDEX IF NOT EXISTS idx_alerts_owner ON alerts(owner_id,created_at);
    CREATE TABLE IF NOT EXISTS push_subscriptions(id INTEGER PRIMARY KEY AUTOINCREMENT,owner_id TEXT NOT NULL,endpoint TEXT UNIQUE NOT NULL,subscription TEXT NOT NULL);
    ''')

class Credentials(BaseModel):
    email:str
    password:str
class MonitorInput(BaseModel):
    origin:str
    destination:str
    depart_start:str
    depart_end:str
    return_start:str|None=None
    return_end:str|None=None
    min_stay:int|None=None
    max_stay:int|None=None
    airlines:list[str]
    cabin:str='economy'
    notify_up:bool=True
    notify_down:bool=True
    up_threshold:int=0
    down_threshold:int=0
    target_price:int|None=None
    enabled:bool=True
class PushInput(BaseModel):
    endpoint:str
    keys:dict[str,str]

def password_hash(pw,salt):
    return hashlib.pbkdf2_hmac('sha256',pw.encode(),bytes.fromhex(salt),250000).hex()
def account(req:Request,mutating:bool=False):
    raw=req.cookies.get('flight_session','')
    if not raw: raise HTTPException(401,'Please sign in')
    digest=hashlib.sha256(raw.encode()).hexdigest()
    with connect() as db:
        row=db.execute('SELECT user_id,csrf FROM sessions WHERE token_hash=? AND expiry>?',(digest,int(time.time()))).fetchone()
    if row is None: raise HTTPException(401,'Session expired')
    if mutating and not hmac.compare_digest(req.headers.get('X-CSRF-Token',''),row['csrf']):
        raise HTTPException(403,'Invalid CSRF token')
    return row['user_id']

def start_session(res:Response,user_id:str):
    token=secrets.token_urlsafe(48);csrf=secrets.token_urlsafe(32)
    with connect() as db:
        db.execute('INSERT INTO sessions VALUES(?,?,?,?)',(hashlib.sha256(token.encode()).hexdigest(),user_id,csrf,int(time.time())+30*86400))
    res.set_cookie('flight_session',token,httponly=True,secure=COOKIE_SECURE,samesite='lax',max_age=30*86400)
    return csrf

@app.post('/api/register')
def register(c:Credentials,response:Response):
    email=c.email.strip().lower()
    if len(email)>254 or '@' not in email or len(c.password)<12:raise HTTPException(400,'Valid email and password (at least 12 characters) required')
    if os.environ.get('TRACKER_ALLOW_SIGNUP','0')!='1':raise HTTPException(403,'Registration is currently closed')
    uid=secrets.token_hex(16);salt=secrets.token_hex(16)
    try:
        with connect() as db:db.execute('INSERT INTO users VALUES(?,?,?,?,?)',(uid,email,salt,password_hash(c.password,salt),datetime.now(timezone.utc).isoformat()))
    except sqlite3.IntegrityError:raise HTTPException(409,'Account already exists')
    return {'csrf':start_session(response,uid),'email':email}

@app.post('/api/login')
def login(c:Credentials,response:Response):
    with connect() as db:row=db.execute('SELECT * FROM users WHERE email=?',(c.email.strip().lower(),)).fetchone()
    if row is None or not hmac.compare_digest(password_hash(c.password,row['salt']),row['password_hash']):raise HTTPException(401,'Invalid credentials')
    return {'csrf':start_session(response,row['id']),'email':row['email']}

@app.post('/api/logout')
def logout(req:Request,response:Response):
    account(req,True)
    with connect() as db:db.execute('DELETE FROM sessions WHERE token_hash=?',(hashlib.sha256(req.cookies['flight_session'].encode()).hexdigest(),))
    response.delete_cookie('flight_session')
    return {'ok':True}

@app.get('/api/me')
def me(req:Request):
    uid=account(req)
    with connect() as db:row=db.execute('SELECT email FROM users WHERE id=?',(uid,)).fetchone()
    # csrf token is session-specific and is returned to the authenticated same-origin app
    digest=hashlib.sha256(req.cookies['flight_session'].encode()).hexdigest()
    with connect() as db:session=db.execute('SELECT csrf FROM sessions WHERE token_hash=?',(digest,)).fetchone()
    return {'email':row['email'],'csrf':session['csrf']}

@app.get('/api/monitors')
def list_monitors(req:Request):return store.list(account(req))

@app.post('/api/monitors',status_code=201)
def create_monitor(req:Request,monitor:MonitorInput):
    uid=account(req,True)
    try:return store.create(uid,monitor.model_dump())
    except ValidationError as exc:raise HTTPException(422,str(exc))

@app.put('/api/monitors/{monitor_id}')
def update_monitor(monitor_id:str,req:Request,monitor:MonitorInput):
    uid=account(req,True)
    try:return store.update(uid,monitor_id,monitor.model_dump())
    except ValidationError as exc:raise HTTPException(422,str(exc))
    except NotFoundError:raise HTTPException(404,'Not found')

@app.delete('/api/monitors/{monitor_id}')
def delete_monitor(monitor_id:str,req:Request):
    uid=account(req,True)
    try:store.delete(uid,monitor_id)
    except NotFoundError:raise HTTPException(404,'Not found')
    with connect() as db:
        db.execute('DELETE FROM observations WHERE monitor_id=?',(monitor_id,))
        db.execute('DELETE FROM alerts WHERE monitor_id=? AND owner_id=?',(monitor_id,uid))
    return {'ok':True}

@app.get('/api/monitors/{monitor_id}/history')
def history(monitor_id:str,req:Request):
    uid=account(req)
    try:store.get(uid,monitor_id)
    except NotFoundError:raise HTTPException(404,'Not found')
    with connect() as db:rows=db.execute('SELECT airline,departure,return_date,price,currency,booking_url,checked_at FROM observations WHERE monitor_id=? ORDER BY checked_at DESC LIMIT 500',(monitor_id,)).fetchall()
    return [dict(r) for r in reversed(rows)]

@app.get('/api/alerts')
def alerts(req:Request):
    uid=account(req)
    with connect() as db:rows=db.execute('SELECT * FROM alerts WHERE owner_id=? ORDER BY created_at DESC LIMIT 100',(uid,)).fetchall()
    return [dict(r) for r in rows]

@app.post('/api/push-subscriptions')
def push_subscribe(req:Request,sub:PushInput):
    uid=account(req,True)
    if not sub.endpoint.startswith('https://') or not all(k in sub.keys for k in ('auth','p256dh')):raise HTTPException(422,'Invalid push subscription')
    with connect() as db:db.execute('INSERT INTO push_subscriptions(owner_id,endpoint,subscription) VALUES(?,?,?) ON CONFLICT(endpoint) DO UPDATE SET owner_id=excluded.owner_id,subscription=excluded.subscription',(uid,sub.endpoint,json.dumps(sub.model_dump())))
    return {'ok':True}

@app.get('/api/push-public-key')
def push_public_key():return {'key':os.environ.get('VAPID_PUBLIC_KEY',''),'configured':bool(os.environ.get('VAPID_PUBLIC_KEY') and os.environ.get('VAPID_PRIVATE_KEY'))}

@app.get('/manifest.webmanifest')
def manifest():return FileResponse(ROOT/'web'/'manifest.webmanifest',media_type='application/manifest+json')
@app.get('/service-worker.js')
def worker():return FileResponse(ROOT/'web'/'service-worker.js',media_type='application/javascript',headers={'Service-Worker-Allowed':'/'})
@app.get('/')
def index():return FileResponse(ROOT/'web'/'index.html')
@app.get('/app.js')
def script():return FileResponse(ROOT/'web'/'app.js',media_type='application/javascript')
@app.get('/styles.css')
def css():return FileResponse(ROOT/'web'/'styles.css',media_type='text/css')

@app.get("/icon.svg")
def icon():return FileResponse(ROOT/"web"/"icon.svg",media_type="image/svg+xml")
