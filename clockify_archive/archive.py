from __future__ import annotations

import json
import shutil
import sys
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from . import __version__
from .api import ClockifyAPIError, ClockifyClient
from .normalize import normalized_tables, write_all_csv, write_sqlite
from .util import dedupe_by_id, dump_json, iso_z, sha256_file, slugify, utc_now

DELETED_ENTITY_TYPES = [
    "CLIENTS", "PROJECTS", "TAGS", "TASKS", "SCHEDULED_ASSIGNMENT", "TIME_ENTRY",
    "TIME_ENTRY_RATE", "TIME_ENTRY_CUSTOM_FIELD_VALUE", "CUSTOM_FIELDS", "USER",
    "USER_GROUPS", "INVOICES", "APPROVAL_REQUESTS", "BALANCE", "HOLIDAYS",
    "PTO_POLICY", "TIME_OFF_REQUEST",
]


@dataclass
class ArchiveOptions:
    workspace: str | None
    output: Path
    start: str
    end: str
    raw: bool = True
    csv: bool = True
    sqlite: bool = True
    receipts: bool = True
    include_deleted: bool = True
    strict: bool = False
    keep_directory: bool = False
    csv_delimiter: str = ","
    verbose: bool = False


@dataclass
class ArchiveResult:
    zip_path: Path
    archive_dir: Path | None
    warnings: list[str] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)


