/* HK Property Radar — client rendering. Loads tidy JSON from ./data and draws
   with Plotly.js. Palette follows the validated data-viz reference; charts are
   single-axis; dark mode is a deliberate token set (not an auto-flip). */
'use strict';

const WORKER_URL = ""; // set to the Cloudflare Worker URL once deployed (email brief)

const PALETTE = {
  light:{page:'#f9f9f7',surface:'#fcfcfb',ink:'#0b0b0b',ink2:'#52514e',muted:'#898781',
         grid:'#e1e0d9',baseline:'#c3c2b7',s1:'#2a78d6',s2:'#eb6834',s3:'#1baf7a',success:'#006300'},
  dark:{page:'#0d0d0d',surface:'#1a1a19',ink:'#ffffff',ink2:'#c3c2b7',muted:'#898781',
        grid:'#2c2c2a',baseline:'#383835',s1:'#3987e5',s2:'#d95926',s3:'#199e70',success:'#0ca30c'},
};
const REGION_SLOT = {'HK Island':'s1','Kowloon':'s2','New Territories':'s3'};
const CFG = {displayModeBar:false, responsive:true};

const state = {};              // cached JSON
const rendered = new Set();    // tabs already drawn

/* ---------- theme ---------- */
function theme(){
  const t = document.documentElement.getAttribute('data-theme');
  if (t === 'light' || t === 'dark') return t;
  return matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}
const C = () => PALETTE[theme()];

/* ---------- helpers ---------- */
const $ = s => document.querySelector(s);
const fmt = n => (n === null || n === undefined || Number.isNaN(n)) ? '—' : Number(n).toLocaleString('en-US');
const fmt1 = n => (n === null || n === undefined) ? '—' : Number(n).toLocaleString('en-US',{maximumFractionDigits:1});

function baseLayout(opts={}){
  const c = C();
  return Object.assign({
    paper_bgcolor:'rgba(0,0,0,0)', plot_bgcolor:'rgba(0,0,0,0)',
    font:{family:'system-ui,-apple-system,"Segoe UI",sans-serif', size:12, color:c.ink2},
    margin:{l:52,r:14,t:10,b:36},
    hoverlabel:{bgcolor:c.surface, bordercolor:c.grid, font:{color:c.ink,size:12.5}},
    xaxis:{gridcolor:c.grid, zerolinecolor:c.baseline, linecolor:c.baseline, tickcolor:c.grid,
           tickfont:{color:c.muted}, automargin:true},
    yaxis:{gridcolor:c.grid, zerolinecolor:c.baseline, linecolor:c.baseline, tickcolor:c.grid,
           tickfont:{color:c.muted}, automargin:true},
    legend:{orientation:'h', y:1.12, x:0, font:{color:c.ink2}, bgcolor:'rgba(0,0,0,0)'},
    colorway:[c.s1,c.s2,c.s3],
  }, opts);
}
const draw = (id, data, layout) => Plotly.react(id, data, baseLayout(layout), CFG);

/* ---------- KPIs ---------- */
function renderKpis(){
  const el = $('#kpis'); el.innerHTML='';
  (state.kpis||[]).forEach(k=>{
    const val = (k.value===null||k.value===undefined) ? '—'
      : (typeof k.value==='number' ? Number(k.value).toLocaleString('en-US',{maximumFractionDigits: k.unit==='%'?2:1}) : k.value);
    const unit = k.unit ? `<small> ${k.unit}</small>` : '';
    const cls = /▲/.test(k.sub||'') ? 'up' : /▼/.test(k.sub||'') ? 'down' : '';
    el.insertAdjacentHTML('beforeend',
      `<div class="kpi"><div class="k-label">${k.label}</div>
       <div class="k-value">${val}${unit}</div>
       <div class="k-sub ${cls}">${k.sub||''}</div></div>`);
  });
}

