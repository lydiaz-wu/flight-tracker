# Flight Tracker 2.0 — Phase 1 (partial)

## Implemented
- `monitor_store.py`: SQLite storage for user-scoped monitoring preferences
- Flexible departure and return date ranges, optional stay length range
- Airline preferences: JX, CI, BR, TR, KE, JL (configuration only; not verified fare scraper coverage)
- Notification preferences and enabled status
- CRUD, strict per-owner filtering, input validation
- Tests in `tests/test_monitor_store.py`

## Not implemented yet
- Authentication / account system (owner ID must come from a trusted authentication system)
- HTTP API / responsive dashboard / PWA / Web Push
- Scheduling from database records and real price-history database
- Real-time scraper validation for additional airlines

## Test
`python -m pytest -q`

Tests pass locally, but no live airfare fetches, iOS Push testing, or deployment tests have been performed.
