
const $nodes = document.getElementById('nodes');
const $range = document.getElementById('range');
const $refresh = document.getElementById('refresh');
const $autoref = document.getElementById('autoref');
const $nick = document.getElementById('nick');
const $saveNick = document.getElementById('save-nick');
const $showNick = document.getElementById('show-nick');

let nodesMap = {};

// apply theme colors to charts
const _style = getComputedStyle(document.documentElement);
const _textColor = _style.getPropertyValue('--text').trim();
const _gridColor = _style.getPropertyValue('--bd').trim();
const _accent   = _style.getPropertyValue('--accent').trim();
if (window.Chart) {
  Chart.defaults.color = _textColor;
  Chart.defaults.borderColor = _gridColor;
} else {
  console.error('Chart.js failed to load');
  alert('Chart.js failed to load');
  throw new Error('Chart.js failed to load');
}

function fmtTs(ms){ return new Date(ms).toLocaleString(); }

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

function mkChart(ctx, yLabel){
  return new Chart(ctx, {
    type: 'line',
    data: { datasets: [] },
    options: {
      responsive: true, parsing: false, animation: false,
      interaction: { mode: 'nearest', intersect: false },
      elements: { point: { radius: 3, borderColor: _accent, backgroundColor: _accent } },
      plugins: {
        legend: { position: 'bottom', labels: { usePointStyle: true, boxWidth: 8, boxHeight: 8 } },
        tooltip: {
          callbacks: {
            title: items => fmtTs(items[0].raw.x),
            label: item => {
              const prefix = item.dataset.showNode ? `${item.dataset.node}: ` : '';
              return `${prefix}${item.raw.y} ${item.dataset.unit}`;
            }
          }
        }
      },
      scales: {
        x: { type:'time', time:{ unit:'minute' }, grid:{ color:_gridColor } },
        y: { title: { display:true, text:yLabel }, grid:{ color:_gridColor } }
      }
    }
  });
}
const charts = {
  temperature: mkChart(document.getElementById('chart-temp'), '°C'),
  humidity:    mkChart(document.getElementById('chart-hum'), '%'),
  pressure:    mkChart(document.getElementById('chart-press'), 'hPa'),
  voltage:     mkChart(document.getElementById('chart-volt'), 'V'),
  current:     mkChart(document.getElementById('chart-curr'), 'mA')
};

const cards = {
  temperature: document.getElementById('card-temp'),
  humidity:    document.getElementById('card-hum'),
  pressure:    document.getElementById('card-press'),
  voltage:     document.getElementById('card-volt'),
  current:     document.getElementById('card-curr')
};

const toggles = {
  temperature: document.getElementById('toggle-temperature'),
  humidity:    document.getElementById('toggle-humidity'),
  pressure:    document.getElementById('toggle-pressure'),
  voltage:     document.getElementById('toggle-voltage'),
  current:     document.getElementById('toggle-current')
};
const zeroToggles = {
  temperature: document.getElementById('zero-temperature'),
  humidity:    document.getElementById('zero-humidity'),
  pressure:    document.getElementById('zero-pressure'),
  voltage:     document.getElementById('zero-voltage'),
  current:     document.getElementById('zero-current')
};
const VIEW_SETTINGS_KEY = 'view_settings';
let _hasViewSettings = false;
let _savedNodes = [];
try {
  const tmp = JSON.parse(localStorage.getItem('fav_nodes') || '[]');
  if (Array.isArray(tmp)) _savedNodes = tmp;
} catch (err) {
  console.error('Failed to parse saved nodes', err);
}

function saveViewSettings(){
  const settings = {
    range: $range.value,
    showNick: $showNick.checked,
    autoref: $autoref.checked,
    toggles: Object.fromEntries(Object.entries(toggles).map(([fam, el]) => [fam, el.checked])),
    zeroes: Object.fromEntries(Object.entries(zeroToggles).map(([fam, el]) => [fam, el.checked])),
    nodes: Array.from($nodes.querySelectorAll('input[type=checkbox]:checked')).map(cb => cb.value)
  };
  try {
    localStorage.setItem(VIEW_SETTINGS_KEY, JSON.stringify(settings));
    localStorage.setItem('fav_nodes', JSON.stringify(settings.nodes));
  } catch (err) {
    console.error('Failed to save view settings', err);
  }
}

function loadViewSettings(){
  try {
    const raw = localStorage.getItem(VIEW_SETTINGS_KEY);
    if (!raw) return;
    const settings = JSON.parse(raw);
    _hasViewSettings = true;
    if (settings.range) $range.value = settings.range;
    if ('showNick' in settings){
      const v = settings.showNick;
      $showNick.checked = v === true || v === 'true' || v === 1 || v === '1';
    }
    if (typeof settings.autoref === 'boolean') $autoref.checked = settings.autoref;
    if (settings.toggles){
      for (const [fam, on] of Object.entries(settings.toggles)){
        if (toggles[fam]){
          toggles[fam].checked = on;
          cards[fam].style.display = on ? '' : 'none';
        }
      }
    }
    if (settings.zeroes){
      for (const [fam, on] of Object.entries(settings.zeroes)){
        if (zeroToggles[fam]) zeroToggles[fam].checked = on;
      }
    }
    if (Array.isArray(settings.nodes)) _savedNodes = settings.nodes;
  } catch (err) {
    console.error('Failed to load view settings', err);
  }
}

