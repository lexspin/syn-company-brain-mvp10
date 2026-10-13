const assert=require('node:assert/strict');
const controls=require('../app/operating-controls.js');
const view={policy:{requested_state:null,effective_state:'active',source:'legacy-active',version:0},agents:[{id:'worker',version:7,requested_state:'active',effective_state:'idle'}],activity:{worker_busy:true,view:{asof:'today',stale:true}}};
assert.match(controls.description(view,''),/legacy; not configured/);
assert.match(controls.description(view,'worker'),/Saved request: Active. Effective admission: Idle/);
assert.match(controls.activity(view),/work in progress.*stale/);
assert.match(controls.activity({activity:{worker_busy:null}}),/unavailable/);
assert.match(controls.activity(view),/Native chat activity is not reported/);
assert.deepEqual(controls.body(view,'','idle'),{state:'idle',version:0});
assert.deepEqual(controls.body(view,'worker','off'),{state:'off',version:7,agent_id:'worker'});
assert.throws(()=>controls.body(view,'deleted','off'));
assert.throws(()=>controls.body(view,'','running'));
const response=(status,value)=>({ok:status<400,status,json:async()=>value});
async function mountedRefresh(){
 const fs=require('node:fs'),vm=require('node:vm');
 // Minimal DOM fixture executes the actual mounted handlers with controlled reads/timers.
 class Element{
  constructor(){this.dataset={};this.children=[];this.listeners={};this.value='';this.disabled=false;this.hidden=false;this.textContent='';this.isConnected=true;}
  setAttribute(key,value){this[key]=value;}
  addEventListener(name,fn){(this.listeners[name]??=[]).push(fn);}
  removeEventListener(name,fn){this.listeners[name]=(this.listeners[name]||[]).filter(f=>f!==fn);}
  async emit(name){await Promise.all((this.listeners[name]||[]).map(fn=>fn()));}
  click(){if(!this.disabled)return this.emit('click');}
  append(child){this.children.push(child);}
  insertBefore(child){this.children.push(child);}
 }
 const host=new Element(),details=new Element(),elements={};
 for(const key of ['summary','target','mode','apply','refresh','saved','profile','rules','activity','message','recover'])elements[key]=new Element();
 elements.mode.value='off';details.children=[new Element(),new Element(),new Element()];
 host.querySelector=selector=>selector==='details'?details:elements[selector.slice(6,-1)];
 const document=new Element();document.visibilityState='visible';document.getElementById=()=>host;document.createElement=()=>new Element();
 const window=new Element(),stored=new Map(),calls=[],timers=[];
 let current={controls_available:true,policy:{requested_state:'idle',effective_state:'idle',source:'configured',version:10,idle:{max_batch:2,cooldown_seconds:60}},agents:[{id:'worker',name:'Worker',version:2,requested_state:'idle',effective_state:'idle'}]},fail=false,release=null;
 const context={document,sessionStorage:{getItem:k=>stored.get(k),setItem:(k,v)=>stored.set(k,v),removeItem:k=>stored.delete(k)},crypto:{randomUUID:()=> 'a'.repeat(32)},addEventListener:window.addEventListener.bind(window),removeEventListener:window.removeEventListener.bind(window),setInterval:(fn,ms)=>{timers.push({fn,ms});return 1;},clearInterval:()=>{},fetch:async(path,options)=>{
  calls.push({path,options});
  if(options?.method==='POST')throw Error('uncertain write');
  if(release)await new Promise(resolve=>{release=resolve;});
  if(fail)throw Error('network unavailable');
  return response(200,structuredClone(current));
 }};
 vm.runInNewContext(fs.readFileSync(require.resolve('../app/operating-controls.js'),'utf8'),context);
 const settle=async()=>{for(let i=0;i<8;i++)await Promise.resolve();};
 context.CompanyBrainOperating.mount('token');await settle();
 assert.equal(elements.summary.textContent,'Idle company setting');assert.equal(timers[0].ms,15000);
 elements.target.value='worker';await elements.target.emit('change');
 elements.mode.value='off';await elements.mode.emit('change');
 current.policy.requested_state=current.policy.effective_state='active';current.policy.version=11;current.agents[0].requested_state=current.agents[0].effective_state='active';
 timers[0].fn();await settle();
 assert.equal(elements.summary.textContent,'Active company setting');assert.match(elements.saved.textContent,/Saved request: Active/);
 assert.equal(elements.target.value,'worker');assert.equal(elements.mode.value,'off');assert.equal(calls.filter(c=>c.options?.method==='POST').length,0);
 await elements.apply.click();await settle();
 assert.equal(JSON.parse(calls.find(c=>c.options?.method==='POST').options.body).state,'off');
 const pending=stored.get('company-brain-operating-request'),message=elements.message.textContent;
 assert.ok(pending);assert.equal(elements.recover.hidden,false);
 current.policy.effective_state=current.policy.requested_state='idle';current.policy.version=12;
 await window.emit('focus');await settle();
 assert.equal(elements.summary.textContent,'Idle company setting');assert.equal(elements.mode.value,'off');assert.equal(elements.target.value,'worker');
 assert.equal(stored.get('company-brain-operating-request'),pending);assert.equal(elements.message.textContent,message);
 const before=calls.length;document.visibilityState='hidden';timers[0].fn();await settle();assert.equal(calls.length,before);
 document.visibilityState='visible';release=true;
 const first=window.emit('focus');await settle();timers[0].fn();await document.emit('visibilitychange');await settle();
 assert.equal(calls.length,before+1);release();release=null;await first;await settle();
 fail=true;await window.emit('focus');await settle();
 const freshness=details.children.find(child=>child.role==='status');
 assert.equal(elements.summary.textContent,'Idle company setting');assert.match(freshness.textContent,/last successful read.*network unavailable/);
 assert.equal(elements.message.textContent,message);assert.equal(stored.get('company-brain-operating-request'),pending);
 fail=false;current.policy.effective_state=current.policy.requested_state='active';await document.emit('visibilitychange');await settle();
 assert.equal(elements.summary.textContent,'Active company setting');assert.equal(freshness.textContent,'');
 assert.equal(calls.filter(c=>c.options?.method==='POST').length,1);assert.ok(calls.filter(c=>c.path==='/api/os-operating').every(c=>c.options.cache==='no-store'));
 assert.equal(elements.mode.value,'off');assert.equal(elements.target.value,'worker');assert.equal(elements.message.textContent,message);
 console.log('Mounted refresh: external updates, preserved edits/target/pending receipt, visible-only polling, focus/visibility, no overlap, truthful read failures and no automatic writes passed.');
}
(async()=>{
 let calls=[];const fetcher=async(path,options)=>{calls.push({path,options});return options?response(200,{version:1}):response(200,{id:'a'.repeat(32),ok:true,state:'completed'});};
 let r=await controls.send(fetcher,'token',{state:'idle',version:0},'a'.repeat(32));
 assert.equal(r.state,'completed');assert.equal(calls.length,2);assert.equal(calls[0].options.headers['X-Brain-Request-ID'],'a'.repeat(32));
 assert.deepEqual(JSON.parse(calls[0].options.body),{state:'idle',version:0});assert.match(calls[1].path,/api\/command/);
 calls=[];r=await controls.send(async(path,options)=>{calls.push(path);throw Error('disconnected');},'token',{},'b'.repeat(32));
 assert.equal(r.state,'uncertain');assert.equal(calls.length,1);
 calls=[];r=await controls.send(async(path,options)=>{calls.push(path);return options?response(202,{state:'queued'}):response(200,{state:'queued'});},'token',{},'c'.repeat(32));
 assert.equal(r.state,'uncertain');assert.equal(calls.length,2);
 r=await controls.send(async()=>response(400,{error:'Expected version changed'}),'token',{},'d'.repeat(32));
 assert.equal(r.state,'failed');assert.match(r.message,/version changed/);
 r=await controls.send(async()=>response(200,{id:'foreign',ok:true,state:'completed'}),'token',{},'e'.repeat(32));
 assert.equal(r.state,'uncertain');assert.match(r.message,/identity mismatch/);
 await mountedRefresh();
 console.log('Operating controls: exact version, legacy/effective/activity distinction, single submission and receipt recovery passed.');
})().catch(error=>{console.error(error);process.exitCode=1;});
