"""Local installed-version history; dates are first launch after installation."""
import json
from datetime import datetime, timezone
from shared.config import APP_DIR


def history(path=None):
    path=path or APP_DIR/'update_history.json'
    try:
        rows=json.loads(path.read_text(encoding='utf-8'))
        return rows if isinstance(rows,list) else []
    except (OSError,ValueError):return []


def record(version,notes,path=None):
    path=path or APP_DIR/'update_history.json';rows=history(path)
    if rows and rows[-1].get('version')==version:return
    rows.append({'version':version,'first_started_at':datetime.now(timezone.utc).isoformat(),'notes':notes})
    path.parent.mkdir(parents=True,exist_ok=True);temp=path.with_suffix('.tmp');temp.write_text(json.dumps(rows[-50:],ensure_ascii=False,indent=2),encoding='utf-8');temp.replace(path)


def show(parent):
    from PyQt6.QtWidgets import QComboBox,QPlainTextEdit,QLabel
    from shared.account_ui import dialog,button
    d,lay=dialog(parent,'Update history');lay.addWidget(QLabel('Dates show the first launch after each installation.'))
    select=QComboBox();lay.addWidget(select);notes=QPlainTextEdit();notes.setReadOnly(True);lay.addWidget(notes,1)
    rows=list(reversed(history()))
    for row in rows:select.addItem('v'+row['version']+' • '+row['first_started_at'])
    def changed(i):notes.setPlainText(rows[i]['notes'] if 0<=i<len(rows) else 'No history recorded yet.')
    select.currentIndexChanged.connect(changed);changed(0);button(lay,'Close',d.reject);d.exec()