class Archiver:
    def __init__(self, client: ClockifyClient, options: ArchiveOptions) -> None:
        self.client = client
        self.options = options
        self.warnings: list[str] = []
        self.raw_pages: dict[str, Any] = {}
        # Optional Clockify features can be unavailable because of the workspace
        # subscription or the API user's permissions.  Remember feature-level
        # access failures so repeated per-entity calls do not flood the console
        # or waste API requests.
        self.unavailable_features: dict[str, dict[str, Any]] = {}

    def log(self, message: str) -> None:
        if self.options.verbose:
            print(message, file=sys.stderr)

    def warn(self, message: str) -> None:
        self.warnings.append(message)
        print(f"warning: {message}", file=sys.stderr)

    def _optional(
        self,
        label: str,
        fn: Callable[[], Any],
        default: Any,
        *,
        feature: str | None = None,
        feature_label: str | None = None,
    ) -> Any:
        """Run an optional API call, gracefully handling unavailable features.

        When ``feature`` is supplied, authorization/plan failures are remembered
        for the rest of the run.  Subsequent calls for the same feature return
        ``default`` without hitting the API or emitting another warning.

        HTTP 404 is intentionally *not* cached: it can be specific to one
        project/policy/attachment rather than proving that the feature is
        unavailable workspace-wide.
        """
        if feature and feature in self.unavailable_features:
            self.log(f"Skipping {label}: optional feature '{feature}' is unavailable.")
            return default

        try:
            return fn()
        except ClockifyAPIError as exc:
            if self.options.strict or exc.status not in (400, 401, 402, 403, 404, 405, 409):
                raise

            if feature and exc.status in (401, 402, 403, 405):
                display = feature_label or label
                self.unavailable_features[feature] = {
                    "label": display,
                    "http_status": exc.status,
                }
                self.warn(
                    f"{display} not archived: HTTP {exc.status}. "
                    "Further requests for this optional feature will be skipped. "
                    "This may require a paid Clockify feature or additional permission."
                )
            else:
                self.warn(
                    f"{label} not archived: HTTP {exc.status}. "
                    "This may require a paid feature or additional permission."
                )
            return default

    def resolve_workspace(self) -> dict[str, Any]:
        workspaces = self.client.get("/workspaces").data or []
        if not isinstance(workspaces, list) or not workspaces:
            raise RuntimeError("No Clockify workspaces are visible to this API key.")
        selector = self.options.workspace
        if not selector:
            if len(workspaces) == 1:
                return workspaces[0]
            names = ", ".join(f"{w.get('name')} ({w.get('id')})" for w in workspaces)
            raise RuntimeError(f"Multiple workspaces found; use --workspace. Available: {names}")
        exact_id = [w for w in workspaces if w.get("id") == selector]
        if exact_id:
            return exact_id[0]
        exact_name = [w for w in workspaces if str(w.get("name", "")).casefold() == selector.casefold()]
        if len(exact_name) == 1:
            return exact_name[0]
        raise RuntimeError(f"Workspace not found or name is ambiguous: {selector}")

    def _paged_get(self, label: str, path: str, *, params: dict[str, Any] | None = None, extractor: str | None = None, page_size: int = 200) -> list[Any]:
        self.log(f"Fetching {label}...")
        items, pages = self.client.paginate("GET", path, params=params, extractor=extractor, page_size=page_size)
        self.raw_pages[label] = pages
        return items

    def collect(self, workspace_id: str) -> dict[str, Any]:
        wid = workspace_id
        data: dict[str, Any] = {}
        data["workspace"] = self.client.get(f"/workspaces/{wid}").data

        data["users"] = self._paged_get("users", f"/workspaces/{wid}/users", params={"status": "ALL", "memberships": "ALL", "include-roles": "true"})

        clients = []
        for archived in (False, True):
            clients += self._paged_get(f"clients_{'archived' if archived else 'active'}", f"/workspaces/{wid}/clients", params={"archived": str(archived).lower()})
        data["clients"] = dedupe_by_id(clients)

        projects = []
        for archived in (False, True):
            projects += self._paged_get(f"projects_{'archived' if archived else 'active'}", f"/workspaces/{wid}/projects", params={"archived": str(archived).lower(), "hydrated": "true"})
        data["projects"] = dedupe_by_id(projects)

        tags = []
        for archived in (False, True):
            tags += self._paged_get(f"tags_{'archived' if archived else 'active'}", f"/workspaces/{wid}/tags", params={"archived": str(archived).lower()})
        data["tags"] = dedupe_by_id(tags)

        data["user_groups"] = self._paged_get("user_groups", f"/workspaces/{wid}/user-groups", params={"includeTeamManagers": "true"})
        data["custom_fields"] = self._optional(
            "custom fields",
            lambda: self.client.get(f"/workspaces/{wid}/custom-fields").data or [],
            [],
            feature="custom_fields",
            feature_label="custom fields",
        )

        tasks_by_project: dict[str, list[Any]] = {}
        project_custom_fields: dict[str, list[Any]] = {}
        for project in data["projects"]:
            pid = project.get("id")
            if not pid:
                continue
            tasks_by_project[pid] = self._paged_get(f"tasks_{pid}", f"/workspaces/{wid}/projects/{pid}/tasks", params={"is-active": "false"})
            # The API's task filters vary by release; a second active query prevents losing active tasks.
            active = self._paged_get(f"tasks_active_{pid}", f"/workspaces/{wid}/projects/{pid}/tasks", params={"is-active": "true"})
            tasks_by_project[pid] = dedupe_by_id(tasks_by_project[pid] + active)
            project_custom_fields[pid] = self._optional(
                f"project custom fields for {pid}",
                lambda pid=pid: self.client.get(f"/workspaces/{wid}/projects/{pid}/custom-fields").data or [],
                [],
                feature="project_custom_fields",
                feature_label="project custom fields",
            )
        data["tasks_by_project"] = tasks_by_project
        data["project_custom_fields"] = project_custom_fields

        time_entries: list[Any] = []
        time_entries_by_user: dict[str, list[Any]] = {}
        for user in data["users"]:
            uid = user.get("id")
            if not uid:
                continue
            entries, pages = self.client.paginate(
                "GET", f"/workspaces/{wid}/user/{uid}/time-entries",
                params={"start": self.options.start, "end": self.options.end},
                page_size=200,
            )
            time_entries.extend(entries)
            time_entries_by_user[uid] = entries
            self.raw_pages[f"time_entries_{uid}"] = pages
        data["time_entries"] = dedupe_by_id(time_entries)
        data["time_entries_by_user"] = time_entries_by_user

        data["expense_categories"] = self._optional("expense categories", lambda: self._collect_expense_categories(wid), [])
        data["expenses"] = self._optional("expenses", lambda: self._paged_get("expenses", f"/workspaces/{wid}/expenses", extractor="expenses"), [])
        data["invoices"] = self._optional("invoices", lambda: self._paged_get("invoices", f"/workspaces/{wid}/invoices", extractor="invoices"), [])
        data["approval_requests"] = self._optional("approval requests", lambda: self._paged_get("approval_requests", f"/workspaces/{wid}/approval-requests"), [])
        data["holidays"] = self._optional("holidays", lambda: self.client.get(f"/workspaces/{wid}/holidays").data or [], [])
        data["time_off_policies"] = self._optional("time off policies", lambda: self._paged_get("time_off_policies", f"/workspaces/{wid}/time-off/policies", params={"status": "ALL"}), [])
        data["time_off_requests"] = self._optional("time off requests", lambda: self._collect_time_off_requests(wid), [])

        balances: dict[str, Any] = {}
        for policy in data["time_off_policies"]:
            pid = policy.get("id")
            if pid:
                balances[pid] = self._optional(
                    f"time off balances for policy {pid}",
                    lambda pid=pid: self._paged_get(f"time_off_balance_{pid}", f"/workspaces/{wid}/time-off/balance/policy/{pid}"),
                    [],
                    feature="time_off_balances",
                    feature_label="time off balances",
                )
        data["time_off_balances_by_policy"] = balances

        if self.options.include_deleted:
            data["deleted_entities"] = self._optional("deleted entities", lambda: self._collect_deleted(wid), [])
        else:
            data["deleted_entities"] = []
        return data

    def _collect_expense_categories(self, wid: str) -> list[Any]:
        values = []
        for archived in (False, True):
            values += self._paged_get(
                f"expense_categories_{'archived' if archived else 'active'}",
                f"/workspaces/{wid}/expenses/categories",
                params={"archived": str(archived).lower()}, extractor="categories",
            )
        return dedupe_by_id(values)

    def _collect_time_off_requests(self, wid: str) -> list[Any]:
        items, pages = self.client.paginate(
            "POST", f"/workspaces/{wid}/time-off/requests",
            params={"start": self.options.start, "end": self.options.end, "statuses": ["ALL"]},
            extractor="requests", page_size=200, page_size_param="pageSize", json_body=None,
        )
        self.raw_pages["time_off_requests"] = pages
        return items

    def _collect_deleted(self, wid: str) -> list[Any]:
        items, pages = self.client.paginate(
            "GET", f"/workspaces/{wid}/entities/deleted",
            params={"type": DELETED_ENTITY_TYPES, "start": self.options.start, "end": self.options.end},
            extractor="response", page_param="page", page_size_param="limit", page_size=200, start_page=0,
        )
        self.raw_pages["deleted_entities"] = pages
        return items

    def _write_raw(self, raw_dir: Path, data: dict[str, Any]) -> None:
        for key, value in data.items():
            dump_json(raw_dir / f"{key}.json", value)
        dump_json(raw_dir / "api_pages.json", self.raw_pages)

    def _download_receipts(self, root: Path, wid: str, expenses: list[dict[str, Any]]) -> None:
        for expense in expenses:
            eid, fid = expense.get("id"), expense.get("fileId")
            if not eid or not fid:
                continue
            dest = root / "attachments" / "receipts" / f"{eid}_{fid}"
            self._optional(
                f"expense receipt {eid}/{fid}",
                lambda eid=eid, fid=fid, dest=dest: self.client.download(
                    f"/workspaces/{wid}/expenses/{eid}/files/{fid}", dest
                ),
                None,
                feature="expense_receipts",
                feature_label="expense receipt downloads",
            )

    @staticmethod
    def _counts(data: dict[str, Any]) -> dict[str, int]:
        counts = {}
        for key, value in data.items():
            if isinstance(value, list):
                counts[key] = len(value)
            elif isinstance(value, dict) and key.endswith("_by_project"):
                counts[key] = sum(len(v or []) for v in value.values())
            elif isinstance(value, dict) and key.endswith("_by_policy"):
                counts[key] = sum(len(v or []) if isinstance(v, list) else 1 for v in value.values())
        return counts

    def run(self) -> ArchiveResult:
        workspace_hint = self.resolve_workspace()
        wid = workspace_hint["id"]
        self.log(f"Archiving workspace {workspace_hint.get('name')} ({wid})")
        data = self.collect(wid)
        workspace = data.get("workspace") or workspace_hint
        timestamp = utc_now().strftime("%Y%m%d-%H%M%S")
        basename = f"clockify-{slugify(workspace.get('name', 'workspace'))}-{timestamp}"

        output = self.options.output
        if output.suffix.lower() == ".zip":
            zip_path = output
            parent = output.parent
            archive_dir = parent / output.stem
        else:
            parent = output
            archive_dir = parent / basename
            zip_path = parent / f"{basename}.zip"
        parent.mkdir(parents=True, exist_ok=True)
        if archive_dir.exists():
            shutil.rmtree(archive_dir)
        archive_dir.mkdir(parents=True)

        counts = self._counts(data)
        manifest = {
            "format": "clockify-portable-archive",
            "format_version": "1.0",
            "tool": "clockify-archive",
            "tool_version": __version__,
            "exported_at": iso_z(utc_now()),
            "source": "Clockify API v1",
            "api_base_url": self.client.base_url,
            "workspace_id": wid,
            "workspace_name": workspace.get("name", ""),
            "range": {"start": self.options.start, "end": self.options.end},
            "counts": counts,
            "warnings": self.warnings,
            "unavailable_optional_features": self.unavailable_features,
        }

        if self.options.raw:
            self._write_raw(archive_dir / "raw", data)
        tables = normalized_tables(data)
        if self.options.csv:
            write_all_csv(archive_dir / "csv", tables, self.options.csv_delimiter)
        if self.options.sqlite:
            write_sqlite(archive_dir / "database" / "clockify.sqlite", tables, manifest)
        if self.options.receipts:
            self._download_receipts(archive_dir, wid, data.get("expenses") or [])

        dump_json(archive_dir / "manifest.json", manifest)
        (archive_dir / "README.txt").write_text(
            "Clockify portable archive\n\n"
            "raw/ contains API data; csv/ contains normalized portable tables; "
            "database/clockify.sqlite contains the same normalized tables in SQLite.\n"
            "csv/clockify_import_compatible.csv uses the 14-column schema accepted by the companion clockify-import tool.\n"
            "See the project README for restoration and migration guidance.\n",
            encoding="utf-8",
        )

        checksum_lines = []
        for path in sorted(p for p in archive_dir.rglob("*") if p.is_file() and p.name != "SHA256SUMS"):
            checksum_lines.append(f"{sha256_file(path)}  {path.relative_to(archive_dir).as_posix()}")
        (archive_dir / "SHA256SUMS").write_text("\n".join(checksum_lines) + "\n", encoding="utf-8")

        if zip_path.exists():
            zip_path.unlink()
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
            for path in sorted(p for p in archive_dir.rglob("*") if p.is_file()):
                zf.write(path, f"{archive_dir.name}/{path.relative_to(archive_dir).as_posix()}")

        kept = archive_dir if self.options.keep_directory else None
        if not self.options.keep_directory:
            shutil.rmtree(archive_dir)
        return ArchiveResult(zip_path=zip_path, archive_dir=kept, warnings=self.warnings, counts=counts)
