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
    const maxHops = Math.max(...list.map(r => r.route.length));
    const thead = document.createElement('thead');
    const headerRow = document.createElement('tr');
    headerRow.innerHTML = '<th>Destinazione</th><th>Hop</th>';
    for (let i = 1; i <= maxHops; i++){
      const th = document.createElement('th');
      th.textContent = i;
      headerRow.appendChild(th);
    }
    thead.appendChild(headerRow);
    table.appendChild(thead);
    const tbody = document.createElement('tbody');
    for (const r of list){
      const tr = document.createElement('tr');
      const destName = nameOf(r.dest_id);
      const destCell = document.createElement('td');
      destCell.textContent = `${destName} (${r.dest_id})`;
      tr.appendChild(destCell);
      const hopCell = document.createElement('td');
      hopCell.textContent = r.hop_count;
      tr.appendChild(hopCell);
      for (let i = 0; i < maxHops; i++){
        const td = document.createElement('td');
        if (i < r.route.length){
          td.textContent = nameOf(r.route[i]);
        }
        tr.appendChild(td);
      }
      tbody.appendChild(tr);
    }
    table.appendChild(tbody);
    sec.appendChild(table);
    container.appendChild(sec);
  }
}

loadNodes().then(loadTraceroutes);
