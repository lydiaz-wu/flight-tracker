# Flight Tracker 2.0 — Web/PWA beta

This package includes the original command-line scraper plus a new web application, per-user flight monitors, price history, local accounts, Web Push subscription support, and a bounded background scraper worker.

## Setup

Python 3.11+ recommended. In this directory:

```bash
python -m pip install -r requirements.txt
python -m playwright install chromium
```

Set deployment secrets in environment variables (never commit these):

```bash
export TRACKER_DB=./data/tracker_v2.sqlite3
export TRACKER_SESSION_SECRET='REPLACE_WITH_LONG_RANDOM_SECRET'
export TRACKER_ALLOW_SIGNUP=1
export TRACKER_HTTPS=0  # change to 1 behind production HTTPS
```

Start the API:

```bash
uvicorn webapp:app --host 127.0.0.1 --port 8000
```

Open http://127.0.0.1:8000 and create an account. After registering intended users, **disable public signups** (`TRACKER_ALLOW_SIGNUP=0`) and restart. Never expose a non-HTTPS deployment on the public Internet.

Run scheduler in a separate process:

```bash
python worker_v2.py --loop --interval-minutes 180
```

For production use a process manager, persistent database volume, HTTPS reverse proxy, backups, and environment-managed secrets. SQLite is appropriate for small deployments, not a high-scale public SaaS. **Do not run multiple worker instances simultaneously.**

## Push notifications

Install dependency `pywebpush` (in requirements). Generate Web Push VAPID keys using a trusted Web Push utility, and set `VAPID_PUBLIC_KEY` (URL-safe public P-256 key), `VAPID_PRIVATE_KEY` and `VAPID_SUBJECT=mailto:you@example.com`. The client must open the HTTPS PWA on a supported browser; on iPhone, add to Home Screen and grant notification permission. Endpoint cannot be verified without real device and deployment. Never put the private VAPID key in Git.

## Limits / before production

- Website uses IATA airport codes rather than an airport autocomplete catalog; names/country search not yet implemented.
- All six airline codes are selectable. JX uses the existing Starlux scraper, others use its existing Google Flights scraper. This **does not guarantee** the extra airlines can be scraped reliably. Real website tests are needed.
- Flexible date combos are bounded to 12 per monitor per round, scanning earliest dates first. This is intentionally not an exhaustive best-price search.
- The service currently records **cheapest observed fare per airline/date combination**, not detailed flight-time filtering or a per-flight fare history.
- Price change calculation is against the latest observation of the **same airline/departure/return date**, not against a different travel date.
- No emails/forgot-password, social logins, owner/admin dashboard, billing, rate limits, or public self-service scalable multi-tenant auth. Initial scope is invite-by-enabling-signup for friends only.
- Workers do not record scraper failures in a dedicated user-visible status view, and need operational monitoring.
- Production load/security assessment, deployment, iPhone live push test and real airline integration verification are outstanding.

## Tests

```bash
python -m pytest -q
```
