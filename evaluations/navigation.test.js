const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../app/mvp02-navigation.js'),'utf8');
function entry(href,selected='Overview'){
 const stored=new Map([['brain-tab',selected]]);
 let url=new URL(href);
 const ctx={URL,URLSearchParams,location:url,localStorage:{setItem:(k,v)=>stored.set(k,v)},
  history:{replaceState:(_,__,value)=>{url=new URL(value,url)}}};
 vm.runInNewContext(source,ctx);
 return {url:url.href,selected:stored.get('brain-tab')};
}
const hub=entry('http://127.0.0.1:14702/?area=hubs');
assert.equal(hub.selected,'Hubs');
assert.equal(entry(hub.url,'Graph').selected,'Graph','A MAPS reload must not reopen Hubs');
const linked=entry('http://127.0.0.1:14702/?area=maps&filter=team#agent/coordinator');
assert.equal(linked.selected,'Graph');
assert.equal(linked.url,'http://127.0.0.1:14702/?filter=team#agent/coordinator');
assert.deepEqual(entry('http://127.0.0.1:14702/?area=unknown','Runs'),
 {url:'http://127.0.0.1:14702/?area=unknown',selected:'Runs'});
console.log('3 navigation regression scenarios passed');
