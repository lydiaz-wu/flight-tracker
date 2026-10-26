"""Per-monitor fare processing: baseline, threshold alerts and independent history."""
from __future__ import annotations
import json,secrets
from datetime import datetime,timezone
from webapp import connect,store

def ingest(owner_id:str,monitor_id:str,observations:list[dict],now:str|None=None):
    """Called ONLY by trusted scheduler, never exposed as a public API."""
    monitor=store.get(owner_id,monitor_id)
    now=now or datetime.now(timezone.utc).isoformat()
    changes=[]
    with connect() as db:
        for v in observations:
            airline=v['airline'];departure=v['departure'];ret=v.get('return_date','');price=v['price']
            if airline not in monitor['airlines'] or type(price) is not int or price<0:raise ValueError('Invalid observation')
            if not monitor['depart_start']<=departure<=monitor['depart_end']:raise ValueError('Departure outside monitor range')
            if ret and not monitor['return_start']:raise ValueError('Unexpected return flight')
            if monitor['return_start'] and not monitor['return_start']<=ret<=monitor['return_end']:raise ValueError('Return outside range')
            old=db.execute('''SELECT price FROM observations WHERE monitor_id=? AND airline=? AND departure=? AND return_date=? ORDER BY checked_at DESC,id DESC LIMIT 1''',(monitor_id,airline,departure,ret)).fetchone()
            db.execute('INSERT INTO observations(monitor_id,airline,departure,return_date,price,currency,booking_url,checked_at) VALUES(?,?,?,?,?,?,?,?)',(monitor_id,airline,departure,ret,price,'TWD',v.get('booking_url',''),now))
            kind=None
            if old is not None:
                diff=price-old['price']
                if diff>0 and monitor['notify_up'] and diff>=monitor['up_threshold']:kind='up'
                if diff<0 and monitor['notify_down'] and -diff>=monitor['down_threshold']:kind='down'
            target=monitor['target_price']
            if target is not None and price<=target and (old is None or old['price']>target):kind='target'
            if kind:
                alert={'id':secrets.token_hex(12),'monitor_id':monitor_id,'owner_id':owner_id,'kind':kind,'airline':airline,'old_price':old['price'] if old else None,'new_price':price,'created_at':now}
                db.execute('INSERT INTO alerts(id,monitor_id,owner_id,kind,airline,old_price,new_price,created_at) VALUES(:id,:monitor_id,:owner_id,:kind,:airline,:old_price,:new_price,:created_at)',alert)
                changes.append(alert)
    return changes

def notify_push(changes):
    """Web Push requires pywebpush, configured VAPID keys, and HTTPS."""
    import os
    if not changes or not all(os.environ.get(k) for k in ('VAPID_PRIVATE_KEY','VAPID_SUBJECT')):return {'sent':0,'configured':False}
    try:from pywebpush import webpush,WebPushException
    except ImportError:return {'sent':0,'configured':False}
    sent=0
    with connect() as db:
        for alert in changes:
            rows=db.execute('SELECT id,subscription FROM push_subscriptions WHERE owner_id=?',(alert['owner_id'],)).fetchall()
            for row in rows:
                data={'title':'✈️ 機票價格通知','body':f"{alert['airline']} {alert['kind']}: NT${alert['new_price']:,}",'url':'/','tag':alert['id']}
                try:
                    webpush(subscription_info=json.loads(row['subscription']),data=json.dumps(data),vapid_private_key=os.environ['VAPID_PRIVATE_KEY'],vapid_claims={'sub':os.environ['VAPID_SUBJECT']})
                    sent+=1
                except WebPushException as exc:
                    if getattr(getattr(exc,'response',None),'status_code',0) in (404,410):db.execute('DELETE FROM push_subscriptions WHERE id=?',(row['id'],))
    return {'sent':sent,'configured':True}
