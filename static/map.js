let map;
let nodes = [];
const nodeMarkers = new Map();
const nodePositions = new Map();
const routeLines = [];
const routeMarkers = new Map();
let focusLine = null;
let routesVisible = true;
let showNames = false;
let centerNodeId = localStorage.getItem('centerNodeId');
let nodeRouteFilter = null;

function colorFor(str){
  let hash = 0;
  for (let i = 0; i < str.length; i++){
    hash = str.charCodeAt(i) + ((hash << 5) - hash);
  }
  const abs = Math.abs(hash);
  const h = abs % 360;
  const s = 65 + ((abs >> 8) % 20);  // 65-84
  const l = 50 + ((abs >> 16) % 20); // 50-69
  return `hsl(${h}, ${s}%, ${l}%)`;
}

const MAX_HOPS = 7;
function hopColor(count){
  return colorFor('hop' + count);
}

function nodeIcon(nodeId, label){
  const color = colorFor(nodeId);
  return L.divIcon({
    className:'',
    html:`<div class="node-label" style="background:${color};">${label||''}</div>`,
    iconSize:[24,24]
  });
}


function haversine(lat1, lon1, lat2, lon2){
  const R = 6371;
  const toRad = d => d * Math.PI / 180;
  const dLat = toRad(lat2 - lat1);
  const dLon = toRad(lon2 - lon1);
  const a = Math.sin(dLat/2)**2 + Math.cos(toRad(lat1))*Math.cos(toRad(lat2))*Math.sin(dLon/2)**2;
  return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}


async function loadNodes(){
  let fetched = [];
  try{
    const res = await fetch('/api/nodes');
    fetched = await res.json();
  }catch{
    return;
  }
  let first = nodes.length === 0;
  if (first && centerNodeId){
    const cn = fetched.find(n => n.node_id === centerNodeId && n.lat != null && n.lon != null);
    if (cn){
      map.setView([cn.lat, cn.lon],13);
      first = false;
    }
  }
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
        const label = showNames && n.short_name ? n.short_name : '';
        const m = L.marker(pos,{icon:nodeIcon(n.node_id, label)}).addTo(map);
        const last = n.last_seen ? new Date(n.last_seen*1000).toLocaleString() : '';
        const alt = n.alt != null ? `<br/>Alt: ${n.alt} m` : '';

        const checked = nodeRouteFilter === n.node_id ? 'checked' : '';
        m.bindPopup(`<b>${name}</b><br/>ID: ${n.node_id}<br/>Ultimo: ${last}${alt}<br/><label><input type="checkbox" onclick="viewNodeRoutes('${n.node_id}', this.checked)" ${checked}/> Visualizza tracce nodo</label>`);
        nodeMarkers.set(n.node_id,{marker:m,short:n.short_name||''});
        if (first && !centerNodeId){ map.setView(pos,13); first=false; }
      }
      nodePositions.set(n.node_id,pos);
    }
  }
  nodes = fetched;
  if (centerNodeId){
    const cn = nodes.find(n => n.node_id === centerNodeId && n.lat != null && n.lon != null);
    if (cn) map.setView([cn.lat, cn.lon],13);
  }

}

function clearRoutes(){
  routeLines.forEach(l => {
    map.removeLayer(l);
    routeMarkers.get(l).forEach(m => map.removeLayer(m));
  });
  routeLines.length = 0;
  routeMarkers.clear();
  focusLine = null;
}

