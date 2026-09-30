# v1.6.0 Library Suite setup

Existing v1.5 users: run `migrations/003_library_suite.sql` once in your Supabase SQL Editor, then sign in again. This adds the new services and preserves existing records. Keep a database backup before changing your live schema. New installations use the base database, then 002, then 003, in that order. Do not run an older migration on top of the latest one.

The Windows app is updated through **Updates / Repair → Check for updates → Restart & Update**. SQL migration is a separate, one-time database step. No database administrator secret is embedded in the app.

## Where to find the new features

- **Admin → Library Services**: notifications, request approvals, member tools, CSV/Excel import, book covers/shelves, announcements, maintenance, reports, receipts, inventory, backups and diagnostics.
- **Admin → Accounts & Services → Staff accounts**: administrator, librarian or read-only assistant roles. Staff-management and station configuration require administrator access.
- **Kiosk → Register here**: submits an approval request. After approving it, the librarian assigns a PIN under Member management → Access / PIN.
- **Kiosk → My Account**: RFID + PIN, borrowing history, due-date reminders, catalog, reservations, renewals, feedback and request status.
- **Updates**: live download progress, Restart later, version history and What's new. History dates show the first launch of each installed version.

Reservation approval means the librarian has physically handed over the book; it creates a seven-day loan. Renewals take effect only after approval and are blocked when a reservation is waiting. Inventory tracks catalog records, not separate copies under the same RFID; manually verify multi-copy counts. Reports reject more than 10,000 results so you can narrow the dates rather than unknowingly export a partial report.

Imports add new records only, with an all-or-nothing transaction. Download a template first. Keep identifiers as text in Excel to preserve leading zeros. Use Member management to select multiple members for promotion or graduate archiving. Archived members retain their history.

Operational backups include members, books, loans, attendance, return requests and suite data. They exclude passwords, PINs, station credentials and schema. Restore merges records by ID, retains records created later, recalculates stock and signs out member sessions. A server recovery snapshot is created before each restore; seven are retained. Disable maintenance mode before restoring borrowing records. Use your database provider's backup tools for complete database disaster recovery.

---

# SMPCS Library 1.5.4

1. Download the Windows ZIP and use **Extract All** once.
2. Open **SMPCS_Library.exe** and choose Kiosk or Admin.
3. Keep the `_internal` folder beside the executable. No Python is needed.

## Future updates
Updates download automatically in the background. When ready, open **Updates** and click **Restart & Update**. On the kiosk, use **Settings → staff sign-in → GitHub updates**.

The app verifies the checksum, keeps a backup, installs and restarts automatically. It will not restart in the middle of a kiosk transaction. Close other copies of this installation when updating. Keep the application in a writable folder such as your own Documents folder.

Your connection settings and credentials remain in your Windows profile. The old version stays in a neighboring `.previous-*` folder, and a failed startup test restores it automatically.

**Versions before 1.4.0 need this ZIP installed once.** They only had update checking, so they cannot automatically install the new updater.

The source ZIP is for developers; install Python and run `install.bat` only if you deliberately choose the source version.

## Enable the new account and library features
1. Update all PCs to v1.5.0. Existing v1.4.0 users can use Restart & Update.
2. In your Supabase project, back up the database, open SQL Editor, paste `migrations/002_accounts_services.sql` from this folder and click Run once.
3. Reopen the app and sign in to Admin. Select a member in Members → Account access / PIN and assign their PIN.
4. On the kiosk choose My Account, tap the member card and enter that PIN.
5. Confirm book returns in Admin → Accounts & Services → Pending book returns.

New services require the migration. Database changes are not applied by the app updater. The migration blocks older clients from using legacy login/member-write/direct-return endpoints, so upgrade the PCs together.

## Cannot sign in after the database migration?
Do not undo the database permissions or reset your password for `permission denied for function library_login`.
- On 1.5.2 and later, choose **Updates / Repair** on the opening screen or librarian login. No Supabase sign-in is required.
- On 1.4.0/1.5.0, close the app, then run `SMPCS_Library.exe updates`. You can also place the release's `Open_Updates.vbs` beside `SMPCS_Library.exe` and double-click it. This only opens the existing updater; no Python or terminal is needed.
- Choose **Save and check now**, wait for the download, then **Restart & Update**. Close other copies of the old app first.
- Versions older than 1.4.0 need the current Windows ZIP once.
The database migration is not needed again if it has already been applied.

## v1.5.3 layout and attendance fix
Use Updates / Repair → Check for updates → Restart & Update. No new SQL migration is needed for this release.
My Account now has separate Borrowing history and Change PIN tabs. The history page includes title search, status filters and summary counts; the PIN keypad appears only on PIN screens. Dialog controls are grouped and tables use the available space.
Attendance uses the existing member_no column and supports legacy student_id-only schemas. Load failures appear above the table with a retry instruction.

## v1.5.4 — account styling and update notes
The account screen has a blue profile header, separate summary cards, balanced table columns and colored loan status badges. Updates / Repair now shows What's new for the installed version offline and retrieves the available release's notes when checking GitHub. No new SQL migration is required. Users on older versions get the in-app notes panel after installing v1.5.4.
