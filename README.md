# clockify-archive

`clockify-archive` creates a vendor-neutral, long-term archive of a Clockify workspace. It is designed as the export-side companion to `clockify-import` and follows the same lightweight approach: **Python 3.11+, standard library only, `argparse`, TOML configuration, and `CLOCKIFY_API_KEY` support**.

The generated archive directory contains three complementary representations:

- **Raw JSON** — Clockify API objects and page responses, retaining native IDs and Clockify-specific fields.
- **Normalized UTF-8 CSV** — portable tables for payroll, ERP, BI, spreadsheets, and import scripts.
- **SQLite** — a single queryable relational-style archive containing the normalized tables.

It also creates `csv/clockify_import_compatible.csv`, using the same 14-column schema as the companion `clockify-import` tool:

`Date, Start, End, Duration (h), Project, Customer, Task, Description, Tags, Billable, Hourly Rate, Currency, Type, Timezone`

## What is archived

The tool attempts to archive:

- workspace information and settings
- users and memberships/roles
- clients, including archived clients
- projects, including archived projects
- tasks for every project
- tags, including archived tags
- user groups
- workspace and project custom fields
- all user time entries in the requested date range
- time-entry tags and custom-field values
- expense categories and expenses
- expense receipt attachments
- invoices
- approval requests
- holidays
- time-off policies, requests, and policy balances
- deleted entities through Clockify's experimental deleted-entities endpoint

Some Clockify features depend on the subscription plan and the API user's permissions. By default, inaccessible optional endpoints produce warnings and the archive continues. Use `--strict` to fail instead.

## Installation

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install .
```

No third-party runtime Python packages are required.

## API key

Create an API key in Clockify and use one of these methods:

```bash
export CLOCKIFY_API_KEY='...'
clockify-archive --list-workspaces
```

or create a config file:

```bash
clockify-archive --init-config
```

Default config path:

```text
~/.config/clockify-archive/config.toml
```

The tool also checks the companion-tool locations `~/.config/clockify-tools/config.toml` and `~/.config/clockify-import/config.toml`, so an existing `clockify-import` configuration can be reused.

Example:

```toml
[clockify]
api_key = "YOUR_CLOCKIFY_API_KEY"
workspace = "YOUR_WORKSPACE"
base_url = "https://api.clockify.me/api/v1"
```

Environment variables override TOML settings:

- `CLOCKIFY_API_KEY`
- `CLOCKIFY_WORKSPACE`
- `CLOCKIFY_BASE_URL`

## Basic usage

List workspaces:

```bash
clockify-archive --list-workspaces
```

Archive the complete history of a workspace:

```bash
clockify-archive -w "YOUR_WORKSPACE" ./archives
```

Archive a date range:

```bash
clockify-archive -w "YOUR_WORKSPACE" --from 2024-01-01 --to 2026-09-25 ./archives
```

By default, the export remains as a normal directory. To also create a ZIP copy beside it:

```bash
clockify-archive -w "YOUR_WORKSPACE" --zip ./archives
```

To organize recurring exports automatically under `YEAR/MONTH/DAY`:

```bash
clockify-archive -w "YOUR_WORKSPACE" --date-subdirs ./archives
```

For example, an export on 2026-09-28 is written below:

```text
./archives/2026/09/28/clockify-your-workspace-20260928-150000/
```

The options can be combined; the ZIP is created beside the directory:

```bash
clockify-archive -w "YOUR_WORKSPACE" --date-subdirs --zip ./archives
```

For compatibility with v0.1.x, an explicit `.zip` output path still creates a ZIP, but the preferred interface is `--zip`.

For an EU/US/UK/AU regional workspace, set the API URL shown by Clockify's API documentation, for example:

```bash
clockify-archive --base-url https://euc1.clockify.me/api/v1 -w "YOUR_WORKSPACE" ./archives
```

## Generated archive

A typical archive directory looks like:

```text
clockify-your-workspace-20260925-150000/
├── manifest.json
├── README.txt
├── SHA256SUMS
├── raw/
│   ├── workspace.json
│   ├── users.json
│   ├── clients.json
│   ├── projects.json
│   ├── tasks_by_project.json
│   ├── tags.json
│   ├── time_entries.json
│   ├── expenses.json
│   ├── invoices.json
│   ├── time_off_policies.json
│   ├── time_off_requests.json
│   ├── deleted_entities.json
│   └── api_pages.json
├── csv/
│   ├── users.csv
│   ├── clients.csv
│   ├── projects.csv
│   ├── tasks.csv
│   ├── tags.csv
│   ├── time_entries.csv
│   ├── time_entry_tags.csv
│   ├── time_entry_custom_fields.csv
│   ├── expenses.csv
│   ├── time_off_requests.csv
│   └── clockify_import_compatible.csv
├── database/
│   └── clockify.sqlite
└── attachments/
    └── receipts/
