"""Release notes bundled for offline reading and the admin login update dialog."""
CURRENT_CHANGES = '''LIBRARY OPERATIONS — v1.7.0
ONE-TIME DATABASE SETUP
• Apply migrations/20260930115934_library_operations.sql after migration 003.
• Take a database backup first; update every kiosk and sign in again.
• Verify generated physical copies in Library Services → Physical copies & repairs.
  Existing loans are retained; generated accession/RFID assignments need a physical check.

CIRCULATION
• School calendar moves due dates to open days and blocks closed return dates.
• Borrowing limits, loan duration and overdue blocking by member type.
• Member clearance shows outstanding loans and unresolved incidents; export PDF.
• Individual copies track accession, RFID, condition, loan history and inventory scans.
• Reservations get pickup deadlines and advance to the next member after expiry.
• Quarantine damaged copies during repair; return them to circulation after verification.
• Print PDF shelf/spine, accession, QR and barcode labels for selected copies.

ADMIN
• Search members, books, copies and loans from one place; save filters per staff account.
• Preview duplicate member/book merges before typed confirmation; source records are archived.
• Review requested book acquisitions through Under review, Ordered and Added.
• Maintain subject/grade reading lists available in member accounts.
• Attendance-based occupancy with capacity and stale time-in review.
• Class visit bookings reject overlapping schedules and closed dates.
• Attendance corrections require reasons; changes retain an audit record.
• Member profile corrections need librarian approval.
• Staff handover notes and completion tracking.
• Daily closing summaries with PDF/Excel export and saved snapshots.

MY ACCOUNT / KIOSK & UPDATES
• My Account → Library services: acquisitions, profile/attendance corrections,
  request status, reading lists and clearance.
• Accessibility: larger text/buttons, high contrast and optional system voice guidance.
• Scheduled installation of verified updates within an optional maintenance window.
  Waits for 5 minutes idle, no active member, no dialog and no database work.
• Blue theme, single Admin/Kiosk launcher and windowless Windows EXE retained.

BACKUPS
• v3 operational backups include the new copy and operations tables.
• Restore is for the same configured database; staff accounts, credentials and schema
  remain outside the operational snapshot. Use a full database backup for disaster recovery.
• Older operational snapshots must be restored on a pre-v1.7 database, then migrated.
• Occupancy is an attendance estimate; review stale entries before relying on it.'''
