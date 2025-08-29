const map = L.map('map').setView([0,0], 2);
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
  maxZoom: 19,
  attribution: '&copy; OpenStreetMap contributors'
}).addTo(map);

async function loadNodes(){
  const res = await fetch('/api/nodes');
  const nodes = await res.json();
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
loadNodes();
