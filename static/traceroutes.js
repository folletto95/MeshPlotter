let nodeNames = new Map();
const MAX_AGE = 0; // seconds; 0 = no expiry

function nameOf(id){
  return nodeNames.get(id) || id;
}

function shortName(id){
  const name = nameOf(id);
  // Limit displayed name to keep table cells compact
  return name.length > 10 ? name.slice(0, 9) + '\u2026' : name;
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
  const url = new URL('/api/traceroutes', window.location.origin);
  url.searchParams.set('limit', '1000');
  if (MAX_AGE > 0) url.searchParams.set('max_age', MAX_AGE);
  const res = await fetch(url, {cache:'no-store'});
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
    headerRow.innerHTML = '<th>Destinazione</th><th>Data</th><th>Hop</th>';
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
      const dt = new Date(r.ts * 1000);
      // show destination ID (user-friendly name and ID) in first cell
      destCell.innerHTML = `${destName} (${r.dest_id})`;
      tr.appendChild(destCell);

      const timeCell = document.createElement('td');
      // show human-readable date/time of reception in second cell
      timeCell.textContent = dt.toLocaleString();
      tr.appendChild(timeCell);

      const hopCell = document.createElement('td');
      hopCell.textContent = r.hop_count;
      tr.appendChild(hopCell);

      for (let i = 0; i < maxHops; i++){
        const stepCell = document.createElement('td');
        if (i < r.route.length){
          stepCell.textContent = shortName(r.route[i]);
          stepCell.title = nameOf(r.route[i]);
        }
        tr.appendChild(stepCell);
      }

      tbody.appendChild(tr);
    }
    table.appendChild(tbody);
    sec.appendChild(table);
    container.appendChild(sec);
  }
}

async function clearAllRoutes(){
  if (!confirm('Eliminare tutte le tracce?')) return;
  let res;
  try{
    res = await fetch('/api/traceroutes', {method:'DELETE'});
  }catch{
    alert('Errore durante l\'eliminazione delle tracce');
    return;
  }
  if (!res.ok){
    alert('Errore durante l\'eliminazione delle tracce');
    return;
  }
  await loadTraceroutes();
}

document.getElementById('clearRoutes').addEventListener('click', clearAllRoutes);

loadNodes().then(loadTraceroutes);

