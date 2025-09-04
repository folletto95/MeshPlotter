let map;
let nodes = [];
const nodeMarkers = new Map();
const nodePositions = new Map();
const routeLines = [];
const routeMarkers = new Map();
let focusLine = null;
let routesVisible = true;
let showNames = false;
const hopColors = ['#00ff00','#7fff00','#bfff00','#ffff00','#ffbf00','#ff8000','#ff4000','#ff0000'];

async function loadNodes(){
  let fetched = [];
  try{
    const res = await fetch('/api/nodes');
    fetched = await res.json();
  }catch{
    return;
  }
  let first = nodes.length === 0;
  for (const n of fetched){
    if (n.lat != null && n.lon != null){
      const pos = [n.lat, n.lon];
      const prev = nodePositions.get(n.node_id);
      if (prev){
        if (prev[0] !== pos[0] || prev[1] !== pos[1]){
          removeNodeRoutes(n.node_id);
          const mk = nodeMarkers.get(n.node_id);
          if (mk) mk.marker.setLatLng(pos);
        }
      }else{
        const name = n.nickname || n.long_name || n.short_name || n.node_id;
        const icon = L.divIcon({className:'node-label', html:showNames && n.short_name ? n.short_name : '', iconSize:[24,24]});
        const m = L.marker(pos,{icon}).addTo(map);
        const last = n.last_seen ? new Date(n.last_seen*1000).toLocaleString() : '';
        const alt = n.alt != null ? `<br/>Alt: ${n.alt} m` : '';
        m.bindPopup(`<b>${name}</b><br/>ID: ${n.node_id}<br/>Ultimo: ${last}${alt}`);
        nodeMarkers.set(n.node_id,{marker:m,short:n.short_name||''});
        if (first){ map.setView(pos,13); first=false; }
      }
      nodePositions.set(n.node_id,pos);
    }
  }
  nodes = fetched;
}

async function loadTraceroutes(){
  let routes = [];
  try{
    // Fetch a large batch so recent traceroutes appear on the map
    const res = await fetch('/api/traceroutes?limit=1000');
    routes = await res.json();
  }catch{
    routes = [];
  }

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
      const color = hopColors[Math.min(r.hop_count, hopColors.length-1)];
      const line = L.polyline(path, {color, weight:2});
      line.bindTooltip(`${r.hop_count} hop${r.hop_count===1?'':'s'}`);
      line.on('click', () => highlightRoute(line));
      line.nodeIds = ids;
      line.defaultColor = color;
      const markers = path.map(pt => L.circleMarker(pt, {radius:4, color}));
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
        l.addTo(map).setStyle({color:l.defaultColor, weight:2});
        routeMarkers.get(l).forEach(m => m.addTo(map).setStyle({color:l.defaultColor}));
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
      l.addTo(map).setStyle({color:l.defaultColor, weight:2});
      routeMarkers.get(l).forEach(m => m.addTo(map).setStyle({color:l.defaultColor}));
    } else {
      map.removeLayer(l);
      routeMarkers.get(l).forEach(m => map.removeLayer(m));
    }
  });
  if (!vis) focusLine = null;
}

function setNamesVisibility(vis){
  showNames = vis;
  nodeMarkers.forEach(v => {
    const html = vis ? v.short : '';
    v.marker.setIcon(L.divIcon({className:'node-label', html, iconSize:[24,24]}));
  });
}

function removeNodeRoutes(nodeId){
  routeLines.slice().forEach(l => {
    if (l.nodeIds && l.nodeIds.includes(nodeId)){
      map.removeLayer(l);
      routeMarkers.get(l).forEach(m => map.removeLayer(m));
      routeMarkers.delete(l);
      const idx = routeLines.indexOf(l);
      if (idx >= 0) routeLines.splice(idx,1);
      if (focusLine === l) focusLine = null;
    }
  });
}

function addHopLegend(){
  const legend = L.control({position:'bottomleft'});
  legend.onAdd = function(){
    const div = L.DomUtil.create('div','hop-legend');
    hopColors.forEach((c,i)=>{
      div.innerHTML += `<span style="background:${c}"></span>${i}<br/>`;
    });
    return div;
  };
  legend.addTo(map);
}

function init(){
  map = L.map('map').setView([0,0], 2);
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '&copy; OpenStreetMap contributors'
  }).addTo(map);

  document.getElementById('showRoutes').addEventListener('change', e => {
    setRoutesVisibility(e.target.checked);
  });
  document.getElementById('showNames').addEventListener('change', e => {
    setNamesVisibility(e.target.checked);
  });

  loadNodes().then(loadTraceroutes);
  setInterval(loadNodes, 10000);
  addHopLegend();
}

window.addEventListener('DOMContentLoaded', init);
