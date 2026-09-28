"""Build and smoke-test a single windowless Windows executable."""
from pathlib import Path
import hashlib
import json
import os
import subprocess
import sys
import tempfile

ROOT=Path(__file__).resolve().parent.parent
if sys.platform!='win32': raise SystemExit('Build this executable on Windows.')
os.chdir(ROOT)
subprocess.run([sys.executable,'-m','PyInstaller','--noconfirm','--clean','--onefile',
    '--windowed','--name','SMPCS_Library','--icon','assets/school_logo.png',
    '--add-data','assets:assets','--add-data','update_settings.json:.',
    'launch.pyw'],check=True)
exe=ROOT/'dist/SMPCS_Library.exe'
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
with (ROOT/'dist/SHA256SUMS.txt').open('a',encoding='utf-8') as stream:
    stream.write(hashlib.sha256(exe.read_bytes()).hexdigest()+'  '+exe.name+'\n')
print(f'Built and tested {exe.name}: {exe.stat().st_size:,} bytes')