/* ---------- Home ---------- */
function drawHome(){
  renderKpis();
  // price vs rent (All Classes) — one index axis
  const pri = state.price_rent_index, allc = (pri.classes['All Classes']||pri.classes[pri.default_class]);
  const c = C();
  draw('homeIndexChart', [
    {x:pri.periods, y:allc.price, name:'Price index', mode:'lines', connectgaps:true, line:{color:c.s1,width:2}},
    {x:pri.periods, y:allc.rent,  name:'Rent index',  mode:'lines', connectgaps:true, line:{color:c.s2,width:2}},
  ], {hovermode:'x unified', xaxis:{gridcolor:c.grid,linecolor:c.baseline,tickfont:{color:c.muted},
      range:['2008-01-01', pri.periods[pri.periods.length-1]]}});
  const lp = allc.price.filter(v=>v!=null), lr = allc.rent.filter(v=>v!=null);
  $('#homeIdxSub').textContent = `Price ${fmt1(lp.at(-1))} · Rent ${fmt1(lr.at(-1))}`;

  // cheapest vs priciest districts (new-launch psf)
  const priced = state.districts.by_district.filter(d=>d.avg_psf!=null).sort((a,b)=>b.avg_psf-a.avg_psf);
  const pick = [...priced.slice(0,5), ...priced.slice(-5)];
  drawDistrictBars('homeDistrictChart', pick, 'avg_psf', 'HK$ / sq.ft');
  $('#homeDistrictChart').style.height='300px';

  renderMiniNews();
}

/* ---------- Districts ---------- */
function drawDistrictBars(id, rows, metric, axisTitle){
  const c = C();
  const sorted = rows.filter(d=>d[metric]!=null).sort((a,b)=>a[metric]-b[metric]); // asc → biggest on top
  const names = sorted.map(d=>d.district);
  const byRegion = {};
  sorted.forEach(d=>{ (byRegion[d.region]=byRegion[d.region]||{x:[],y:[]}); });
  const traces = Object.keys(REGION_SLOT).filter(r=>sorted.some(d=>d.region===r)).map(region=>({
    type:'bar', orientation:'h', name:region,
    y:sorted.map(d=>d.district), x:sorted.map(d=>d.region===region?d[metric]:null),
    marker:{color:c[REGION_SLOT[region]]},
    hovertemplate:`%{y} · ${region}<br>${axisTitle}: %{x:,}<extra></extra>`,
  }));
  document.getElementById(id).style.height = Math.max(260, names.length*26+70)+'px';
  draw(id, traces, {barmode:'stack', margin:{l:150,r:20,t:10,b:34},
    xaxis:{title:{text:axisTitle,font:{color:c.ink2}},gridcolor:c.grid,linecolor:c.baseline,tickfont:{color:c.muted}},
    yaxis:{categoryorder:'array', categoryarray:names, gridcolor:'rgba(0,0,0,0)', linecolor:c.baseline, tickfont:{color:c.ink2,size:11.5}}});
}

function drawDistricts(){
  const d = state.districts || {by_district:[],totals:{}};
  const regionsMode = d.totals && d.totals.mode === 'regions';
  const region = $('#distRegion').value;
  const metric = regionsMode ? 'avg_psf' : $('#distMetric').value;
  document.querySelector('#pane-districts .card-head h2').textContent =
    regionsMode ? 'Where to buy — by region (official)' : 'Where to buy — the 18 districts';
  document.querySelector('#pane-districts .card-sub').textContent =
    regionsMode ? 'RVD average price, family flats' : 'primary-market new launches';
  $('#distMetric').parentElement.style.display = regionsMode ? 'none' : '';
  let rows = d.by_district || [];
  if (region!=='all') rows = rows.filter(x=>x.region===region);
  const titles={avg_psf:'HK$ / sq.ft', remaining:'Unsold units', units:'Total new units'};
  drawDistrictBars('districtChart', rows, metric, titles[metric]);
  const t = d.totals || {};
  $('#districtNote').textContent = regionsMode ? (d.source||'')
    : `Primary-market new launches: ${fmt(t.projects)} projects, ${fmt(t.units)} units across ${t.districts_with_launches}/18 districts. `
      + `Official RVD 18-district secondary-price series will be added once the source is confirmed.`;
  const cols = regionsMode
    ? [['district','Region'],['avg_psf','$/sq.ft']]
    : [['district','District'],['region','Region'],['avg_psf','$/sq.ft'],['units','New units'],['remaining','Unsold'],['sold_pct','Sold %']];
  buildTable('#districtTable', cols, d.by_district || [], region);
}

