"""Reproducible isolated journey and trace benchmark; no production writes."""
import importlib.util
import json
import runpy
import statistics
import sys
import time
from pathlib import Path
root=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(root/'app'),str(root/'evaluations')]
original=importlib.util.spec_from_file_location
def spec(name,location,*args,**kwargs):
    if Path(location).resolve()==(root/'vendor/AI-OS-Dashboard-Current-1.0.4/server.py').resolve():
        location=root.parent/'V2/vendor/AI-OS-Dashboard-Current-1.0.4/server.py'
    return original(name,location,*args,**kwargs)
importlib.util.spec_from_file_location=spec
start=time.perf_counter()
runpy.run_path(str(root/'evaluations/simulate_workflow_journey.py'))
journey_ms=(time.perf_counter()-start)*1000
from test_task_trace import TraceTests
from task_trace import verify
f=TraceTests();f.setUp()
try:
    times=[]
    for _ in range(200):
        start=time.perf_counter();result=verify(f.plan,f.events)
        times.append((time.perf_counter()-start)*1000)
        assert result['status']=='verified'
    report={'label':'Isolated simulation; models and role exchanges are fixtures',
            'iterations':len(times),'trace_steps':len(f.plan['steps']),
            'median_ms':statistics.median(times),'p95_ms':sorted(times)[int(.95*len(times))-1],
            'journey_ms':journey_ms,'trace':result,
            'limits':['No model latency, provider quality or cloud uptime measured.',
                      'Trace checks do not create a dispatcher or prove semantic acceptance.',
                      'Repeated fixture trials are not an independent transfer benchmark.']}
    (root/'runtime/mvp03-benchmark.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report,indent=2))
finally:f.doCleanups()
