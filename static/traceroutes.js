let nodeNames = new Map();

function nameOf(id){
  return nodeNames.get(id) || id;
}

async function loadNodes(){
  const res = await fetch('/api/nodes');
  const nodes = await res.json();
  for (const n of nodes){
    const name = n.nickname || n.long_name || n.short_name || n.node_id;
    nodeNames.set(n.node_id, name);
  }
}

async function loadTraceroutes(){
  const res = await fetch('/api/traceroutes?limit=1000');
  const routes = await res.json();
  const groups = new Map();
  for (const r of routes){
    if (!groups.has(r.src_id)) groups.set(r.src_id, []);
    groups.get(r.src_id).push(r);
  }
  const container = document.getElementById('routes');
  container.innerHTML = '';
  for (const [src, list] of groups){
    const sec = document.createElement('section');
    const h = document.createElement('h3');
    h.textContent = `${nameOf(src)} (${src})`;
    sec.appendChild(h);
    const table = document.createElement('table');
    const thead = document.createElement('thead');
    thead.innerHTML = '<tr><th>Destinazione</th><th>Hop</th><th>Percorso</th></tr>';
    table.appendChild(thead);
    const tbody = document.createElement('tbody');
    for (const r of list){
      const tr = document.createElement('tr');
      const destCell = document.createElement('td');
      destCell.textContent = `${nameOf(r.dest_id)} (${r.dest_id})`;
      tr.appendChild(destCell);
      const hopCell = document.createElement('td');
      hopCell.textContent = r.hop_count;
      tr.appendChild(hopCell);
      const pathCell = document.createElement('td');
      pathCell.textContent = r.route.map(id => nameOf(id)).join(' → ');
      tr.appendChild(pathCell);
      tbody.appendChild(tr);
    }
    table.appendChild(tbody);
    sec.appendChild(table);
    container.appendChild(sec);
  }
}

loadNodes().then(loadTraceroutes);
