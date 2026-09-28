"""Build a credential-free source release from an explicit file allowlist."""
from pathlib import Path
import hashlib
import json
import re
import sys
import zipfile
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from shared.updates import VERSION
assert re.fullmatch(r'\d+\.\d+\.\d+', VERSION)
files = ['README.md', 'START_HERE.md', '.env.example', 'requirements.txt',
         'install.bat', 'run_admin.bat', 'run_kiosk.bat', 'launch.pyw',
         'Start_App.vbs', 'Start_Admin.vbs', 'Start_Kiosk.vbs', 'Update_Settings.vbs',
         'update_settings.json', 'SMPCS_LIBRARY_FULL_DATABASE.sql', 'assets/school_logo.png']
for folder in ('admin', 'kiosk', 'shared', 'tests'):
    files += [str(p.relative_to(ROOT)).replace('\\', '/') for p in (ROOT/folder).rglob('*.py')]
output = ROOT/'dist'
output.mkdir(exist_ok=True)
archive = output/f'SMPCS_Library_v{VERSION}.zip'
with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as z:
    for name in sorted(files):
        z.write(ROOT/name, f'SMPCS_Library/{name}')
digest = hashlib.sha256(archive.read_bytes()).hexdigest()
(output/'SHA256SUMS.txt').write_text(f'{digest}  {archive.name}\n')
with zipfile.ZipFile(archive) as z:
    assert z.testzip() is None
    assert all(Path(name).name != '.env' for name in z.namelist())
print(json.dumps({'version':VERSION, 'archive':str(archive), 'files':len(files)}))
