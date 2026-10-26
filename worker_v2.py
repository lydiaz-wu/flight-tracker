"""Bounded scheduler for Flight Tracker 2.0.

Run separately from the web server: python worker_v2.py --loop
Each scheduled tick processes a limited number of combinations; failures are logged
and never interpreted as prices disappearing. The scraper's Google Flights integration
may be blocked and requires external integration testing.
"""
import argparse,logging,os,time
from datetime import date,datetime,timedelta,timezone
from zoneinfo import ZoneInfo
from config import AirlineConfig,BrowserConfig,TripConfig
from fare_engine import ingest,notify_push
from monitor_store import MonitorStore
from scrapers import BrowserSession,GoogleFlightsScraper,StarluxScraper
from webapp import store,connect

AIRLINE_NAMES={'JX':'星宇航空','CI':'中華航空','BR':'長榮航空','TR':'酷航','KE':'大韓航空','JL':'日本航空'}
log=logging.getLogger('worker_v2')

def combinations(m,limit=12):
    """Enumerate valid departure/return combos, bounded to prevent runaway traffic."""
    start=date.fromisoformat(m['depart_start']);end=date.fromisoformat(m['depart_end']);d=start;n=0
    while d<=end and n<limit:
        if d>=date.today():
            if m['return_start']:
                r=date.fromisoformat(m['return_start']);r_end=date.fromisoformat(m['return_end'])
                while r<=r_end and n<limit:
                    stay=(r-d).days
                    if stay>0 and (m['min_stay'] is None or m['min_stay']<=stay<=m['max_stay']):
                        yield d.isoformat(),r.isoformat();n+=1
                    r+=timedelta(days=1)
            else:
                yield d.isoformat(),'';n+=1
        d+=timedelta(days=1)

def scrape_monitor(m,limit=12):
    observations=[];errors=[]
    # Fresh browser for one monitor, shared across its bounded set of queries.
    browser=BrowserConfig(headless=True,channel='',timeout_sec=25,retry=0)
    with BrowserSession(browser) as session:
        for depart,ret in combinations(m,limit):
            trip=TripConfig(trip_type='來回' if ret else '單程',origin=m['origin'],destination=m['destination'],depart_date=depart,return_date=ret,depart_time=None,return_time=None,adults=1,cabin=m['cabin'],currency='TWD',max_stops=1)
            for code in m['airlines']:
                airline=AirlineConfig(code=code,name=AIRLINE_NAMES[code],source='starlux' if code=='JX' else 'google_flights',enabled=True,color='#354e48',booking_url='',reference_page='')
                cls=StarluxScraper if code=='JX' else GoogleFlightsScraper
                try:
                    result=cls(airline,trip,session,ZoneInfo('Asia/Taipei'),retry=0).run()
                    if not result.success:
                        errors.append(f'{code} {depart}/{ret}: {result.error}');continue
                    prices=[f for f in result.data if f.comparable_price is not None]
                    if prices:
                        cheapest=min(prices,key=lambda f:f.comparable_price)
                        observations.append({'airline':code,'departure':depart,'return_date':ret,'price':cheapest.comparable_price,'booking_url':cheapest.booking_url or cheapest.source_url})
                except Exception as ex:
                    errors.append(f'{code} {depart}/{ret}: {ex}')
    return observations,errors

def run_once(limit_monitors=10,max_pairs=12):
    with connect() as db:
        rows=db.execute('SELECT DISTINCT owner_id FROM monitors WHERE enabled=1').fetchall()
    processed=0
    for row in rows:
        for m in store.list(row['owner_id']):
            if not m['enabled']:continue
            if processed>=limit_monitors:return processed
            processed+=1
            try:
                fares,errors=scrape_monitor(m,max_pairs)
                if errors:log.warning('Monitor %s scrape errors: %s',m['id'],errors[:4])
                # Empty/failed scrapes NEVER erase last known prices or generate a false drop.
                if fares:
                    alerts=ingest(row['owner_id'],m['id'],fares)
                    notify_push(alerts)
                log.info('Monitor %s: %d observations',m['id'],len(fares))
            except Exception:log.exception('Monitor %s processing failed',m['id'])
    return processed

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--loop',action='store_true');parser.add_argument('--interval-minutes',type=int,default=180);a=parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    if a.interval_minutes<60:parser.error('Minimum monitoring interval is 60 minutes to reduce throttling')
    while True:
        run_once()
        if not a.loop:break
        time.sleep(a.interval_minutes*60)
