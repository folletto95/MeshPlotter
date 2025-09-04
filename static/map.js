const map = L.map('map').setView([0,0], 2);
L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
  maxZoom: 19,
  attribution: '&copy; OpenStreetMap contributors &copy; CARTO'
}).addTo(map);

let nodes = [];
const routeLines = [];
const routeMarkers = new Map();
let focusLine = null;
let routesVisible = true;

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
  // Fetch a large batch so recent traceroutes appear on the map
  const res = await fetch('/api/traceroutes?limit=1000');
  const routes = await res.json();
  for (const r of routes){
    // Include src and dest IDs even if the stored route only contains hops
    const ids = [r.src_id, ...(r.route || []), r.dest_id].filter(Boolean);
    const path = [];
    for (const id of ids){
      const n = nodes.find(nd => nd.node_id === id);
      if (n && n.lat != null && n.lon != null){
        path.push([n.lat, n.lon]);
      }
    }
    if (path.length >= 2){
      const line = L.polyline(path, {color:'#ff6d00', weight:2});
      line.bindTooltip(`${r.hop_count} hop${r.hop_count===1?'':'s'}`, {permanent:true});
      line.on('click', () => highlightRoute(line));
      const markers = path.map(pt => L.circleMarker(pt, {radius:4, color:'#ff6d00'}));
      routeLines.push(line);
      routeMarkers.set(line, markers);
      if (routesVisible){
        line.addTo(map);
        markers.forEach(m => m.addTo(map));
      }
    }
  }
}

function highlightRoute(line){
  if (!routesVisible) return;
  if (focusLine === line){
    routeLines.forEach(l => {
      if (!map.hasLayer(l)){
        l.addTo(map).setStyle({color:'#ff6d00', weight:2});
        routeMarkers.get(l).forEach(m => m.addTo(map).setStyle({color:'#ff6d00'}));
      }
    });
    focusLine = null;
  } else {
    routeLines.forEach(l => {
      if (l === line){
        l.setStyle({color:'#0ff', weight:4}).bringToFront();
        routeMarkers.get(l).forEach(m => m.addTo(map).setStyle({color:'#0ff'}).bringToFront());
      } else {
        map.removeLayer(l);
        routeMarkers.get(l).forEach(m => map.removeLayer(m));
      }
    });
    focusLine = line;
  }
}

function setRoutesVisibility(vis){
  routesVisible = vis;
  routeLines.forEach(l => {
    if (vis){
      l.addTo(map).setStyle({color:'#ff6d00', weight:2});
      routeMarkers.get(l).forEach(m => m.addTo(map).setStyle({color:'#ff6d00'}));
    } else {
      map.removeLayer(l);
      routeMarkers.get(l).forEach(m => map.removeLayer(m));
    }
  });
  if (!vis) focusLine = null;
}

document.getElementById('showRoutes').addEventListener('change', e => {
  setRoutesVisibility(e.target.checked);
});

loadNodes().then(loadTraceroutes);