```

## Date handling

The API archive stores Clockify timestamps as returned by Clockify, generally ISO-8601 timestamps. The normalized `time_entries.csv` explicitly includes UTC start/end timestamps and a timezone column.

The `clockify_import_compatible.csv` representation converts each entry to the user's Clockify timezone when that timezone is available. This mirrors the import-oriented format used by `clockify-import`.

Duration is stored in `time_entries.csv` as both:

- `duration_seconds` — canonical integer representation for calculations and payroll
- `duration_hours` — convenience decimal value

## SQLite examples

Hours per employee and day:

```sql
SELECT
    user_name,
    substr(start_utc, 1, 10) AS work_day,
    round(sum(duration_seconds) / 3600.0, 2) AS hours
FROM time_entries
GROUP BY user_id, work_day
ORDER BY work_day, user_name;
```

Entries by project:

```sql
SELECT project_name, count(*) AS entries,
       round(sum(duration_seconds) / 3600.0, 2) AS hours
FROM time_entries
GROUP BY project_id
ORDER BY hours DESC;
```

## Integrity verification

Every archive contains `SHA256SUMS` covering all generated files except `SHA256SUMS` itself:

```bash
cd clockify-your-workspace-20260925-150000
sha256sum -c SHA256SUMS
```

## Important limitations

Clockify exposes some data only when the corresponding feature is enabled and when the API key belongs to a sufficiently privileged user. The archive's `manifest.json` records warnings for feature-specific data that could not be retrieved.

The Clockify API currently documents paginated endpoints using `page`/`page-size` and a `Last-Page` response header. The tool honors that behavior and also stops safely when a short page is returned.

The deleted-entity API is marked experimental by Clockify. It is included because deleted objects can be important for a historical archive, but it can be disabled with `--no-deleted`.

Rates and monetary values are preserved as returned by Clockify. Consumers should not assume a particular currency minor-unit convention without checking the corresponding Clockify fields and workspace settings.

## CLI reference

```text
-w, --workspace        Workspace ID or exact name
--api-key              API key (prefer environment/config)
--base-url             API v1 base URL
--from                 Start date/time; default 1970-01-01
--to                   End date/time; default now
--no-raw               Omit raw JSON
--no-csv               Omit normalized CSV
--no-sqlite            Omit SQLite
--no-receipts          Do not download expense receipts
--no-deleted           Do not query deleted entities
--strict               Fail on unavailable optional endpoints
--zip                  Also create a ZIP copy beside the archive directory
--date-subdirs         Store exports below YEAR/MONTH/DAY directories
--csv-delimiter        ',', ';', or tab
--list-workspaces      List visible workspaces
--init-config [PATH]   Write example TOML config
-v, --verbose          Progress output
```

## Clockify API references

Implementation is based on Clockify API v1 documentation, including workspace, users, clients, projects, tasks, tags, time entries, custom fields, expenses, invoices, approvals, holidays, time off, balances, and deleted entities:

- https://docs.clockify.me/

## License

MIT. See `LICENSE`.

### Optional paid features and permissions

Some Clockify API endpoints depend on the workspace plan or on the API user's permissions. `clockify-archive` treats those endpoints as optional unless `--strict` is used. For repeated feature-level calls (for example project custom fields, time-off balances, and expense receipt downloads), an HTTP 401/402/403/405 is reported once and that feature is skipped for the remainder of the export. The archive continues with all other accessible data. Unavailable features are listed in `manifest.json` under `unavailable_optional_features`.

HTTP 404 responses are not cached as feature-wide failures because they can refer to a single project, policy, or attachment.

