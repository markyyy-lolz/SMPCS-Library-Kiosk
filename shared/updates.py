"""Non-blocking GitHub release checks; no running files are overwritten."""
import json
import os
import queue
import re
import threading
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

VERSION = '1.2.0'
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
                    'enabled': data.get('enabled', True) is True}
        except (OSError, ValueError, KeyError, TypeError, AttributeError): pass
    return {'repository': '', 'enabled': True}

def write_settings(repo, enabled):
    data = {'repository': normalize_repo(repo) if repo.strip() else '', 'enabled': bool(enabled)}
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
    return {'newer': newer, 'tag': tag, 'url': f'https://github.com/{repo}/releases/latest'}

def attach_updates(window, kiosk=False):
    from PyQt6.QtCore import QObject, QTimer, QUrl, Qt
    from PyQt6.QtGui import QDesktopServices
    from PyQt6.QtWidgets import QDialog, QVBoxLayout, QLabel, QLineEdit, QCheckBox, QPushButton

    class Controller(QObject):
        def __init__(self):
            super().__init__(window)
            self.results = queue.Queue()
            self.busy = False
            self.dialog = None
            self.last = 'Ready to check.'
            self.url = ''
            self.notified = ''
            self.poll = QTimer(self)
            self.poll.timeout.connect(self.finish); self.poll.start(200)
            self.schedule = QTimer(self)
            self.schedule.timeout.connect(self.automatic)
            self.schedule.start(6 * 60 * 60 * 1000)
            QTimer.singleShot(4000, self.automatic)
            if not kiosk:
                menu = window.menuBar().addMenu('Updates')
                menu.addAction('Update settings / Check now', self.show_settings)

        def automatic(self):
            cfg = read_settings()
            if cfg['enabled'] and cfg['repository']: self.check(False)

        def show_settings(self):
            if self.dialog:
                self.dialog.show(); self.dialog.raise_(); self.dialog.activateWindow(); return
            dlg = self.dialog = QDialog(window)
            dlg.setWindowTitle('SMPCS Library — Updates'); dlg.resize(530, 310)
            layout = QVBoxLayout(dlg)
            layout.addWidget(QLabel(f'Installed version: {VERSION}'))
            layout.addWidget(QLabel('Public GitHub repository URL or owner/repository'))
            cfg = read_settings()
            self.repo = QLineEdit(cfg['repository'])
            self.repo.setPlaceholderText('https://github.com/your-account/your-repository')
            layout.addWidget(self.repo)
            self.enabled = QCheckBox('Check at startup and every 6 hours')
            self.enabled.setChecked(cfg['enabled']); layout.addWidget(self.enabled)
            self.label = QLabel(self.last); self.label.setWordWrap(True)
            self.label.setTextFormat(Qt.TextFormat.PlainText); layout.addWidget(self.label)
            save = QPushButton('Save settings'); save.clicked.connect(self.save); layout.addWidget(save)
            check = QPushButton('Save and check now'); check.clicked.connect(self.manual); layout.addWidget(check)
            self.open_btn = QPushButton('Open latest GitHub release')
            self.open_btn.setEnabled(bool(self.url))
            self.open_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(self.url)))
            layout.addWidget(self.open_btn)
            dlg.finished.connect(self.closed); dlg.show()

        def closed(self, *_):
            self.dialog.deleteLater(); self.dialog = None

        def save(self):
            try:
                write_settings(self.repo.text(), self.enabled.isChecked())
                self.url = ''; self.open_btn.setEnabled(False)
                self.label.setText('Settings saved.'); return True
            except (ValueError, OSError) as exc:
                self.label.setText(str(exc)); return False

        def manual(self):
            if self.save(): self.check(True)

        def check(self, manual):
            if self.busy:
                if self.dialog: self.label.setText('A check is already in progress.')
                return
            repo = read_settings()['repository']
            if not repo:
                if self.dialog: self.label.setText('Enter your GitHub repository first.')
                return
            self.busy = True
            if self.dialog: self.label.setText('Checking GitHub…')
            def work():
                try: self.results.put((repo, manual, fetch_release(repo), None))
                except Exception as exc: self.results.put((repo, manual, None, str(exc)))
            threading.Thread(target=work, daemon=True).start()

        def finish(self):
            try: repo, manual, result, error = self.results.get_nowait()
            except queue.Empty: return
            self.busy = False
            cfg = read_settings()
            if cfg['repository'] != repo or (not manual and not cfg['enabled']): return
            self.url = result['url'] if result else ''
            self.last = error or (f"Update available: {result['tag']} (installed: {VERSION})." if result['newer']
                                  else f'You are up to date (installed: {VERSION}).')
            if self.dialog:
                self.label.setText(self.last); self.open_btn.setEnabled(bool(self.url))
            if result and result['newer']:
                window.statusBar().showMessage(self.last + (' Ask the librarian to update.' if kiosk else ''))
                if not kiosk and not manual and self.notified != result['tag']:
                    self.notified = result['tag']; self.show_settings()

    controller = Controller()
    window.update_controller = controller
    return controller
