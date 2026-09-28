# SMPCS Library Kiosk

RFID library attendance, book borrowing and returns, with separate admin and kiosk apps for St. Martin de Porres Catholic School.

## Install on Windows
1. Download and extract the ZIP from [Releases](https://github.com/markyyy-lolz/SMPCS-Library-Kiosk/releases/latest).
2. Install Python 3, then run `install.bat` once.
3. Open `Start_App.vbs` and choose **Go to Kiosk** or **Go to Admin** for terminal-free startup.
4. Complete the existing Supabase setup when prompted. See `START_HERE.md` for details.

The app checks this repository for stable releases at startup and every six hours. The admin Updates menu also supports manual checks. Checks notify only; download and install updates manually after closing both apps.

## Development and releases
Run `python -m unittest discover -s tests -v`.
Push a new numeric `VERSION` in `shared/updates.py` to `main` to publish the next release. GitHub Actions tests the code, packages an explicit list of application files, and publishes a ZIP with a SHA-256 checksum. Existing release versions are not overwritten. The workflow can also be run from the Actions tab.

Do not commit `.env`, credentials, local configuration, or student records. `.env.example` contains blank placeholders only. Database schema is in `SMPCS_LIBRARY_FULL_DATABASE.sql`.

This is Python source distribution, not a compiled EXE. Windows hardware and live database testing must be performed on the deployment PC.

## Kiosk settings
Use the **Settings** button at the bottom of the kiosk. Sign in with your existing librarian/admin account to change full-screen mode, animations, GitHub update settings, or the station connection. Settings are available between transactions; RFID capture is paused while the settings dialogs are open and restored afterward.
