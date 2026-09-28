# Windows release 1.3.1

Download **SMPCS_Library_Windows_v1.3.1.zip** from GitHub Releases. Extract the entire ZIP and open **SMPCS_Library.exe** inside. Keep the `_internal` folder beside the EXE. No Python installation is needed.

The new package uses an application folder instead of extracting bundled executable files into a temporary folder on every launch. UPX is disabled. This may reduce packaging-related false positives but does not establish the cause of a reported detection. The build remains unsigned. Keep antivirus enabled and read `SCAN_REPORT.txt` for the actual scan outcome. If it is still blocked, provide the antivirus product and exact detection name for investigation.

# SMPCS Library Kiosk

RFID library attendance, book borrowing and returns, with separate admin and kiosk apps for St. Martin de Porres Catholic School.

## Run on Windows 10/11 (64-bit)
Download **SMPCS_Library.exe** from [Releases](https://github.com/markyyy-lolz/SMPCS-Library-Kiosk/releases/latest), then double-click it. Choose **Go to Kiosk** or **Go to Admin**. No Python installation or BAT file is required. Complete the existing database/station setup if this PC has not been configured before.

The app checks this repository for stable releases at startup and every six hours. The admin Updates menu also supports manual checks. Checks notify only; download and install updates manually after closing both apps.

## Development and releases
Run `python -m unittest discover -s tests -v`.
Push a new numeric `VERSION` in `shared/updates.py` to `main` to publish the next release. GitHub Actions tests the code, packages an explicit list of application files, and publishes a ZIP with a SHA-256 checksum. Existing release versions are not overwritten. The workflow can also be run from the Actions tab.

Do not commit `.env`, credentials, local configuration, or student records. `.env.example` contains blank placeholders only. Database schema is in `SMPCS_LIBRARY_FULL_DATABASE.sql`.

The release includes a standalone Windows EXE plus an optional source ZIP. The EXE is built and smoke-tested on Windows, including both setup screens and bundled assets. Live RFID/database/printing tests must be performed on the deployment PC.

## Kiosk settings
Use the **Settings** button at the bottom of the kiosk. Sign in with your existing librarian/admin account to change full-screen mode, animations, GitHub update settings, or the station connection. Settings are available between transactions; RFID capture is paused while the settings dialogs are open and restored afterward.

## New in 1.3.0
- Consistent light theme for kiosk, admin, setup and update dialogs, even when Windows uses dark mode.
- Redesigned kiosk home with four large service cards and a visible registration entry.
- Light admin navigation and scrollable pages for smaller screens.
- Attendance history with Philippine date boundaries, IN/OUT filters, search and CSV export (up to 10,000 records per date range).
- Page refresh, export-visible-table and overdue-loan shortcuts. CSV exports preserve visible filters and neutralize spreadsheet formulas.

Attendance uses the existing `library_attendance` and `library_members` tables; no schema migration is required.
