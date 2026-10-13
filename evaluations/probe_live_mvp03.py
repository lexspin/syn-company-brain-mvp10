"""Read-only client-observed trace of the real local MVP03 gateway.

Does not create a Brain, call a model or claim server-wide instrumentation.
"""
import hashlib
import http.client
import json
from pathlib import Path
import sys
import uuid
root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root/'app'))
from task_trace import verify
trace=uuid.uuid4().hex
plan={'trace_id':trace,'steps':[]};events=[]
targets=[('state','/api/state','Canonical workspace responds'),
         ('map','/api/brain','Harness and MVP03 nodes are published'),
         ('view','/validation','Human validation view renders')]
for i,(key,url,acceptance) in enumerate(targets):
    plan['steps'].append({'id':key,'owner':'MVP03 local gateway','source_version':'MVP03 probe v1',
                         'acceptance':acceptance,'depends_on':[targets[i-1][0]] if i else []})
    base={'trace_id':trace,'step_id':key,'operation_id':uuid.uuid4().hex}
    events.append(base|{'kind':'request','source_version':'MVP03 probe v1'})
    connection=http.client.HTTPConnection('127.0.0.1',14703,timeout=10)
    try:
        connection.request('GET',url);response=connection.getresponse();body=response.read(16*1024*1024)
        assert response.status==200, (url,response.status)
    finally:connection.close()
    if key=='state':assert Path(json.loads(body)['root']).resolve()==(root.parent/'V2').resolve()
    if key=='map':
        graph=json.loads(body);ids={n.get('record_id') for n in graph['nodes'] if not n.get('audit_only')}
        assert {'project:mvp03-ai-os','skill:company-brain-harness'}<=ids
        assert not graph['unmapped_current_records']
    if key=='view':assert b'Follow the work. Check the result.' in body and b'Simulation evidence' in body
    artifact=root/'runtime'/('live-'+key+'.json' if key!='view' else 'live-view.html')
    artifact.write_bytes(body);digest=hashlib.sha256(body).hexdigest()
    events.extend([base|{'kind':'response','status':'returned','artifact':{'path':str(artifact),'sha256':digest}},
                   base|{'kind':'validation','status':'passed','artifact_sha256':digest,'evidence':acceptance+'; HTTP and content assertions passed'}])
capture={'plan':plan,'events':events};result=verify(plan,events)
(root/'runtime/mvp03-live-capture.json').write_text(json.dumps(capture,indent=2),encoding='utf-8')
(root/'runtime/mvp03-live-result.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
print(json.dumps(result,indent=2))
assert result['status']=='verified'
