
"""Scheduled Supabase flight fare monitoring."""

import json
import logging
import os
from urllib.parse import quote

import requests

log = logging.getLogger("cloud_worker")

BASE = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
KEY = os.getenv("SUPABASE_SECRET_KEY", "").strip()


def request(method, path, *, body=None, prefer=None):
    if not BASE or not KEY:
        raise RuntimeError(
            "Missing SUPABASE_URL or SUPABASE_SECRET_KEY"
        )

    if not KEY.startswith("sb_secret_"):
        raise RuntimeError(
            "SUPABASE_SECRET_KEY must be a Supabase sb_secret_ key"
        )

    headers = {
        "apikey": KEY,
        "Content-Type": "application/json",
    }

    if prefer:
        headers["Prefer"] = prefer

    response = requests.request(
        method,
        f"{BASE}/rest/v1/{path}",
        headers=headers,
        json=body,
        timeout=30,
    )

    if not response.ok:
        try:
            payload = response.json()
            if isinstance(payload, dict):
                detail = {
                    k: payload[k]
                    for k in ("code", "message", "hint")
                    if k in payload
                }
            else:
                detail = {"status": response.status_code}
        except ValueError:
            detail = {"status": response.status_code}

        raise RuntimeError(
            f"Supabase REST error {response.status_code}: {detail}"
        )

    if not response.content:
        return None

    return response.json()


def alert_kind(monitor, previous, current):
    target = monitor.get("target_price")

    if (
        target is not None
        and current <= target
        and (previous is None or previous > target)
    ):
        return "target"

    if previous is None:
        return None

    change = current - previous

    if (
        change > 0
        and monitor.get("notify_up")
        and change >= (monitor.get("up_threshold") or 0)
    ):
        return "up"

    if (
        change < 0
        and monitor.get("notify_down")
        and -change >= (monitor.get("down_threshold") or 0)
    ):
        return "down"

    return None


def send_push(monitor, fare, previous, current, kind):
    private_key = os.getenv("VAPID_PRIVATE_KEY")
    subject = os.getenv("VAPID_SUBJECT")

    if not private_key or not subject:
        log.info("Push skipped: VAPID configuration is missing")
        return

    from pywebpush import webpush, WebPushException

    owner = quote(str(monitor["owner_id"]), safe="")

    subscriptions = request(
        "GET",
        f"push_subscriptions?owner_id=eq.{owner}"
        "&select=id,subscription"
    ) or []

    titles = {
        "up": "📈 機票漲價",
        "down": "📉 機票降價",
        "target": "🎯 達到目標票價",
    }

    payload = json.dumps({
        "title": titles[kind],
        "body": (
            f"{monitor['origin']} → {monitor['destination']} "
            f"{fare['airline']} NT${current:,}"
            + (
                f" (前次 NT${previous:,})"
                if previous is not None else ""
            )
        ),
        "url": "./",
        "tag": f"{monitor['id']}-{kind}-{fare['airline']}",
    }, ensure_ascii=False)

    for sub in subscriptions:
        try:
            webpush(
                subscription_info=sub["subscription"],
                data=payload,
                vapid_private_key=private_key,
                vapid_claims={"sub": subject},
            )
        except WebPushException as exc:
            status = getattr(
                getattr(exc, "response", None),
                "status_code",
                None,
            )

            if status in (404, 410):
                request(
                    "DELETE",
                    f"push_subscriptions?id=eq.{sub['id']}"
                )
            else:
                log.warning(
                    "Push delivery failed (HTTP %s)",
                    status,
                )


def fresh_fares(limit_monitors=10, max_pairs=12):
    monitors = request(
        "GET",
        "monitors?enabled=eq.true"
        "&select=*"
        "&order=created_at.asc"
        f"&limit={int(limit_monitors)}"
    ) or []

    log.info("Loaded %d enabled monitors", len(monitors))

    if not monitors:
        return 0

    from worker_v2 import scrape_monitor

    recorded = 0
    failed = 0

    for monitor in monitors:
        try:
            fares, errors = scrape_monitor(monitor, max_pairs)

            for error in errors[:4]:
                log.warning(
                    "Scraper error for %s: %s",
                    monitor["id"],
                    error,
                )

            for fare in fares:
                try:
                    amount = int(fare["price"])

                    if amount <= 0:
                        continue

                    airline = quote(
                        str(fare["airline"]), safe=""
                    )

                    departure = quote(
                        str(fare["departure"]), safe=""
                    )

                    return_date = (
                        fare.get("return_date") or None
                    )

                    returned = (
                        "eq." + quote(
                            str(return_date), safe=""
                        )
                        if return_date
                        else "is.null"
                    )

                    query = (
                        f"observations?monitor_id=eq.{monitor['id']}"
                        f"&airline=eq.{airline}"
                        f"&departure=eq.{departure}"
                        f"&return_date={returned}"
                        "&select=price"
                        "&order=checked_at.desc"
                        "&limit=1"
                    )

                    old = request("GET", query) or []

                    previous = (
                        int(old[0]["price"])
                        if old else None
                    )

                    record = {
                        "monitor_id": monitor["id"],
                        "airline": fare["airline"],
                        "departure": fare["departure"],
                        "return_date": return_date,
                        "price": amount,
                        "booking_url": (
                            fare.get("booking_url") or None
                        ),
                    }

                    request(
                        "POST",
                        "observations",
                        body=record,
                        prefer="return=minimal",
                    )

                    recorded += 1

                    kind = alert_kind(
                        monitor, previous, amount
                    )

                    if kind:
                        try:
                            send_push(
                                monitor,
                                fare,
                                previous,
                                amount,
                                kind,
                            )
                        except Exception:
                            log.exception(
                                "Push failed for monitor %s",
                                monitor["id"],
                            )

                except Exception:
                    failed += 1
                    log.exception(
                        "Failed to store fare for monitor %s",
                        monitor["id"],
                    )

            log.info(
                "Monitor %s: %d scraper results, "
                "%d scraper errors",
                monitor["id"],
                len(fares),
                len(errors),
            )

        except Exception:
            failed += 1
            log.exception(
                "Monitor processing failed: %s",
                monitor["id"],
            )

    log.info(
        "Recorded %d fares; %d processing errors",
        recorded,
        failed,
    )

    if failed:
        raise RuntimeError(
            f"Fare monitoring had {failed} "
            "processing errors; inspect logs"
        )

    return recorded


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )
    fresh_fares()
