import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import './map.css';

const labels = {L1: 'L1 · 既有管网', L2: 'L2 · 现状塘', A: 'L2+ A · Parsons', B1: 'L2+ B1 · 自主 150 mm', B2: 'L2+ B2 · 自主 300 mm'};
const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const fmt = (v, d=1) => v == null ? '—' : Number(v).toLocaleString('en-US', {maximumFractionDigits:d});
const ll = f => [f.geometry.coordinates[1], f.geometry.coordinates[0]];
const metricKeys = {volume:'flood_volume_m3',depth:'max_ponded_depth_m'};
const categories = {
  resolved:{label:'不再报告溢流',color:'#06b6d4'},
  improved:{label:'溢流量减少',color:'#10b981'},
  new:{label:'新增溢流',color:'#f43f5e'},
  worsened:{label:'溢流量增加',color:'#f59e0b'},
  unchanged:{label:'无变化',color:'#a3afc1'},
};
function category(a,b) {
  if (!a || !b) return null;
  if (a.flooding_reported && !b.flooding_reported) return 'resolved';
  if (!a.flooding_reported && b.flooding_reported) return 'new';
  return b.flood_volume_m3 < a.flood_volume_m3 ? 'improved' : b.flood_volume_m3 > a.flood_volume_m3 ? 'worsened' : 'unchanged';
}
function absoluteColour(v, metric) {
  const cuts = metric === 'depth' ? [0,.15,.3,.5] : [0,10,50,100];
  return v <= cuts[0] ? '#a3afc1' : v < cuts[1] ? '#38bdf8' : v < cuts[2] ? '#facc15' : v < cuts[3] ? '#fb923c' : '#e11d48';
}

