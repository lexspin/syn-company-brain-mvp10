/* Requested admission settings; independent of observed backend activity. */
(function(root){
  'use strict';
  const modes=['off','idle','active'];
  const label=s=>modes.includes(s)?s[0].toUpperCase()+s.slice(1):'Unknown';
  const escape=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  function selected(view,target){return target?view.agents.find(a=>a.id===target):view.policy;}
  function body(view,target,mode){
    const row=selected(view,target);
    if(!row||!modes.includes(mode)||!Number.isInteger(row.version)||row.version<0)throw Error('Refresh the operating settings before applying a change.');
    return {state:mode,version:row.version,...(target?{agent_id:target}:{})};
  }
  function description(view,target){
    const row=selected(view,target);
    if(!row)return 'This team member is no longer available. Refresh the settings.';
    let requested=row.requested_state?label(row.requested_state):target?'Use company setting':view.policy.source==='legacy-active'?'Active (legacy; not configured)':'Unavailable';
    return `Saved request: ${requested}. Effective admission: ${label(row.effective_state)}.`;
  }
  function activity(view){
    const a=view.activity||{},v=a.view||{};
    let result=a.worker_busy===true?'Backend reported work in progress':a.worker_busy===false?'Backend reported no work in progress':'Backend activity unavailable';
    if(v.asof)result+=` · ${v.asof}`;
    if(v.stale)result+=' · saved view is stale';
    return result+'. Native chat activity is not reported here.';
  }
  async function receipt(fetcher,id){
    const response=await fetcher('/api/command?id='+encodeURIComponent(id));
    if(!response.ok)throw Error('Receipt unavailable. Keep request '+id+' and check again; do not resubmit.');
    const result=await response.json();
    if(result.id!==id)throw Error('Receipt identity mismatch. Keep request '+id+' and reconcile it before another change.');
    return result;
  }
  async function send(fetcher,token,payload,id){
    let response,data;
    try{
      response=await fetcher('/api/operating-state',{method:'POST',headers:{'Content-Type':'application/json','X-Brain-Token':token,'X-Brain-Request-ID':id},body:JSON.stringify(payload)});
      data=await response.json();
    }catch(error){return {state:'uncertain',id,message:'The outcome is not yet known. Check this same request before trying another change.'};}
    if(!response.ok&&response.status<500&&data.state!=='uncertain')return {state:'failed',id,message:data.error||'The setting was rejected. Refresh before trying again.'};
    try{
      const saved=await receipt(fetcher,id);
      if(saved.ok&&saved.state==='completed')return {state:'completed',id,message:'Requested setting saved.'};
      if(['failed','interrupted'].includes(saved.state))return {state:saved.state,id,message:saved.error||'The request did not complete. Review its receipt.'};
      return {state:'uncertain',id,message:'The request is still pending. Check its receipt before making another change.'};
    }catch(error){return {state:'uncertain',id,message:error.message};}
  }
  function mount(token){
    const host=document.getElementById('operating-controls');if(!host||host.dataset.mounted)return;
    host.dataset.mounted='yes';
    host.innerHTML='<details style="border:1px solid #39504b;border-radius:8px;padding:10px 14px;margin:8px 0 16px"><summary style="cursor:pointer">Operating mode · <span data-summary>Loading settings…</span></summary><p>Off pauses new work. Idle admits bounded upkeep. Active permits normal authorised work. Existing work is not cancelled.</p><div style="display:flex;gap:12px;flex-wrap:wrap;align-items:end"><label>Applies to<br><select data-target aria-label="Operating setting target"><option value="">Company</option></select></label><label>Requested mode<br><select data-mode aria-label="Requested operating mode"><option value="off">Off</option><option value="idle">Idle</option><option value="active">Active</option></select></label><button data-apply disabled>Apply setting</button><button data-refresh>Refresh settings</button></div><p data-saved></p><p data-profile></p><p data-rules></p><p data-activity></p><p data-message role="status" aria-live="polite"></p><button data-recover hidden>Check pending request</button></details>';
    const el=k=>host.querySelector('[data-'+k+']');let view=null,target='',busy=false,pending=null,refreshing=false,dirty=false,readError=false;
    const freshness=document.createElement('p');freshness.setAttribute('role','status');host.querySelector('details').append(freshness);
    if(host.dataset.expanded==='true')host.querySelector('details').open=true;
    const choices=document.createElement('div');choices.setAttribute('role','group');choices.setAttribute('aria-label','Choose operating mode');choices.style='display:flex;gap:8px;margin:12px 0';
    for(const mode of modes){const button=document.createElement('button');button.type='button';button.textContent=label(mode);button.dataset.choice=mode;button.setAttribute('aria-pressed','false');button.disabled=true;button.addEventListener('click',()=>{if(busy||pending||!view)return;el('mode').value=mode;el('apply').click();});choices.append(button);}
    host.querySelector('details').insertBefore(choices,host.querySelector('details').children[2]);
    const storageKey='company-brain-operating-request';
    try{pending=JSON.parse(sessionStorage.getItem(storageKey)||'null');if(pending&&!/^[a-f0-9]{32}$/.test(pending.id))pending=null;}catch(error){pending=null;}
    function remember(value){pending=value;try{value?sessionStorage.setItem(storageKey,JSON.stringify(value)):sessionStorage.removeItem(storageKey);}catch(error){} }
    function draw(){
      const row=view&&selected(view,target);
      el('apply').disabled=busy||refreshing||!!pending||readError||!row||!view.controls_available;
      el('target').disabled=busy||!!pending;el('mode').disabled=busy||!!pending;
      for(const button of choices.children){button.disabled=busy||refreshing||!!pending||readError||!row||!view?.controls_available;button.setAttribute('aria-pressed',String(button.dataset.choice===row?.effective_state));button.style=button.dataset.choice===row?.effective_state?'border-color:#d1ec97;background:#354b38;font-weight:700':'';}
      el('recover').hidden=!pending;el('recover').disabled=busy||refreshing;el('refresh').disabled=busy||refreshing;
      if(!view)return;
      el('summary').textContent=label(view.policy.effective_state)+(view.policy.source==='legacy-active'?' legacy default':' company setting');
      el('saved').textContent=description(view,target);
      el('profile').textContent=target&&row?`Saved model: ${row.model||'not recorded'} · reasoning effort: ${row.reasoning_effort||'not recorded'}. This control does not change either.`:'';
      el('rules').textContent=target?'The more restrictive company or team setting wins. Active here still obeys the company setting.':`Idle admits up to ${view.policy.idle.max_batch} routines per batch, with a ${view.policy.idle.cooldown_seconds}-second cooldown. Scheduled pulses are paused or resumed separately through Codex; this button changes work admission only.`;
      el('activity').textContent=activity(view);
    }
    function syncMode(){const row=view&&selected(view,target);if(row&&!dirty&&!pending&&!busy)el('mode').value=modes.includes(row.requested_state)?row.requested_state:row.effective_state;}
    async function load(){
      if(refreshing||busy)return;
      refreshing=true;draw();
      try{
        const response=await fetch('/api/os-operating',{cache:'no-store'});const value=await response.json();if(!response.ok)throw Error(value.error||'Settings unavailable.');
        view=value;readError=false;
        el('target').innerHTML='<option value="">Company</option>'+view.agents.map(a=>`<option value="${escape(a.id)}">${escape(a.name)}</option>`).join('');
        if(target&&!selected(view,target))el('target').innerHTML+=`<option value="${escape(target)}">Unavailable team member</option>`;
        el('target').value=target;
        freshness.textContent=view.policy.error||'';syncMode();
      }catch(error){readError=true;freshness.textContent=(view?'Settings refresh failed; showing the last successful read. ':'')+error.message;if(!view)el('summary').textContent='Unavailable';}
      finally{refreshing=false;draw();}
    }
    el('target').addEventListener('change',()=>{target=el('target').value;dirty=false;if(!pending)el('message').textContent='';syncMode();draw();});
    el('mode').addEventListener('change',()=>{dirty=true;});
    el('refresh').addEventListener('click',load);
    el('apply').addEventListener('click',async()=>{
      if(busy||refreshing||pending||readError||!view)return;
      const payload=body(view,target,el('mode').value),id=crypto.randomUUID().replaceAll('-','');
      remember({id});busy=true;draw();el('message').textContent='Saving requested setting…';
      const result=await send(fetch,token,payload,id);busy=false;
      if(result.state==='completed'||result.state==='failed')remember(null);
      if(result.state==='completed')dirty=false;
      el('message').textContent=result.message+(pending?' Request '+id+'.':'');draw();
      if(result.state==='completed')await load();
    });
    el('recover').addEventListener('click',async()=>{
      if(!pending||busy||refreshing)return;busy=true;draw();
      try{const r=await receipt(fetch,pending.id);
        if(r.ok&&r.state==='completed'){remember(null);dirty=false;el('message').textContent='Requested setting saved.';}
        else if(r.state==='failed'){remember(null);el('message').textContent=r.error||'Setting rejected. Refresh before retrying.';}
        else el('message').textContent='Outcome still needs reconciliation. Keep request '+pending.id+'; do not resubmit.';
      }catch(error){el('message').textContent=error.message;}
      finally{busy=false;draw();if(!pending)await load();}
    });
    if(pending)el('message').textContent='A previous request needs a receipt check before another change. Request '+pending.id+'.';
    const refreshVisible=()=>{if(document.visibilityState!=='hidden'&&host.isConnected)load();};
    root.addEventListener('focus',refreshVisible);
    document.addEventListener('visibilitychange',refreshVisible);
    const interval=root.setInterval(()=>{if(!host.isConnected){root.clearInterval(interval);root.removeEventListener('focus',refreshVisible);document.removeEventListener('visibilitychange',refreshVisible);return;}refreshVisible();},15000);
    load();
  }
  const api={body,description,activity,send,receipt,mount};
  root.CompanyBrainOperating=api;if(typeof module!=='undefined'&&module.exports)module.exports=api;
})(globalThis);
