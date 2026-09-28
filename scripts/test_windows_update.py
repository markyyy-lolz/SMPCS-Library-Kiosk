"""Exercise the real frozen updater against a disposable installation."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from shared import installer
from shared.updates import VERSION
with tempfile.TemporaryDirectory(prefix='smpcs-update-ci-') as work:
    root=Path(work);target=root/'installed'
    shutil.copytree(ROOT/'dist/SMPCS_Library',target)
    (target/'.env').write_text('# preserved local settings\n')
    installer.CACHE=root/'cache'
    archive=ROOT/f'dist/SMPCS_Library_Windows_v{VERSION}.zip'
    ready={'archive':str(archive),'sha256':installer.sha256(archive),'tag':'v'+VERSION,'repository':'markyyy-lolz/SMPCS-Library-Kiosk'}
    manifest=installer.prepare_helper(ready,target=target,parent_pid=-1,launch=False)
    request=json.loads(manifest.read_text());request['restart']=False;manifest.write_text(json.dumps(request))
    env=installer.new_process_env();env['APPDATA']=str(root/'appdata');env['LOCALAPPDATA']=str(root/'local')
    subprocess.run([str(manifest.parent/'SMPCS_Library.exe'),'--apply-update',str(manifest)],env=env,check=True,timeout=180)
    assert (target/'SMPCS_Library.exe').exists()
    assert (target/'.env').read_text()=='# preserved local settings\n'
    assert list(root.glob('installed.previous-*'))
    print('Frozen Windows updater passed: checksum, extraction, folder replacement, startup probe, backup, config preservation.')