async function loadTraceroutes(){
  clearRoutes();

  let routes = [];
  try{
    // Fetch a large batch so recent traceroutes appear on the map
    const res = await fetch('/api/traceroutes?limit=1000');
    routes = await res.json();
  }catch{
    routes = [];
  }
  if (nodeRouteFilter){
    routes = routes.filter(r => {
      const ids = [r.src_id, ...(r.route || []), r.dest_id].filter(Boolean);
      return ids.includes(nodeRouteFilter);
    });
  }

  for (const r of routes){
    // Include src and dest IDs even if the stored route only contains hops
    const ids = [r.src_id, ...(r.route || []), r.dest_id].filter(Boolean);
    const path = [];
    const names = [];
    for (const id of ids){
      const n = nodes.find(nd => nd.node_id === id);
      if (n && n.lat != null && n.lon != null){
        path.push([n.lat, n.lon]);
      }
      names.push(n ? (n.nickname || n.long_name || n.short_name || id) : id);
    }
    if (path.length >= 2){
      const hop = Math.min(r.hop_count, MAX_HOPS);
      const color = hopColor(hop);
      const line = L.polyline(path, {color, weight:2});
      line.bindTooltip(`${r.hop_count} hop${r.hop_count===1?'':'s'}`);

      const srcNode = nodes.find(nd => nd.node_id === r.src_id) || {};
      const destNode = nodes.find(nd => nd.node_id === r.dest_id) || {};
      const srcName = srcNode.nickname || srcNode.long_name || srcNode.short_name || r.src_id;
      const destName = destNode.nickname || destNode.long_name || destNode.short_name || r.dest_id;
      let distance = null;
      if (srcNode.lat != null && srcNode.lon != null && destNode.lat != null && destNode.lon != null){
        distance = haversine(srcNode.lat, srcNode.lon, destNode.lat, destNode.lon);
      }
      const segments = [];
      for (let i=0;i<ids.length-1;i++){
        const a = nodes.find(nd => nd.node_id === ids[i]) || {};
        const b = nodes.find(nd => nd.node_id === ids[i+1]) || {};
        let dist = null;
        if (a.lat!=null && a.lon!=null && b.lat!=null && b.lon!=null){
          dist = haversine(a.lat,a.lon,b.lat,b.lon);
        }
        segments.push({from:names[i], to:names[i+1], distance:dist});
      }
      line.info = {srcName, destName, ts:r.ts, distance, radio:r.radio, via:r.via, names, segments};
      line.on('click', e => {highlightRoute(line); if (focusLine === line) showRouteInfo(line, e.latlng);});

      line.nodeIds = ids;
      line.defaultColor = color;
      const markers = path.map((pt, idx) => {
        const c = colorFor(ids[idx]);
        const mk = L.circleMarker(pt, {radius:4, color:c});
        mk.defaultColor = c;
        return mk;
      });
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
        routeMarkers.get(l).forEach(m => m.addTo(map).setStyle({color:m.defaultColor}));
      }
    });
    focusLine = null;
    map.closePopup();
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

function showRouteInfo(line, latlng){
  const info = line.info || {};
  const time = info.ts ? new Date(info.ts*1000).toLocaleString() : '';
  const dist = info.distance != null ? info.distance.toFixed(2) + ' km' : 'N/D';
  const type = info.via === 'radio' ? 'Radio' : 'MQTT';
  let signal = '';
  if (info.via === 'radio'){
    signal = info.radio ? Object.entries(info.radio).map(([k,v]) => `${k}: ${v}`).join('<br/>') : 'N/D';
  }
  const pathStr = info.names ? info.names.join(' → ') : '';
  let segHtml = '';
  if (info.segments){
    segHtml = info.segments.map(s => `${s.from} → ${s.to}: ${s.distance != null ? s.distance.toFixed(2)+' km' : 'N/D'}`).join('<br/>');
  }
  const html = `<b>${info.srcName||''}</b> → <b>${info.destName||''}</b><br/>${time}<br/>Collegamento: ${type}${signal?'<br/>'+signal:''}<br/>Distanza: ${dist}${pathStr?'<br/>'+pathStr:''}${segHtml?'<br/>'+segHtml:''}`;
  L.popup().setLatLng(latlng).setContent(html).openOn(map);
}

function setRoutesVisibility(vis){
  routesVisible = vis;
  routeLines.forEach(l => {
    if (vis){
      l.addTo(map).setStyle({color:l.defaultColor, weight:2});
      routeMarkers.get(l).forEach(m => m.addTo(map).setStyle({color:m.defaultColor}));
    } else {
      map.removeLayer(l);
      routeMarkers.get(l).forEach(m => map.removeLayer(m));
    }
  });
  if (!vis) focusLine = null;
}

function setNamesVisibility(vis){
  showNames = vis;
  nodeMarkers.forEach((v, k) => {
    const label = vis ? v.short : '';
    v.marker.setIcon(nodeIcon(k, label));
  });
}


function viewNodeRoutes(nodeId, checked){
  nodeRouteFilter = checked ? nodeId : null;
  if (checked && !routesVisible){
    document.getElementById('showRoutes').checked = true;
    setRoutesVisibility(true);
  }
  loadTraceroutes();

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
    for(let i=1;i<=MAX_HOPS;i++){
      const label = i === MAX_HOPS ? `${i}+` : `${i}`;
      div.innerHTML += `<span style="background:${hopColor(i)}"></span>${label}<br/>`;
    }
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
  addHopLegend();
}

async function refresh(){
  await loadNodes();
  await loadTraceroutes();
}

window.addEventListener('DOMContentLoaded', () => {
  init();
  refresh();
  setInterval(refresh, 10000);
});