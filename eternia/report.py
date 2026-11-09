"""Create a portable, offline HTML world-history explorer (no dependencies)."""
import json


def make_html(data):
    if data.get('mode') in ('community', 'institutions'):
        return make_community_html(data)
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
 const max=Math.max(...values),end=Math.max(1,data.year);
 const pts=values.map((value,i)=>[20+snaps[i].year*860/end,180-(value/Math.max(1,max))*154]);
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


def make_community_html(data):
    """Render the community's recorded state, without rerunning its policies."""
    encoded = json.dumps(data, ensure_ascii=False, allow_nan=False).replace('<', '\\u003c')
    template = r'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Eternia v0.3 · Community Observatory</title>
<style>
:root{color-scheme:dark;--bg:#0b1419;--panel:#122229;--line:#2b4249;--text:#e7eee9;--muted:#a3b9b7;--gold:#e3bd7e;--mint:#83cdb4;--red:#e18f82}
*{box-sizing:border-box}body{margin:0;background:radial-gradient(ellipse at 90% 0,#254337 0,transparent 46%),var(--bg);color:var(--text);font:15px/1.5 system-ui,-apple-system,Segoe UI,sans-serif}main{max-width:1360px;padding:42px 24px 72px;margin:auto}h1{font-size:clamp(32px,5vw,54px);letter-spacing:-2px;line-height:1.1;margin:12px 0}h2{font-size:19px;letter-spacing:-.3px;margin:0 0 14px}h3{font-size:20px;margin:6px 0 0}p{color:var(--muted);margin:8px 0 18px}.eyebrow,small{font-size:11px;letter-spacing:1.6px;text-transform:uppercase;color:var(--gold)}.header{display:flex;justify-content:space-between;align-items:start;gap:24px}.stamp{padding:12px 16px;border:1px solid var(--line);border-radius:12px;color:var(--mint);white-space:nowrap}.panel,.agent{border:1px solid var(--line);background:var(--panel);border-radius:16px;padding:22px;min-width:0}.timeline{margin:22px 0}.row{display:flex;justify-content:space-between;align-items:center;gap:14px}.muted,.hint{color:var(--muted);font-size:12px}.stats{display:grid;grid-template-columns:repeat(6,1fr);gap:12px;margin-bottom:24px}.stats>div{border-left:2px solid var(--line);padding:8px 14px}.value{display:block;font-size:28px;letter-spacing:-1px;font-weight:700}.agents{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:12px}.agent{padding:18px;position:relative}.role{color:var(--mint);font-size:12px}.badge{font-size:11px;padding:2px 7px;border:1px solid var(--line);border-radius:20px;color:var(--muted)}.goal{min-height:45px;font-size:12px;margin:12px 0}.inventory{display:grid;grid-template-columns:1fr 1fr;gap:7px;font-size:12px;color:var(--muted);margin:14px 0}.inventory b{color:var(--text);font-weight:600}progress{display:block;width:100%;height:6px;accent-color:var(--mint);margin:8px 0 4px}.two{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-top:16px}#network{width:100%;height:290px;display:block}#chart{width:100%;height:200px;display:block}.scroll{max-height:370px;overflow:auto;scrollbar-color:var(--line) transparent}article{padding:12px 0;border-bottom:1px solid var(--line)}article:last-child{border-bottom:0}article p{color:var(--text);margin:6px 0;font-size:13px}time{font-size:11px;color:var(--gold)}.empty{padding:20px 0;color:var(--muted);font-size:13px}label{font-size:12px;color:var(--muted)}select,button{font:inherit;font-size:12px;border:1px solid var(--line);border-radius:8px;background:#0d1b21;color:var(--text);padding:7px 10px}select{max-width:210px}button{cursor:pointer}button:hover,button:focus-visible{border-color:var(--mint)}input[type=range]{width:100%;accent-color:var(--mint);margin:18px 0 6px}details{font-size:12px;margin-top:10px;color:var(--muted)}summary{cursor:pointer;color:var(--mint)}pre{white-space:pre-wrap;overflow-wrap:anywhere;line-height:1.6;font-size:11px}.offer{display:flex;justify-content:space-between;gap:12px;padding:10px 0;border-bottom:1px solid var(--line);font-size:13px}.offer span{color:var(--muted)}.accepted{color:var(--mint)}.rejected{color:var(--red)}.section-label{margin:28px 0 12px}.footer{font-size:12px;margin:26px 0 0;max-width:920px}svg text{font-family:inherit}
@media(max-width:1100px){.agents{grid-template-columns:repeat(3,minmax(0,1fr))}.stats{grid-template-columns:repeat(3,1fr)}}
@media(max-width:720px){main{padding:24px 16px 46px}.header{display:block}.stamp{display:inline-block;margin:8px 0}.two{grid-template-columns:1fr}.agents{grid-template-columns:repeat(2,minmax(0,1fr))}.panel{padding:18px}.stats>div{padding:6px 10px}.value{font-size:24px}.row{flex-wrap:wrap}.goal{min-height:0}}
@media(max-width:430px){.agents{grid-template-columns:1fr}.stats{grid-template-columns:repeat(2,1fr)}.inventory{grid-template-columns:repeat(4,1fr)}h1{letter-spacing:-1px}}
</style></head><body><main>
<header class="header"><div><div class="eyebrow">Eternia / Society Engine v0.3</div><h1>Five lives. One shared world.</h1><p>Follow the trades, tensions, and knowledge that cross generations.</p></div><div class="stamp" id="runStamp"></div></header>
<section class="panel timeline" aria-label="Recorded history timeline"><div class="row"><h2 style="margin:0">Community history</h2><strong id="yearLabel"></strong></div><input type="range" id="timeline" min="0" step="1" aria-label="Select recorded year"><div class="row hint"><span>Year 0 · Five founders</span><span id="endLabel"></span></div></section>
<div class="stats" id="stats" aria-live="polite"></div>
<div class="row section-label"><h2 style="margin:0">The community</h2><span class="hint">Needs, goals, and property at the selected year</span></div><section id="agents" class="agents" aria-label="Living community members"></section>
<section id="institutionPanel" hidden style="margin-top:24px"><div class="row section-label"><h2 style="margin:0">Institutions and collective decisions</h2><span class="hint" id="institutionSummary"></span></div><p class="hint">Members contribute existing resources, propose decisions, and vote. Approved authority and available funds are checked again before execution.</p><div id="institutions" class="two"></div><section class="panel" style="margin-top:16px"><h2>Settlement policy</h2><div id="settlementPolicies"></div><p class="hint" style="margin-bottom:0">These settings connect approved decisions to annual production and exchange. Production remains an aggregate population model.</p></section></section>
<div class="two"><section class="panel"><div class="row"><h2>Relationships</h2><span class="hint">Trust, directed from one person to another</span></div><svg id="network" viewBox="0 0 520 290" role="img" aria-label="Community relationship network"></svg><p class="hint" style="margin-bottom:0">Green: trust · Coral: distrust · Stronger lines indicate stronger relationships. Hover a line or person for details.</p></section>
<section class="panel"><div class="row"><h2>Open exchange</h2><span class="badge" id="offerCount"></span></div><div class="scroll" id="offers"></div><p class="hint" style="margin:14px 0 0">Offers reserve the owner's goods or coins. Another person must independently accept the terms.</p></section></div>
<div class="two"><section class="panel"><div class="row"><h2>Historical record</h2><label>Show <select id="eventFilter" aria-label="Filter historical events"><option value="">All events</option></select></label></div><div class="scroll" id="events"></div></section>
<section class="panel"><div class="row"><h2>Inside a decision</h2><label>Person <select id="personFilter" aria-label="Choose a community member"></select></label></div><div class="scroll" id="decisions"></div></section></div>
<section class="panel" style="margin-top:16px"><div class="row"><h2>Across the years</h2><label>Measure <select id="chartMetric" aria-label="Choose history chart measure"><option value="population">Population</option><option value="coins">Personal coins</option><option value="knowledge">People with reproduced knowledge</option><option value="trades">Completed peer trades</option></select></label></div><svg id="chart" viewBox="0 0 1000 200" role="img" aria-label="Recorded community measure over time"></svg></section>
<details class="panel" style="margin-top:16px"><summary>Resource accounting and experiment rules</summary><div id="accounting"></div><p class="hint">Trades move existing resources between people. Production and consumption are explicit flows; annual population dynamics are aggregate approximations. A policy chooses actions from public observations; the world validates them. A successful run is evidence to inspect, not proof of open-ended intelligence.</p></details>
<p class="footer">This is an offline, seeded experiment using classical goal policies. Different personal incentives can produce cooperation and competition under programmed rules. No LLM, network connection, or guaranteed partnership is involved. Every card and event comes from the recorded run.</p>
</main><script>
const data=__ETERNIA_DATA__;
const snaps=data.snapshots, byId=id=>document.getElementById(id), slider=byId('timeline');
const n=value=>Number.isFinite(Number(value))?Number(value):0;
const fmt=value=>n(value).toLocaleString('en-US',{maximumFractionDigits:1});
const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const colors=['#83cdb4','#e3bd7e','#9fb8eb','#dca7c7','#b9c780'];
const institutional=data.mode==='institutions';
let current=snaps.length-1;
slider.max=Math.max(0,current);slider.value=current;
byId('runStamp').textContent='Seed '+data.seed+' · '+fmt(data.ticks_per_year||4)+' cycles / year';
byId('endLabel').textContent='Year '+fmt(data.year);
const kinds=[...new Set((data.events||[]).map(e=>e.kind))].sort();
byId('eventFilter').innerHTML+=[...kinds].map(k=>`<option value="${esc(k)}">${esc(k).replaceAll('_',' ')}</option>`).join('');
function goalLabel(a){const g=a.goal||{};const kind=String(g.kind||a.role);if(kind.includes('house')||a.role==='builder')return 'Build '+fmt(g.target||3)+' houses';if(kind.includes('knowledge')||a.role==='researcher')return 'Understand unusual minerals';if(kind.includes('food')||a.role==='farmer')return 'Secure '+fmt(g.target||12)+' food';if(a.role==='merchant')return 'Grow trading wealth to '+fmt(g.target||120)+' coins';return 'Earn '+fmt(g.target||a.wealth_goal||60)+' coins';}
function goalProgress(a){const g=a.goal||{},inv=a.inventory||{};let value=inv.coins||0,target=g.target||a.wealth_goal||60;if(a.role==='builder'){value=(a.structures||{}).house||0;target=g.target||3;}if(a.role==='researcher'){value=a.knowledge||0;target=2;}if(a.role==='farmer'){value=inv.food||0;target=g.target||12;}return [n(value),Math.max(1,n(target))];}
function render(){
const snap=snaps[current],agents=snap.agents||[],metrics=snap.metrics||{},towns=snap.settlements||[];
byId('yearLabel').textContent='Year '+fmt(snap.year)+' · Tick '+fmt(snap.tick||0);
const stats=[['Population',snap.population],['Living individuals',agents.length],['Peer trades',metrics.trades||0],['Conflicts',metrics.conflicts||0],['Cooperations',metrics.cooperations||0],['Knowledge transfers',metrics.knowledge_transfers||0]];
byId('stats').innerHTML=stats.map(([label,value])=>`<div><small>${esc(label)}</small><strong class="value">${fmt(value)}</strong></div>`).join('');
byId('agents').innerHTML=agents.length?agents.map((a,i)=>{const inv=a.inventory||{},[value,target]=goalProgress(a),town=towns.find(t=>t.id===a.home);return `<article class="agent" style="border-top:3px solid ${colors[i%colors.length]}"><div class="row"><span class="role">${esc(a.role)}</span><span class="badge">Generation ${fmt(a.generation||0)}</span></div><h3>${esc(a.name)}</h3><div class="hint">${esc(town?.name||'Unknown settlement')} · Age ${fmt(a.age)}</div><div class="goal">${esc(goalLabel(a))}<progress value="${value}" max="${target}" aria-label="${esc(a.name)} goal progress"></progress><span class="hint">${fmt(value)} / ${fmt(target)}</span></div><div class="inventory">${['food','wood','iron','coins'].map(r=>`<span>${esc(r)} <b>${fmt(inv[r])}</b></span>`).join('')}</div><div class="hint">Hunger ${fmt(a.hunger)} · Energy ${fmt(a.energy)}<br>Reputation ${fmt(n(a.reputation)*100)}% · Knowledge ${fmt(a.knowledge)}/2</div><details><summary>Skills and remembered experiences</summary><p class="hint">${esc((a.skills||[]).join(', '))}</p><pre>${esc(JSON.stringify((a.memory||[]).slice(-5),null,2))}</pre></details></article>`}).join(''):'<p class="empty">No living named agents at this point.</p>';
renderNetwork(agents);renderOffers(snap,agents);renderEvents(snap);renderDecisions(snap,agents);drawChart();
renderInstitutions(snap,agents,towns);
const ledger=snap.ledger||{};byId('accounting').innerHTML=`<p class="hint">Cumulative production: ${['food','wood','iron','coins'].map(r=>esc(r)+' '+fmt((ledger.produced||{})[r])).join(' · ')}<br>Cumulative consumption: ${['food','wood','iron','coins'].map(r=>esc(r)+' '+fmt((ledger.consumed||{})[r])).join(' · ')}</p>`;
}
function renderInstitutions(snap,agents,towns){
byId('institutionPanel').hidden=!institutional;if(!institutional)return;
const institutions=snap.institutions||[],metrics=snap.metrics||{};
byId('institutionSummary').textContent=fmt(metrics.institutions_formed)+' formed · '+fmt(metrics.proposals_passed)+' decisions enacted · '+fmt(metrics.institutions_collapsed)+' collapsed';
byId('institutions').innerHTML=institutions.length?institutions.map(inst=>{const members=Array.from(inst.members||[]),inventory=inst.inventory||{},town=towns.find(t=>t.id===inst.settlement_id),decisions=inst.decisions||[];return `<article class="panel"><div class="row"><h3>${esc(inst.name)}</h3><span class="badge ${inst.active===false?'rejected':'accepted'}">${inst.active===false?'Collapsed':'Active'}</span></div><div class="hint">${esc(town?.name||'Settlement '+inst.settlement_id)} · Institution #${esc(inst.id)}</div><p class="hint" style="margin-top:12px">Members: ${members.length?members.map(id=>esc(agents.find(a=>a.id===id)?.name||'Person #'+id)).join(', '):'No current members'}</p><div class="inventory">${['food','wood','iron'].map(r=>`<span>${esc(r)} <b>${fmt(inventory[r])}</b></span>`).join('')}<span>Treasury <b>${fmt(inst.treasury)}</b></span></div><details><summary>Rules and collective decisions (${fmt(decisions.length)})</summary><pre>${esc(JSON.stringify(inst.rules||{},null,2))}</pre><div class="scroll">${decisions.length?decisions.slice(-12).reverse().map(d=>`<article><div class="row"><strong>${esc(String(d.kind||d.type||'proposal').replaceAll('_',' '))}</strong><span class="badge">${esc(d.status||'pending')}</span></div><div class="hint">Proposal #${esc(d.id)} · ${esc(JSON.stringify(d.params||{}))}</div><pre>${esc(JSON.stringify(d.votes||{},null,2))}</pre>${d.enacted!==undefined?`<div class="hint">Executed at tick ${fmt(d.enacted)}</div>`:''}</article>`).join(''):'<p class="empty">No decisions recorded.</p>'}</div></details></article>`}).join(''):'<p class="empty">No institution has formed by this year. Formation and participation depend on individual decisions.</p>';
const policies=snap.settlement_policies||{};const entries=Array.isArray(policies)?policies.map((p,i)=>[p.settlement_id??i,p]):Object.entries(policies);
byId('settlementPolicies').innerHTML=entries.length?entries.map(([id,p])=>{const town=towns.find(t=>String(t.id)===String(id));return `<article><strong>${esc(town?.name||'Settlement '+id)}</strong><p class="hint">Member levy ${fmt(n(p.tax_rate)*100)}% · Communal labor ${fmt(n(p.communal_labor)*100)}% · Granaries ${fmt(p.granaries??(town?.buildings||{}).granary)} · Added storage ${fmt(p.granary_capacity)} food<br>Trade partners: ${esc((p.trade_partners||[]).map(partner=>towns.find(t=>t.id===partner)?.name||partner).join(', ')||'None')}</p></article>`}).join(''):'<p class="hint">No enacted settlement policies are recorded at this point.</p>';
}
function renderNetwork(agents){
const count=agents.length,positions=agents.map((a,i)=>({id:a.id,x:260+Math.cos(i*2*Math.PI/Math.max(1,count)-Math.PI/2)*190,y:145+Math.sin(i*2*Math.PI/Math.max(1,count)-Math.PI/2)*100}));let edges='';
agents.forEach((a,i)=>{agents.forEach((b,j)=>{if(i===j)return;const trust=n((a.trust||{})[b.id]);if(Math.abs(trust)<.005)return;const p=positions[i],q=positions[j],dx=q.x-p.x,dy=q.y-p.y,len=Math.max(1,Math.hypot(dx,dy)),ox=-dy/len*3,oy=dx/len*3;edges+=`<line x1="${p.x+ox}" y1="${p.y+oy}" x2="${q.x+ox}" y2="${q.y+oy}" stroke="${trust>0?'#83cdb4':'#e18f82'}" stroke-opacity="${Math.min(.9,.2+Math.abs(trust)*.6)}" stroke-width="${1+Math.abs(trust)*4}"><title>${esc(a.name)} → ${esc(b.name)}: ${fmt(trust)} trust</title></line>`;});});
byId('network').innerHTML=edges+agents.map((a,i)=>{const p=positions[i];return `<g><circle cx="${p.x}" cy="${p.y}" r="21" fill="#122229" stroke="${colors[i%colors.length]}" stroke-width="2"><title>${esc(a.name)} · ${esc(a.role)} · reputation ${fmt(n(a.reputation)*100)}%</title></circle><text x="${p.x}" y="${p.y+4}" text-anchor="middle" fill="${colors[i%colors.length]}" font-size="12">${esc(String(a.name).slice(0,1))}</text><text x="${p.x}" y="${p.y+37}" text-anchor="middle" fill="#e7eee9" font-size="11">${esc(a.name)}</text></g>`}).join('');
}
function renderOffers(snap,agents){const offers=snap.offers||[];byId('offerCount').textContent=offers.length+' active';byId('offers').innerHTML=offers.length?offers.map(o=>{const actor=agents.find(a=>a.id===o.actor);return `<div class="offer"><div><strong>${esc(actor?.name||'Agent '+o.actor)}</strong><br><span>${esc(o.direction==='buy'?'Wants to buy':'Offers to sell')} ${fmt(o.amount)} ${esc(o.resource)}</span></div><div>${fmt(o.unit_price)} coins / unit<br><span>Offer #${esc(o.id)}</span></div></div>`}).join(''):'<p class="empty">No open offers. Exchanges depend on what people currently need and can afford.</p>';}
function atTime(entry,snap){return entry.year<=snap.year&&(entry.year<snap.year||entry.tick===undefined||entry.tick<=snap.tick);}
function renderEvents(snap){const kind=byId('eventFilter').value;const recorded=(data.events||[]).slice(0,snap.event_count??data.events.length);const events=recorded.filter(e=>atTime(e,snap)&&(!kind||e.kind===kind)).slice(-80).reverse();byId('events').innerHTML=events.length?events.map(e=>`<article><time>Year ${fmt(e.year)} · Tick ${fmt(e.tick||0)} · ${esc(e.kind).replaceAll('_',' ')}</time><p>${esc(e.message)}</p></article>`).join(''):'<p class="empty">No matching events by this year.</p>';}
function renderDecisions(snap,agents){const select=byId('personFilter'),previous=select.value;select.innerHTML=agents.map(a=>`<option value="${n(a.id)}">${esc(a.name)}</option>`).join('');if(agents.some(a=>String(a.id)===previous))select.value=previous;const id=n(select.value);const recorded=(data.decisions||[]).slice(0,snap.decision_count??(data.decisions||[]).length);const decisions=recorded.filter(d=>atTime(d,snap)&&n(d.actor??d.proposal?.actor)===id).slice(-20).reverse();byId('decisions').innerHTML=decisions.length?decisions.map(d=>{const result=d.result||{},p=d.proposal||{};return `<article><time>Year ${fmt(d.year)} · Tick ${fmt(d.tick||0)} · ${esc(p.type||'action').replaceAll('_',' ')}</time><span class="badge ${result.success?'accepted':'rejected'}">${result.success?'Accepted':'Rejected'}</span><p>${esc(d.rationale||'')}</p><div class="hint">${esc(result.message||'')}</div><details><summary>Proposed action</summary><pre>${esc(JSON.stringify(p,null,2))}</pre></details></article>`}).join(''):'<p class="empty">No recorded decisions for this person by this year.</p>';}
function drawChart(){const key=byId('chartMetric').value,values=snaps.map(s=>key==='coins'?(s.agents||[]).reduce((sum,a)=>sum+n(a.inventory?.coins),0):key==='knowledge'?(s.agents||[]).filter(a=>a.knowledge===2).length:key==='trades'?n(s.metrics?.trades):n(s.population));const max=Math.max(1,...values),end=Math.max(1,n(data.year)),pts=snaps.map((s,i)=>[36+n(s.year)/end*920,166-values[i]/max*130]),selected=pts[current];byId('chart').innerHTML=`<line x1="36" x2="956" y1="166" y2="166" stroke="#2b4249"/><polyline points="${pts.map(p=>p.join(',')).join(' ')}" fill="none" stroke="#83cdb4" stroke-width="2.5"/><line x1="${selected[0]}" x2="${selected[0]}" y1="18" y2="167" stroke="#e3bd7e" stroke-dasharray="4 4"/><circle cx="${selected[0]}" cy="${selected[1]}" r="4" fill="#e3bd7e"/><text x="36" y="18" fill="#a3b9b7" font-size="11">Max ${fmt(Math.max(...values))} · Selected ${fmt(values[current])}</text><text x="36" y="190" fill="#a3b9b7" font-size="11">Year 0</text><text x="900" y="190" fill="#a3b9b7" font-size="11">Year ${fmt(data.year)}</text>`;}
slider.addEventListener('input',()=>{current=n(slider.value);render();});byId('eventFilter').addEventListener('change',()=>renderEvents(snaps[current]));byId('personFilter').addEventListener('change',()=>renderDecisions(snaps[current],snaps[current].agents||[]));byId('chartMetric').addEventListener('change',drawChart);render();
</script></body></html>'''
    if data.get('mode') == 'institutions':
        template = template.replace('Eternia v0.3 · Community Observatory', 'Eternia v0.4 · Institutional Observatory')
        template = template.replace('Eternia / Society Engine v0.3', 'Eternia / Society Engine v0.4')
        template = template.replace('Five lives. One shared world.', 'A community that can outlive its founders.')
        template = template.replace('Follow the trades, tensions, and knowledge that cross generations.',
                                    'Follow organizations, shared resources, votes, and their effects on settlement life.')
    return template.replace('__ETERNIA_DATA__', encoded)
