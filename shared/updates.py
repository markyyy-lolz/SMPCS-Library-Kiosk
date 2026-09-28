"""Non-blocking GitHub release checks; no running files are overwritten."""
import json
import os
import queue
import re
import threading
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

VERSION = '1.4.0'
ROOT = Path(__file__).resolve().parent.parent
SETTINGS = Path(os.getenv('APPDATA', str(Path.home()))) / 'SMPCS_Library' / 'updates.json'

def normalize_repo(value):
    value = value.strip().rstrip('/')
    if value.startswith('https://github.com/'):
        value = value[len('https://github.com/'):]
    if value.endswith('.git'): value = value[:-4]
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9_.-]+', value):
        raise ValueError('Enter owner/repository or https://github.com/owner/repository.')
    return value

def version_tuple(value):
    match = re.fullmatch(r'v?(\d+)\.(\d+)\.(\d+)', value.strip())
    if not match:
        raise ValueError('Release tags must use major.minor.patch, for example v1.1.1.')
    return tuple(map(int, match.groups()))

def read_settings():
    for path in (SETTINGS, ROOT / 'update_settings.json'):
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
            return {'repository': normalize_repo(data['repository']) if data.get('repository') else '',
                    'enabled': data.get('enabled', True) is True, 'auto_download': data.get('auto_download',True) is True}
        except (OSError, ValueError, KeyError, TypeError, AttributeError): pass
    return {'repository': '', 'enabled': True, 'auto_download':True}

def write_settings(repo, enabled, auto_download=True):
    data = {'repository': normalize_repo(repo) if repo.strip() else '', 'enabled': bool(enabled), 'auto_download':bool(auto_download)}
    SETTINGS.parent.mkdir(parents=True, exist_ok=True)
    temp = SETTINGS.with_suffix('.tmp')
    temp.write_text(json.dumps(data, indent=2), encoding='utf-8')
    temp.replace(SETTINGS)

def fetch_release(repo, opener=urlopen):
    repo = normalize_repo(repo)
    request = Request(f'https://api.github.com/repos/{repo}/releases/latest', headers={
        'Accept': 'application/vnd.github+json', 'User-Agent': f'SMPCS-Library/{VERSION}',
        'X-GitHub-Api-Version': '2022-11-28'})
    try:
        with opener(request, timeout=12) as response:
            data = json.loads(response.read(2_000_000).decode('utf-8'))
    except HTTPError as exc:
        if exc.code == 404:
            raise ValueError('No public stable release found. Check the repository and publish a release.') from exc
        if exc.code in (403, 429):
            raise ValueError('GitHub temporarily limited requests. Try again later.') from exc
        raise ValueError(f'GitHub returned HTTP {exc.code}. Try again later.') from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise ValueError('Cannot reach GitHub. The app can still be used; try again later.') from exc
    if not isinstance(data, dict) or data.get('draft') or data.get('prerelease'):
        raise ValueError('No stable release is available.')
    tag = data.get('tag_name', '')
    newer = version_tuple(tag) > version_tuple(VERSION)
    version='.'.join(str(v) for v in version_tuple(tag))
    name=f'SMPCS_Library_Windows_v{version}.zip'
    names={a.get('name') for a in data.get('assets',[]) if isinstance(a,dict)}
    base=f'https://github.com/{repo}/releases/download/{tag}'
    return {'newer':newer,'tag':tag,'repository':repo,'url':f'https://github.com/{repo}/releases/latest',
            'package_name':name,'package_url':base+'/'+name if name in names and 'SHA256SUMS.txt' in names else '',
            'checksum_url':base+'/SHA256SUMS.txt'}