for (const fam of Object.keys(charts)){
  cards[fam].style.display = 'none';
  toggles[fam].onchange = () => {
    cards[fam].style.display = toggles[fam].checked ? '' : 'none';
    saveViewSettings();
  };
}
for (const fam of Object.keys(zeroToggles)){
  zeroToggles[fam].onchange = () => { saveViewSettings(); loadData(); };
}

async function loadNodes(){
  try {
    // FIXME: temporary filter for placeholder nodes without activity
    const res = await fetch('/api/nodes?include_inactive=false');
    const nodes = await res.json();
    const selected = Array.from($nodes.querySelectorAll('input[type=checkbox]:checked')).map(cb => cb.value);
    const preselect = selected.length ? selected : _savedNodes;
    $nodes.innerHTML = '';
    nodesMap = {};
    const useNick = $showNick.checked;
    for (const n of nodes){
      nodesMap[n.node_id] = n;
      const labelEl = document.createElement('label');
      const cb = document.createElement('input');
      cb.type = 'checkbox';
      cb.value = n.node_id;
      if (preselect.includes(n.node_id)) cb.checked = true;
      cb.onchange = () => { updateNickInput(); saveViewSettings(); loadData(); };
      let label;
      if (useNick){
        label = n.nickname || n.long_name || n.short_name || n.node_id;

      } else {
        const parts = [];
        if (n.long_name) parts.push(n.long_name);
        if (n.short_name && n.short_name !== n.long_name) parts.push(n.short_name);
        if (!parts.length) parts.push(n.node_id);
        label = parts.join(' / ');
      }
      labelEl.appendChild(cb);
      labelEl.append(` ${label} (${n.info_packets})`);
      labelEl.title = `${n.node_id} — info: ${n.info_packets}`;
      $nodes.appendChild(labelEl);
      $nodes.appendChild(document.createElement('br'));
    }
    updateNickInput();
    const errEl = document.getElementById('nodes-error');
    if (errEl) errEl.remove();
  } catch (err) {
    console.error('Errore durante il caricamento dei nodi', err);
    let errEl = document.getElementById('nodes-error');
    if (!errEl) {
      errEl = document.createElement('div');
      errEl.id = 'nodes-error';
      errEl.style.color = 'red';
      $nodes.parentNode.appendChild(errEl);
    }
    errEl.textContent = 'Errore nel caricamento dei nodi';
  }
}

function updateNickInput(){
  const first = $nodes.querySelector('input[type=checkbox]:checked');
  const n = first ? nodesMap[first.value] : null;
  $nick.value = n && n.nickname ? n.nickname : '';
}

async function loadData(){
  const ids = Array.from($nodes.querySelectorAll('input[type=checkbox]:checked')).map(cb => cb.value);
  const names = ids.join(',');
  const since = $range.value;
  const url = new URL('/api/metrics', location.origin);
  if (names) url.searchParams.set('nodes', names);
  url.searchParams.set('since_s', since);
  url.searchParams.set('use_nick', $showNick.checked ? '1' : '0');
  const res = await fetch(url);
  const data = await res.json();
  const series = data.series || {};
  const units = data.units || {};
  const showNode = ids.length > 1;
  for (const fam of Object.keys(charts)){
    const unit = units[fam] || '';
    const showZero = zeroToggles[fam]?.checked;
    const ds = (series[fam] || []).map(s => {
      const dataPoints = showZero ? s.data : s.data.filter(p => Number(p.y) !== 0);
      const last = dataPoints.length ? Number(dataPoints[dataPoints.length - 1].y).toFixed(2) : 'n/a';
      const nodeId = s.node_id;
      const short = nodesMap[nodeId]?.short_name || nodeId.slice(-4);
      const node = short;
      const label = showNode ? `${last} ${unit} ${node}` : `${last} ${unit}`;
      const color = colorFor(nodeId);
      return { label, data: dataPoints, node, unit, showNode, borderColor: color, backgroundColor: color };
    });
    charts[fam].data.datasets = ds;
    charts[fam].update();
    if (ds.length > 0 && !_hasViewSettings) toggles[fam].checked = true;
    cards[fam].style.display = toggles[fam].checked ? '' : 'none';
  }
}

$refresh.onclick = () => { loadNodes(); loadData(); };
$saveNick.onclick = async () => {
  const first = $nodes.querySelector('input[type=checkbox]:checked');
  const id = first ? first.value : null;
  if (!id) return;
  await fetch('/api/nodes/nickname', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ node_id: id, nickname: $nick.value })
  });
  await loadNodes();
  await loadData();
};
$range.onchange = () => { saveViewSettings(); loadData(); };
$showNick.onchange = () => { saveViewSettings(); loadNodes(); loadData(); };
$autoref.onchange = () => {
  saveViewSettings();
  clearInterval(window._timer);
  if ($autoref.checked){
    const tick = () => { loadNodes(); loadData(); };
    tick();
    window._timer = setInterval(tick, 15000);
  }
};
window.addEventListener('beforeunload', saveViewSettings);
(async function init(){
  loadViewSettings();
  await loadNodes();
  await loadData();
  if ($autoref.checked) $autoref.onchange();
  saveViewSettings();
})();
