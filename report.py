"""Create a portable, offline HTML world-history explorer (no dependencies)."""
import json


def make_html(data):
    encoded = json.dumps(data, ensure_ascii=False).replace('<', '\\u003c')
    template = r'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Eternia — Historical Observatory</title>
<style>
:root {color-scheme:dark;--bg:#09131b;--panel:#10222d;--line:#2a4652;--text:#e4e9e7;--muted:#a5b9bb;--gold:#d8b877;--teal:#72c5b6}
*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at 80% 0,#203a41 0,transparent 33%),var(--bg);color:var(--text);font:15px system-ui,-apple-system,Segoe UI,sans-serif}
main{max-width:1200px;margin:auto;padding:38px 22px 90px}h1{font-size:42px;letter-spacing:-1.4px;margin:6px 0}h2{font-size:17px;margin:0 0 16px}
p{color:var(--muted);line-height:1.5}small,.overline{font-size:12px;letter-spacing:2px;text-transform:uppercase;color:var(--gold)}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:16px;padding:20px;min-width:0}
.cards{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:20px 0}.stat{font-size:30px;font-weight:750;margin-top:7px}
.content{display:grid;grid-template-columns:1.2fr .8fr;gap:14px;margin-top:14px}
svg{max-width:100%}#map{width:100%;height:auto;background:#122a30;border-radius:12px}circle.town{fill:#d9bc7b;stroke:#fff2cf;stroke-width:.65}circle.magic{fill:#92a8ff;stroke:#e0e5ff}
path.river{stroke:#478ea5;stroke-width:2.5;fill:none;opacity:.7}#timeline{width:100%;accent-color:var(--teal);margin:20px 0 4px}
#events{height:460px;overflow-y:auto}#events>article{border-bottom:1px solid var(--line);padding:12px 0}#events time{color:var(--gold);font-size:12px}#events p{margin:5px 0;color:var(--text);font-size:14px}
#chart{width:100%;height:200px}.legend{font-size:12px;fill:#a5b9bb}.hint{font-size:13px;margin:4px 0}
.npc-stats{display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin:18px 0}.npc-stats b{display:block;font-size:24px;margin-top:5px}
#npc{margin:14px 0}#decisions{max-height:460px;overflow-y:auto}#decisions article{padding:14px 0;border-bottom:1px solid var(--line)}
#decisions p{margin:6px 0}#decisions time{color:var(--gold)}.badge{font-size:11px;border:1px solid var(--line);padding:3px 7px;border-radius:20px;margin-left:8px;color:var(--teal)}.rejected{color:#ffb1a6}
details{color:var(--muted);font-size:13px}details summary{cursor:pointer}progress{width:100%;accent-color:var(--teal)}
@media(max-width:800px){.cards{grid-template-columns:repeat(2,1fr)}.content{grid-template-columns:1fr}h1{font-size:34px}}
@media(max-width:600px){.npc-stats{grid-template-columns:repeat(2,1fr)}}
</style></head><body><main>
<div class="overline">Project Eternia · Society Engine v0.2</div>
<h1>Historical Observatory</h1>
<p id="intro">An actual run of the rule-based prototype. Move through time to see what its simulated settlements and populations did.</p>
<div class="panel"><div style="display:flex;justify-content:space-between;align-items:center;gap:16px"><h2 style="margin:0">Simulation timeline</h2><b id="year">Year 0</b></div>
<input type="range" id="timeline" min="0" step="1" aria-label="Historical year">
<div style="display:flex;justify-content:space-between;color:var(--muted);font-size:12px"><span id="startLabel">Year Zero</span><span id="maxYear"></span></div></div>
<div class="cards">
<div class="panel"><small>Population</small><div class="stat" id="population"></div></div>
<div class="panel"><small>Settlements</small><div class="stat" id="settlements"></div></div>
<div class="panel"><small>Aether techniques</small><div class="stat" id="magic"></div></div>
<div class="panel"><small>Active named agents</small><div class="stat" id="agents"></div></div>
</div>
<section class="panel" id="npc" hidden>
<div class="overline">One agent · World-validated actions</div>
<h2 style="margin-top:8px" id="npcTitle">Edrin's decisions</h2><p id="goal"></p>
<div class="npc-stats"><div><small>Personal coins</small><b id="coins"></b></div><div><small>House ownership</small><b id="houses"></b></div><div><small>Hunger / 100</small><b id="hunger"></b></div><div><small>Energy / 100</small><b id="energy"></b></div></div>
<progress id="wealthProgress" aria-label="Progress toward personal wealth goal"></progress>
<p class="hint" id="npcState"></p><h2 style="margin-top:22px">Decision journal</h2>
<p class="hint">Each entry shows the proposal, its reason, and the world's response. Move the timeline to inspect earlier decisions.</p>
<div id="decisions"></div></section>
<div class="content"><section class="panel"><h2>Known world map</h2>
<svg id="map" viewBox="0 0 500 440" role="img" aria-label="Map showing settlements and population sizes">
<defs><pattern id="dots" width="24" height="24" patternUnits="userSpaceOnUse"><circle cx="2" cy="2" r="1" fill="#31505a"/></pattern></defs>
<rect width="500" height="440" fill="url(#dots)"/><path d="M-10 112 Q80 80 175 140 T500 240" class="river"/>
<g id="towns"></g></svg><p class="hint">Circle size represents settlement population. Purple indicates a reproduced Aether technique. Hover to inspect.</p></section>
<section class="panel"><h2>Historical events</h2><div id="events"></div></section></div>
<section class="panel" style="margin-top:14px"><h2 id="chartTitle">Population through history</h2><svg id="chart" viewBox="0 0 900 200" preserveAspectRatio="none" role="img" aria-label="Population over time"></svg></section>
<p class="hint">The world seed fixes randomness. The prototype has no human-controlled players, no combat, no realistic map generation, and no autonomous software updates. Designed for extension.</p>
</main><script>
const data=__ETERNIA_DATA__;
const snaps=data.snapshots, slider=document.getElementById('timeline');
const unit=data.demo?'Turn':'Year';
slider.max=snaps.length-1; document.getElementById('maxYear').textContent=unit+' '+data.year;
slider.setAttribute('aria-label','Simulation '+unit.toLowerCase());
if(data.demo){
 document.getElementById('startLabel').textContent='Turn 0';
 document.getElementById('intro').textContent='One miner pursues house ownership and personal wealth. An offline goal-based planner chooses from current observations; the world checks every action. The annual society simulation is paused during this experiment. No LLM is connected.';
 document.getElementById('chartTitle').textContent='Personal wealth through decisions';
 document.getElementById('chart').setAttribute('aria-label','Personal coins over time');
}
const fmt=n=>n.toLocaleString('en-US');
const escapeHtml=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function render(i){
 const snap=snaps[i];
 document.getElementById('year').textContent=unit+' '+fmt(snap.year);
 document.getElementById('population').textContent=fmt(snap.population);
 document.getElementById('settlements').textContent=fmt(snap.settlements.length);
 document.getElementById('magic').textContent=fmt(snap.magic_discoveries);
 document.getElementById('agents').textContent=fmt(snap.named_agents);
 document.getElementById('towns').innerHTML=snap.settlements.map(s=>{
 const x=s.x*5,y=s.y*4.4,r=Math.min(16,Math.max(3,Math.sqrt(s.population)/2.7));
 const focal=snap.focal_agent&&snap.focal_agent.home===s.id;
 return `<g>${focal?`<circle cx="${x}" cy="${y}" r="${r+5}" fill="none" stroke="#72c5b6" stroke-width="2"><title>${escapeHtml(snap.focal_agent.name)} is here</title></circle>`:''}<circle class="town ${s.knowledge===2?'magic':''}" cx="${x}" cy="${y}" r="${r}"><title>${escapeHtml(s.name)} — ${fmt(s.population)} residents, knowledge level ${s.knowledge}, ${(s.buildings||{}).house||0} houses</title></circle>${s.population>=150?`<text x="${x+r+3}" y="${y-5}" fill="#e5ecea" font-size="9">${escapeHtml(s.name)}</text>`:''}</g>`
 }).join('');
 const events=data.events.filter(e=>e.year<=snap.year).slice(-18).reverse();
 document.getElementById('events').innerHTML=events.length?events.map(e=>`<article><time>${unit} ${fmt(e.year)} · ${escapeHtml(e.kind)}</time><p>${escapeHtml(e.message)}</p></article>`).join(''):'<p>No events yet</p>';
 renderNpc(snap);
 drawChart(i);
}
function renderNpc(snap){
 const agent=snap.focal_agent, panel=document.getElementById('npc');
 panel.hidden=!agent;
 if(!agent)return;
 const town=snap.settlements.find(s=>s.id===agent.home), inv=agent.inventory;
 document.getElementById('npcTitle').textContent=agent.name+"'s decisions";
 document.getElementById('goal').textContent=data.demo.goal;
 document.getElementById('coins').textContent=fmt(inv.coins)+' / '+fmt(agent.wealth_goal);
 document.getElementById('houses').textContent=fmt(agent.structures.house||0);
 document.getElementById('hunger').textContent=fmt(agent.hunger);
 document.getElementById('energy').textContent=fmt(agent.energy);
 const progress=document.getElementById('wealthProgress');progress.max=agent.wealth_goal;progress.value=inv.coins;
 document.getElementById('npcState').textContent='Currently in '+town.name+' · Food '+fmt(inv.food)+' · Wood '+fmt(inv.wood)+' · Iron '+fmt(inv.iron)+' · Skills: '+agent.skills.join(', ')+'. A house remains in the settlement where it was built.';
 const decisions=(data.decisions||[]).filter(d=>d.year<=snap.year).slice(-24).reverse();
 document.getElementById('decisions').innerHTML=decisions.length?decisions.map(d=>{
  const result=d.result,p=d.perception||{},proposal=d.proposal||{};
  const action=String(proposal.type||'invalid proposal').replaceAll('_',' ');
  const inputs=Object.entries(proposal.params||{}).map(([key,value])=>key+': '+String(value)).join(' · ');
  const seen=p.inventory||{},deposits=p.deposits||{};
  return `<article><time>${unit} ${fmt(d.year)} · ${escapeHtml(action)}</time><span class="badge ${result.success?'':'rejected'}">${result.success?'Accepted':'Rejected'}</span>
  <p>${escapeHtml(d.rationale||'')}</p><p class="hint">${escapeHtml(inputs)}</p><p>${escapeHtml(result.message)}</p>
  <details><summary>What ${escapeHtml(agent.name)} observed</summary><p>${escapeHtml(p.settlement||'')} · Hunger ${fmt(p.hunger||0)} · Energy ${fmt(p.energy||0)} · Coins ${fmt(seen.coins||0)}<br>Accessible deposits: food ${fmt(deposits.food||0)}, wood ${fmt(deposits.wood||0)}, iron ${fmt(deposits.iron||0)}</p></details></article>`
 }).join(''):'<p>No decisions yet. Advance the timeline to watch the agent act.</p>';
}
function drawChart(selected){
 const values=snaps.map(s=>data.demo?s.focal_agent.inventory.coins:s.population);
 const max=Math.max(...values),end=snaps.length-1;
 const pts=values.map((value,i)=>[20+i*860/Math.max(1,end),180-(value/Math.max(1,max))*154]);
 const poly=pts.map(p=>p.join(',')).join(' ');
 const sel=pts[selected];
 document.getElementById('chart').innerHTML=`<line x1="20" y1="180" x2="880" y2="180" stroke="#45616a"/>
 <polyline points="${poly}" stroke="#72c5b6" stroke-width="2.5" fill="none" vector-effect="non-scaling-stroke"/>
 <line x1="${sel[0]}" x2="${sel[0]}" y1="10" y2="182" stroke="#d8b877" stroke-dasharray="4 4"/>
 <circle cx="${sel[0]}" cy="${sel[1]}" r="5" fill="#d8b877"/>
 <text x="26" y="16" class="legend">Max ${fmt(max)}</text><text x="20" y="196" class="legend">${unit} 0</text>
 <text x="830" y="196" class="legend">${data.year}</text>`;
}
slider.addEventListener('input',()=>render(+slider.value));slider.value=data.demo?snaps.length-1:0;render(+slider.value);
</script></body></html>'''
    return template.replace('__ETERNIA_DATA__', encoded)
