async function loadNodes(){
  let nodes=[];
  try{
    const res=await fetch('/api/nodes');
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

document.getElementById('save').addEventListener('click',()=>{
  const id=document.getElementById('centerNode').value;
  if(id) localStorage.setItem('centerNodeId',id);
  else localStorage.removeItem('centerNodeId');
  alert('Salvato');
});

window.addEventListener('DOMContentLoaded',loadNodes);
