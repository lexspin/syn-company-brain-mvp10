const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const source=fs.readFileSync(require('node:path').join(__dirname,'../app/connections-view.js'),'utf8');
const ctx={esc:s=>String(s??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;')};
vm.createContext(ctx);vm.runInContext(source,ctx);
assert.equal(ctx.connectionToolChecks(null),'');
const mixed=ctx.connectionToolChecks({tool_checks:[
 {tool:'identity',status:'returned',result:'Identity only',evidence_validated:true},
 {tool:'search',status:'failed',result:'Missing <tool>',evidence_validated:true},
 {tool:'jobs',status:'unverified',result:'Not called'}],next_action:'Refresh list'});
assert.match(mixed,/Read returned/);assert.match(mixed,/Read failed/);assert.match(mixed,/Not tested/);
assert.match(mixed,/Missing &lt;tool>/);assert.doesNotMatch(mixed,/Missing <tool>/);
assert.match(mixed,/Next step:.*Refresh list/);
assert.match(ctx.connectionToolChecks({tool_checks:[{tool:'future',status:'new-status',result:'Unknown'}]}),/Evidence not validated/);
console.log('Connection evidence: absent, mixed, escaped, recovery and unknown status checks passed.');
assert.equal(ctx.connectionStatus({recorded_status:'available-in-codex-host'}),'Not yet tested');
assert.equal(ctx.connectionStatus({probe:{tool_checks:[{status:'returned',evidence_validated:true},{status:'failed',evidence_validated:true}]}}),'Partly working');
assert.equal(ctx.connectionStatus({probe:{tool_checks:[{status:'returned',evidence_validated:true},{status:'unverified'}]}}),'Reads verified');
assert.equal(ctx.connectionStatus({probe:{tool_checks:[{status:'failed',evidence_validated:true}]}}),'Connection failed');
assert.equal(ctx.connectionStatus({recorded_status:'live-read-verified'}),'Not yet tested');
assert.equal(ctx.connectionStatus({recorded_status:'unreachable'}),'Not yet tested');
assert.equal(ctx.connectionStatus({probe:{tool_checks:[{tool:'imaginary',status:'returned'}]}}),'Not yet tested');
