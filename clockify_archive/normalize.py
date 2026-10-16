from __future__ import annotations

import csv
import json
import sqlite3
from collections import OrderedDict
from datetime import timezone
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .util import duration_seconds_from_entry, json_compact, parse_datetime

IMPORT_COLUMNS = [
    "Date", "Start", "End", "Duration (h)", "Project", "Customer", "Task",
    "Description", "Tags", "Billable", "Hourly Rate", "Currency", "Type", "Timezone",
]


def _scalar(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, bool):
        return value
    if isinstance(value, (dict, list)):
        return json_compact(value)
    return value


def flatten_top_level(item: dict[str, Any], *, prefix: dict[str, Any] | None = None) -> dict[str, Any]:
    row: OrderedDict[str, Any] = OrderedDict()
    if prefix:
        for k, v in prefix.items():
            row[k] = _scalar(v)
    for key, value in item.items():
        row[key] = _scalar(value)
    return dict(row)


def write_csv(path: Path, rows: list[dict[str, Any]], preferred: list[str] | None = None, delimiter: str = ",") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    keys: list[str] = []
    seen: set[str] = set()
    for key in preferred or []:
        if key not in seen:
            keys.append(key); seen.add(key)
    for row in rows:
        for key in row.keys():
            if key not in seen:
                keys.append(key); seen.add(key)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=keys, delimiter=delimiter, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: _scalar(row.get(k)) for k in keys})


def _timezone_for_user(user: dict[str, Any] | None) -> str:
    if not user:
        return "UTC"
    settings = user.get("settings") or {}
    tz = settings.get("timeZone") or settings.get("timezone") or user.get("timeZone")
    return tz or "UTC"


def _zone(name: str):
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return timezone.utc


