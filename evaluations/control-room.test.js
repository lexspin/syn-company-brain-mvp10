const fs=require('node:fs'),vm=require('node:vm'),path=require('node:path'),assert=require('node:assert/strict');
let base=fs.readFileSync(path.join(__dirname,'map-live.test.js'),'utf8').split('(async()=>{')[0];
base=base.replace('window.test={refresh,','window.test={imageStrip,evidencePeek,inspectSource,historyState,branchTree,historyList,sourceLink,refresh,');
base=base.replace('signals,notices,tasks,gaps','sourcePreview,signals,notices,tasks,gaps');
const sandbox={require,__dirname,console,URL,URLSearchParams};vm.runInNewContext(base+';this.fixture=fixture;this.task=task;this.event=event;',sandbox);
(async()=>{
 const f=sandbox.fixture(),task=sandbox.task,event=sandbox.event;
 const selected=task('old',{id:'native:selected',status:'completed'});
 const busy=Array.from({length:8},(_,i)=>task('a',{id:'native:busy'+i}));
 f.payload({tasks:[...busy,selected]});await f.api.refresh();f.api.selectTask('native:selected');
 f.history('selected',[event('old')]);
 for(let n=0;n<3;n++){for(let i=0;i<8;i++)f.history('busy'+i,[event('a'),event('n'+n)]);f.payload({tasks:[...busy.map(t=>({...t,evidence_id:'n'+n})),selected]});await f.api.refresh();}
 assert.ok(f.calls.some(u=>u.includes('task_id=selected')),'selected history must not starve behind eight active workers');
 assert.match(f.api.historyState({id:'request:q',status:'queued'}),/not started/i,'queued work is not a broken loading timeline');
 assert.equal(f.api.sourceLink({reference:'skill:company-brain-harness'}),'/api/file?path=record%2Fskill%3Acompany-brain-harness');
 assert.equal(f.api.sourceLink({reference:'javascript:alert(1)'}),'');
 const tree=f.api.branchTree();assert.match(tree,/selected/);assert.doesNotMatch(tree,/undefined/);
 const pending=[];f.box.fetch=()=>new Promise(resolve=>pending.push(resolve));const first=f.api.inspectSource('skill:first','1'),second=f.api.inspectSource('skill:second','2');pending[1]({ok:true,json:async()=>[{version:2,data:{name:'Second',instructions:'Readable source text'}}]});await second;pending[0]({ok:false});await first;assert.match(f.api.state().sourcePreview,/Readable source text/);assert.equal(f.api.state().focusEvent.task,'native:selected','source inspection pins the displayed task');assert.equal(f.api.state().selectedEvents.length,1,'source preview remains bound to its original event');assert.doesNotMatch(f.api.state().sourcePreview,/unavailable/,'stale failed fetch must not overwrite newer source');
 f.api.selectBranches('native:selected');assert.equal(f.api.state().sourcePreview,'','branch change clears prior source');
 const images=f.api.imageStrip({filtered:[{task:selected,event:{at:new Date().toISOString(),event_id:'photo',outputs:[{label:'Local preview',reference:'/creative/assets/example.png'},{label:'Remote',reference:'https://example.com/image.png'}]}}]});assert.match(images,/<img src="\/creative\/assets\/example.png"/);assert.doesNotMatch(images,/<img src="https:/,'remote image pointers are never auto-fetched');
 console.log('Control room: selected-history priority, queued explanation, safe source navigation and branch tree passed');
})().catch(e=>{console.error(e);process.exitCode=1});
