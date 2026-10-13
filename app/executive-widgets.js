/* Pure projection and progressive disclosure over existing published records. */
(function(root){
  function project(state){
    const rows=(state.objects||[]).filter(r=>!r.archived), lookup=new Map(rows.map(r=>[r.kind+':'+r.id,r]));
    const work=[],results=[],attention=[];
    const item=r=>({name:r.data.name||r.id,href:'/#'+encodeURIComponent(r.kind)+'/'+encodeURIComponent(r.id)});
    for(const r of rows.filter(r=>r.kind==='memory'&&r.data.type==='native-work-request')){
      const d=r.data, loop=lookup.get('loop:'+d.loop_id), result=lookup.get('memory:'+d.result_ref);
      const legacy=!loop||d.loop_version!==loop.version;
      if(['queued','running'].includes(d.request_state))work.push({...item(r),status:d.request_state,legacy});
      const checked=d.request_state==='completed'&&result&&result.data.type!=='native-work-request'&&result.data.refs?.includes('loop:'+d.loop_id)&&d.completion_evidence&&d.claimant&&d.claimed_at&&d.completed_at;
      if(checked)results.push({...item(result),requestHref:item(r).href,legacy,date:d.completed_at});
      if(['failed','blocked'].includes(d.request_state)||(d.request_state==='completed'&&!checked))attention.push({...item(r),reason:d.failure_reason||'Inspect the request and its missing completion evidence.',action:'Inspect request and evidence'});
    }
    results.sort((a,b)=>String(b.date).localeCompare(String(a.date)));
    return {work,results,attention,knowledge:rows.filter(r=>r.kind==='memory'&&r.data.type!=='native-work-request').map(item)};
  }
  function mount(host,state){
    const data=project(state),n=(tag,text)=>{const x=document.createElement(tag);if(text!==undefined)x.textContent=text;return x;};
    const a=(text,href)=>{const x=n('a',text);x.href=href;return x;};host.replaceChildren();host.className='executive-widgets';
    function card(title,count,label,items,render){const c=n('article'),h=n('h2',title),number=n('strong',String(count));number.className='widget-number';const d=n('details'),s=n('summary',label+' · '+count),list=n('ul');d.append(s,list);for(const item of items){const li=n('li');render(li,item);list.append(li);}if(!items.length)list.append(n('li','Nothing recorded in this view.'));c.append(h,number,d);host.append(c);return c;}
    card('Work in motion',data.work.length,'View exact requests',data.work,(li,i)=>{li.append(a(i.name,i.href),n('p',i.status+(i.legacy?' · earlier workflow version':'')));});
    card('Checked results',data.results.length,'Read results and checks',data.results,(li,i)=>{li.append(a(i.name,i.href),n('p',i.legacy?'Earlier workflow · retained evidence':'Current workflow · checks recorded'),a('Request evidence',i.requestHref));});
    card('Needs a next step',data.attention.length,'Inspect stopped or incomplete work',data.attention,(li,i)=>{li.append(n('strong',i.name),n('p',i.reason),a(i.action,i.href));});
    const c=n('article');c.append(n('h2','Find knowledge'));const input=n('input');input.type='search';input.placeholder='Search saved names…';input.setAttribute('aria-label','Search saved knowledge names');const list=n('ul'),status=n('p','Search '+data.knowledge.length+' saved knowledge records.');status.setAttribute('role','status');input.addEventListener('input',()=>{const q=input.value.trim().toLocaleLowerCase(),matches=q?data.knowledge.filter(i=>i.name.toLocaleLowerCase().includes(q)):[];list.replaceChildren();for(const i of matches.slice(0,8)){const li=n('li');li.append(a(i.name,i.href));list.append(li);}status.textContent=q?matches.length+' matching names'+(matches.length>8?' · showing first 8':''):'Search '+data.knowledge.length+' saved knowledge records.';});c.append(input,status,list,a('Open full knowledge search','/?area=memory'));host.append(c);
  }
  root.CompanyBrainExecutive={project,mount};if(typeof module!=='undefined')module.exports={project};
})(typeof window!=='undefined'?window:globalThis);
