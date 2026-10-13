"""Read-only change inventory with evidence-gated review checkpoints."""
import argparse,hashlib,json,urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def digest(raw):return hashlib.sha256(raw).hexdigest()
def inventory(root=ROOT):
    items={}
    with urllib.request.urlopen('http://127.0.0.1:14699/api/state',timeout=20) as response: state=json.load(response)
    if not state.get('root') or Path(state['root']).resolve() != root.resolve():
        raise ValueError('The running service does not own the expected review workspace.')
    for r in state['objects']:
        if r['kind'] in ('skill','loop','agent','stack','project'):
            key=r['kind']+':'+r['id'];items[key]={'hash':digest(json.dumps(r,sort_keys=True).encode()),'version':r['version'],'archived':bool(r['archived'])}
    for folder in ('app','evaluations','company','routines','docs','skills'):
        for p in (root/folder).rglob('*'):
            if p.is_file() and not any(x in ('__pycache__','node_modules') for x in p.parts) and p.suffix.lower() in ('.py','.js','.html','.css','.json','.md','.toml','.yaml','.yml','.ps1'):
                items['file:'+p.relative_to(root).as_posix()]={'hash':digest(p.read_bytes())}
    for p in root.glob('*'):
        if p.is_file() and (p.suffix.lower() in ('.md','.ps1') or p.name=='.gitignore'):items['file:'+p.name]={'hash':digest(p.read_bytes())}
    native=Path.home()/'.codex/skills'
    for p in native.rglob('SKILL.md'):
        items['native:'+p.relative_to(native).as_posix()]={'hash':digest(p.read_bytes())}
    for p in [Path.home()/'.codex/config.toml',root/'runtime/creative/storage.json']:
        if p.is_file():items['configuration:'+str(p)]={'hash':digest(p.read_bytes())}
    return items

def changes(current,previous):
    return [{'key':k,'change':'deleted' if k not in current else 'new' if k not in previous else 'modified','current':current.get(k),'previous':previous.get(k)} for k in sorted(current.keys()|previous.keys()) if current.get(k)!=previous.get(k)]

def acknowledge(report,current,checkpoint):
    rows=report.get('reviews',[])
    if not isinstance(rows,list) or not rows:raise ValueError('Supply actual individual review results, not an empty completion claim.')
    updated=dict(checkpoint)
    for row in rows:
        k=row['key']
        if row.get('current')!=current.get(k):raise ValueError('Changed since review: '+k)
        if row.get('status') not in ('verified','repaired','unverified','proposed'):raise ValueError('Invalid review status')
        if not isinstance(row.get('evidence'),str) or not row['evidence'].strip():raise ValueError('Record real evidence or the concrete verification gap.')
        # Unverified/proposed work remains outstanding for a future scan.
        if row['status'] in ('verified','repaired'):
            if k in current:updated[k]=current[k]
            else:updated.pop(k,None)
    return updated

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--mode',choices=('prompt','system'),required=True);parser.add_argument('--complete',type=Path);args=parser.parse_args()
    folder=ROOT/'runtime/reviews'/args.mode;folder.mkdir(parents=True,exist_ok=True);checkpoint=folder/'checkpoint.json'
    prior=json.loads(checkpoint.read_text(encoding='utf-8')) if checkpoint.exists() else {};current=inventory()
    if args.complete:
        report=json.loads(args.complete.read_text(encoding='utf-8'));next_state=acknowledge(report,current,prior)
        temp=checkpoint.with_suffix('.tmp');temp.write_text(json.dumps(next_state,indent=2),encoding='utf-8');temp.replace(checkpoint)
    else:
        result={'mode':args.mode,'first_scan':not checkpoint.exists(),'changes':changes(current,prior),'note':'Inventory only. No tests, repairs or review completion are implied.'}
        target=folder/'pending.json';target.write_text(json.dumps(result,indent=2),encoding='utf-8');print(json.dumps({'report':str(target),'changed':len(result['changes']),'first_scan':result['first_scan']}))
if __name__=='__main__':main()
