"""Build and smoke-test a windowless Windows application folder."""
from pathlib import Path
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import shutil
import zipfile

ROOT=Path(__file__).resolve().parent.parent
if sys.platform!='win32': raise SystemExit('Build this executable on Windows.')
os.chdir(ROOT)
subprocess.run([sys.executable,'-m','PyInstaller','--noconfirm','--clean','--onedir','--noupx',
    '--collect-submodules','reportlab.graphics.barcode',
    '--windowed','--name','SMPCS_Library','--icon','assets/school_logo.png',
    '--add-data','assets:assets','--add-data','update_settings.json:.',
    'launch.pyw'],check=True)
exe=ROOT/'dist/SMPCS_Library/SMPCS_Library.exe'
import pefile
pe=pefile.PE(str(exe)); assert pe.OPTIONAL_HEADER.Subsystem==2, 'Executable must have no console'; pe.close()
with tempfile.TemporaryDirectory() as folder:
    result=Path(folder)/'startup.json'
    env=os.environ.copy(); env['APPDATA']=folder
    try:
        subprocess.run([str(exe),'--smoke-test',str(result)],cwd=folder,env=env,check=True,timeout=120)
        report=json.loads(result.read_text()); assert report['ok']
        print(json.dumps(report))
    except Exception:
        for log in Path(folder).rglob('*.log'):
            print(log.read_text(errors='replace'))
        raise
sys.path.insert(0,str(ROOT))
from shared.updates import VERSION
app_folder=exe.parent
(app_folder/'READ_ME.txt').write_text('Extract the whole ZIP, then open SMPCS_Library.exe. Keep the _internal folder beside the EXE. No Python installation is needed. This build is unsigned; keep antivirus enabled. Settings are stored in your Windows profile.\n')
shutil.copytree(ROOT/'migrations',app_folder/'migrations',dirs_exist_ok=True)
shutil.copy2(ROOT/'START_HERE.md',app_folder/'START_HERE.md')
shutil.copy2(ROOT/'Open_Updates.vbs',app_folder/'Open_Updates.vbs')
shutil.copy2(ROOT/'Open_Updates.vbs',ROOT/'dist/Open_Updates.vbs')
shutil.copy2(ROOT/'migrations/002_accounts_services.sql',ROOT/'dist/002_accounts_services.sql')
for migration in (ROOT/'migrations').glob('*.sql'):shutil.copy2(migration,ROOT/'dist'/migration.name)
archive=ROOT/f'dist/SMPCS_Library_Windows_v{VERSION}.zip'
with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as package:
    for path in sorted(app_folder.rglob('*')):
        if path.is_file():package.write(path,Path(app_folder.name)/path.relative_to(app_folder))
print(f'Built and tested {archive.name}: {archive.stat().st_size:,} bytes')
