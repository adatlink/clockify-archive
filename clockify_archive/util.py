from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

_DURATION_RE = re.compile(
    r"^P(?:(?P<days>\d+(?:\.\d+)?)D)?(?:T(?:(?P<hours>\d+(?:\.\d+)?)H)?(?:(?P<minutes>\d+(?:\.\d+)?)M)?(?:(?P<seconds>\d+(?:\.\d+)?)S)?)?$"
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_z(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    value = value.strip()
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def normalize_datetime_arg(value: str | None, *, end_of_day: bool = False) -> str | None:
    if not value:
        return None
    v = value.strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):
        suffix = "T23:59:59Z" if end_of_day else "T00:00:00Z"
        return v + suffix
    dt = parse_datetime(v)
    if not dt:
        raise ValueError(f"Invalid date/time: {value}")
    return iso_z(dt)


def iso8601_duration_seconds(value: str | None) -> int | None:
    if not value:
        return None
    m = _DURATION_RE.match(value)
    if not m:
        return None
    total = 0.0
    total += float(m.group("days") or 0) * 86400
    total += float(m.group("hours") or 0) * 3600
    total += float(m.group("minutes") or 0) * 60
    total += float(m.group("seconds") or 0)
    return int(round(total))


def duration_seconds_from_entry(entry: dict[str, Any]) -> int | None:
    interval = entry.get("timeInterval") or {}
    seconds = iso8601_duration_seconds(interval.get("duration"))
    if seconds is not None:
        return seconds
    start = parse_datetime(interval.get("start"))
    end = parse_datetime(interval.get("end"))
    if start and end:
        return max(0, int(round((end - start).total_seconds())))
    return None


def json_compact(value: Any) -> str:
    if value is None:
        return ""
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def dump_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def slugify(value: str, fallback: str = "workspace") -> str:
    s = value.strip().lower()
    s = re.sub(r"[^a-z0-9._-]+", "-", s)
    s = re.sub(r"-+", "-", s).strip("-._")
    return s or fallback


def dedupe_by_id(items: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        key = str(item.get("id") or json_compact(item))
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()
