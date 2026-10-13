function runsView(){
 runsSignature=resultsSignature();
 const history=state.runs.filter(r=>r.context_current===false);
 const current=state.runs.filter(r=>r.context_current!==false);
 const decisions=current.filter(r=>r.state==='needs_review');
 const active=current.filter(r=>['queued','running','cancelling'].includes(r.state));
 const finished=current.filter(r=>['completed','accepted'].includes(r.state));
 const stopped=current.filter(r=>!['needs_review','queued','running','cancelling','completed','accepted'].includes(r.state));
 const requests=state.objects.filter(o=>o.kind==='memory'&&!o.archived&&o.data.type==='native-work-request').sort((a,b)=>(b.updated||'').localeCompare(a.updated||''));
 const describe=r=>r.context_current===false
   ?'Earlier output kept as history. Its sources or procedure changed; it is not ready for current reuse. No decision is requested on this old version.'
   :r.state==='needs_review'?'A draft is ready. Read the output and its checks, then accept it only if it meets your intended outcome.'
   :r.state==='accepted'?'This output was accepted. Open it to use it or check its supporting evidence.'
   :r.state==='completed'?'The workflow saved a checked candidate. It is available to read, but has not become an approved fact.'
   :['queued','running','cancelling'].includes(r.state)?'Work is recorded as in progress. You do not need to act unless you want to stop it.'
   :'Work stopped before a usable result was confirmed. Inspect the recorded reason; this is not automatically an owner decision.';
 const card=r=>`<article class="cardx"><h3>${esc(displayName(state.objects.find(o=>o.kind==='loop'&&o.id===r.loop_id),r.loop_id))}</h3><span class="tag">${esc(r.context_current===false?'History · '+resultState(r.state):resultState(r.state))}</span><p>${esc(describe(r))}</p><p>${esc(new Date(r.created).toLocaleString('en-GB',{timeZone:'Europe/London'}))} London</p>${r.error?`<details><summary>Recorded outcome notes</summary><p>${esc(r.error)}</p></details>`:''}<button data-run="${r.id}">${r.context_current===false?'Inspect earlier output':r.state==='needs_review'?'Read draft and checks':'Open output and checks'}</button></article>`;
 const section=(title,items)=>items.length?`<section><h3>${title}</h3><div class="cards">${items.map(card).join('')}</div></section>`:'';
 const nativeCard=o=>{const d=o.data,result=state.objects.find(x=>x.kind==='memory'&&x.id===d.result_ref&&!x.archived);const done=d.request_state==='completed';return `<article class="cardx"><h3>${esc(displayName(result||state.objects.find(x=>x.kind==='loop'&&x.id===d.loop_id),d.name))}</h3><span class="tag">${esc(done?(result?'Recorded result available':'Result link needs checking'):d.request_state==='failed'?'Stopped':d.request_state==='running'?'In progress':'Waiting for Codex')}</span><p>${esc(done?'The native workflow recorded a result and completion evidence. Open it to see the actual findings.':d.request_state==='failed'?(d.failure_reason||'The request did not complete. Inspect its recorded reason.'):'The request is queued or owned by a worker. A request is not yet a finished result.')}</p>${result?recordLink('memory',result.id,'Read saved result'):''}<p>${recordLink('memory',o.id,'Request and evidence')}</p></article>`;};
 const nativeDone=requests.filter(o=>o.data.request_state==='completed');
 const nativePending=requests.filter(o=>['queued','running'].includes(o.data.request_state));
 const nativeStopped=requests.filter(o=>!['completed','queued','running'].includes(o.data.request_state));
 const nativeSection=(title,items)=>items.length?'<section><h3>'+title+'</h3><div class="cards">'+items.map(nativeCard).join('')+'</div></section>':'';
 const native=nativeSection('Saved native results',nativeDone)+nativeSection('Waiting or in progress',nativePending)+(nativeStopped.length?'<details id="nativeResultHistory"><summary>Stopped native requests · '+nativeStopped.length+'</summary><p>Retained failure reasons and evidence. These requests are not finished outputs.</p><div class="cards">'+nativeStopped.map(nativeCard).join('')+'</div></details>':'');
 V.innerHTML=`<h2>Results</h2><p>What was produced, what was checked, and what happens next.</p><section class="editor"><h3>${decisions.length?decisions.length+' draft(s) need your decision':'No current draft needs your decision'}</h3><p>${decisions.length?'Review the drafts below. Acceptance records your decision; it does not run the work again.':'Earlier runs and stopped work are kept below for reference. A technical status alone is not a request for you to intervene.'}</p></section>${section('Needs your decision',decisions)}${section('In progress',active)}${section('Available outputs',finished)}${native}${section('Stopped work',stopped)}${history.length?`<details id="resultHistory"><summary>Earlier runs · ${history.length} · sources changed</summary><p>These outputs retain their original checks and history. Open the owning workflow only if you need a fresh result. They are not current approval requests.</p><div class="cards">${history.map(card).join('')}</div></details>`:''}${!state.runs.length&&!requests.length?'<p>No outputs have been recorded yet. Start from a workflow or your native Codex chat.</p>':''}<div id="runDetail"></div>`;
 document.querySelectorAll('[data-run]').forEach(b=>b.onclick=()=>{const hash='#run/'+b.dataset.run;if(location.hash===hash)safe(followRoute);else location.hash=hash});
 if(runId)safe(runDetail);
}
