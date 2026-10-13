const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const catalog = require('../app/harness-catalog.js');

class Element {
  constructor(tag='div') {this.tagName=tag;this.children=[];this.listeners={};this.textContent='';this.value='';this.disabled=false;}
  append(...children) {this.children.push(...children);}
  replaceChildren(...children) {this.children=[...children];}
  addEventListener(type, handler) {this.listeners[type]=handler;}
  set innerHTML(value) {throw new Error('Unsafe HTML rendering');}
}
const flatten = node => [node, ...node.children.flatMap(flatten)];
const content = node => flatten(node).map(item=>item.textContent).join(' ');
const commit = 'a'.repeat(40), skillPath = 'skills/research/source-check/SKILL.md';
function skill(name='Source check') {return {name,description:'Inspect exact evidence.',category:'research',path:skillPath,commit,
  source_url:'https://github.com/NousResearch/hermes-agent/blob/'+commit+'/'+skillPath,sha256:'b'.repeat(64),
  adoption_status:'catalogued-not-installed-not-executed',fit_validation:'not-evaluated',
  dependency_signals:['network-mentioned'],dependency_gaps:['Provider availability needs review.'],support_file_count:2};}
function response(skills=[skill()]) {return {commit,skills,skills_total:214,matches_total:skills.length,captured_at:'2026-10-11',
  categories:[{name:'research',count:19}],truncated:false};}
const document = {createElement:tag=>new Element(tag)};

assert.equal(catalog.safeSource(skill().source_url,commit,skillPath),skill().source_url);
for(const value of ['javascript:alert(1)','https://evil.test/source','https://github.com.evil.test/source',skill().source_url+'?redirect=x',skill().source_url+'#script']) {
  assert.equal(catalog.safeSource(value,commit,skillPath),null);
}
assert.equal(catalog.safeSource('https://github.com/NousResearch/hermes-agent/blob/'+commit+'/skills/../SKILL.md',commit,'skills/../SKILL.md'),null);
assert.equal(catalog.safeSource(skill().source_url,'main',skillPath),null);

const malicious = skill('<img src=x onerror=alert(1)>'); malicious.description='<script>run()</script>';
const card = catalog.skillCard(document,malicious);
assert.match(content(card),/<img src=x onerror=alert\(1\)>/);
assert.equal(flatten(card).filter(node=>node.tagName==='img'||node.tagName==='script').length,0);
assert.match(content(card),/Catalogued source/); assert.match(content(card),/unevaluated/);
const link = flatten(card).find(node=>node.tagName==='a'); assert.equal(link.rel,'noopener noreferrer');
const unsafeCard = catalog.skillCard(document,{...skill(),source_url:'javascript:alert(1)'});
assert.equal(flatten(unsafeCard).filter(node=>node.tagName==='a').length,0);
assert.match(content(unsafeCard),/Source link unavailable/);
assert.throws(()=>catalog.checkedResponse(response([{...skill(),adoption_status:'verified'}])));
assert.throws(()=>catalog.checkedResponse(response([{...skill(),fit_validation:'tested'}])));
assert.throws(()=>catalog.checkedResponse(response(Array(33).fill(skill()))));
assert.throws(()=>catalog.checkedResponse({...response(),skills_total:-1}));
assert.throws(()=>catalog.checkedResponse({...response(),categories:[{name:'research',count:'pretend'}]}));

function fixture() {
  const ids=['catalog-search','catalog-query','catalog-category','catalog-submit','catalog-clear','catalog-status','catalog-pin','catalog-results'];
  const nodes=Object.fromEntries(ids.map(id=>[id,new Element()]));
  return {nodes,document:{createElement:tag=>new Element(tag),getElementById:id=>nodes[id]}};
}
const flush=()=>new Promise(resolve=>setImmediate(resolve));
function ok(value) {return {ok:true,text:async()=>JSON.stringify(value)};}

async function main() {
  const f=fixture(),calls=[];let value=response(),failure=false;
  catalog.mount(f.document,async(url,options)=>{calls.push({url,options});if(failure)throw new Error('Unavailable');return ok(value);});
  await flush();assert.match(f.nodes['catalog-status'].textContent,/1 of 1.*214/);
  assert.equal(f.nodes['catalog-results'].children.length,1);
  f.nodes['catalog-query'].value='<script> & exact'; f.nodes['catalog-category'].value='research';
  await f.nodes['catalog-search'].listeners.submit({preventDefault(){}});
  const request=new URL(calls.at(-1).url,'http://127.0.0.1');
  assert.equal(request.searchParams.get('query'),'<script> & exact');
  assert.equal(request.searchParams.get('category'),'research');assert.equal(request.searchParams.get('limit'),'32');
  assert.ok(calls.every(c=>c.options.method==='GET'));
  value=response([]);await f.nodes['catalog-search'].listeners.submit({preventDefault(){}});
  assert.match(f.nodes['catalog-status'].textContent,/No sources match/);
  failure=true;await f.nodes['catalog-search'].listeners.submit({preventDefault(){}});
  assert.match(f.nodes['catalog-status'].textContent,/could not be loaded.*retry/);
  assert.equal(f.nodes['catalog-submit'].disabled,false);assert.equal(f.nodes['catalog-results'].children.length,0);
  failure=false;value=response();await f.nodes['catalog-clear'].listeners.click();
  assert.equal(f.nodes['catalog-query'].value,'');assert.equal(f.nodes['catalog-category'].value,'');
  assert.equal(f.nodes['catalog-results'].children.length,1);

  const race=fixture();let resolveOld;let invocation=0;
  const mounted=catalog.mount(race.document,async()=>{invocation++;if(invocation===1)return new Promise(resolve=>resolveOld=resolve);return ok(response([skill('New result')]));});
  await mounted.load();resolveOld(ok(response([skill('Old result')])));await flush();
  assert.match(content(race.nodes['catalog-results']),/New result/);assert.doesNotMatch(content(race.nodes['catalog-results']),/Old result/);

  const html=fs.readFileSync(path.join(__dirname,'../app/harness-catalog.html'),'utf8');
  assert.match(html,/Local adaptations/);assert.match(html,/Pinned upstream resources/);
  assert.match(html,/not been installed, executed or evaluated/);
  assert.match(html,/\/docs\/HERMES-ADAPTATION\.md/);
  assert.doesNotMatch(html,/<button[^>]*>\s*(Install|Import|Execute|Run skill)/i);
  console.log('Harness catalogue UI: safe links, text-only rendering, honest statuses, bounded response, query/category GET, empty/error/retry, stale-response protection and local/upstream separation passed.');
}
main().catch(error=>{console.error(error);process.exitCode=1;});
