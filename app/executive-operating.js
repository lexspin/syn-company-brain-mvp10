// Reuse the canonical same-origin session and receipt-bound controls.
(async()=>{
  const host=document.getElementById('operating-controls');
  try{
    const response=await fetch('/',{cache:'no-store'});
    if(!response.ok)throw Error('Company controls are unavailable.');
    const html=await response.text();
    const match=html.match(/\bconst\s+token\s*=\s*['"]([A-Za-z0-9_-]+)['"]/);
    if(!match)throw Error('Company controls could not connect to the current session.');
    CompanyBrainOperating.mount(match[1]);
  }catch(error){host.textContent=error.message;host.setAttribute('role','alert');}
})();
