"""Read only explicitly reported, bounded OS documentation outputs."""
from pathlib import Path
from live_activity import activity_view

def read_output(root, task_id, index):
    root=Path(root).resolve()
    if type(index) is not int or index < 0: raise ValueError('Invalid output index')
    task=next((t for t in activity_view(root)['tasks'] if t['id']==task_id),None)
    if not task or index >= len(task['outputs']): raise ValueError('Output not reported')
    ref=task['outputs'][index].get('reference','')
    path=Path(ref)
    if not path.is_absolute(): raise ValueError('No local document reference')
    path=path.resolve()
    allowed=path.is_relative_to(root/'docs') or path==root/'runtime/live-neurolinks-regression.log'
    if not allowed or path.suffix.lower() not in {'.md','.txt','.json','.log'}:
        raise ValueError('Use the registered product workspace for this output')
    with path.open('rb') as handle: data=handle.read(256*1024+1)
    if len(data)>256*1024: raise ValueError('Document exceeds preview limit')
    return data.decode('utf-8').encode('utf-8')
