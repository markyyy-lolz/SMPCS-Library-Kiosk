from pathlib import Path
import hashlib
root=Path(__file__).resolve().parent.parent/'dist'
files=sorted(p for p in root.iterdir() if p.is_file() and p.name!='SHA256SUMS.txt')
(root/'SHA256SUMS.txt').write_text(''.join(hashlib.sha256(p.read_bytes()).hexdigest()+'  '+p.name+'\n' for p in files),encoding='utf-8')
