# SMPCS Library Kiosk

Blue-themed RFID library kiosk and staff administration for SMPCS.

## First installation on Windows 10/11 x64
Download the **Windows ZIP** from [Releases](https://github.com/markyyy-lolz/SMPCS-Library-Kiosk/releases/latest), extract the entire folder, and open **SMPCS_Library.exe**. Keep `_internal` beside the executable. No Python installation is needed.

Choose **Go to Kiosk** or **Go to Admin**. Existing database and station settings are reused from your Windows profile. New PCs complete the setup screen.

## Updates from version 1.4.0 onward
The app checks at startup and every six hours. New Windows packages download in the background and are verified against the release's SHA-256 checksum. Open **Updates** (or **Kiosk Settings → GitHub updates**) and click **Restart & Update**. No GitHub page, manual extraction, or file copying is needed for later releases.

The helper waits for open copies of this installation to close, backs up the old application folder, replaces the files, tests the new build, then reopens the chooser. A failed startup test triggers rollback. Database credentials/settings remain in your Windows profile; portable `.env`/configuration files are preserved too. Backups remain in a sibling `.previous-*` folder. The installation folder and its parent must be writable; the app does not elevate privileges. Finish active transactions before restarting.

Older versions cannot install this updater themselves: install **1.4.0 once** using the ZIP. Thereafter use in-app updates. Source Python runs continue to support checks; in-app installation is for the Windows EXE distribution.

## Features
- Original kiosk layout with blue styling, registration, attendance, borrowing/returns and USB printing.
- Staff-protected kiosk settings, full-screen and animation controls.
- Admin attendance history with date/action/search filters and CSV export.
- Page refresh, export visible tables and overdue-loan shortcuts.
- Windowless application and rotating logs in `%APPDATA%\SMPCS_Library\logs`.

## Release integrity
The Windows app uses a normal folder bundle with UPX disabled. The release includes `SHA256SUMS.txt`, `SCAN_REPORT.txt` and build dependency versions. The application is unsigned. A checksum verifies downloaded bytes against the selected GitHub release; it is not a publisher signature. Keep antivirus enabled.

## Development
Install `requirements.txt`, then run `python -m unittest discover -s tests -v`. Run `launch.pyw` for the chooser. Build on Windows using `requirements-build.txt` and `scripts/build_windows.py`. GitHub Actions runs tests, builds the EXE, tests the actual update helper on a disposable installation, records Defender scan status and publishes a release when `VERSION` in `shared/updates.py` changes.

Never commit `.env`, local credentials or student data.

## Version 1.5.0: accounts and library services
Apply `migrations/002_accounts_services.sql` once in your Supabase project's SQL Editor. Take a Supabase backup first. This additive migration preserves existing records, adds session/PIN/return/offline tables, and restricts old unauthenticated login, member-write and direct-return RPCs. Upgrade all PCs to 1.5.0 alongside this migration; older clients cannot use those restricted operations afterward. No database credentials or service-role keys are included in the app or release.

- **Kiosk → My Account:** tap RFID, enter the PIN assigned by a librarian, view profile, borrowing history and overdue reminders, and change PIN. The screen signs out after two minutes. Identity/RFID corrections remain staff-controlled.
- **Admin → Members:** select a member, then **Account access / PIN** to activate/deactivate or set/reset a 6–12 digit PIN. Name, grade, section and RFID are edited in the existing member form.
- **Admin → Accounts & Services:** administrators can create/edit staff, assign admin/librarian roles, reset passwords and disable accounts. Self-disable/self-demotion is blocked. Account writes and permissions are checked in the database. Five failed sign-ins lock that identity for 15 minutes.
- **Return requests:** scan the card and book at the kiosk, then hand over the book. Staff approve/reject in Accounts & Services; stock and loan status change only after approval.
- **Offline attendance:** select Attendance before tapping. Scans persist in a local SQLite outbox and retry every 30 seconds while the kiosk is online and idle. Original timestamps and unique event IDs survive restarts and lost responses. Duplicate taps within ten seconds are ignored. Unknown/inactive cards, scans older than 30 days, or late scans conflicting with newer records are retained for staff review. Staff can retry/export through Kiosk Settings → Attendance sync queue. Offline capture is pending verification, not proof that the card is authorized. Other kiosk services require internet.
- **Backups:** while an administrator is signed in, save one operational JSON snapshot per UTC day, keeping seven snapshots in `%APPDATA%/SMPCS_Library/backups`. Manual backup lets you select another folder. Includes members, catalog, loans, attendance and return requests. Does not contain credentials, PIN/password hashes, database schema or storage files. Recovery requires a database administrator; retain Supabase backups for full recovery. Copy operational snapshots off the PC for protection against disk failure.

The shipped schema is used for isolated PostgreSQL integration tests. Your live Supabase deployment is not modified or tested by this release pipeline. Apply the migration and verify with a test member before regular use.
