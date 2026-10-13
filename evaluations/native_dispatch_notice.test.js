const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const source=fs.readFileSync(require('node:path').join(__dirname,'../app/workspace.html'),'utf8');
const helper=source.slice(source.indexOf('function nativeDispatchNotice()'),source.indexOf('function recordCard('));
function notice(status,archived=false){const context={state:{objects:status?[{kind:'loop',id:'native-workflow-dispatch',archived,data:{execution:{status}}}]:[]}};vm.createContext(context);vm.runInContext(helper,context);return context.nativeDispatchNotice();}
assert.match(notice('PAUSED'),/paused.*waits/);
assert.doesNotMatch(notice('PAUSED'),/every five/);
assert.match(notice('ACTIVE'),/host availability and operating mode/);
assert.match(notice(null),/unavailable/);
assert.match(notice('ACTIVE',true),/unavailable/);
assert.ok(source.includes('${esc(nativeDispatchNotice())}'));
assert.ok(source.includes("This has not run yet. '+nativeDispatchNotice()"));
console.log('7 dispatcher notice assertions passed');