def normalized_tables(data: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    users = data.get("users") or []
    clients = data.get("clients") or []
    projects = data.get("projects") or []
    tags = data.get("tags") or []
    groups = data.get("user_groups") or []
    custom_fields = data.get("custom_fields") or []
    entries = data.get("time_entries") or []
    expenses = data.get("expenses") or []
    expense_categories = data.get("expense_categories") or []
    invoices = data.get("invoices") or []
    approvals = data.get("approval_requests") or []
    holidays = data.get("holidays") or []
    policies = data.get("time_off_policies") or []
    requests = data.get("time_off_requests") or []

    users_by_id = {x.get("id"): x for x in users if x.get("id")}
    clients_by_id = {x.get("id"): x for x in clients if x.get("id")}
    projects_by_id = {x.get("id"): x for x in projects if x.get("id")}
    tags_by_id = {x.get("id"): x for x in tags if x.get("id")}
    categories_by_id = {x.get("id"): x for x in expense_categories if x.get("id")}

    tasks: list[dict[str, Any]] = []
    tasks_by_id: dict[str, dict[str, Any]] = {}
    for project_id, project_tasks in (data.get("tasks_by_project") or {}).items():
        project = projects_by_id.get(project_id, {})
        for task in project_tasks or []:
            row = flatten_top_level(task, prefix={"project_id": project_id, "project_name": project.get("name", "")})
            tasks.append(row)
            if task.get("id"):
                tasks_by_id[task["id"]] = task

    project_custom_fields: list[dict[str, Any]] = []
    for project_id, fields in (data.get("project_custom_fields") or {}).items():
        for field in fields or []:
            project_custom_fields.append(flatten_top_level(field, prefix={"project_id": project_id}))

    te_rows: list[dict[str, Any]] = []
    te_tags: list[dict[str, Any]] = []
    te_custom: list[dict[str, Any]] = []
    import_rows: list[dict[str, Any]] = []

    for e in entries:
        uid, pid, tid = e.get("userId"), e.get("projectId"), e.get("taskId")
        user = users_by_id.get(uid, {})
        project = projects_by_id.get(pid, {})
        task = tasks_by_id.get(tid, {})
        client = clients_by_id.get(project.get("clientId"), {})
        interval = e.get("timeInterval") or {}
        seconds = duration_seconds_from_entry(e)
        tzname = _timezone_for_user(user)
        row = OrderedDict([
            ("id", e.get("id", "")),
            ("workspace_id", e.get("workspaceId", "")),
            ("user_id", uid or ""),
            ("user_name", user.get("name", "")),
            ("user_email", user.get("email", "")),
            ("project_id", pid or ""),
            ("project_name", project.get("name", "")),
            ("client_id", project.get("clientId", "")),
            ("client_name", client.get("name", "")),
            ("task_id", tid or ""),
            ("task_name", task.get("name", "")),
            ("description", e.get("description", "")),
            ("start_utc", interval.get("start", "")),
            ("end_utc", interval.get("end", "")),
            ("timezone", tzname),
            ("duration_seconds", seconds if seconds is not None else ""),
            ("duration_hours", round(seconds / 3600, 6) if seconds is not None else ""),
            ("billable", e.get("billable", False)),
            ("type", e.get("type", "REGULAR")),
            ("is_locked", e.get("isLocked", "")),
            ("hourly_rate", json_compact(e.get("hourlyRate")) if e.get("hourlyRate") is not None else ""),
            ("cost_rate", json_compact(e.get("costRate")) if e.get("costRate") is not None else ""),
        ])
        for k, v in e.items():
            if k not in {"timeInterval", "tagIds", "customFieldValues", "hourlyRate", "costRate"} and k not in row:
                row[k] = _scalar(v)
        te_rows.append(dict(row))

        for tag_id in e.get("tagIds") or []:
            te_tags.append({
                "time_entry_id": e.get("id", ""),
                "tag_id": tag_id,
                "tag_name": tags_by_id.get(tag_id, {}).get("name", ""),
            })
        for cf in e.get("customFieldValues") or []:
            if isinstance(cf, dict):
                te_custom.append(flatten_top_level(cf, prefix={"time_entry_id": e.get("id", "")}))

        start_dt, end_dt = parse_datetime(interval.get("start")), parse_datetime(interval.get("end"))
        zone = _zone(tzname)
        start_local = start_dt.astimezone(zone) if start_dt else None
        end_local = end_dt.astimezone(zone) if end_dt else None
        rate = e.get("hourlyRate") or {}
        currency = rate.get("currency") or (project.get("hourlyRate") or {}).get("currency") or ""
        amount = rate.get("amount") if isinstance(rate, dict) else ""
        import_rows.append({
            "Date": start_local.strftime("%Y-%m-%d") if start_local else "",
            "Start": start_local.strftime("%H:%M") if start_local else "",
            "End": end_local.strftime("%H:%M") if end_local else "",
            "Duration (h)": f"{seconds / 3600:.4f}" if seconds is not None else "",
            "Project": project.get("name", ""),
            "Customer": client.get("name", ""),
            "Task": task.get("name", ""),
            "Description": e.get("description", ""),
            "Tags": ",".join(tags_by_id.get(t, {}).get("name", t) for t in (e.get("tagIds") or [])),
            "Billable": "Yes" if e.get("billable") else "No",
            "Hourly Rate": amount if amount is not None else "",
            "Currency": currency,
            "Type": e.get("type", "REGULAR"),
            "Timezone": tzname,
        })

    expense_rows = []
    for x in expenses:
        p = projects_by_id.get(x.get("projectId"), {})
        u = users_by_id.get(x.get("userId"), {})
        c = categories_by_id.get(x.get("categoryId"), {})
        expense_rows.append(flatten_top_level(x, prefix={
            "user_name": u.get("name", ""), "user_email": u.get("email", ""),
            "project_name": p.get("name", ""), "category_name": c.get("name", ""),
        }))

    balance_rows: list[dict[str, Any]] = []
    for policy_id, payload in (data.get("time_off_balances_by_policy") or {}).items():
        values = payload if isinstance(payload, list) else payload.get("balances", []) if isinstance(payload, dict) else []
        for item in values:
            if isinstance(item, dict):
                balance_rows.append(flatten_top_level(item, prefix={"policy_id": policy_id}))

    tables = {
        "users": [flatten_top_level(x) for x in users],
        "clients": [flatten_top_level(x) for x in clients],
        "projects": [flatten_top_level(x, prefix={"client_name": clients_by_id.get(x.get("clientId"), {}).get("name", "")}) for x in projects],
        "tasks": tasks,
        "tags": [flatten_top_level(x) for x in tags],
        "user_groups": [flatten_top_level(x) for x in groups],
        "custom_fields": [flatten_top_level(x) for x in custom_fields],
        "project_custom_fields": project_custom_fields,
        "time_entries": te_rows,
        "time_entry_tags": te_tags,
        "time_entry_custom_fields": te_custom,
        "expenses": expense_rows,
        "expense_categories": [flatten_top_level(x) for x in expense_categories],
        "invoices": [flatten_top_level(x) for x in invoices],
        "approval_requests": [flatten_top_level(x) for x in approvals],
        "holidays": [flatten_top_level(x) for x in holidays],
        "time_off_policies": [flatten_top_level(x) for x in policies],
        "time_off_requests": [flatten_top_level(x) for x in requests],
        "time_off_balances": balance_rows,
        "clockify_import_compatible": import_rows,
    }
    return tables


def write_all_csv(csv_dir: Path, tables: dict[str, list[dict[str, Any]]], delimiter: str = ",") -> None:
    preferred = {
        "time_entries": ["id", "workspace_id", "user_id", "user_name", "user_email", "project_id", "project_name", "client_id", "client_name", "task_id", "task_name", "description", "start_utc", "end_utc", "timezone", "duration_seconds", "duration_hours", "billable", "type"],
        "clockify_import_compatible": IMPORT_COLUMNS,
    }
    for name, rows in tables.items():
        write_csv(csv_dir / f"{name}.csv", rows, preferred.get(name), delimiter)


def _sqlite_type(values: list[Any]) -> str:
    nonempty = [v for v in values if v not in (None, "")]
    if not nonempty:
        return "TEXT"
    if all(isinstance(v, (bool, int)) and not isinstance(v, float) for v in nonempty):
        return "INTEGER"
    if all(isinstance(v, (bool, int, float)) for v in nonempty):
        return "REAL"
    return "TEXT"


def _sqlite_value(v: Any) -> Any:
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False, separators=(",", ":"))
    return v


