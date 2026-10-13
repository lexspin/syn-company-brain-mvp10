"""Check public entry links and obvious release-boundary regressions; no network."""
from pathlib import Path
import re, sys
from urllib.parse import unquote
root=Path(__file__).resolve().parents[1]
errors=[]; count=0
for folder in ['records','store','vendor']:
    if (root/folder).exists(): errors.append('Excluded directory: '+folder)
for p in [root/'README.md',*root.glob('presentation/**/*.html'),*root.glob('presentation/**/*.md')]:
    text=p.read_text(encoding='utf-8')
    urls=re.findall(r'(?:href|src)=["\']([^"\']+)',text) if p.suffix=='.html' else re.findall(r'!?\[[^\]]*\]\(([^)]+)\)',text)
    for url in urls:
        url=url.split('#')[0].split('?')[0]
        if not url or re.match(r'^[a-z]+:|^//',url,re.I):continue
        count+=1
        if not (p.parent/unquote(url)).exists():errors.append(str(p.relative_to(root))+': '+url)
    if 'syn-company-brain/blob/MVP10' in text or 'syn-company-brain/tree/MVP10' in text:
        errors.append('Old repository navigation: '+str(p.relative_to(root)))
print('Checked',count,'local navigation targets')
for e in errors:print(e)
sys.exit(bool(errors))
