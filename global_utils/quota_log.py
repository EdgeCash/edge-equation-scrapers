"""
The Odds API quota log.
=======================
Cross-sport helper: every Odds API response includes rate-limit headers
(`x-requests-used` / `x-requests-remaining`). We log them to a small
persistent file so combined burn from MLB + NFL + NCAAF (and any other
project sharing the same key) is visible at a glance.

File format (one file per sport, e.g. public/data/mlb/quota_log.json):

    {
      "updated_at": "...",
      "current": {"used": 1234, "remaining": 3766},
      "recent": [
        {"timestamp": "...", "used": ..., "remaining": ..., "endpoint": "..."},
        ...                                                  (last 200 entries)
      ]
    }

Used by every sport's odds scraper. Pass the desired log path through
the scraper's constructor so each sport gets its own file (which makes
per-sport burn visible) but they all share the helper.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

QUOTA_LOG_NAME = "quota_log.json"
QUOTA_LOG_MAX_HISTORY = 200


def log_quota(path: Path, headers: dict, endpoint: str) -> None:
    """Append The Odds API rate-limit headers to a small persistent log.

    No-op when the response doesn't contain the expected headers (e.g.
    the call hit a non-Odds-API URL or the response was malformed).
    Atomic write via tmp + rename so concurrent runs can't corrupt it.
    """
    try:
        used = int(headers.get("x-requests-used", "") or 0)
        remaining = int(headers.get("x-requests-remaining", "") or 0)
        last = headers.get("x-requests-last", "")
    except (TypeError, ValueError):
        return

    if not (used or remaining):
        return  # not an Odds API response; nothing to log

    entry = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "used": used,
        "remaining": remaining,
        "last_cost": last,
        "endpoint": endpoint,
    }

    try:
        if path.exists():
            data = json.loads(path.read_text())
        else:
            data = {"updated_at": None, "current": {}, "recent": []}
    except (json.JSONDecodeError, OSError):
        data = {"updated_at": None, "current": {}, "recent": []}

    data["updated_at"] = entry["timestamp"]
    data["current"] = {"used": used, "remaining": remaining}
    history = data.get("recent", [])
    history.append(entry)
    data["recent"] = history[-QUOTA_LOG_MAX_HISTORY:]

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2, default=str))
    tmp.replace(path)
