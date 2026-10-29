"""GitHub Actions job: Supabase-owned monitor → existing browser scraper → fare history → push.
All service-role secrets MUST remain server-side. Never commit them to web/.
"""
import json,logging,os
from datetime import datetime,timezone
from urllib.parse import quote
import requests

log=logging.getLogger('cloud_worker')
BASE=os.environ.get('SUPABASE_URL','').rstrip('/')
KEY=os.environ.get('SUPABASE_SERVICE_ROLE_KEY','')

def request(method,path,*,body=None,prefer=None):
    if not BASE or not KEY:raise RuntimeError('Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY')
    h={'apikey':KEY,'Authorization':f'Bearer {KEY}','Content-Type':'application/json'}
    if prefer:h['Prefer']=prefer
    r=requests.request(method,BASE+'/rest/v1/'+path,headers=h,json=body,timeout=30)
    r.raise_for_status()
    return r.json() if r.content else None

def fresh_fares(limit_monitors=10,max_pairs=12):
    from worker_v2 import scrape_monitor
    ms=request('GET','monitors?enabled=eq.true&select=*&order=created_at.asc&limit='+str(limit_monitors))
    for m in ms:
        try:
            fares,errors=scrape_monitor(m,max_pairs)
            for err in errors[:4]:log.warning('Scraper error %s: %s',m['id'],err)
            # Empty scrape means unknown, NEVER zero price or inferred cancellation.
            for f in fares:
                key=f"observations?monitor_id=eq.{m['id']}&airline=eq.{quote(f['airline'])}&departure=eq.{f['departure']}&return_date="
                key+=f"eq.{f['return_date']}" if f.get('return_date') else 'is.null'
                old=request('GET',key+'&select=price&order=checked_at.desc&limit=1')
                amount=int(f['price'])
                if amount<=0:continue
                record={'monitor_id':m['id'],'airline':f['airline'],'departure':f['departure'],'return_date':f['return_date'] or None,'price':amount,'booking_url':f.get('booking_url') or None}
                request('POST','observations',body=record,prefer='return=minimal')
                previous=old[0]['price'] if old else None
                kind=alert_kind(m,previous,amount)
                if kind:send_push(m,f,previous,amount,kind)
            log.info('Monitor %s: %d valid observations',m['id'],len(fares))
        except Exception:log.exception('Monitor processing failure %s',m['id'])

def alert_kind(m,previous,current):
    if m.get('target_price') is not None and current<=m['target_price'] and (previous is None or previous>m['target_price']):return 'target'
    if previous is None:return None
    diff=current-previous
    if diff>0 and m['notify_up'] and diff>=m['up_threshold']:return 'up'
    if diff<0 and m['notify_down'] and -diff>=m['down_threshold']:return 'down'
    return None

def send_push(m,f,previous,current,kind):
    private=os.environ.get('VAPID_PRIVATE_KEY');subject=os.environ.get('VAPID_SUBJECT')
    if not private or not subject:return
    from pywebpush import webpush,WebPushException
    subscriptions=request('GET',f"push_subscriptions?owner_id=eq.{m['owner_id']}&select=id,subscription")
    title={'up':'📈 機票漲價','down':'📉 機票降價','target':'🎯 達到目標票價'}[kind]
    payload=json.dumps({'title':title,'body':f"{m['origin']} → {m['destination']} {f['airline']} NT${current:,}"+(f" (前次 NT${previous:,})" if previous is not None else ''),'url':'./','tag':f"{m['id']}-{kind}-{f['airline']}"},ensure_ascii=False)
    for sub in subscriptions:
        try:webpush(subscription_info=sub['subscription'],data=payload,vapid_private_key=private,vapid_claims={'sub':subject})
        except WebPushException as exc:
            status=getattr(getattr(exc,'response',None),'status_code',None)
            if status in (404,410):request('DELETE',f"push_subscriptions?id=eq.{sub['id']}")
            else:log.warning('Push failed status=%s',status)

if __name__=='__main__':
    logging.basicConfig(level=logging.INFO)
    fresh_fares()
