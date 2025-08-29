const $nodes = document.getElementById('nodes');
const $range = document.getElementById('range');
const $refresh = document.getElementById('refresh');
const $autoref = document.getElementById('autoref');

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
  current:     mkChart(document.getElementById('chart-curr'), 'A')
};

async function loadNodes(){
  const res = await fetch('/api/nodes');
  const nodes = await res.json();
  $nodes.innerHTML = '';
  for (const n of nodes){
    const opt = document.createElement('option');
    opt.value = n.node_id;
    const parts = [];
    if (n.long_name) parts.push(n.long_name);
    if (n.short_name && n.short_name !== n.long_name) parts.push(n.short_name);
    if (!parts.length) parts.push(n.node_id);
    opt.textContent = parts.join(' / ');
    opt.title = n.node_id;
    $nodes.appendChild(opt);
  }
}

async function loadData(){
  const names = Array.from($nodes.selectedOptions).map(o => o.value).join(',');
  const since = $range.value;
  const url = new URL('/api/metrics', location.origin);
  if (names) url.searchParams.set('nodes', names);
  url.searchParams.set('since_s', since);
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
  }
}

$refresh.onclick = loadData;
$autoref.onchange = () => {
  if ($autoref.checked){
    loadData();
    window._timer = setInterval(loadData, 15000);
  } else {
    clearInterval(window._timer);
  }
};

(async function init(){ await loadNodes(); await loadData(); })();
