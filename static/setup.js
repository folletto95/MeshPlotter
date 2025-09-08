async function loadNodes(){
  let nodes=[];
  try{
    // FIXME: skip nodes with no activity until real info is present
    const res=await fetch('/api/nodes?include_inactive=false');
    nodes=await res.json();
  }catch{
    nodes=[];
  }
  const sel=document.getElementById('centerNode');
  sel.innerHTML='';
  const optNone=document.createElement('option');
  optNone.value='';
  optNone.textContent='-- Nessuno --';
  sel.appendChild(optNone);
  const current=localStorage.getItem('centerNodeId')||'';
  for(const n of nodes){
    if(n.lat==null||n.lon==null) continue;
    const opt=document.createElement('option');
    opt.value=n.node_id;
    opt.textContent=n.display_name||n.node_id;
    if(n.node_id===current) opt.selected=true;
    sel.appendChild(opt);
  }
}


function loadSettings(){
  document.getElementById('mqttServer').value=localStorage.getItem('mqttServer')||'';
}

document.getElementById('save').addEventListener('click',()=>{
  const id=document.getElementById('centerNode').value;
  if(id) localStorage.setItem('centerNodeId',id);
  else localStorage.removeItem('centerNodeId');
  const srv=document.getElementById('mqttServer').value.trim();
  if(srv) localStorage.setItem('mqttServer',srv);
  else localStorage.removeItem('mqttServer');
  alert('Salvato');
});

window.addEventListener('DOMContentLoaded',()=>{
  loadNodes();
  loadSettings();
});