def attach_updates(window, kiosk=False):
    import sys
    from PyQt6.QtCore import QObject,QTimer,QThread,Qt
    from PyQt6.QtWidgets import QApplication,QDialog,QVBoxLayout,QLabel,QLineEdit,QCheckBox,QPushButton,QProgressBar
    from shared.installer import stage_release,prepare_helper
    from shared.theme import LIGHT_QSS

    class Controller(QObject):
        def __init__(self):
            super().__init__(window)
            self.events=queue.Queue();self.busy=False;self.dialog=None;self.ready=None;self.release=None
            self.last='Checks and downloads run in the background. Restart when you are ready.'
            self.percent=0;self.paused=[]
            self.poll=QTimer(self);self.poll.timeout.connect(self.finish);self.poll.start(150)
            self.schedule=QTimer(self);self.schedule.timeout.connect(self.automatic);self.schedule.start(6*60*60*1000)
            QTimer.singleShot(4000,self.automatic)
            if not kiosk:window.menuBar().addMenu('Updates').addAction('Update settings / Check now',self.show_settings)

        def automatic(self):
            cfg=read_settings()
            if cfg['enabled'] and cfg['repository'] and not self.busy:self.check(False)

        def refresh(self):
            if self.dialog:
                self.label.setText(self.last)
                self.progress.setValue(self.percent)
                self.install_btn.setEnabled(bool(self.ready) and not self.busy)
                self.download_btn.setEnabled(bool(self.release and self.release.get('package_url')) and not self.busy and not self.ready)
                self.check_btn.setEnabled(not self.busy)

        def show_settings(self):
            if self.dialog:self.dialog.show();self.dialog.raise_();return
            dlg=self.dialog=QDialog(window);dlg.setStyleSheet(LIGHT_QSS);dlg.resize(620,470)
            dlg.setWindowTitle('SMPCS Library — Automatic Updates')
            layout=QVBoxLayout(dlg);layout.addWidget(QLabel(f'Installed version: {VERSION}'))
            cfg=read_settings();layout.addWidget(QLabel('GitHub update repository'))
            self.repo=QLineEdit(cfg['repository']);layout.addWidget(self.repo)
            self.enabled=QCheckBox('Check at startup and every 6 hours');self.enabled.setChecked(cfg['enabled']);layout.addWidget(self.enabled)
            self.auto_download=QCheckBox('Automatically download verified Windows updates');self.auto_download.setChecked(cfg['auto_download']);layout.addWidget(self.auto_download)
            self.label=QLabel(self.last);self.label.setWordWrap(True);self.label.setTextFormat(Qt.TextFormat.PlainText);layout.addWidget(self.label)
            self.progress=QProgressBar();self.progress.setRange(0,100);layout.addWidget(self.progress)
            save=QPushButton('Save settings');save.clicked.connect(self.save);layout.addWidget(save)
            self.check_btn=QPushButton('Save and check now');self.check_btn.clicked.connect(self.manual);layout.addWidget(self.check_btn)
            self.download_btn=QPushButton('Download update');self.download_btn.clicked.connect(self.download_now);layout.addWidget(self.download_btn)
            self.install_btn=QPushButton('Restart & Update');self.install_btn.clicked.connect(self.install);layout.addWidget(self.install_btn)
            note=QLabel('Your settings are preserved. The current version is kept as a backup.');note.setWordWrap(True);layout.addWidget(note)
            dlg.finished.connect(self.closed);self.refresh();dlg.show()

        def closed(self,*_):
            if self.dialog:self.dialog.deleteLater();self.dialog=None

        def save(self):
            try:
                repo=normalize_repo(self.repo.text()) if self.repo.text().strip() else ''
                if repo!=read_settings()['repository']:self.ready=None;self.release=None;self.percent=0
                write_settings(repo,self.enabled.isChecked(),self.auto_download.isChecked())
                self.last='Settings saved.';self.refresh();return True
            except (OSError,ValueError) as exc:self.last=str(exc);self.refresh();return False

        def manual(self):
            if self.save():self.check(True)

        def check(self,manual):
            if self.busy:return
            repo=read_settings()['repository']
            if not repo:self.last='Enter your GitHub repository first.';self.refresh();return
            self.busy=True;self.last='Checking for updates…';self.refresh()
            def work():
                try:self.events.put(('check',repo,manual,fetch_release(repo),None))
                except Exception as exc:self.events.put(('check',repo,manual,None,str(exc)))
            threading.Thread(target=work,daemon=True).start()

        def download_now(self):
            if self.busy or not self.release:return
            if not getattr(sys,'frozen',False):
                self.last='Automatic installation requires the Windows EXE build.';self.refresh();return
            release=dict(self.release);repo=release['repository'];self.busy=True;self.percent=0
            self.last='Downloading update in the background…';self.refresh()
            def work():
                def progress(count,total):self.events.put(('progress',repo,False,int(count*100/total) if total else 0,None))
                try:self.events.put(('download',repo,False,stage_release(release,progress),None))
                except Exception as exc:self.events.put(('download',repo,False,None,str(exc)))
            threading.Thread(target=work,daemon=True).start()

        def install(self):
            if self.busy or not self.ready:return
            if kiosk and (getattr(window,'member',None) is not None or (getattr(window,'busy',False) and not getattr(window,'_settings_open',False))):
                self.last='Finish the current kiosk transaction before restarting.';self.refresh();return
            if any(t.isRunning() for t in window.findChildren(QThread)):
                self.last='A database request is still running. Try Restart & Update again in a moment.';self.refresh();return
            self.busy=True;self.last='Preparing restart. Please wait…';self.refresh()
            self.paused=[(t,t.interval()) for t in window.findChildren(QTimer) if t.parent() is not self and t.isActive()]
            for timer,_ in self.paused:timer.stop()
            window.setEnabled(False)
            ready=dict(self.ready)
            def work():
                try:prepare_helper(ready);self.events.put(('prepared',ready['repository'],False,True,None))
                except Exception as exc:self.events.put(('prepared',ready['repository'],False,None,str(exc)))
            threading.Thread(target=work,daemon=True).start()

        def finish(self):
            while True:
                try:kind,repo,manual,result,error=self.events.get_nowait()
                except queue.Empty:return
                if kind=='prepared':
                    self.busy=False
                    if error:
                        window.setEnabled(True)
                        for timer,interval in self.paused:timer.start(interval)
                        self.last='Cannot prepare update: '+error;self.refresh();continue
                    window._update_requested=True
                    for dialog in list(QApplication.instance().topLevelWidgets()):
                        if isinstance(dialog,QDialog):dialog.reject()
                    window.close();QApplication.instance().quit();return
                cfg=read_settings()
                if kind=='progress':
                    if cfg['repository']==repo:self.percent=result;self.refresh()
                    continue
                self.busy=False
                if cfg['repository']!=repo:self.refresh();continue
                if error:self.last='Update not installed: '+error;self.refresh();continue
                if kind=='download':
                    self.ready=result;self.percent=100
                    self.last=f"{result['tag']} downloaded and checksum verified. Click Restart & Update."
                    window.statusBar().showMessage('Update ready — open Settings → Updates to restart.' if kiosk else self.last)
                    self.refresh()
                    if not kiosk:self.show_settings()
                elif kind=='check':
                    self.release=result
                    if self.ready and self.ready["tag"]!=result["tag"]:self.ready=None
                    if not result['newer']:
                        self.ready=None;self.last=f'You are up to date ({VERSION}).';self.refresh();continue
                    self.last=f"Update available: {result['tag']}."
                    self.refresh()
                    if cfg['auto_download'] and (cfg['enabled'] or manual) and result.get('package_url'):self.download_now()
                    else:
                        window.statusBar().showMessage(self.last)
                        if not kiosk:self.show_settings()
    controller=Controller();window.update_controller=controller;return controller
