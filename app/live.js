(function(root){'use strict';

const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

const safeUrl=u=>{if(typeof u!=='string'||/[\\\r\n]/.test(u))return null;if(u.startsWith('/')&&!u.startsWith('//'))return u;try{const p=new URL(u);return ['https:','http:'].includes(p.protocol)&&!p.username&&!p.password?u:null;}catch(e){return null;}};

function normalize(value){if(!value||!Array.isArray(value.tasks))throw Error('Invalid observation');return {...value,coverage:Array.isArray(value.coverage)?value.coverage:[],tasks:value.tasks.filter(t=>t&&typeof t.id==='string').map(t=>({...t,nodes:Array.isArray(t.nodes)?t.nodes:[],edges:Array.isArray(t.edges)?t.edges:[],outputs:Array.isArray(t.outputs)?t.outputs:[]}))};}
function visible(tasks,query,filter){return tasks.filter(t=>(filter==='all'||t.status===filter)&&JSON.stringify([t.label,t.agent_id,t.project_id,t.nodes]).toLowerCase().includes(query.toLowerCase()));}

function graph(t){

 const nodes=t.nodes||[],edges=(t.edges||[]).filter(e=>nodes.some(n=>n.id===e.source)&&nodes.some(n=>n.id===e.target));

 if(!nodes.length)return '<span>No area usage reported</span>';

 const width=680,height=Math.max(150,Math.ceil(nodes.length/3)*110+30),pos=new Map(nodes.map((n,i)=>[n.id,{x:110+(i%3)*225,y:70+Math.floor(i/3)*110}]));

 return `<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="Recorded task connections">${edges.map((e,i)=>{const a=pos.get(e.source),b=pos.get(e.target),path=`M ${a.x} ${a.y-25} Q ${(a.x+b.x)/2} ${Math.min(a.y,b.y)-65} ${b.x} ${b.y-25}`;return `<g><path class="wire" d="${path}" marker-end="url(#arrow)"/><title>${esc(e.label||'Recorded connection')}</title>${t.flash&&e.animate===true&&!(typeof matchMedia==='function'&&matchMedia('(prefers-reduced-motion: reduce)').matches)?`<circle r="3" fill="#b2ffe5"><animateMotion dur="1.5s" repeatCount="1" fill="freeze" path="${path}"/></circle>`:''}</g>`;}).join('')}<defs><marker id="arrow" viewBox="0 0 10 10" refX="10" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="#61958f"/></marker></defs>${nodes.map(n=>{const p=pos.get(n.id);return `<g><rect x="${p.x-99}" y="${p.y-24}" width="198" height="48" rx="12" class="mapnode"/><text x="${p.x}" y="${p.y-2}" text-anchor="middle">${esc(String(n.label||n.id).slice(0,25))}</text><text class="kind" x="${p.x}" y="${p.y+15}" text-anchor="middle">${esc(n.kind)}  /  ${esc(n.usage||'context')}</text><title>${esc(n.label)}  /  ${esc(n.id)}</title></g>`;}).join('')}</svg>`;

}

function row(t,selected){return `<div class="task ${esc(t.status)} ${selected===t.id?'selected':''}" data-task="${esc(t.id)}"><button><strong>${esc(t.label)}</strong><small>${esc(t.status)}  /  ${esc(t.agent_id||'Recorded task')}</small></button><div class="areas">${graph(t)}</div></div>`;}

if(typeof module!=='undefined')module.exports={esc,safeUrl,visible,row,normalize};

if(typeof document==='undefined')return;

let data={tasks:[]},selected=null,paused=false,inflight=false;const seen=new Map();let initialized=false;const $=id=>document.getElementById(id);

function draw(){const tasks=visible(data.tasks||[],$('search').value,$('filter').value);$('counts').innerHTML=['active','completed','failed','unknown'].map(s=>`<div class="count"><strong>${(data.tasks||[]).filter(t=>t.status===s).length}</strong>${{active:'Working',completed:'Completed',failed:'Recorded failures',unknown:'Observation expired'}[s]}</div>`).join('');$('graph').innerHTML=tasks.map(t=>row(t,selected)).join('');data.tasks.forEach(t=>{t.flash=false;});$('empty').textContent=tasks.length?'':'No matching activity is recorded. Unreported work is not shown as idle or complete.';const t=(data.tasks||[]).find(x=>x.id===selected);$('selection').textContent=t?`${t.label}    /  ${t.status}    /  Last report ${t.updated||'unknown'}`:'Select a task or an area to inspect its recorded work.';$('results').innerHTML=t?((t.outputs||[]).map(o=>`<div class="result">${safeUrl(o.url)?`<a href="${esc(o.url)}">${esc(o.label)}</a>`:esc(o.label)}${o.reference?'<p>'+esc(o.reference)+'</p>':''}</div>`).join('')||'<p>No output has been reported for this task.</p>')+'<h3>Recorded connections</h3>'+((t.edges||[]).map(e=>'<p>'+esc(e.source)+'  ->  '+esc(e.target)+'<br>'+esc(e.label)+'</p>').join('')||'<p>No directional connection reported.</p>')+(safeUrl(t.evidence_url)?`<p><a href="${esc(t.evidence_url)}">Inspect recorded evidence</a></p>`:''):`<p>${(data.tasks||[]).reduce((n,t)=>n+(t.outputs||[]).length,0)} output references across the observed work.</p>`;$('coverage').innerHTML=(data.coverage||[]).map(x=>`<p>${esc(x)}</p>`).join('');}

async function refresh(){if(paused||inflight||document.hidden)return;inflight=true;try{const r=await fetch('/api/live-activity',{cache:'no-store'});if(!r.ok)throw Error('Activity source unavailable');const next=normalize(await r.json());data=next;data.tasks=(data.tasks||[]).map(t=>{t={...t,status:t.status==='running'?'active':t.status};const revision=t.evidence_id||t.updated;const flash=initialized&&seen.get(t.id)!==revision&&t.status!=='unknown';seen.set(t.id,revision);return {...t,flash};});initialized=true;$('connection').textContent=data.stale?'Observation is stale    /  motion stopped':'Observing    /  '+new Date().toLocaleTimeString();draw();}catch(e){$('connection').textContent='Disconnected    /  motion stopped';data.tasks=data.tasks.map(t=>({...t,status:t.status==='active'?'unknown':t.status,flash:false}));draw();}finally{inflight=false;}}

$('graph').addEventListener('click',e=>{const el=e.target.closest('[data-task]');if(el){selected=el.dataset.task;draw();}});for(const k of ['search','filter'])$(k).addEventListener('input',draw);$('pause').onclick=()=>{paused=!paused;$('pause').textContent=paused?'Resume live view':'Pause view';if(paused){data.tasks=data.tasks.map(t=>({...t,flash:false}));draw();}document.body.classList.toggle('paused',paused);if(paused){$('connection').textContent='Paused snapshot';}else refresh();};document.addEventListener('visibilitychange',refresh);setInterval(refresh,3000);refresh();

})(globalThis);
