"""Use the same human-readable notes in the app and on GitHub Releases."""
from pathlib import Path
import sys
root=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(root))
from shared.updates import VERSION
from shared.changelog import CURRENT_CHANGES
(root/'dist/RELEASE_NOTES.md').write_text('SMPCS Library v'+VERSION+'\n\n'+CURRENT_CHANGES+'\n\nINSTALLATION\nExisting users: Updates / Repair → Check for updates → Restart & Update.\nFirst installation: extract the complete Windows ZIP, then open SMPCS_Library.exe. Keep _internal beside it. Windows 10/11 x64.\nSee SCAN_REPORT.txt and SHA256SUMS.txt for build verification.\n',encoding='utf-8')
