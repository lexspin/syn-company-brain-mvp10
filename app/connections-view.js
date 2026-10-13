async function connectionsView(){
 V.innerHTML='<h2>Connections</h2><p>Loading recorded capabilities and checks…</p>';
 const catalog=await api('/api/os-connections');if(tab!=='Connections')return;
 const groups={};catalog.connections.forEach(c=>{const label=connectionStatus(c);groups[label]=(groups[label]||0)+1;});
 V.innerHTML='<h2>Connections</h2><p>What Company Brain can use, what failed, and what still needs a test.</p><section class="editor"><h3>Connection checks</h3><p>'+Object.entries(groups).map(([label,count])=>esc(label)+': '+count).join(' · ')+'</p><p>Checks apply only to the operations listed below. A successful read does not verify generation or publishing.</p><p>Evidence updated: '+esc(catalog.observed_at||'Date not recorded')+'</p></section><label><span>Find a connection or area</span><input id="connectionQuery" type="search" placeholder="Search tools, projects or skills"></label><label><span>Show</span><select id="connectionStatus"><option value="">All connections</option><option>Reads verified</option><option>Partly working</option><option>Connection failed</option><option>Not yet tested</option></select></label><div id="connectionCards" class="cards"></div>';
 const render=()=>{const query=document.getElementById('connectionQuery').value.toLowerCase();const status=document.getElementById('connectionStatus').value;document.getElementById('connectionCards').innerHTML=catalog.connections.filter(c=>JSON.stringify(c).toLowerCase().includes(query)&&(!status||connectionStatus(c)===status)).map(c=>{
 const recorded=connectionStatus(c);
 const execution=c.execution==='not-connected-to-cli'?'Available to native Codex when exposed; not connected as a V2 execution adapter.':c.execution==='selected-current-source-versions-read-only'?'Scoped read-only memory adapter.':c.execution;
 return '<article class="cardx"><h3>'+esc(c.name)+'</h3><span class="tag">'+recorded+'</span><p>'+esc(execution)+'</p><p>'+c.tool_count+' tools listed</p><h4>Linked areas and skills</h4>'+(c.related.length?c.related.map(r=>'<p>'+recordLink(r.kind,r.id,r.name)+' · '+esc(r.relationship)+'</p>').join(''):'<p>No explicit area or tool-reference link recorded.</p>')+'<h4>Recorded check</h4><p>'+esc(c.probe?.result||'No test result recorded. Functionality is unverified.')+'</p>'+(c.probe?.date?'<p>Checked '+esc(c.probe.date)+'</p>':'')+connectionToolChecks(c.probe)+'<p>'+esc(c.usage)+'</p><details><summary>Tool and evidence details</summary><pre>'+esc(JSON.stringify({tools:c.tools,evidence:c.probe},null,2))+'</pre></details></article>';
 }).join('')||'<p>No connections match this search.</p>';};
 document.getElementById('connectionQuery').addEventListener('input',render);document.getElementById('connectionStatus').addEventListener('change',render);render();
}

function connectionStatus(connection){
 const checks=connection.probe?.tool_checks||[];
 const returned=checks.some(c=>c.status==='returned'&&c.evidence_validated===true);
 const failed=checks.some(c=>c.status==='failed'&&c.evidence_validated===true);
 if(returned&&failed)return 'Partly working';
 if(failed)return 'Connection failed';
 if(returned)return 'Reads verified';
 return 'Not yet tested';
}

function connectionToolChecks(probe){
 const checks=probe?.tool_checks||[];
 if(!checks.length)return '';
 const labels={returned:'Read returned',failed:'Read failed',unverified:'Not tested'};
 return '<h4>Checks by tool</h4><ul>'+checks.map(check=>'<li><b>'+esc(check.label||check.tool)+'</b> · '+esc(check.evidence_validated===true?labels[check.status]||'Not verified':check.status==='unverified'?'Not tested':'Evidence not validated')+'<p>'+esc(check.result)+'</p></li>').join('')+'</ul>'+(probe.next_action?'<p><b>Next step:</b> '+esc(probe.next_action)+'</p>':'');
}

function knowledgeHubsView(){
 const hubs=state.objects.filter(o=>o.kind==='memory'&&!o.archived&&o.data.type==='knowledge-hub');
 V.innerHTML='<h2>Knowledge Hubs</h2><p>Researched places to find methods, tools and evidence. Each card records what was inspected and when to use it.</p><section class="editor"><h3>Not sure how to approach a task?</h3><p>Recall previous work → choose relevant hubs → compare methods and available tools → check a practical plan → work and retain the result.</p>'+recordLink('loop','thinking-task-intake','Plan a thinking task')+'</section><label><span>Find a hub by topic</span><input id="hubQuery" type="search" placeholder="Try workflows, memory, plugins or skills"></label><div id="hubCards" class="cards"></div>';
 const render=()=>{const query=document.getElementById('hubQuery').value.toLowerCase();const matches=hubs.filter(o=>JSON.stringify(o.data).toLowerCase().includes(query));document.getElementById('hubCards').innerHTML=matches.map(o=>{const d=o.data;const related=(d.refs||[]).map(ref=>state.objects.find(r=>!r.archived&&r.kind+':'+r.id===ref)).filter(Boolean);return '<article class="cardx"><h3>'+esc(d.name.replace(/^Knowledge hub: /,''))+'</h3><span class="tag">Sources reviewed '+esc(d.reviewed_at||'date unrecorded')+'</span><p>'+esc(d.use_when||'Open the library entry for its purpose.')+'</p><p><b>Use this for</b><br>'+esc(d.search_method||'Read the source and check its fit for your task.')+'</p><p>'+webLink(d.url,'Explore source')+' · '+recordLink('memory',o.id,'Read findings')+'</p><details><summary>Connected work ('+related.length+')</summary>'+related.map(r=>'<p>'+recordLink(r.kind,r.id,r.display_name||r.data.name||r.id)+'</p>').join('')+'</details><details><summary>What was checked and what remains</summary><p>'+esc(d.coverage||'Coverage not recorded.')+'</p><p>'+esc(d.limits||'Runtime not verified.')+'</p></details></article>';}).join('')||'<p>No indexed hubs match this topic.</p>';};
 document.getElementById('hubQuery').addEventListener('input',render);render();
}