function buildTable(sel, cols, data, region){
  let rows = region && region!=='all' ? data.filter(d=>d.region===region) : data.slice();
  const table = $(sel);
  const pillCls = {'HK Island':'r1','Kowloon':'r2','New Territories':'r3'};
  const head = `<thead><tr>${cols.map((c,i)=>`<th data-i="${i}" data-k="${c[0]}">${c[1]}</th>`).join('')}</tr></thead>`;
  const cell = (d,k)=>{
    if (k==='region') return `<span class="pill ${pillCls[d[k]]||''}">${d[k]||'—'}</span>`;
    if (k==='sold_pct') return d[k]==null?'—':d[k]+'%';
    if (typeof d[k]==='number') return fmt(d[k]);
    return d[k]??'—';
  };
  const render = list => `<tbody>${list.map(d=>`<tr>${cols.map(c=>`<td>${cell(d,c[0])}</td>`).join('')}</tr>`).join('')}</tbody>`;
  table.innerHTML = head + render(rows.sort((a,b)=>(b.avg_psf||0)-(a.avg_psf||0)));
  table.querySelectorAll('th').forEach(th=>{
    let asc=false;
    th.onclick=()=>{ const k=th.dataset.k; asc=!asc;
      rows.sort((a,b)=>{ const x=a[k],y=b[k];
        if(x==null)return 1; if(y==null)return -1;
        return typeof x==='number' ? (asc?x-y:y-x) : (asc?String(x).localeCompare(y):String(y).localeCompare(x)); });
      table.querySelector('tbody').outerHTML = render(rows); };
  });
}

/* ---------- Rent vs Buy ---------- */
function drawRentBuy(){
  const pri = state.price_rent_index, c = C();
  const sel = $('#rbClass');
  if (!sel.options.length){
    pri.class_order.forEach(cl=>{ const o=document.createElement('option'); o.value=cl;
      o.textContent=labelClass(cl); if(cl===pri.default_class)o.selected=true; sel.appendChild(o); });
    sel.onchange=drawRentBuy;
  }
  const cl = sel.value, s = pri.classes[cl];
  draw('rentBuyChart', [
    {x:pri.periods, y:s.price, name:'Price index', mode:'lines', connectgaps:true, line:{color:c.s1,width:2}},
    {x:pri.periods, y:s.rent,  name:'Rent index',  mode:'lines', connectgaps:true, line:{color:c.s2,width:2}},
  ], {hovermode:'x unified', xaxis:{gridcolor:c.grid,linecolor:c.baseline,tickfont:{color:c.muted},
      range:['2005-01-01', pri.periods.at(-1)]}});
  const lp=s.price.filter(v=>v!=null).at(-1), lr=s.rent.filter(v=>v!=null).at(-1);
  $('#rbSub').textContent = `${labelClass(cl)} · price ${fmt1(lp)} / rent ${fmt1(lr)}`;
  // yield
  draw('yieldChart', [{x:pri.periods, y:s.yield, mode:'lines', line:{color:c.s3,width:2},
    hovertemplate:'%{x|%Y}<br>%{y:.2f}%<extra></extra>'}],
    {showlegend:false, yaxis:{ticksuffix:'%',gridcolor:c.grid,linecolor:c.baseline,tickfont:{color:c.muted}},
     xaxis:{range:['2005-01-01',pri.periods.at(-1)],gridcolor:c.grid,linecolor:c.baseline,tickfont:{color:c.muted}}});
  const ly=s.yield.filter(v=>v!=null).at(-1);
  $('#yieldSub').textContent = ly!=null?`${ly}% latest`:'';
  drawAvgTable();
}

