# Windows EXE release 1.2.1

Download **SMPCS_Library.exe** from GitHub Releases and open it. Choose **Go to Kiosk** or **Go to Admin**. No Python installation is needed. Settings and credentials stay in your Windows profile. The instructions below apply only when running the optional Python source ZIP.

# SMPCS Library 1.2.0

## Start without a terminal
1. Extract the entire ZIP into a writable folder.
2. Run `install.bat` once (Python 3 for Windows is required). Installation shows its progress in a terminal.
3. Double-click `Start_App.vbs`, then choose **Go to Kiosk** or **Go to Admin**. These launch with Python's windowless interpreter.

The old `run_admin.bat` and `run_kiosk.bat` now hand off to the hidden launcher, but Windows may briefly flash a command window when opening a BAT file. Use the VBS launchers for no terminal flash. If Windows disables VBScript, use the `.venv\Scripts\pythonw.exe` interpreter with `launch.pyw admin` or `launch.pyw kiosk` in a Windows shortcut.

## Configure GitHub updates
Open `Update_Settings.vbs`, or use **Updates → Update settings / Check now** in the admin app.
Paste your public GitHub repository URL, enable automatic checks, and click **Save and check now**.
The default update source is `markyyy-lolz/SMPCS-Library-Kiosk`. No URL entry is required on a fresh installation. If you previously saved a blank repository, enter this repository once in Update Settings.
Settings are shared by the admin and kiosk for the current Windows account.

Checks run four seconds after the main window opens and every six hours while running. They use a background worker with a network timeout. New stable releases appear in the admin update window. The kiosk only shows a status notice, so students are not interrupted. Offline failures leave the app running; use a manual check to see the error.

**This version checks and notifies; it does not download, install, or restart automatically.** Click **Open latest GitHub release** to get the release. Close both apps before manually replacing application files. Preserve local configuration and `.env`; rerun `install.bat` if requirements change. Existing database setup and credentials are not changed by this update checker.

## Publish future releases
- Use public GitHub Releases with stable tags such as `v1.1.1`, `v1.2.0`, or `v2.0.0`.
- Update `VERSION` in `shared/updates.py` for each new build.
- Attach your distributable ZIP to the release. Drafts and prereleases are not offered.
- No GitHub access token is needed; private repositories are not supported.
- Optional: set the repository in `update_settings.json` before distribution. Saved per-user settings override this default.
- Keep `.env`, local credentials, logs, `.venv`, and `__pycache__` out of your public repository and public release ZIP. Public release packages omit `.env` and local credentials.

GitHub API reference: https://docs.github.com/en/rest/releases/releases#get-the-latest-release

## Troubleshooting
Logs are written to `%APPDATA%\SMPCS_Library\logs` and rotated at 2 MB with three backups per app. Startup failures show a dialog even without a terminal. Update settings are stored separately in `%APPDATA%\SMPCS_Library\updates.json`.

## Changes
- Windowless admin, kiosk, and update-settings launchers.
- Background GitHub release checks and numeric version comparisons.
- Manual check and automatic-check toggle.
- Non-interrupting kiosk update notice.
- Rotating error logs, including exceptions previously printed only to the terminal.
- Isolated dependency installer with failure reporting.

The existing interface, database calls, borrowing workflow, and RFID behavior are retained.

## Kiosk settings
Use the **Settings** button at the bottom of the kiosk. Sign in with your existing librarian/admin account to change full-screen mode, animations, GitHub update settings, or the station connection. Settings are available between transactions; RFID capture is paused while the settings dialogs are open and restored afterward.
