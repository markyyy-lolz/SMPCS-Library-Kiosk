"""Verified release downloads and transactional application-folder updates."""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from urllib.request import Request, urlopen
import uuid
import zipfile

CACHE=Path(os.getenv('LOCALAPPDATA',str(Path.home()))) / 'SMPCS_Library' / 'updates'
MAX_ARCHIVE=300*1024*1024
MAX_EXPANDED=900*1024*1024

def sha256(path):
    digest=hashlib.sha256()
    with open(path,'rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):digest.update(chunk)
    return digest.hexdigest()

def checksum_for(text,name):
    for line in text.splitlines():
        fields=line.split()
        if len(fields)==2 and fields[1].lstrip('*')==name and re.fullmatch('[a-fA-F0-9]{64}',fields[0]):return fields[0].lower()
    raise ValueError('The release does not contain a valid checksum for the Windows package.')

def download(url,path,limit,progress=None):
    request=Request(url,headers={'User-Agent':'SMPCS-Library-Updater'})
    with urlopen(request,timeout=30) as response, open(path,'wb') as output:
        total=int(response.headers.get('Content-Length',0)); count=0
        if total>limit:raise ValueError('Update download exceeds the size limit.')
        while True:
            chunk=response.read(256*1024)
            if not chunk:break
            count+=len(chunk)
            if count>limit:raise ValueError('Update download exceeds the size limit.')
            output.write(chunk)
            if progress:progress(count,total)
        if total and count!=total:raise ValueError('Incomplete download. Please try again.')

def stage_release(release,progress=None):
    name=release['package_name']
    if not release.get('package_url'):raise ValueError('This release has no installable Windows package.')
    CACHE.mkdir(parents=True,exist_ok=True)
    folder=Path(tempfile.mkdtemp(prefix='download-',dir=CACHE))
    try:
        download(release['checksum_url'],folder/'SHA256SUMS.txt',128*1024)
        expected=checksum_for((folder/'SHA256SUMS.txt').read_text(encoding='utf-8-sig'),name)
        archive=folder/name
        download(release['package_url'],archive,MAX_ARCHIVE,progress)
        if sha256(archive)!=expected:raise ValueError('Checksum mismatch. The update was not installed.')
        validate_archive(archive)
        return {'archive':str(archive),'sha256':expected,'tag':release['tag'],'repository':release['repository']}
    except Exception:
        shutil.rmtree(folder,ignore_errors=True);raise

def validate_archive(archive):
    with zipfile.ZipFile(archive) as package:
        files=package.infolist()
        if len(files)>10000 or sum(f.file_size for f in files)>MAX_EXPANDED:raise ValueError('Update archive is too large.')
        seen=set()
        for entry in files:
            name=entry.filename
            parts=PurePosixPath(name).parts
            if PurePosixPath(name).as_posix()!=name.rstrip('/') or not parts or parts[0]!='SMPCS_Library' or '\\' in name or ':' in name or any(p in ('.','..') or p.endswith((' ','.')) for p in parts):
                raise ValueError('Unsafe path in update archive.')
            if any(re.fullmatch(r'(?i)(con|prn|aux|nul|com[1-9]|lpt[1-9])(\..*)?',p) for p in parts):raise ValueError('Invalid Windows path.')
            if stat.S_ISLNK(entry.external_attr>>16):raise ValueError('Symbolic links are not allowed in updates.')
            key=name.rstrip('/').lower()
            if key in seen:raise ValueError('Duplicate path in update archive.')
            seen.add(key)
        if 'smpcs_library/smpcs_library.exe' not in seen or not any(k.startswith('smpcs_library/_internal/') for k in seen):
            raise ValueError('This is not a complete Windows application package.')

def extract_verified(archive,expected,destination):
    if sha256(archive)!=expected:raise ValueError('Update checksum changed before installation.')
    validate_archive(archive)
    with zipfile.ZipFile(archive) as package:package.extractall(destination)
    return Path(destination)/'SMPCS_Library'

def new_process_env():
    env=os.environ.copy();env['PYINSTALLER_RESET_ENVIRONMENT']='1';return env

def prepare_helper(ready,target=None,parent_pid=None,launch=True):
    if target is None:
        if not getattr(sys,'frozen',False):raise ValueError('In-app installation is available in the Windows EXE build.')
        target=Path(sys.executable).resolve().parent
    target=Path(target).resolve()
    if not (target/'SMPCS_Library.exe').is_file():raise ValueError('The installed executable could not be found.')
    # A writable sibling is required for atomic folder replacement; never request elevation.
    with tempfile.TemporaryDirectory(prefix='.smpcs-write-test-',dir=target.parent):pass
    CACHE.mkdir(parents=True,exist_ok=True)
    helper=Path(tempfile.mkdtemp(prefix='helper-',dir=CACHE))
    shutil.copy2(target/'SMPCS_Library.exe',helper/'SMPCS_Library.exe')
    shutil.copytree(target/'_internal',helper/'_internal')
    request=dict(ready,target=str(target),parent_pid=parent_pid or os.getpid())
    manifest=helper/'request.json';manifest.write_text(json.dumps(request),encoding='utf-8')
    if launch:
        subprocess.Popen([str(helper/'SMPCS_Library.exe'),'--apply-update',str(manifest)],cwd=helper,
                         env=new_process_env(),creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    return manifest

def wait_for_exit(target,parent_pid,timeout=120):
    import psutil
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        running=psutil.pid_exists(parent_pid)
        for process in psutil.process_iter(['pid','exe'],ad_value=None):
            executable=process.info.get('exe')
            if executable and Path(executable).resolve().is_relative_to(target):running=True
        if not running:return
        time.sleep(.3)
    raise TimeoutError('Another copy of SMPCS Library is still open. Close both Admin and Kiosk, then retry the update.')

def replace_install(target,staged,probe):
    """Keep the previous folder; roll back any failed swap or startup probe."""
    target=Path(target);staged=Path(staged)
    backup=target.with_name(target.name+'.previous-'+uuid.uuid4().hex[:8])
    # Portable local overrides survive; normal settings already live in APPDATA.
    for name in ('.env','config.json','updates.json'):
        if (target/name).is_file():shutil.copy2(target/name,staged/name)
    target.rename(backup)
    try:
        staged.rename(target)
        probe(target)
    except Exception:
        if target.exists():target.rename(target.with_name(target.name+'.failed-'+uuid.uuid4().hex[:8]))
        backup.rename(target)
        raise
    return backup

def apply_request(path):
    CACHE.mkdir(parents=True,exist_ok=True)
    request=json.loads(Path(path).read_text(encoding='utf-8'))
    target=Path(request['target']).resolve()
    if target==Path(sys.executable).resolve().parent:raise ValueError('The update helper must run outside the installation folder.')
    if not (target/'SMPCS_Library.exe').is_file():raise ValueError('Installed application is missing.')
    wait_for_exit(target,int(request['parent_pid']))
    with tempfile.TemporaryDirectory(prefix='.smpcs-stage-',dir=target.parent) as staging:
        staged=extract_verified(Path(request['archive']),request['sha256'],staging)
        def probe(installed):
            with tempfile.TemporaryDirectory(prefix='smpcs-check-') as check:
                result=Path(check)/'startup.json';env=new_process_env();env['APPDATA']=check
                subprocess.run([str(installed/'SMPCS_Library.exe'),'--smoke-test',str(result)],env=env,cwd=check,check=True,timeout=120)
                report=json.loads(result.read_text())
                if not report.get('ok') or 'v'+report['version']!=request['tag']:raise ValueError('The updated application failed its startup check.')
        try:backup=replace_install(target,staged,probe)
        except Exception:
            if request.get('restart',True):subprocess.Popen([str(target/'SMPCS_Library.exe')],cwd=target,env=new_process_env())
            raise
    (CACHE/'last_update.json').write_text(json.dumps({'version':request['tag'],'backup':str(backup),'target':str(target)}))
    if request.get('restart',True):subprocess.Popen([str(target/'SMPCS_Library.exe')],cwd=target,env=new_process_env())
    return 0
