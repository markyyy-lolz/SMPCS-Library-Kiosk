# SMPCS Library 1.4.0

1. Download the Windows ZIP and use **Extract All** once.
2. Open **SMPCS_Library.exe** and choose Kiosk or Admin.
3. Keep the `_internal` folder beside the executable. No Python is needed.

## Future updates
Updates download automatically in the background. When ready, open **Updates** and click **Restart & Update**. On the kiosk, use **Settings → staff sign-in → GitHub updates**.

The app verifies the checksum, keeps a backup, installs and restarts automatically. It will not restart in the middle of a kiosk transaction. Close other copies of this installation when updating. Keep the application in a writable folder such as your own Documents folder.

Your connection settings and credentials remain in your Windows profile. The old version stays in a neighboring `.previous-*` folder, and a failed startup test restores it automatically.

**Versions before 1.4.0 need this ZIP installed once.** They only had update checking, so they cannot automatically install the new updater.

The source ZIP is for developers; install Python and run `install.bat` only if you deliberately choose the source version.
