"""Local deterministic routines, bounded by one shared registry and append-only receipts."""
import argparse,hashlib,json,os,subprocess,sys,threading,time,uuid
from contextlib import contextmanager
from datetime import datetime,timezone,timedelta
from pathlib import Path
from zoneinfo import ZoneInfo,ZoneInfoNotFoundError
ROOT=Path(__file__).resolve().parents[1]

def stamp():return datetime.now(timezone.utc).isoformat()
def append(path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('a',encoding='utf-8',newline='\n') as f:
        f.write(json.dumps(data,ensure_ascii=False)+'\n');f.flush();os.fsync(f.fileno())
def rows(path):
    if not path.exists():return []
    output=[]
    for line in path.read_text(encoding='utf-8').splitlines():
        if line.strip():output.append(json.loads(line))
    return output
def local_clock(value,zone):
    try:return value.astimezone(ZoneInfo(zone))
    except ZoneInfoNotFoundError:
        if os.name!='nt' or zone!='Europe/London':raise
        # Windows ships this timezone database even when Python has no tzdata wheel.
        script="$taskUtc = [DateTimeOffset]::Parse([Console]::In.ReadToEnd()).UtcDateTime; [TimeZoneInfo]::ConvertTimeBySystemTimeZoneId($taskUtc, 'GMT Standard Time').ToString('yyyy-MM-ddTHH:mm:ss')"
        result=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',script],input=value.isoformat(),capture_output=True,text=True,timeout=15,check=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        return datetime.fromisoformat(result.stdout.strip())

class RoutineEngine:
    def __init__(self,root=ROOT):
        self.root=Path(root).resolve();self.directory=self.root/'store/routines';self.directory.mkdir(parents=True,exist_ok=True)
        self.queue=self.root/'runtime/routines/queue';self.queue.mkdir(parents=True,exist_ok=True)
        self.events=self.directory/'events.jsonl';self.briefs=self.directory/'messages.jsonl'
        self.guard=threading.RLock();self.closed=threading.Event();self.last_tick=None
    def registry(self):
        config=json.loads((self.root/'routines/registry.json').read_text(encoding='utf-8'))
        for r in config['routines']:
            if r['kind'] not in ('map-check','morning-digest') or r['max_turns']!=0:
                raise ValueError('Only the registered deterministic routines are enabled. Add a verified model adapter before scheduling model work.')
            if not 1<=r['timeout_seconds']<=120:raise ValueError('Routine timeout must be 1–120 seconds.')
            if not (self.root/r['output']).resolve().is_relative_to(self.root/'deliverables'):
                raise ValueError('Routine outputs must stay inside deliverables.')
        return config
    @contextmanager
    def exclusive(self):
        with self.guard:
            with (self.directory/'runner.lock').open('a+b') as f:
                if f.tell()==0:f.write(b'0');f.flush()
                f.seek(0)
                if os.name=='nt':
                    import msvcrt
                    try:msvcrt.locking(f.fileno(),msvcrt.LK_NBLCK,1)
                    except OSError:yield False;return
                else:
                    import fcntl
                    try:fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
                    except OSError:yield False;return
                try:yield True
                finally:
                    f.seek(0)
                    if os.name=='nt':msvcrt.locking(f.fileno(),msvcrt.LK_UNLCK,1)
                    else:fcntl.flock(f,fcntl.LOCK_UN)
    def request_run(self,id,key=None):
        from operating_policy import policy_for_root, require_allowed
        require_allowed(policy_for_root(self.root), 'routine')
        config=self.registry();routine=next((r for r in config['routines'] if r['id']==id),None)
        if not routine:raise ValueError('Unknown routine.')
        key=key or uuid.uuid4().hex
        import re
        if not isinstance(key,str) or not re.fullmatch('[A-Za-z0-9_-]{8,100}',key):raise ValueError('Invalid request identity.')
        path=self.queue/(key+'.json')
        data={'id':key,'routine':id,'machine':routine['machine'],'time':stamp(),'requested_by':'local-owner'}
        if path.exists():
            previous=json.loads(path.read_text())
            if previous['routine']!=id:raise ValueError('Request identity belongs to another routine.')
            return previous|{'status':'queued'}
        with path.open('x',encoding='utf-8') as f:json.dump(data,f);f.flush();os.fsync(f.fileno())
        return data|{'status':'queued'}
    def messages(self):return rows(self.briefs)
    def status(self):
        from operating_policy import policy_for_root
        config=self.registry();history=rows(self.events)
        return {'asof':self.last_tick,'machine':config['machine_id'],'poll_seconds':config['poll_seconds'],
                'operating_policy':policy_for_root(self.root),
                'routines':config['routines'],'recent':history[-30:],
                'queued':[json.loads(p.read_text()) for p in sorted(self.queue.glob('*.json'))
                          if not any(e.get('request_id')==p.stem and e['status']!='started' for e in history)]}
    def tick(self,now=None):
        with self.exclusive() as acquired:
            if not acquired:return {'status':'another-runner-active'}
            config=self.registry();now=now or datetime.now(timezone.utc)
            history=rows(self.events);self.last_tick=now.isoformat()
            latest={e['occurrence']:e for e in history}
            # A started-but-unfinished occurrence is preserved and never silently repeated.
            for event in list(latest.values()):
                if event['status']=='started':
                    event=event|{'time':now.isoformat(),'status':'interrupted','error':'Previous runner stopped before a completion receipt. Review before queuing new work.'}
                    append(self.events,event);latest[event['occurrence']]=event
            from operating_policy import policy_for_root, require_allowed
            policy=policy_for_root(self.root)
            try:require_allowed(policy, 'routine')
            except ValueError:return self.status()|{'admission':policy['effective_state']}
            try:require_allowed(policy, 'scheduled');scheduled_allowed=True
            except ValueError:scheduled_allowed=False
            local=local_clock(now,config['timezone']);pending=[]
            for routine in config['routines']:
                if not scheduled_allowed:continue
                if routine['machine']!=config['machine_id'] or not routine.get('enabled',True):continue
                occurrence=routine['id']+':'+local.date().isoformat()
                due=datetime.strptime(routine['schedule'],'%H:%M').time()
                if local.time().replace(tzinfo=None)>=due and occurrence not in latest:
                    pending.append((routine,occurrence,None))
            for path in sorted(self.queue.glob('*.json')):
                request=json.loads(path.read_text());occurrence='manual:'+request['id']
                if request['machine']!=config['machine_id'] or occurrence in latest:continue
                routine=next((r for r in config['routines'] if r['id']==request['routine']),None)
                if routine:pending.append((routine,occurrence,request['id']))
            admitted=0
            for routine,occurrence,request_id in pending:
                # Re-read before each start; a state change never interrupts or
                # replays a begun effect, but stops admitting subsequent work.
                policy=policy_for_root(self.root)
                try:require_allowed(policy, 'routine' if request_id is not None else 'scheduled')
                except ValueError:
                    if policy['effective_state']=='off':break
                    continue
                if policy['source']!='legacy-active' and admitted>=policy['idle']['max_batch']:break
                previous=[e for e in rows(self.events) if e['routine']==routine['id'] and e['status']=='started']
                if policy['source']!='legacy-active' and previous and datetime.fromisoformat(previous[-1]['time'])>now-timedelta(seconds=policy['idle']['cooldown_seconds']):continue
                starts=[e for e in rows(self.events) if e['status']=='started']
                day=sum(e.get('local_date',datetime.fromisoformat(e['time']).date().isoformat())==local.date().isoformat() for e in starts)
                window=sum(datetime.fromisoformat(e['time'])>=now-timedelta(minutes=config['caps']['window_minutes']) for e in starts)
                if day>=config['caps']['daily_runs'] or window>=config['caps']['window_runs']:
                    event={'time':now.isoformat(),'name':routine['name'],'routine':routine['id'],'occurrence':occurrence,'request_id':request_id,'model':None,'turns':0,'cost':0,'status':'capped'}
                    append(self.events,event);continue
                # Check again at the effect boundary, before consuming the occurrence.
                policy=policy_for_root(self.root)
                try:require_allowed(policy, 'routine' if request_id is not None else 'scheduled')
                except ValueError:
                    if policy['effective_state']=='off':break
                    continue
                event={'time':now.isoformat(),'local_date':local.date().isoformat(),'name':routine['name'],'routine':routine['id'],'occurrence':occurrence,'request_id':request_id,'model':None,'turns':0,'cost':0,'status':'started'}
                append(self.events,event)
                admitted+=1
                try:
                    text=self.execute(routine,now)
                    folder=self.root/routine['output'];folder.mkdir(parents=True,exist_ok=True)
                    artifact=folder/(now.strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:8]+'.md')
                    artifact.write_text(text,encoding='utf-8',newline='\n')
                    if routine['kind']=='morning-digest':
                        append(self.briefs,{'role':'assistant','text':text,'created':now.isoformat(),'routine':routine['id'],'occurrence':occurrence})
                    append(self.events,event|{'time':stamp(),'status':'completed','artifact':artifact.relative_to(self.root).as_posix(),'sha256':hashlib.sha256(artifact.read_bytes()).hexdigest()})
                except Exception as error:append(self.events,event|{'time':stamp(),'status':'failed','error':str(error)})
            return self.status()
    def execute(self,routine,now):
        if routine['kind']=='map-check':
            result=subprocess.run([sys.executable,str(self.root/'app/check_map.py')],cwd=self.root,capture_output=True,text=True,timeout=routine['timeout_seconds'],creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            if result.returncode:raise RuntimeError((result.stdout+'\n'+result.stderr).strip()[:4000])
            from map_graph import publish_map
            graph_path=publish_map(self.root)
            return '# Memory map check\n\n'+result.stdout.strip()+'\n\nRefreshed map: '+graph_path.relative_to(self.root).as_posix()+'\n'
        path=self.root/'data/state.json'
        if not path.exists():raise ValueError('Current published workspace state is not available.')
        state=json.loads(path.read_text(encoding='utf-8'))
        if 'data' in state and 'objects' not in state:state=state['data']
        recent=[r for r in state.get('runs',[]) if datetime.fromisoformat(r['created'])>=now-timedelta(hours=24)]
        tasks=[r for r in state.get('objects',[]) if r['kind']=='memory' and not r['archived'] and r['data'].get('type')=='task' and r['data'].get('status')=='accepted']
        lines=['# Morning briefing',f'\nPrepared {local_clock(now,self.registry()["timezone"]).strftime("%d %B %Y %H:%M")} — Europe/London.', '\n## Work in the last 24 hours']
        lines += [f'- {r["loop_id"]}: {r["state"]}; {r["step"]} saved steps.' for r in recent] or ['- No recorded workflow activity in this period.']
        lines+=['\n## Due and waiting']
        lines += [f'- {r["data"]["name"]}: due {r["data"].get("due","not recorded")}; waiting on {r["data"].get("waiting_on","not recorded")}.' for r in tasks] or ['- No verified task deadlines or people waiting are registered yet. Add them to Knowledge; this briefing does not infer obligations from old notes.']
        lines+=['\nThis briefing reports saved local records. It does not claim that external applications were checked.']
        return '\n'.join(lines)+'\n'
    def start(self):
        def work():
            while not self.closed.is_set():
                try:self.tick()
                except Exception as error:append(self.directory/'runner-errors.jsonl',{'time':stamp(),'error':str(error)})
                self.closed.wait(self.registry().get('poll_seconds',300))
        threading.Thread(target=work,name='company-brain-routines',daemon=True).start()
    def close(self):self.closed.set()

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--serve',action='store_true');args=parser.parse_args()
    engine=RoutineEngine()
    if args.serve:
        engine.start()
        try:
            while True:time.sleep(1)
        except KeyboardInterrupt:engine.close()
    else:print(json.dumps(engine.tick(),ensure_ascii=False,indent=2))
