"""Choose an installed CLI that advertises the exact requested model/effort.

Bundled catalog inspection makes no model call and does not refresh account
catalogs. An explicit CODEX_BIN is authoritative and fails closed if unsuitable.
"""
import json
import os
import re
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path

def candidate_paths():
    override=os.environ.get('CODEX_BIN','').strip()
    if override:
        path=Path(override)
        if not path.is_absolute() or not path.is_file():raise RuntimeError('CODEX_BIN must name an existing absolute Codex executable.')
        return [path.resolve()]
    candidates=[]
    first=shutil.which('codex')
    if first:candidates.append(Path(first))
    names=('codex.exe',) if os.name=='nt' else ('codex',)
    for directory in os.get_exec_path():
        candidates.extend(Path(directory)/name for name in names)
    # Desktop updates use versioned installation directories, not a stable hash.
    local=os.environ.get('LOCALAPPDATA','')
    if os.name=='nt' and local:
        folder=Path(local)/'OpenAI/Codex/bin'
        if folder.is_dir():candidates.extend(folder.glob('*/codex.exe'))
    return sorted({p.resolve() for p in candidates if p.is_file()},key=lambda p:str(p).lower())

def version_key(version):
    match=re.search(r'(\d+)\.(\d+)\.(\d+)([^\s]*)',version)
    if not match:raise ValueError('Unrecognized Codex client version.')
    suffix=match.group(4)
    return (*map(int,match.group(1,2,3)),int(not suffix),tuple(map(int,re.findall(r'\d+',suffix))))

@lru_cache(maxsize=32)
def _probe(path,mtime_ns,size):
    options={'capture_output':True,'text':True,'encoding':'utf-8','errors':'replace','timeout':10,
             'creationflags':getattr(subprocess,'CREATE_NO_WINDOW',0)}
    version=subprocess.run([path,'--version'],**options)
    if version.returncode:raise ValueError('Cannot read Codex client version.')
    label=version.stdout.strip();key=version_key(label)
    catalog=subprocess.run([path,'debug','models','--bundled'],**options)
    if catalog.returncode:raise ValueError('Cannot inspect bundled Codex model catalog.')
    models=json.loads(catalog.stdout).get('models',[])
    advertised={m['slug']:{e['effort'] for e in m.get('supported_reasoning_levels',[])} for m in models}
    return {'path':path,'version':label,'version_key':key,'models':advertised}

def select_client(model,reasoning_effort):
    compatible=[]
    for path in candidate_paths():
        try:
            stat=path.stat();info=_probe(str(path),stat.st_mtime_ns,stat.st_size)
            if reasoning_effort in info['models'].get(model,set()):compatible.append(info)
        except (OSError,ValueError,KeyError,TypeError,subprocess.SubprocessError):continue
    if not compatible:
        prefix='CODEX_BIN does not advertise' if os.environ.get('CODEX_BIN','').strip() else 'No installed Codex CLI advertises'
        raise RuntimeError(prefix+' '+model+' at '+reasoning_effort+' effort. Select a compatible installed client or update Codex; no different model was selected.')
    info=max(compatible,key=lambda item:(item['version_key'],item['path'].lower()))
    return {key:info[key] for key in ('path','version')}
