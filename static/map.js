const map = L.map('map').setView([0,0], 2);
L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
  maxZoom: 19,
  attribution: '&copy; OpenStreetMap contributors &copy; CARTO'
}).addTo(map);

let nodes = [];
const routeLines = [];
let focusLine = null;

async function loadNodes(){
  const res = await fetch('/api/nodes');
  nodes = await res.json();
  let first = true;
  for (const n of nodes){
    if (n.lat != null && n.lon != null){
      const name = n.nickname || n.long_name || n.short_name || n.node_id;

      const m = L.marker([n.lat, n.lon]).addTo(map);
      const last = n.last_seen ? new Date(n.last_seen*1000).toLocaleString() : '';
      const alt = n.alt != null ? `<br/>Alt: ${n.alt} m` : '';
      m.bindPopup(`<b>${name}</b><br/>ID: ${n.node_id}<br/>Ultimo: ${last}${alt}`);
      if (first){ map.setView([n.lat, n.lon], 13); first = false; }
    }
  }
}

async function loadTraceroutes(){
  const res = await fetch('/api/traceroutes');
  const routes = await res.json();
  for (const r of routes){
    const path = [];
    for (const id of r.route){
      const n = nodes.find(nd => nd.node_id === id);
      if (n && n.lat != null && n.lon != null){
        path.push([n.lat, n.lon]);
      }
    }
    if (path.length >= 2){
      const line = L.polyline(path, {color:'#ff6d00', weight:2}).addTo(map);
      line.bindTooltip(`${r.hop_count} hop${r.hop_count===1?'':'s'}`, {permanent:true});
      line.on('click', () => highlightRoute(line));
      routeLines.push(line);
    }
  }
}

function highlightRoute(line){
  if (focusLine === line){
    routeLines.forEach(l => { if (!map.hasLayer(l)) l.addTo(map).setStyle({color:'#ff6d00', weight:2}); });
    focusLine = null;
  } else {
    routeLines.forEach(l => {
      if (l === line){
        l.setStyle({color:'#0ff', weight:4}).bringToFront();
      } else {
        map.removeLayer(l);
      }
    });
    focusLine = line;
  }
}

loadNodes().then(loadTraceroutes);
