# Changelog

## 0.1.1

- Cache optional-feature access failures during an export.
- After the first HTTP 401/402/403/405 for a repeated optional feature, skip later calls for that feature.
- Prevent per-project custom-field warnings from flooding the console.
- Apply the same behavior to repeated time-off balance and expense-receipt calls.
- Record unavailable optional features in `manifest.json`.

## 0.1.0 - 2026-09-25

- Initial release.
- Raw JSON, normalized CSV, and SQLite archive formats.
- `clockify-import`-compatible 14-column CSV.
- Workspace/user/client/project/task/tag/custom-field export.
- Time entries across all workspace users.
- Best-effort expenses, receipts, invoices, approvals, holidays, and time-off export.
- Optional experimental deleted-entity export.
- SHA-256 manifest for archive integrity.