function drawAvgTable(){
  const a = state.avg_price_rent, m = a.price_matrix;
  const classes = a.classes.filter(cl=>cl.includes('m2'));
  const regions = a.regions_en;
  const head = `<thead><tr><th>Flat size</th>${regions.map(r=>`<th>${r}</th>`).join('')}</tr></thead>`;
  const body = classes.map(cl=>`<tr><td>${labelClass(cl)}</td>${regions.map(r=>`<td>${fmt(m[r]?.[cl])}</td>`).join('')}</tr>`).join('');
  $('#avgTable').innerHTML = head+`<tbody>${body}</tbody>`;
  $('#avgSub').textContent = `HK$/m² · ${a.latest_period?.slice(0,7)||''}`;
}

/* ---------- Market ---------- */
function drawMarket(){
  const c=C();
  const mac=state.macro, vol=state.volume, sup=state.supply;
  draw('hiborChart', [{x:mac.hibor.dates, y:mac.hibor.values, mode:'lines', line:{color:c.s1,width:2},
    hovertemplate:'%{x|%b %Y}<br>%{y:.2f}%<extra></extra>'}],
    {showlegend:false, yaxis:{ticksuffix:'%',gridcolor:c.grid,linecolor:c.baseline,tickfont:{color:c.muted}}});
  $('#hiborSub').textContent = mac.hibor.values.length?`${mac.hibor.values.at(-1)}% now`:'';
  draw('volumeChart', [
    {x:vol.periods, y:vol.primary, name:'Primary', type:'bar', marker:{color:c.s1}},
    {x:vol.periods, y:vol.secondary, name:'Secondary', type:'bar', marker:{color:c.s2}},
  ], {barmode:'group'});
  draw('completionsChart', [{x:sup.years, y:sup.completions, type:'bar', marker:{color:c.s1},
    hovertemplate:'%{x}<br>%{y:,} units<extra></extra>'}], {showlegend:false});
  const vy=sup.years.filter((y,i)=>sup.vacancy_pct[i]!=null), vv=sup.vacancy_pct.filter(v=>v!=null);
  draw('vacancyChart', [{x:vy, y:vv, mode:'lines+markers', line:{color:c.s2,width:2}, marker:{size:6},
    hovertemplate:'%{x}<br>%{y:.1f}%<extra></extra>'}],
    {showlegend:false, yaxis:{ticksuffix:'%',gridcolor:c.grid,linecolor:c.baseline,tickfont:{color:c.muted}}});
}

/* ---------- News ---------- */
function renderMiniNews(){
  const el=$('#homeNews'); const items=(state.news&&state.news.items)||[];
  if(!items.length){el.innerHTML='<div class="empty">News updates will appear here after the next scheduled run.</div>';return;}
  el.innerHTML = items.slice(0,4).map(n=>
    `<a href="${n.url}" target="_blank" rel="noopener">${n.title}<span class="src"> — ${n.publisher||''}</span></a>`).join('');
}
function drawNews(){
  const top3=(state.top3&&state.top3.items)||[];
  $('#top3').innerHTML = top3.length ? top3.map((t,i)=>
    `<div class="t3"><div class="rank">${i+1}</div><div><h3>${t.title}</h3><p>${t.summary||''} ${t.url?`<a class="readmore" href="${t.url}" target="_blank" rel="noopener">Read more →</a>`:''}</p></div></div>`).join('')
    : '<div class="empty">The AI brief runs on a schedule — top moves will show here once the pipeline is live.</div>';
  const items=(state.news&&state.news.items)||[];
  $('#newsFeed').innerHTML = items.length ? items.map(n=>
    `<div class="news-item"><h3>${n.title}</h3><div class="meta">${n.publisher||''} ${n.date?'· '+n.date:''}</div>
     <p>${n.summary||''}</p><a class="readmore" href="${n.url}" target="_blank" rel="noopener">Read more →</a></div>`).join('')
    : '<div class="empty">No news items yet.</div>';
}

/* ---------- labels ---------- */
function labelClass(cl){
  return cl.replace('Less than 40 m2','< 40 m² (studio)')
           .replace('40 m2 to 69.9 m2','40–70 m² (1–2 bed)')
           .replace('70 m2 to 99.9 m2','70–100 m² (family)')
           .replace('100 m2 to 159.9 m2','100–160 m² (large)')
           .replace('160 m2 or above','160 m²+ (luxury)')
           .replace('Less than 100 m2','< 100 m²').replace('100 m2 or above','100 m²+')
           .replace('All Classes','All sizes');
}

