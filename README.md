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
