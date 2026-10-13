"""Push notifications to the household's phones (Expo push service), and links people can tap from a calendar.

Push goes out through Expo's push API when HELPER_PUSH=expo (the app registers its Expo push token at sign-in);
otherwise each notification is written to output/outbox/push-*.json (offline, CI, the demo). A notification carries
only a short message and a deep link into the app (lilhelper://…): no names of children, no menu detail beyond the
dish, nothing about money.
"""
from __future__ import annotations

import json
import os

import httpx

from . import accounts, telemetry
from .config import work_root

EXPO_URL = "https://exp.host/--/api/v2/push/send"


def send(hid: str, title: str, body: str, *, to_users: list[str] | None = None, link: str = "lilhelper://",
         kind: str = "info") -> dict:
    con = accounts.connect()
    devs = accounts.devices(con, hid, to_users)
    con.close()
    messages = [{"to": d["token"], "title": title[:60], "body": body[:180], "sound": "default",
                 "data": {"url": link, "kind": kind}} for d in devs]
    result = {"devices": len(messages), "sent": 0, "mode": "outbox"}
    if not messages:
        return result
    if os.getenv("HELPER_PUSH") == "expo":
        result["mode"] = "expo"
        try:
            headers = {"Accept": "application/json", "Content-Type": "application/json"}
            if os.getenv("EXPO_ACCESS_TOKEN"):
                headers["Authorization"] = f"Bearer {os.environ['EXPO_ACCESS_TOKEN']}"
            r = httpx.post(EXPO_URL, json=messages, headers=headers, timeout=15)
            r.raise_for_status()
            tickets = r.json().get("data", [])
            result["sent"] = sum(1 for t in tickets if t.get("status") == "ok")
            # a device that uninstalled the app: stop sending to it
            con = accounts.connect()
            for msg, t in zip(messages, tickets):
                if (t.get("details") or {}).get("error") == "DeviceNotRegistered":
                    accounts.remove_device(con, msg["to"])
            con.close()
        except httpx.HTTPError as e:
            result["error"] = type(e).__name__
    else:
        d = work_root() / "output" / "outbox"
        d.mkdir(parents=True, exist_ok=True)
        n = len(list(d.glob("push-*.json"))) + 1
        (d / f"push-{n:04d}.json").write_text(json.dumps(messages, indent=1))
        result["sent"] = len(messages)
    telemetry.emit("push", records_out=result["sent"], detail={"kind": kind, "mode": result["mode"]})
    return result
