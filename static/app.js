
const $nodes = document.getElementById('nodes');
const $range = document.getElementById('range');
const $refresh = document.getElementById('refresh');
const $autoref = document.getElementById('autoref');
const $nick = document.getElementById('nick');
const $saveNick = document.getElementById('save-nick');
const $showNick = document.getElementById('show-nick');

let nodesMap = {};

function fmtTs(ms){ return new Date(ms).toLocaleString(); }

function mkChart(ctx, yLabel){
  return new Chart(ctx, {
    type: 'line',
    data: { datasets: [] },
    options: {
      responsive: true, parsing: false, animation: false,
      interaction: { mode: 'nearest', intersect: false },
      elements: { point: { radius: 3 } },
      plugins: {
        legend: { position: 'bottom' },
        tooltip: {
          callbacks: {
            title: items => fmtTs(items[0].raw.x),
            label: item => `${item.dataset.label}: ${item.raw.y}`
          }
        }
      },
      scales: { x: { type:'time', time:{ unit:'minute' } }, y: { title: { display:true, text:yLabel } } }
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

for (const fam of Object.keys(charts)){
  cards[fam].style.display = 'none';
  toggles[fam].onchange = () => {
    cards[fam].style.display = toggles[fam].checked ? '' : 'none';
  };
}

async function loadNodes(){
  const res = await fetch('/api/nodes');
  const nodes = await res.json();
  const selected = Array.from($nodes.selectedOptions).map(o => o.value);
  $nodes.innerHTML = '';
  nodesMap = {};
  const useNick = $showNick.checked;
  for (const n of nodes){
    nodesMap[n.node_id] = n;
    const opt = document.createElement('option');
    opt.value = n.node_id;
    let label;
    if (useNick){
      label = n.display_name;
    } else {
      const parts = [];
      if (n.long_name) parts.push(n.long_name);
      if (n.short_name && n.short_name !== n.long_name) parts.push(n.short_name);
      if (!parts.length) parts.push(n.node_id);
      label = parts.join(' / ');
    }
    opt.textContent = `${label} (${n.info_packets})`;
    opt.title = `${n.node_id} — info: ${n.info_packets}`;
    if (selected.includes(n.node_id)) opt.selected = true;
    $nodes.appendChild(opt);
  }
  updateNickInput();
}

function updateNickInput(){
  const id = $nodes.value;
  const n = nodesMap[id];
  $nick.value = n && n.nickname ? n.nickname : '';
}

async function loadData(){
  const names = Array.from($nodes.selectedOptions).map(o => o.value).join(',');
  const since = $range.value;
  const url = new URL('/api/metrics', location.origin);
  if (names) url.searchParams.set('nodes', names);
  url.searchParams.set('since_s', since);
  url.searchParams.set('use_nick', $showNick.checked ? '1' : '0');
  const res = await fetch(url);
  const data = await res.json();
  const series = data.series || {};
  for (const fam of Object.keys(charts)){
    const ds = (series[fam] || []).map(s => {
      const last = s.data.length ? s.data[s.data.length - 1].y.toFixed(2) : 'n/a';
      return { label: `${s.label} — Ultimo: ${last}`, data: s.data };
    });
    charts[fam].data.datasets = ds;
    charts[fam].update();
    if (ds.length > 0) toggles[fam].checked = true;
    cards[fam].style.display = toggles[fam].checked ? '' : 'none';
  }
}

$nodes.onchange = () => { updateNickInput(); };
$refresh.onclick = loadData;
$saveNick.onclick = async () => {
  const id = $nodes.value;
  if (!id) return;
  await fetch('/api/nodes/nickname', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ node_id: id, nickname: $nick.value })
  });
  await loadNodes();
  await loadData();
};
$showNick.onchange = () => { loadNodes(); loadData(); };
$autoref.onchange = () => {
  if ($autoref.checked){
    loadData();
    window._timer = setInterval(loadData, 15000);
  } else {
    clearInterval(window._timer);
  }
};

(async function init(){ await loadNodes(); await loadData(); })();