def write_sqlite(path: Path, tables: dict[str, list[dict[str, Any]]], manifest: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    conn = sqlite3.connect(path)
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("CREATE TABLE archive_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        for key, value in manifest.items():
            conn.execute("INSERT INTO archive_meta(key,value) VALUES (?,?)", (str(key), json_compact(value) if isinstance(value, (dict, list)) else str(value)))

        for name, rows in tables.items():
            columns: list[str] = []
            seen: set[str] = set()
            for row in rows:
                for key in row:
                    if key not in seen:
                        columns.append(key); seen.add(key)
            if not columns:
                conn.execute(f'CREATE TABLE "{name}" (_empty INTEGER)')
                continue
            types = {c: _sqlite_type([row.get(c) for row in rows]) for c in columns}
            col_sql = ", ".join(f'"{c}" {types[c]}' for c in columns)
            conn.execute(f'CREATE TABLE "{name}" ({col_sql})')
            placeholders = ",".join("?" for _ in columns)
            cols_sql = ",".join(f'"{c}"' for c in columns)
            sql = f'INSERT INTO "{name}" ({cols_sql}) VALUES ({placeholders})'
            for row in rows:
                conn.execute(sql, [_sqlite_value(row.get(c, "")) for c in columns])

        for table, column in (("time_entries", "id"), ("users", "id"), ("projects", "id"), ("clients", "id"), ("tasks", "id")):
            try:
                conn.execute(f'CREATE INDEX "idx_{table}_{column}" ON "{table}"("{column}")')
            except sqlite3.OperationalError:
                pass
        conn.commit()
    finally:
        conn.close()