/* ---------- tabs / theme ---------- */
const DRAW = {home:drawHome, districts:drawDistricts, rentbuy:drawRentBuy, market:drawMarket, news:drawNews};
function showTab(name){
  document.querySelectorAll('.tab').forEach(t=>t.classList.toggle('is-active',t.dataset.tab===name));
  document.querySelectorAll('.tabpane').forEach(p=>p.classList.toggle('is-active',p.id==='pane-'+name));
  DRAW[name](); rendered.add(name);
  window.scrollTo({top:0,behavior:'smooth'});
}
function rerenderAll(){ rendered.forEach(n=>DRAW[n]()); }

function initEvents(){
  document.querySelectorAll('.tab').forEach(t=>t.onclick=()=>showTab(t.dataset.tab));
  document.querySelectorAll('[data-goto]').forEach(a=>a.onclick=e=>{e.preventDefault();showTab(a.dataset.goto);});
  $('#distRegion').onchange=drawDistricts; $('#distMetric').onchange=drawDistricts;
  $('#themeBtn').onclick=()=>{
    const next = theme()==='dark'?'light':'dark';
    document.documentElement.setAttribute('data-theme',next);
    localStorage.setItem('hkpr-theme',next); rerenderAll();
  };
  // settings modal
  $('#settingsBtn').onclick=()=>{ $('#settingsModal').hidden=false;
    $('#setEmail').value=localStorage.getItem('hkpr-email')||'';
    $('#setToggle').checked=localStorage.getItem('hkpr-optin')==='1'; $('#setStatus').textContent=''; };
  $('#settingsClose').onclick=()=>$('#settingsModal').hidden=true;
  $('#settingsModal').onclick=e=>{ if(e.target===$('#settingsModal')) $('#settingsModal').hidden=true; };
  $('#setSave').onclick=saveSettings;
  matchMedia('(prefers-color-scheme: dark)').addEventListener('change',()=>{ if(!localStorage.getItem('hkpr-theme')) rerenderAll(); });
}

async function saveSettings(){
  const email=$('#setEmail').value.trim(), enabled=$('#setToggle').checked, st=$('#setStatus');
  if(enabled && !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)){ st.textContent='Please enter a valid email.'; return; }
  localStorage.setItem('hkpr-email',email); localStorage.setItem('hkpr-optin',enabled?'1':'0');
  if(!WORKER_URL){ st.textContent='Saved. Email delivery activates once the server is connected.'; return; }
  st.textContent='Saving…';
  try{
    const r=await fetch(`${WORKER_URL}/${enabled?'subscribe':'unsubscribe'}`,{method:'POST',
      headers:{'Content-Type':'application/json'}, body:JSON.stringify({email})});
    st.textContent = r.ok ? (enabled?'You’re subscribed to the email brief.':'Email brief turned off.') : 'Could not save — try again.';
  }catch(_){ st.textContent='Network error — try again.'; }
}

/* ---------- boot ---------- */
async function boot(){
  const saved=localStorage.getItem('hkpr-theme'); if(saved) document.documentElement.setAttribute('data-theme',saved);
  const files=['meta','kpis','price_rent_index','avg_price_rent','districts','volume','supply','macro','news','top3'];
  const results=await Promise.all(files.map(f=>fetch(`data/${f}.json`,{cache:'no-store'}).then(r=>r.ok?r.json():null).catch(()=>null)));
  files.forEach((f,i)=>state[f]=results[i]);
  if(state.meta&&state.meta.data_through){
    const d=new Date(state.meta.data_through);
    $('#dataStamp').textContent='Data to '+d.toLocaleDateString('en-GB',{month:'short',year:'numeric'});
  }
  initEvents(); showTab('home');
  if ('serviceWorker' in navigator) navigator.serviceWorker.register('service-worker.js').catch(()=>{});
}
document.addEventListener('DOMContentLoaded',boot);
