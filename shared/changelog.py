"""Release notes bundled with the installed application for offline reading."""
CURRENT_CHANGES = '''LIBRARY SUITE — v1.6.0
SETUP REQUIRED
• Apply migrations/003_library_suite.sql in Supabase SQL Editor after migration 002.
• Sign in again after applying the migration. Existing records are retained.

ADMIN
• Library Services center with clickable notifications and request queues.
• Approve real kiosk registrations, book reservations and renewal requests.
• Search member/staff accounts, reset PINs and confirm account deactivation.
• Replace lost RFID cards, retire old cards, promote sections and archive graduates.
• Preview CSV/Excel imports with duplicate validation and atomic saving.
• Administrator, librarian and read-only assistant roles checked on the server.
• Manage book covers, shelf locations, expiring announcements and maintenance mode.
• Date-filtered attendance/loan/return/overdue reports with PDF, Excel and CSV export.
• Printable borrowing receipt PDFs; lost/damaged book remarks and resolution tracking.
• Inventory sessions show found, misplaced and unscanned catalog records.
• Backup center with restore preview, confirmation and automatic recovery snapshots.

MY ACCOUNT / KIOSK
• Find books with covers, shelf details and copy availability.
• Reserve unavailable books and track your queue position.
• Request borrowing extensions; send feedback and view librarian responses.
• Due-today, due-tomorrow and days-overdue reminders.
• Visible privacy countdown with Continue session before automatic sign-out.
• Announcements and maintenance notices; clearer attendance-sync status.

UPDATES & SUPPORT
• Download percentage, Restart later and local installed-version history.
• What's new still appears immediately after admin login.
• Copy diagnostic/error reports without passwords, tokens or member records.

NOTES
• Inventory scans identify catalog records; verify multi-copy counts physically.
• Backups restore operational records, not passwords, PINs or database schema.
• Restores merge by record ID, retain newer records and recalculate available stock.'''
