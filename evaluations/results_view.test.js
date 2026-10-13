const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const source=fs.readFileSync(require('node:path').join(__dirname,'../app/results-view.js'),'utf8');
function render(runs,objects=[]){
 const context={state:{runs,objects,memory_freshness:{}},V:{innerHTML:''},runId:null,runsSignature:'',
  // The mounted workspace supplies this refresh-signature helper to runsView.
  resultsSignature:()=>JSON.stringify([context.state.runs,context.state.objects,context.state.memory_freshness]),
  esc:s=>String(s??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;'),
  resultState:s=>s,displayName:(o,f)=>o?.data?.name||f,
  recordLink:(kind,id,label)=>`<a href="#${kind}/${id}">${label}</a>`,
  document:{querySelectorAll:()=>[]}};
 vm.createContext(context);vm.runInContext(source+'\nrunsView();',context);return context.V.innerHTML;
}
const base={id:'test',loop_id:'workflow',created:'2026-10-10T22:00:00Z'};
const stale=render([{...base,state:'needs_review',context_current:false,error:'Old failure'}]);
assert.match(stale,/No current draft needs your decision/);
assert.match(stale,/<details id="resultHistory">/);
assert.doesNotMatch(stale,/Why this needs attention|<h3>Needs your decision/);
const review=render([{...base,state:'needs_review',context_current:true}]);
assert.match(review,/1 draft\(s\) need your decision/);
assert.match(review,/Read draft and checks/);
const stopped=render([{...base,state:'failed',error:'<unsafe>',context_current:true}]);
assert.match(stopped,/<h3>Stopped work/);assert.match(stopped,/&lt;unsafe>/);
assert.match(stopped,/No current draft needs your decision/);
const native=render([],[{kind:'memory',id:'req',data:{type:'native-work-request',request_state:'completed',result_ref:'saved',name:'Native work'}},
 {kind:'memory',id:'saved',data:{name:'Saved result'}}]);
assert.match(native,/Read saved result/);assert.match(native,/Recorded result available/);
const missing=render([],[{kind:'memory',id:'req',data:{type:'native-work-request',request_state:'completed',result_ref:'missing'}}]);
assert.match(missing,/Result link needs checking/);assert.doesNotMatch(missing,/Read saved result/);
console.log('Results view: five behavior checks passed.');