function mount(root, data, geo, onStateChange) {
  let left='L2', right='B1', mode='split', metric='volume', basemap='satellite', scope='network', filter='all';
  let syncing=false, selectedNode=null;
  const layers={network:true, historical:true, plans:true, boundary:true};
  const nodes=geo.features.filter(f=>f.properties.kind==='node');
  const nodeById=new Map(nodes.map(f=>[f.properties.id,f]));
  const boundary=geo.features.find(f=>f.properties.kind==='boundary');
  const options=(current)=>Object.entries(labels).map(([k,v])=>`<option value="${k}" ${k===current?'selected':''}>${v}</option>`).join('');
  root.classList.add('mc');
  root.innerHTML=`
    <div class="mc-head"><div><h2>在真实位置比较防线效果</h2><p>卫星 / 道路底图 · 两图同步缩放与移动 · 48 h 累计结果</p></div><span class="mc-badge">一维节点结果</span></div>
    <div class="mc-controls"><label>左侧基准<select data-control="left" aria-label="左侧基准状态">${options(left)}</select></label><span class="mc-arrow">→</span><label>右侧方案<select data-control="right" aria-label="右侧对比方案">${options(right)}</select></label><div class="mc-modes"><button class="active" data-mode="split">左右对比</button><button data-mode="delta">变化分布</button></div><label>指标<select data-control="metric" aria-label="地图结果指标"><option value="volume">节点累计溢流量（m³）</option><option value="depth">节点地表蓄水深度（m）</option></select></label><label>底图<select data-control="basemap" aria-label="对比底图"><option value="satellite">卫星影像</option><option value="street">道路地图</option></select></label></div>
    <div class="mc-tools"><span>定位</span><button data-locate="boundary">正式边界</button><button data-locate="network">完整模型</button><button data-locate="A">Parsons 塘</button><button data-locate="B">自主塘</button><button data-locate="best">最大改善</button><button data-locate="worst">最大加重</button><span class="mc-tool-space"></span><label><input type="checkbox" data-layer="network" checked>管网</label><label><input type="checkbox" data-layer="plans" checked>规划设施</label><label><input type="checkbox" data-layer="historical" checked>历史积水点</label><label><input type="checkbox" data-layer="boundary" checked>边界</label></div>
    <div class="mc-maps"><div class="mc-map-panel" data-panel="left"><div class="mc-map-caption" data-caption="left"></div><div class="mc-map" data-map="left" aria-label="基准状态地理地图"></div><div class="mc-map-stat" data-stat="left"></div></div><div class="mc-map-panel" data-panel="right"><div class="mc-map-caption" data-caption="right"></div><div class="mc-map" data-map="right" aria-label="规划方案地理地图"></div><div class="mc-map-stat" data-stat="right"></div></div></div>
    <div class="mc-legend"></div><div class="mc-tile-error" hidden>底图瓦片加载失败，可切换道路地图重试；计算图层仍保留。</div>
    <div class="mc-footnote">圆点表示模型节点，大小为屏幕符号，颜色表示该节点的计算结果。不是地表淹没面积；历史点为静态位置参考。边界外跨界管网也参与本次计算。</div>
    <div class="mc-inspector"><div class="mc-inspector-head"><h3>变化位置清单 <span data-count></span></h3><label>范围<select data-control="scope" aria-label="变化清单统计范围"><option value="network">完整模型（含跨界）</option><option value="boundary">正式边界内</option></select></label><label>筛选<select data-control="filter" aria-label="节点变化筛选"><option value="all">所有变化</option><option value="new">新增溢流</option><option value="worsened">溢流量增加</option><option value="resolved">不再报告溢流</option><option value="improved">溢流量减少</option></select></label></div><div class="mc-change-summary"></div><div class="mc-inspector-grid"><div class="mc-location-list" aria-label="可定位的节点变化清单"></div><div class="mc-node-detail">点击地图节点或左侧清单，在两张地图上同时定位，并查看五状态原始数值。</div></div></div>`;

  const maps=['left','right'].map(side=>L.map(root.querySelector(`[data-map="${side}"]`),{preferCanvas:true,zoomControl:true,zoomSnap:.25,attributionControl:true}));
  const groups=maps.map(m=>L.layerGroup().addTo(m));
  const highlights=maps.map(m=>L.layerGroup().addTo(m));
  let tiles=[];
  maps.forEach((map,index)=>{
    L.control.scale({imperial:false,position:'bottomleft'}).addTo(map);
    map.on('move zoom',()=>{
      if(syncing)return;
      syncing=true;
      maps[1-index].setView(map.getCenter(),map.getZoom(),{animate:false});
      syncing=false;
    });
  });
  function setBasemap() {
    const url=basemap==='satellite'?'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}':'https://basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png';
    tiles.forEach((tile,i)=>maps[i].removeLayer(tile));
    root.querySelector('.mc-tile-error').hidden=true;
    tiles=maps.map(m=>{
      const tile=L.tileLayer(url,{maxZoom:21,maxNativeZoom:19,attribution:basemap==='satellite'?'Tiles © Esri, Maxar, Earthstar Geographics':'© OpenStreetMap contributors © CARTO'}).addTo(m);
      tile.on('tileerror',()=>root.querySelector('.mc-tile-error').hidden=false);
      tile.on('tileload',()=>root.querySelector('.mc-tile-error').hidden=true);
      tile.bringToBack();return tile;
    });
  }
  function allChanges() {
    return nodes.filter(f=>scope!=='boundary'||f.properties.inside_boundary).map(f=>{
      const a=f.properties.states[left],b=f.properties.states[right];
      return {f,a,b,kind:category(a,b),delta:a&&b?b.flood_volume_m3-a.flood_volume_m3:null};
    }).filter(x=>x.kind&&x.kind!=='unchanged').sort((a,b)=>Math.abs(b.delta)-Math.abs(a.delta)||a.f.properties.id.localeCompare(b.f.properties.id));
  }
  function locate(which) {
    if(which==='boundary') maps[0].fitBounds(L.geoJSON(boundary).getBounds(),{padding:[25,25],animate:false});
    else if(which==='network')maps[0].fitBounds(L.latLngBounds(nodes.map(ll)),{padding:[25,25],animate:false});
    else if(which==='A'||which==='B'){
      const f=nodeById.get(which==='A'?'STO-PO3':'OPT-B-167073');
      if(f){maps[0].setView(ll(f),17.5,{animate:false});showNode(f,false);}
    } else {
      const changes=allChanges().filter(x=>which==='best'?x.delta<0:x.delta>0);
      if(changes.length)showNode(changes[0].f,true);
    }
  }
  function popupHTML(f) {
    const p=f.properties;
    return `<strong>${esc(p.id)}</strong><p>${p.inside_boundary?'正式边界内':'正式边界外 · 跨界模型节点'}</p><table class="mc-popup-table"><thead><tr><th>状态</th><th>溢流 m³</th><th>蓄水深度 m</th></tr></thead><tbody>${Object.keys(labels).map(k=>`<tr class="${k===left||k===right?'mc-row-selected':''}"><td>${esc(labels[k])}</td><td>${fmt(p.states[k]?.flood_volume_m3,0)}</td><td>${fmt(p.states[k]?.max_ponded_depth_m,3)}</td></tr>`).join('')}</tbody></table><small>— 表示该状态不存在此设施。数值来自原始 RPT。</small>`;
  }
  function showNode(f,zoom=true) {
    selectedNode=f;
    if(zoom)maps[0].setView(ll(f),Math.max(17,maps[0].getZoom()),{animate:false});
    highlights.forEach((g,i)=>{
      g.clearLayers();
      const ring=L.circleMarker(ll(f),{radius:12,color:'#fff',weight:3,fill:false,interactive:false}).addTo(g);
      L.circleMarker(ll(f),{radius:14,color:'#2563eb',weight:2,fill:false,interactive:false}).addTo(g);
      if(f.properties.states[i===0?left:right])ring.bindTooltip(f.properties.id,{permanent:true,direction:'top',offset:[0,-12],className:'mc-tooltip'}).openTooltip();
    });
    root.querySelector('.mc-node-detail').innerHTML=popupHTML(f)+`<p class="mc-coordinates">${fmt(f.geometry.coordinates[1],6)}° N, ${fmt(f.geometry.coordinates[0],6)}° E</p>`;
    root.querySelectorAll('[data-node]').forEach(el=>el.classList.toggle('active',el.dataset.node===f.properties.id));
  }
  function draw() {
    root.querySelector('.mc-maps').classList.toggle('mc-delta',mode==='delta');
    root.querySelector('[data-control="metric"]').disabled=mode==='delta';
    root.querySelectorAll('[data-mode]').forEach(el=>el.classList.toggle('active',el.dataset.mode===mode));
    root.querySelector('[data-caption="left"]').textContent=labels[left];
    root.querySelector('[data-caption="right"]').textContent=mode==='delta'?`${labels[right]} 相对 ${labels[left]} · 变化位置`:labels[right];
    groups.forEach((group,index)=>{
      group.clearLayers();
      const state=index===0?left:right;
      for(const f of geo.features){
        const p=f.properties;
        if(p.kind==='boundary'&&layers.boundary)L.geoJSON(f,{style:{color:basemap==='satellite'?'#fef08a':'#475569',weight:2,dashArray:'6 5',fill:false},interactive:false}).addTo(group);
        if(p.kind==='link'&&p.states.includes(state)){
          const planned=!p.states.includes('L1');
          if((planned&&!layers.plans)||(!planned&&!layers.network))continue;
          const color=planned?(p.states.includes('A')?'#fbbf24':'#d8b4fe'):(basemap==='satellite'?'#b4d8e5':'#809db0');
          L.geoJSON(f,{style:{color,weight:planned?4:1.2,opacity:planned?1:.5,dashArray:planned?'7 4':undefined}})
            .bindPopup(`<b>${esc(p.id)}</b><p>${esc(p.from)} → ${esc(p.to)}</p><p>${planned?'规划连接':'源模型管网'} · ${esc(p.type)}</p><small>${p.has_vertices?'采用源模型折点':'采用模型节点连线；未提供线路折点'}</small>`).addTo(group);
        }
        if((p.kind==='parcel'||p.kind==='pond')&&layers.plans&&p.states.includes(state)){
          L.geoJSON(f,{style:{color:'#d8b4fe',weight:p.kind==='pond'?3:2,fillColor:'#a855f7',fillOpacity:p.kind==='pond'?.32:.03,dashArray:p.kind==='parcel'?'5 3':undefined}})
            .bindPopup(`<b>${p.kind==='pond'?'自主方案拟建塘':'Makani 地块'} · 167073</b><p>${p.kind==='pond'?'塘顶 2,500 m² · 深 1 m · 规划 footprint':'工业 / 展厅 · 未建设 · 已分配'}</p><small>建设及管线许可尚未核定。</small>`).addTo(group);
        }
        if(p.kind==='historical'&&layers.historical)L.marker(ll(f),{icon:L.divIcon({className:'mc-hotspot',html:'×',iconSize:[22,22],iconAnchor:[11,11]})}).bindPopup(`<b>客户历史积水点</b><p>${p.inside_boundary?'正式边界内':'边界附近'}</p><small>静态参考点；本组一维结果不能判断该点地表积水是否消失。</small>`).addTo(group);
      }
      const visible=nodes.filter(f=>f.properties.states[state]).sort((a,b)=>a.properties.states[state][metricKeys[metric]]-b.properties.states[state][metricKeys[metric]]);
      for(const f of visible){
        const p=f.properties, n=p.states[state], kind=category(p.states[left],p.states[right]);
        const isDelta=mode==='delta'&&index===1;
        const v=n[metricKeys[metric]];
        const changed=kind&&kind!=='unchanged';
        const radius=isDelta?(changed?6:2.2):(v>0?5.5:2.2);
        const color=isDelta?(categories[kind]?.color||'#c4b5fd'):absoluteColour(v,metric);
        L.circleMarker(ll(f),{radius,color:v>0||changed?'#fff':color,weight:v>0||changed?1.1:0,fillColor:color,fillOpacity:1})
          .bindTooltip(`${esc(p.id)} · ${isDelta?(categories[kind]?.label||'新增设施'):fmt(v,metric==='depth'?3:0)+(metric==='depth'?' m':' m³')}`,{direction:'top'})
          .on('click',()=>showNode(f,false)).addTo(group);
      }
      if(layers.plans){
        const ponds=nodes.filter(f=>f.properties.states[state]?.type==='STORAGE'&&!f.properties.states.L1);
        for(const f of ponds)L.marker(ll(f),{icon:L.divIcon({className:'mc-pond-label',html:`<span>${state==='A'?'Parsons 塘':'自主塘'}<small>${esc(f.properties.id)}</small></span>`,iconSize:[114,38],iconAnchor:[57,45]})}).on('click',()=>showNode(f,false)).addTo(group);
      }
      const s=data.states.find(s=>s.key===state);
      root.querySelector(`[data-stat="${index===0?'left':'right'}"]`).innerHTML=`完整模型：溢流节点 <b>${s.outputs.flooded_node_count}</b> · 累计溢流 <b>${fmt(s.outputs.node_flood_volume_m3,0)} m³</b>`;
    });
    const legend=mode==='delta'?Object.values(categories).map(x=>[x.color,x.label]):metric==='depth'?[['#a3afc1','0 / 未报告'],['#38bdf8','0–0.15'],['#facc15','0.15–0.30'],['#fb923c','0.30–0.50'],['#e11d48','≥0.50 m']]:[['#a3afc1','0 / 未报告'],['#38bdf8','0–10'],['#facc15','10–50'],['#fb923c','50–100'],['#e11d48','≥100 m³']];
    root.querySelector('.mc-legend').innerHTML=`<b>${mode==='delta'?'溢流变化':metric==='depth'?'两图统一水深色标':'两图统一溢流色标'}</b>`+legend.map(([c,l])=>`<span><i style="background:${c}"></i>${l}</span>`).join('')+'<span class="mc-legend-assets">虚线：规划连接 · 紫色：自主塘 / 地块 · ×：历史点</span>';
    drawList();
    if(selectedNode)showNode(selectedNode,false);
    requestAnimationFrame(()=>{
      const center=maps[0].getCenter(),zoom=maps[0].getZoom();
      syncing=true;
      maps.forEach(m=>{m.invalidateSize({pan:false});m.setView(center,zoom,{animate:false});});
      syncing=false;
    });
  }
  function drawList() {
    const changes=allChanges(), filtered=changes.filter(x=>filter==='all'||x.kind===filter);
    root.querySelector('[data-count]').textContent=`${filtered.length} 处`;
    root.querySelector('.mc-change-summary').innerHTML=Object.entries(categories).filter(([k])=>k!=='unchanged').map(([k,v])=>`<span style="--change:${v.color}">${v.label} <b>${changes.filter(x=>x.kind===k).length}</b></span>`).join('');
    root.querySelector('.mc-location-list').innerHTML=filtered.length?filtered.map(x=>`<button data-node="${esc(x.f.properties.id)}"><span><i style="background:${categories[x.kind].color}"></i><b>${esc(x.f.properties.id)}</b><small>${x.f.properties.inside_boundary?'边界内':'跨界'}</small></span><span>${fmt(x.a.flood_volume_m3,0)} → ${fmt(x.b.flood_volume_m3,0)} m³ <strong style="color:${x.delta>0?'#be123c':'#047857'}">${x.delta>0?'+':''}${fmt(x.delta,0)}</strong></span></button>`).join(''):`<div class="mc-empty">${left===right?'两侧选中相同状态。':left==='L1'&&right==='L2'||left==='L2'&&right==='L1'?'L1 与 L2 相同：正式边界内现状 pond 为 0。':'当前范围及筛选下没有变化节点。'}</div>`;
    root.querySelectorAll('[data-node]').forEach(el=>el.addEventListener('click',()=>showNode(nodeById.get(el.dataset.node))));
  }
  root.querySelectorAll('[data-control]').forEach(el=>el.addEventListener('change',()=>{
    const name=el.dataset.control;
    if(name==='left')left=el.value;
    if(name==='right'){right=el.value;onStateChange?.(right);}
    if(name==='metric')metric=el.value;
    if(name==='basemap'){basemap=el.value;setBasemap();}
    if(name==='scope')scope=el.value;
    if(name==='filter')filter=el.value;
    draw();
  }));
  root.querySelectorAll('[data-mode]').forEach(el=>el.addEventListener('click',()=>{mode=el.dataset.mode;draw();}));
  root.querySelectorAll('[data-locate]').forEach(el=>el.addEventListener('click',()=>locate(el.dataset.locate)));
  root.querySelectorAll('[data-layer]').forEach(el=>el.addEventListener('change',()=>{layers[el.dataset.layer]=el.checked;draw();}));
  maps[0].setView(ll(nodeById.get('OPT-B-167073')),17,{animate:false});
  setBasemap();draw();
  const observer=new ResizeObserver(()=>maps.forEach(m=>m.invalidateSize({pan:false})));
  maps.forEach(m=>observer.observe(m.getContainer()));
  return {
    setRightState(key){if(right===key)return;right=key;root.querySelector('[data-control="right"]').value=key;draw();},
    resize(){maps.forEach(m=>m.invalidateSize({pan:false}));},
    destroy(){observer.disconnect();maps.forEach(m=>m.remove());},
  };
}
window.MussafahMap={mount};
