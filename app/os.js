let current=null, attentionOnly=false;
const el=id=>document.getElementById(id);
function node(tag,text,cls){const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;}
function link(text,href){const a=node('a',text);a.href=location.pathname==='/executive'?href.replace('http://127.0.0.1:14699/','/'):href;return a;}
function renderWorkflows(){
  const list=el('workflows');list.replaceChildren();const query=el('search').value.toLowerCase();
  const matches=current.workflows.filter(w=>(!attentionOnly||w.problems.length)&&`${w.name} ${w.description}`.toLowerCase().includes(query));
  for(const w of matches){const c=node('article',undefined,'card');c.append(node('h3',w.name),node('span',w.status,'pill'),node('p',w.description),node('p',w.mode));
    if(w.schedule)c.append(node('p',`Schedule: ${w.schedule} · ${w.schedule_status||'status unconfirmed'}`),node('p',w.schedule_evidence));
    for(const problem of w.problems)c.append(node('p',problem,'warning'));
    for(const outcome of w.outcomes){const p=node('p',`${outcome.state} · ${outcome.evidence} `);p.append(link('View request',outcome.href));if(outcome.result_href)p.append(document.createTextNode(' · '),link('Read result',outcome.result_href));c.append(p);}
    if(!w.outcomes.length)c.append(node('p','No native request results recorded here. Other execution paths are not assessed.'));
    c.append(link('Open workflow',w.href));list.append(c);
  }if(!matches.length)list.append(node('p','No workflows match this view.'));
}
function render(data){current=data;el('content').classList.remove('hidden');el('metrics').replaceChildren();
  for(const [label,value] of [['Waiting',data.counts.queued],['In progress',data.counts.running],['Recorded complete',data.counts.completed],['Failed requests',data.counts.failed]]){const c=node('div',undefined,'metric');c.append(node('strong',String(value)),node('span',label));el('metrics').append(c);}
  const p=data.publication;el('freshness').textContent=`${p.stale?'Saved view is out of date':'Recent published view'} · ${new Date(p.asof).toLocaleString('en-GB',{timeZone:'Europe/London'})} London · ${data.worker_busy?'Local worker busy':'Local worker idle'}`;
  el('freshness').className=p.stale?'warning':'muted';el('attention').replaceChildren();
  for(const item of data.attention){const c=node('div',undefined,'card');c.append(node('h3',item.name),node('p',item.reason),link('Inspect workflow',item.href));el('attention').append(c);}
  if(!data.attention.length)el('attention').append(node('p','No request or configuration problems detected by this view. This is not a full system audit.'));
  el('projects').replaceChildren();for(const p of data.projects){const c=node('div',undefined,'card');c.append(node('h3',p.name),node('p',p.scope),link('Open work area',p.href));el('projects').append(c);}
  el('memory').replaceChildren(node('p',`${data.memory.total} knowledge records · ${data.memory.current} current according to the Brain · ${data.memory.candidate} candidates`),node('p','One library. Sources, decisions and candidate ideas retain their own evidence and history.'));
  const limits=node('details'),summary=node('summary','Evidence and scope');limits.append(summary,...data.limits.map(t=>node('p',t)));el('limits').replaceChildren(limits);renderWorkflows();
}
async function refresh(){el('refresh').disabled=true;try{const r=await fetch('/api/os-overview',{cache:'no-store'});const d=await r.json();if(!r.ok)throw Error(d.error||'Unable to read Company Brain');const sr=await fetch('/api/state',{cache:'no-store'});if(!sr.ok)throw Error('Published records unavailable');const state=await sr.json();el('error').classList.add('hidden');render(d);CompanyBrainExecutive.mount(el('executive-widgets'),state);}catch(e){el('error').textContent=e.message;el('error').classList.remove('hidden');el('freshness').textContent='Connection unavailable. Any previous view below is not live.';el('freshness').className='warning';}finally{el('refresh').disabled=false;}}
el('refresh').addEventListener('click',refresh);el('search').addEventListener('input',()=>current&&renderWorkflows());el('attention-toggle').addEventListener('click',()=>{attentionOnly=!attentionOnly;el('attention-toggle').setAttribute('aria-pressed',String(attentionOnly));if(current)renderWorkflows();});refresh();
