'use strict';
/* Eternia v0.8 Stage 4.
 *
 * This page draws what the Python server sends and posts the player's choices
 * back: a menu choice by its number, a question, a wait, a save. It never
 * computes a price, resolves an action or changes anyone's state; every number
 * shown here comes from the simulation. Text is always set with textContent,
 * because names are typed in by players. */

const TOKEN = document.querySelector('meta[name="eternia-token"]').content;
const GOODS = ['food', 'wood', 'iron'];
const RESOURCES = ['food', 'wood', 'iron', 'coins'];
const TABS = [
  ['act', 'Act'], ['town', 'Town & roads'], ['people', 'People'], ['economy', 'Economy'],
  ['politics', 'Politics'], ['timeline', 'Timeline'], ['journal', 'Journal'],
];
const ENDED_TABS = ['timeline', 'journal'];
const OPEN_SECTIONS = new Set(['Needs', 'Work', 'Market']);
const GROUPS = [['you', 'You'], ['prices', 'Prices'], ['town', 'Town'], ['jobs', 'Jobs'], ['politics', 'Politics']];
const ASKED = {
  work: 'You asked about work', news: 'You asked what has been happening', trade: 'You asked about trade and the roads',
  politics: 'You asked about local politics', themselves: 'You asked how they are doing and what they want',
  person: 'You asked what they think of someone', proposal: 'You asked how they would vote',
  join: 'You asked them to join your organization', work_for_you: 'You asked if they would work for you',
  teach: 'You asked them to teach you', tell: 'You told them something you had heard',
};

const ui = {
  state: null, tab: 'act', busy: null,
  person: null, topics: null, loadingTopics: false,
  timeline: null, timelineLimit: 40, loadingTimeline: false, showRoutine: false, railRoutine: false,
  town: null, sections: {}, dialog: false, saves: null, exported: null,
};

// ----- Small helpers ------------------------------------------------------

function h(tag, props, ...children) {
  const svg = tag.startsWith('svg:');
  const el = svg ? document.createElementNS('http://www.w3.org/2000/svg', tag.slice(4)) : document.createElement(tag);
  for (const [key, value] of Object.entries(props || {})) {
    if (value === null || value === undefined || value === false) continue;
    if (key === 'text') el.textContent = value;
    else if (key === 'style') Object.assign(el.style, value);
    else if (key.startsWith('on')) el.addEventListener(key.slice(2), value);
    else if (!svg && (key === 'value' || key === 'checked')) el[key] = value;
    else el.setAttribute(key, value === true ? '' : value);
  }
  for (const child of children.flat(Infinity)) {
    if (child === null || child === undefined || child === false || child === '') continue;
    el.append(child instanceof Node ? child : String(child));
  }
  return el;
}

const fmt = (value) => (value === null || value === undefined) ? '–' : String(Math.round(value * 100) / 100);
const pct = (value) => `${Math.round((value || 0) * 100)}%`;
const signed = (value) => `${value > 0 ? '+' : value < 0 ? '−' : ''}${fmt(Math.abs(value || 0))}`;
const cap = (text) => text ? text.charAt(0).toUpperCase() + text.slice(1) : text;
const when = (c) => `Year ${c.year}, season ${c.season}`;
const empty = (text) => h('p', {class: 'empty'}, text);

function card(title, body, note, extra) {
  return h('section', {class: 'card'},
    h('div', {class: 'card-title'}, h('h3', null, title), note ? h('p', null, note) : null, extra || null),
    body);
}

function facts(rows) {
  return h('dl', {class: 'facts'}, rows.filter(Boolean).map(([term, value]) => [h('dt', null, term), h('dd', null, value)]));
}

function table(headers, rows, rowClass) {
  return h('div', {class: 'table-wrap'}, h('table', null,
    h('thead', null, h('tr', null, headers.map(([label, numeric]) => h('th', {class: numeric ? 'num' : null}, label)))),
    h('tbody', null, rows.map((cells, index) => h('tr', {class: rowClass ? rowClass(index) : null},
      cells.map((cell, column) => h('td', {class: headers[column][1] ? 'num' : null}, cell)))))));
}

function toast(message, kind = 'info', ms = 6500) {
  const el = h('div', {class: `toast ${kind}`}, message);
  document.getElementById('toasts').append(el);
  setTimeout(() => el.remove(), ms);
}

// ----- Talking to the server ----------------------------------------------

async function api(method, name, body) {
  const options = {method, headers: {'X-Eternia-Token': TOKEN}};
  if (body !== undefined) {
    options.headers['Content-Type'] = 'application/json';
    options.body = JSON.stringify(body);
  }
  let response;
  try {
    response = await fetch(`/api/${name}`, options);
  } catch (error) {
    throw new Error('The Eternia server is not answering. Is it still running in the terminal?');
  }
  let data;
  try { data = await response.json(); } catch (error) { data = {error: `The server answered ${response.status}.`}; }
  if (!response.ok) {
    const failure = new Error(data.error || `The server answered ${response.status}.`);
    failure.data = data;
    throw failure;
  }
  return data;
}

async function run(label, task) {
  if (ui.busy) return;
  ui.busy = label;
  render();
  try {
    await task();
  } catch (error) {
    if (error.data && error.data.state) adopt(error.data.state);  // the present, after a stale request
    toast(error.message, 'error', 9000);
  } finally {
    ui.busy = null;
    render();
  }
}

function adopt(state) {
  ui.state = state;
  if (state.over && !ENDED_TABS.includes(ui.tab)) ui.tab = 'journal';
  if (!state.over && ui.person !== null && !state.people.some((p) => p.id === ui.person)) ui.person = null;
}

function afterTurn(response) {
  adopt(response.state);
  const turn = response.turn;
  const last = turn.results[turn.results.length - 1];
  if (turn.over) toast('Your household has ended; no heir remains to continue.', 'error', 12000);
  else if (turn.cycles > 1) toast(`${turn.cycles} seasons passed.${turn.note ? ' ' + turn.note : ''}`, 'good');
  else if (last) toast(last.success ? last.text : `Refused (${last.code}): ${last.text}`, last.success ? 'good' : 'warn');
}

function choose(choice, values) {
  run('The season is passing…', async () => {
    const response = await api('POST', 'choose', {version: ui.state.version, index: choice.index, values});
    if (response.refused) {
      adopt(response.state);
      toast(response.refused.message, 'warn', 9000);
    } else {
      afterTurn(response);
    }
  });
}

function propose(proposal) {
  run('The season is passing…', async () => afterTurn(await api('POST', 'propose', {version: ui.state.version, proposal})));
}

function wait(cycles) {
  run(cycles > 1 ? `${cycles} seasons are passing…` : 'The season is passing…',
    async () => afterTurn(await api('POST', 'wait', {version: ui.state.version, cycles})));
}

function ask(person, topic, values) {
  run('Talking…', async () => {
    const response = await api('POST', 'talk', {version: ui.state.version, partner: person.id, index: topic.index, values});
    adopt(response.state);
    ui.topics = null;
    if (response.reply.learned) toast(`You learned ${response.reply.learned} new thing${response.reply.learned === 1 ? '' : 's'}.`, 'good');
  });
}

async function loadTopics() {
  ui.loadingTopics = true;
  const partner = ui.person;
  try {
    ui.topics = await api('GET', `topics?partner=${encodeURIComponent(partner)}`);
  } catch (error) {
    ui.topics = {partner, version: ui.state.version, topics: [], error: error.message};
  } finally {
    ui.loadingTopics = false;
    render();
  }
}

async function loadTimeline() {
  ui.loadingTimeline = true;
  const limit = ui.timelineLimit;
  try {
    ui.timeline = await api('GET', `timeline?limit=${limit}`);
  } catch (error) {
    ui.timeline = {version: ui.state.version, limit, cycles: [], more: false, prices: null, error: error.message};
  } finally {
    ui.loadingTimeline = false;
    render();
  }
}

function ensureData() {
  const s = ui.state;
  if (!s || ui.busy) return;
  if (ui.tab === 'timeline' && !ui.loadingTimeline &&
      (!ui.timeline || ui.timeline.version !== s.version || ui.timeline.limit !== ui.timelineLimit)) {
    loadTimeline();
  }
  if (!s.over && ui.tab === 'people' && ui.person !== null && !ui.loadingTopics &&
      (!ui.topics || ui.topics.partner !== ui.person || ui.topics.version !== s.version)) {
    loadTopics();
  }
}

// ----- Frame ----------------------------------------------------------------

function render() {
  const app = document.getElementById('app');
  if (!ui.state) return;
  app.replaceChildren(page(ui.state));
  if (ui.dialog) renderDialog();
  ensureData();
}

function page(s) {
  const tabs = s.over ? TABS.filter(([id]) => ENDED_TABS.includes(id)) : TABS;
  return h('div', null,
    topbar(s),
    h('div', {class: 'layout'},
      s.over ? endedSidebar(s) : sidebar(s),
      h('main', null, tabBar(s, tabs), h('div', {role: 'tabpanel', 'aria-label': (TABS.find(([id]) => id === ui.tab) || [])[1]}, panel(s))),
      seasonRail(s)));
}

function topbar(s) {
  const c = s.clock;
  return h('header', {class: 'topbar'},
    h('div', {class: 'brand'}, 'Eternia'),
    h('div', {class: 'clock'}, h('strong', null, when(c)), ` of ${c.ticks_per_year} · cycle ${c.tick}`),
    s.over ? null : h('div', {class: 'secondary'}, `${s.character.name} in ${s.character.town}`),
    s.unsaved ? h('span', {class: 'chip warn'}, 'Unsaved') : s.slot ? h('span', {class: 'chip'}, `Saved as ${s.slot}`) : null,
    ui.busy ? h('span', {class: 'busy-note', role: 'status'}, ui.busy) : null,
    h('div', {class: 'grow'}),
    s.over ? null : h('button', {class: 'btn', disabled: !!ui.busy, onclick: () => wait(1),
      title: 'Choose nothing this season; everyone else still acts.'}, 'Wait a season'),
    s.over ? null : h('button', {class: 'btn', disabled: !!ui.busy, onclick: () => wait(c.ticks_per_year),
      title: 'Wait until the same season next year.'}, 'Wait a year'),
    h('button', {class: 'btn', disabled: !!ui.busy, onclick: openGame}, 'Save & load'));
}

function tabBar(s, tabs) {
  const open = s.over ? 0 : s.organizations.reduce((n, o) => n + o.decisions.filter((d) => d.open && o.local).length, 0);
  const counts = s.over ? {} : {people: s.people.length, economy: (s.opportunities || []).length, politics: open};
  return h('nav', {class: 'tabs', role: 'tablist'}, tabs.map(([id, label]) =>
    h('button', {class: 'tab', role: 'tab', 'aria-selected': String(ui.tab === id), onclick: () => showTab(id)},
      label, counts[id] ? h('span', {class: 'count'}, counts[id]) : null)));
}

function showTab(id) {
  ui.tab = id;
  history.replaceState(null, '', `#${id}`);
  render();
}

function panel(s) {
  switch (ui.tab) {
    case 'town': return townPanel(s);
    case 'people': return peoplePanel(s);
    case 'economy': return economyPanel(s);
    case 'politics': return politicsPanel(s);
    case 'timeline': return timelinePanel(s);
    case 'journal': return journalPanel(s);
    default: return actPanel(s);
  }
}

// ----- The character ----------------------------------------------------------

function sidebar(s) {
  const c = s.character;
  const who = [cap(c.role), c.age !== null && c.age !== undefined ? `age ${c.age}` : null,
    c.journey ? 'on the road' : `in ${c.town}`].filter(Boolean).join(', ');
  const hungerClass = {starving: 'critical', hungry: 'warning'}[c.hunger_level] || 'calm';
  return h('aside', {class: 'sidebar'},
    h('section', {class: 'card stack'},
      h('div', {class: 'who'}, h('h2', null, c.name), h('p', null, who),
        c.generation ? h('p', {class: 'small muted'}, `Heir of the household, generation ${c.generation}`) : null),
      c.journey ? h('div', {class: 'banner small'}, c.journey.returning ? `Turning back to ${c.journey.origin}.`
        : `Travelling from ${c.journey.origin} to ${c.journey.destination}. You can only wait until you arrive.`) : null,
      h('div', {class: 'tiles'}, RESOURCES.map((r) => h('div', {class: 'tile'},
        h('div', {class: 'label'}, cap(r)), h('div', {class: 'value'}, fmt(c.inventory[r])),
        c.available[r] < c.inventory[r] - 0.005 ? h('div', {class: 'sub'}, `${fmt(c.available[r])} free to use`) : null))),
      meter('Hunger', c.hunger, hungerClass, c.hunger_level === 'fed' ? 'fed' : c.hunger_level),
      meter('Energy', c.energy, null, null),
      h('div', {class: 'stack-sm'}, h('h4', null, 'Skills'),
        h('div', {class: 'chips'}, c.skills.map((skill) => h('span', {class: 'chip'}, skill)))),
      facts([
        ['Aether knowledge', String(c.knowledge)],
        ['Reputation', fmt(c.reputation)],
        ['Wages earned', fmt(c.earnings)],
        Object.keys(c.structures).length ? ['Buildings', Object.entries(c.structures).map(([k, n]) => `${n} ${k}`).join(', ')] : null,
      ]),
      c.memberships.length ? h('div', {class: 'stack-sm'}, h('h4', null, 'Member of'),
        h('div', {class: 'chips'}, c.memberships.map((name) => h('span', {class: 'chip accent'}, name)))) : null,
      c.advice.length ? h('ul', {class: 'notes'}, c.advice.map((line) =>
        h('li', {class: /starving|hungry/.test(line) ? 'alert' : null}, line))) : null,
      c.household.length > 1 ? h('p', {class: 'small secondary'},
        'Household: ' + c.household.map((p) => p.name).join(' → ')) : null));
}

function meter(label, value, level, word) {
  const width = `${Math.max(0, Math.min(100, value))}%`;
  return h('div', {class: 'meter'},
    h('div', {class: 'spread'}, h('span', null, label), h('span', {class: 'num'}, `${fmt(value)}/100${word ? ' · ' + word : ''}`)),
    h('div', {class: 'meter-track', role: 'meter', 'aria-label': label, 'aria-valuemin': '0', 'aria-valuemax': '100',
      'aria-valuenow': String(Math.round(value))},
    h('div', {class: `meter-fill${level ? ' ' + level : ''}`, style: {width}})));
}

function endedSidebar(s) {
  return h('aside', {class: 'sidebar'}, h('section', {class: 'card stack'},
    h('div', {class: 'banner ended'}, h('h3', null, 'Your household has ended'),
      h('p', {class: 'small'}, 'No heir remains to continue. The society goes on without you.')),
    h('p', {class: 'small secondary'}, 'Your journal and timeline remain. Start a new life or load a save to play on.'),
    h('button', {class: 'btn primary', onclick: openGame}, 'New game or load')));
}

// ----- Choices ----------------------------------------------------------------

function choiceRow(choice, label, verb) {
  const inputs = choice.fields.map((field) => {
    const input = field.kind === 'text'
      ? h('input', {type: 'text', maxlength: String(field.high), value: String(field.default)})
      : h('input', {type: 'number', min: String(field.low), max: String(field.high),
        step: field.kind === 'int' ? '1' : '0.01', value: String(field.default)});
    return [field, input];
  });
  const take = () => choose(choice, inputs.length ? inputs.map(([, input]) => input.value) : null);
  for (const [, input] of inputs) input.addEventListener('keydown', (event) => { if (event.key === 'Enter') take(); });
  return h('div', {class: 'choice'},
    h('div', {class: 'what'}, label || choice.label,
      choice.checked ? null : h('span', {class: 'tag', title: 'This depends on someone else\'s private circumstances, so it is not checked in advance.'}, 'the cycle decides')),
    inputs.length ? h('div', {class: 'fields'}, inputs.map(([field, input]) =>
      h('label', {class: `field${field.kind === 'text' ? ' wide' : ''}`}, field.label, input))) : null,
    h('button', {class: 'btn primary small', disabled: !!ui.busy, onclick: take}, verb || 'Choose'));
}

function choicesWhere(test) {
  return ui.state.menu.filter((choice) => test(choice.type, choice.params, choice));
}

function choiceList(choices, emptyText, relabel) {
  if (!choices.length) return emptyText ? empty(emptyText) : null;
  return h('div', {class: 'choices-inline'}, choices.map((choice) => choiceRow(choice, relabel ? relabel(choice) : null)));
}

function actPanel(s) {
  const groups = [];
  for (const choice of s.menu) {
    const last = groups[groups.length - 1];
    if (last && last[0] === choice.section) last[1].push(choice);
    else groups.push([choice.section, [choice]]);
  }
  return h('div', null,
    h('p', {class: 'secondary section-gap', style: {marginTop: '0', marginBottom: '1rem'}},
      'Each choice is a proposal. It resolves together with everyone else\'s this season, in the world\'s seeded order, '
      + 'so you can still lose contested goods to someone else. A changed amount or price is checked before the season is spent.'),
    groups.map(([section, choices]) => {
      const open = ui.sections[section] ?? OPEN_SECTIONS.has(section);
      return h('details', {class: 'section', open, ontoggle: (event) => { ui.sections[section] = event.target.open; }},
        h('summary', null, h('span', null, section, h('span', {class: 'muted'}, ` · ${choices.length}`))),
        h('div', {class: 'body'}, choices.map((choice) => choiceRow(choice))));
    }),
    handWritten());
}

function handWritten() {
  const area = h('textarea', {placeholder: '{"type": "work", "params": {"order": 1, "amount": 4}}', 'aria-label': 'An action as JSON'});
  const send = () => {
    let proposal;
    try { proposal = JSON.parse(area.value); } catch (error) { toast('That is not valid JSON.', 'error'); return; }
    propose(proposal);
  };
  return h('details', {class: 'section', style: {marginTop: '.6rem'}},
    h('summary', null, h('span', null, 'Write an action by hand')),
    h('div', {class: 'body stack-sm'},
      h('p', {class: 'small secondary'}, 'Propose any action the engine knows, as JSON, like the terminal\'s j command. '
        + 'It is not checked in advance: the cycle accepts or refuses it, and a refusal spends the season.'),
      area, h('button', {class: 'btn', disabled: !!ui.busy, onclick: send}, 'Propose')));
}

// ----- Town and roads -----------------------------------------------------------

function townPanel(s) {
  const w = s.world;
  const towns = [w.town, ...w.neighbors];
  const selected = towns.find((t) => t.id === ui.town) || w.town;
  return h('div', null,
    h('div', {class: 'grid-2'},
      card('The region', mapView(w, selected), 'Select a town for details.'),
      selected.id === w.town.id ? homeCard(w.town, s) : neighborCard(selected, s)),
    card('Prices', pricesTable(w), 'You pay the posted price; the market buys from you at 80% of it.'),
    card('Roads', roadsTable(w), 'Condition, risk and capacity are public; a closed road stops traffic.'));
}

function mapView(w, selected) {
  const towns = [w.town, ...w.neighbors];
  const at = Object.fromEntries(towns.map((t) => [t.id, t]));
  const xs = towns.map((t) => t.x), ys = towns.map((t) => t.y);
  const cx = xs.reduce((a, b) => a + b, 0) / xs.length, cy = ys.reduce((a, b) => a + b, 0) / ys.length;
  const left = Math.min(...xs) - 16, top = Math.min(...ys) - 16;
  const width = Math.max(...xs) - left + 16, height = Math.max(...ys) - top + 16;
  const svg = h('svg:svg', {class: 'map', viewBox: `${left} ${top} ${width} ${height}`, role: 'group', 'aria-label': 'Map of the region'});
  for (const road of w.roads) {
    const a = at[road.a], b = at[road.b];
    if (!a || !b) continue;
    svg.append(h('svg:line', {class: `road${road.local ? ' local' : ''}${road.closed ? ' closed' : ''}`, x1: a.x, y1: a.y, x2: b.x, y2: b.y}));
    // The label sits beside the road's middle, on the side away from the centre of the region.
    const mx = (a.x + b.x) / 2, my = (a.y + b.y) / 2, length = Math.hypot(b.x - a.x, b.y - a.y) || 1;
    let nx = -(b.y - a.y) / length, ny = (b.x - a.x) / length;
    if (nx * (mx - cx) + ny * (my - cy) < 0) { nx = -nx; ny = -ny; }
    const anchor = nx > 0.35 ? 'start' : nx < -0.35 ? 'end' : 'middle';  // text grows away from the road
    const gap = anchor === 'middle' ? 3.6 : 2.4;
    svg.append(h('svg:text', {class: 'road-label', x: mx + nx * gap, y: my + ny * gap + 0.8, 'text-anchor': anchor},
      `${road.terrain} · ${pct(road.condition)}${road.closed ? ' · closed' : ''}`));
  }
  for (const town of towns) {
    const radius = 1.6 + Math.sqrt(Math.max(1, town.population)) / 4.5;
    const pick = () => { ui.town = town.id; render(); };
    svg.append(h('svg:g', {class: `town${town.id === selected.id ? ' selected' : ''}`, tabindex: '0', role: 'button',
      'aria-label': `${town.name}, ${town.population} people${town.id === w.town.id ? ', your home' : ''}`,
      onclick: pick, onkeydown: (event) => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); pick(); } }},
    town.id === w.town.id ? h('svg:circle', {class: 'here', cx: town.x, cy: town.y, r: radius + 1.4}) : null,
    h('svg:circle', {class: `dot town-${town.slot}`, cx: town.x, cy: town.y, r: radius}),
    h('svg:text', {x: town.x, y: town.y < cy ? town.y - radius - 4.6 : town.y + radius + 4, 'text-anchor': 'middle'}, town.name),
    h('svg:text', {class: 'sub', x: town.x, y: town.y < cy ? town.y - radius - 1.8 : town.y + radius + 6.8, 'text-anchor': 'middle'},
      `${town.population} people${town.id === w.town.id ? ' · home' : ''}`)));
  }
  return svg;
}

function townTitle(town) {
  return h('span', null, h('span', {class: `swatch town-${town.slot}`}), town.name);
}

function homeCard(town, s) {
  const p = town.policies;
  return card(townTitle(town), h('div', {class: 'stack'},
    facts([
      ['Population', String(town.population)],
      ['Market holds', GOODS.map((g) => `${fmt(town.stock[g])} ${g}`).join(', ')],
      ['Market coins', fmt(town.treasury)],
      ['Can be gathered now', GOODS.map((g) => `${fmt(town.deposits[g])} ${g}`).join(', ')],
      ['Levy', pct(p.tax_rate)],
      ['Communal labor', pct(p.communal_labor)],
      ['Specialization', p.specialization || 'none'],
      ['Open to newcomers', p.migration_open === false ? 'no' : 'yes'],
      ['Granary capacity', fmt(p.granary_capacity)],
      p.trade_partners && p.trade_partners.length ? ['Trade partners', p.trade_partners.join(', ')] : null,
    ])), 'Where you live');
}

function neighborCard(town, s) {
  const path = town.path;
  return card(townTitle(town), h('div', {class: 'stack'},
    facts([
      ['Population', String(town.population)],
      ['Distance', fmt(town.distance)],
      path ? ['On the road', `about ${path.duration} cycles`] : ['On the road', 'no usable route'],
      path ? ['Food for the road', fmt(path.supplies)] : null,
      path ? ['Risk on the way', pct(path.risk)] : null,
      ['Open to newcomers', town.migration_open === false ? 'no' : 'yes'],
      ['Market holds', GOODS.map((g) => `${fmt(town.stock[g])} ${g}`).join(', ')],
    ]),
    town.jobs.length ? h('div', {class: 'stack-sm'}, h('h4', null, 'Jobs posted there'),
      h('ul', {class: 'events'}, town.jobs.map((job) => h('li', null,
        `Job ${job.id} for ${job.employer}: ${job.remaining} ${job.resource} at ${fmt(job.unit_wage)} each`)))) : null,
    h('div', {class: 'stack-sm'}, h('h4', null, `Go to ${town.name}`),
      choiceList(choicesWhere((type, p) => type === 'migrate' && p.destination === town.id), 'You cannot set out there now.')),
    h('div', {class: 'stack-sm'}, h('h4', null, `Ship goods to ${town.name}`),
      choiceList(choicesWhere((type, p) => type === 'consign' && p.destination === town.id),
        'Shipping needs the trading skill, goods to send and food for the road.'))),
  'A neighboring town');
}

function pricesTable(w) {
  const towns = [w.town, ...w.neighbors];
  return table([['Good'], ...towns.map((t) => [`${t.name}${t.id === w.town.id ? ' (home)' : ''}: you pay / market pays`, true])],
    GOODS.map((good) => [cap(good), ...towns.map((t) => t.prices[good]
      ? `${fmt(t.prices[good].buy)} / ${fmt(t.prices[good].sell)}` : '–')]));
}

function roadsTable(w) {
  return table([['Between'], ['Terrain'], ['Condition', true], ['Risk', true], ['Capacity', true], ['Owner'], ['Open']],
    w.roads.map((r) => [r.between.join(' – '), r.terrain, pct(r.condition), pct(r.risk), fmt(r.capacity),
      r.owner || 'public', r.closed ? 'closed' : 'open']),
    (index) => w.roads[index].local ? 'here' : null);
}

// ----- People -------------------------------------------------------------------

function peoplePanel(s) {
  const person = s.people.find((p) => p.id === ui.person);
  return h('div', null,
    s.people.length ? h('div', {class: 'people'},
      h('div', null, h('h4', {style: {marginBottom: '.5rem'}}, `People in ${s.character.town}`),
        s.people.map((p) => h('button', {class: 'person', 'aria-pressed': String(p.id === ui.person),
          onclick: () => { ui.person = p.id; ui.topics = null; render(); }},
        h('div', {class: 'name'}, p.name),
        h('div', {class: 'meta'}, `${p.role} · ${p.feeling} (${signed(p.your_trust)})`)))),
      person ? conversationCard(s, person) : card('Talk to someone', h('p', {class: 'secondary'},
        'Choose someone to see what you can ask them. Asking takes no season: the world waits while you talk. '
        + `Each person answers up to ${s.talk_limit} questions a season, from what they have seen, done or been told.`)))
      : card('People here', empty(s.character.journey ? 'You are on the road; nobody is walking beside you to talk to.' : 'Nobody is here to talk to.')),
    heardCard(s));
}

function conversationCard(s, person) {
  const history = s.conversations.filter((c) => c.partner === person.id);
  const ready = ui.topics && ui.topics.partner === person.id && ui.topics.version === s.version;
  const log = h('div', {class: 'chat', 'aria-live': 'polite'},
    history.length ? history.map((talk) => h('div', {class: 'turn'},
      h('div', {class: 'asked'}, `${ASKED[talk.topic] || 'You asked about ' + talk.topic} · ${when(talk)}`),
      talk.lines.map((line) => h('div', {class: `bubble${line.startsWith('"') ? '' : ' narration'}`}, line)),
      talk.learned ? h('div', {class: 'learned'}, `You learned ${talk.learned} new thing${talk.learned === 1 ? '' : 's'}.`) : null))
      : empty(`You have not spoken with ${person.name} yet.`));
  const askable = person.answers_left > 0;
  let questions;
  if (!ready) questions = empty(ui.topics && ui.topics.error ? ui.topics.error : 'Finding things to ask…');
  else if (!ui.topics.topics.length) questions = empty('There is nothing to ask right now.');
  else questions = topicGroups(person, ui.topics.topics, askable);
  const together = choicesWhere((type, p) => ['teach', 'collaborate'].includes(type) && p.target === person.id);
  setTimeout(() => { log.scrollTop = log.scrollHeight; }, 0);
  return card(person.name, h('div', {class: 'stack'},
    log,
    h('div', {class: 'stack-sm'},
      h('div', {class: 'spread'}, h('h4', null, 'Ask or tell'),
        h('span', {class: 'small secondary'}, askable ? `${person.answers_left} of ${s.talk_limit} answers left this season`
          : 'They have other things to do this season')),
      questions),
    together.length ? h('div', {class: 'stack-sm'}, h('h4', null, 'Do something together (takes your season)'),
      choiceList(together)) : null),
  `${cap(person.role)} · ${person.feeling} (${signed(person.your_trust)})`);
}

const TOPIC_GROUPS = [
  ['Questions', ['work', 'news', 'trade', 'politics', 'themselves']],
  ['What they think of someone', ['person']],
  ['How they would vote', ['proposal']],
  ['Requests', ['work_for_you', 'join', 'teach']],
  ['Pass on what you have heard', ['tell']],
];

function topicGroups(person, topics, askable) {
  const first = person.name.split(' ')[0];
  return h('div', {class: 'stack'}, TOPIC_GROUPS.map(([title, kinds]) => {
    const group = topics.filter((t) => kinds.includes(t.topic));
    if (!group.length) return null;
    if (kinds[0] === 'person') {  // short names as chips: "what Edrin thinks of …"
      return h('div', {class: 'stack-sm'}, h('div', {class: 'small muted'}, `Ask what ${first} thinks of`),
        h('div', {class: 'chips'}, group.map((topic) => h('button', {class: 'btn small', disabled: !!ui.busy || !askable,
          onclick: () => ask(person, topic, null), title: topic.label},
        topic.label.replace(`Ask what ${first} thinks of `, '')))));
    }
    return h('div', {class: 'stack-sm'}, h('div', {class: 'small muted'}, title),
      h('div', {class: 'topics'}, group.map((topic) => topicRow(person, topic, askable))));
  }));
}

function topicRow(person, topic, askable) {
  const inputs = topic.fields.map((field) => [field, h('input', {type: field.kind === 'text' ? 'text' : 'number',
    min: String(field.low), max: String(field.high), step: field.kind === 'int' ? '1' : '0.01', value: String(field.default),
    'aria-label': field.label})]);
  const go = () => ask(person, topic, inputs.length ? inputs.map(([, input]) => input.value) : null);
  return h('div', {class: 'topic'},
    h('button', {class: 'btn', disabled: !!ui.busy || !askable, onclick: go}, topic.label),
    inputs.map(([field, input]) => h('label', {class: 'field'}, field.label, input)));
}

function heardCard(s) {
  const heard = (s.journal && s.journal.heard) || [];
  return card('What you have heard', heard.length ? h('ul', {class: 'events'}, heard.map((item) => h('li', null,
    cap(item.text), h('div', {class: 'small muted'}, `${item.source} · confidence ${pct(item.confidence)}`))))
    : empty('Nothing yet. Ask people what has been happening.'),
  'News passes from person to person; each retelling is less certain.');
}

// ----- Economy --------------------------------------------------------------------

const SAYS = {job: 'is hiring someone to gather', buyer: 'wants to buy', seller: 'wants to sell'};

function opportunityCard(s) {
  const all = s.opportunities || [];
  const list = all.filter((o) => o.kind !== 'need');
  const heard = all.filter((o) => o.kind === 'need');
  const rows = list.map((o) => {
    const choices = choicesWhere((type, p) => (o.kind === 'job' ? type === 'work' && p.order === o.id
      : type === 'accept' && p.offer_id === o.id));
    const market = o.market === null || o.market === undefined ? ''
      : o.kind === 'seller' ? ` · the market sells it for ${fmt(o.market)}`
        : ` · the ${o.town} market pays ${fmt(o.market)} for ${o.resource} you sell it`;
    return h('div', {class: 'result', style: {display: 'block'}},
      h('div', {class: 'spread'},
        h('strong', null, `${cap(o.who)} ${SAYS[o.kind]} ${o.amount} ${o.resource}${o.purpose ? ' ' + o.purpose : ''}`),
        h('span', {class: 'tag'}, `${o.here ? '' : o.town + ' · '}until cycle ${o.expires}`)),
      h('div', {class: 'small secondary'}, (o.kind === 'job' ? `${fmt(o.unit_price)} coins a unit in wages, ${o.amount} of ${o.quantity} still wanted`
        : `${fmt(o.unit_price)} coins each`) + market),
      o.needs.length ? h('div', {class: 'small muted'}, `To take it you would need ${o.needs.join(' and ')}.`) : null,
      choices.length ? choiceList(choices) : null);
  });
  const told = heard.map((o) => {
    const terms = [o.unit_price !== null && o.unit_price !== undefined ? `would buy it at up to ${fmt(o.unit_price)} a unit` : null,
      o.wage !== null && o.wage !== undefined ? `was paying ${fmt(o.wage)} a unit to have it gathered${o.job !== null && o.job !== undefined ? ` (job ${o.job})` : ''}` : null]
      .filter(Boolean);
    // The menu's own offer, with its fields filled in from what was said: the amount needed, the price they would pay.
    const sell = (o.needs.length ? [] : choicesWhere((type, p) => type === 'offer' && p.direction === 'sell' && p.resource === o.resource))
      .map((choice) => ({...choice,
        label: `Offer ${o.resource} for sale here, where ${o.who} can take it up (for 4 cycles)`,
        fields: choice.fields.map((field) => field.name === 'amount' ? {...field, default: Math.min(field.high, o.amount)}
          : field.name === 'unit_price' && o.unit_price ? {...field, default: o.unit_price} : field)}));
    return h('div', {class: 'result', style: {display: 'block'}},
      h('div', {class: 'spread'},
        h('strong', null, `${cap(o.who)} needs ${fmt(o.amount)} ${o.resource} ${o.purpose}`),
        h('span', {class: 'tag'}, cap(o.heard))),
      terms.length ? h('div', {class: 'small secondary'}, cap(terms.join('; ')) + '.') : null,
      h('div', {class: 'small muted'}, 'What you heard may be out of date: they may have got it already.'
        + (o.needs.length ? ` To answer it you would need ${o.needs.join(' and ')}.`
          : ` Offer it at a fair price${o.unit_price ? `, ${fmt(o.unit_price)} or less,` : ''} and they can take it up.`)),
      sell.length ? choiceList(sell) : null);
  });
  return h('div', null,
    card('Opportunities around you', list.length ? h('div', {class: 'stack-sm'}, rows)
      : empty('Nobody nearby is asking for anything right now.'),
    'Jobs and offers people posted for their own needs. They stand whether or not you answer, and someone else may take them first.'),
    heard.length ? card('Needs you have heard of', h('div', {class: 'stack-sm'}, told),
      'What people told you someone needs, with who said so and when. Ask around to find out more.') : null);
}

function economyPanel(s) {
  const w = s.world;
  const coins = s.journal.coins;
  return h('div', null,
    opportunityCard(s),
    card(`The ${w.town.name} market`, h('div', {class: 'stack'},
      table([['Good'], ['You pay', true], ['Market pays', true], ['In stock', true]],
        GOODS.map((g) => [cap(g), fmt(w.town.prices[g].buy), fmt(w.town.prices[g].sell), fmt(w.town.stock[g])])),
      choiceList(choicesWhere((type) => type === 'trade'), 'You cannot buy or sell at the market right now.')),
    `The market holds ${fmt(w.town.treasury)} coins to buy with. Prices are posted before anyone plans.`),
    card(`Jobs in ${w.town.name}`, h('div', {class: 'stack'},
      w.jobs.length ? table([['Job'], ['Employer'], ['Work'], ['Left', true], ['Wage', true], ['Until cycle', true]],
        w.jobs.map((j) => [String(j.id), j.employer, j.resource, `${j.remaining} of ${j.quantity}`, fmt(j.unit_wage), String(j.expires)]))
        : empty('Nobody here is paying for work right now.'),
      choiceList(choicesWhere((type) => type === 'work'), w.jobs.some((j) => !j.mine)
        ? 'You cannot take these jobs now: the work needs its skill, energy, and something left to gather.' : null)),
    'Wages are held in escrow and paid on delivery.'),
    w.jobs_elsewhere.length ? card('Jobs in neighboring towns', table(
      [['Town'], ['Employer'], ['Work'], ['Left', true], ['Wage', true]],
      w.jobs_elsewhere.map((j) => [j.town, j.employer, j.resource, String(j.remaining), fmt(j.unit_wage)])),
    'You would have to move there to take them.') : null,
    card('Offers from neighbors', h('div', {class: 'stack'},
      w.offers.length ? table([['Offer'], ['Who'], ['Wants to'], ['Amount', true], ['Price', true], ['Until cycle', true]],
        w.offers.map((o) => [String(o.id), cap(o.who), o.direction, `${o.amount} ${o.resource}`, fmt(o.unit_price), String(o.expires)]))
        : empty('No open offers.'),
      choiceList(choicesWhere((type) => type === 'accept'))),
    'Taking up an offer depends on whether they still have the goods or coins.'),
    card('Trade and hiring', choiceList(choicesWhere((type, p, c) => c.section === 'Trade and hiring'),
      'Trading needs the trading skill; hiring needs coins for the wages.'),
    'Post offers, ship to other markets, or hire workers.'),
    card('Your money', h('div', {class: 'stack'},
      h('p', null, `You arrived with ${fmt(coins.start)} coins and hold ${fmt(coins.now)} now.`),
      h('div', {class: 'grid-2'},
        flowTable('Earned', coins.income), flowTable('Spent', coins.spending)),
      Math.abs(coins.unexplained) > 0.005 ? h('p', {class: 'small secondary'},
        `Other changes, such as an inheritance: ${signed(coins.unexplained)} coins.`) : null),
    'Every coin, accounted from the world\'s own records.'));
}

function flowTable(title, flows) {
  const entries = Object.entries(flows || {}).sort((a, b) => b[1] - a[1]);
  return h('div', null, h('h4', {style: {marginBottom: '.3rem'}}, title),
    entries.length ? table([['From', false], ['Coins', true]], entries.map(([k, v]) => [cap(k), fmt(v)])) : empty('Nothing yet.'));
}

// ----- Politics -------------------------------------------------------------------

function politicsPanel(s) {
  const local = s.organizations.filter((o) => o.local);
  const elsewhere = s.organizations.filter((o) => !o.local);
  const caravans = choicesWhere((type) => type === 'dispatch_caravan');
  const j = s.journal;
  return h('div', null,
    local.length ? local.map((org) => organizationCard(org)) : card(`Organizations in ${s.character.town}`, empty('There are none yet.')),
    card('Found an organization', choiceList(choicesWhere((type) => type === 'form_institution'), 'You cannot found one right now.'),
      'A cooperative, guild or council of your own. Others join if it serves them.'),
    caravans.length ? card('Contract caravans', choiceList(caravans), 'Goods your organization has agreed to send.') : null,
    elsewhere.length ? card('Organizations in neighboring towns', table([['Name'], ['Town'], ['Kind'], ['Members', true], ['Open proposals', true]],
      elsewhere.map((o) => [o.name, o.town, o.purpose, String(o.members), String(o.decisions.filter((d) => d.open).length)]))) : null,
    card('Your political record', h('div', {class: 'stack'},
      j.proposals.length ? table([['Proposal'], ['In'], ['About'], ['Outcome'], ['For', true], ['Against', true]],
        j.proposals.map((p) => [String(p.proposal), p.institution, p.about, p.status, String(p.yes), String(p.no)])) : empty('You have made no proposals.'),
      j.votes.length ? table([['Cycle', true], ['Vote'], ['On'], ['In'], ['Now']],
        j.votes.slice().reverse().map((v) => [String(v.tick), v.approve ? 'for' : 'against', v.about, v.institution, v.outcome || ''])) : empty('You have not voted yet.'))));
}

function organizationCard(org) {
  const mine = (type, p) => p.institution === org.id;
  const membership = choicesWhere((type, p) => ['join_institution', 'leave_institution', 'contribute'].includes(type) && mine(type, p));
  const proposals = choicesWhere((type, p) => type === 'propose' && mine(type, p));
  const badges = [
    org.member ? h('span', {class: 'chip accent'}, 'You are a member') : null,
    org.authority ? h('span', {class: 'chip'}, 'Governs the town\'s public funds') : null,
    org.active ? null : h('span', {class: 'chip warn'}, 'Dissolved'),
  ];
  const ruleText = [`levy ${pct(org.levy)}`, org.communal_labor ? `communal labor ${pct(org.communal_labor)}` : null,
    org.embargoes.length ? `embargo on ${org.embargoes.join(', ')}` : null].filter(Boolean).join(' · ');
  return card(org.name, h('div', {class: 'stack'},
    h('div', {class: 'chips'}, badges),
    org.shared ? h('p', {class: 'small secondary'}, 'Shared holdings: '
      + RESOURCES.map((r) => `${fmt(org.shared[r])} ${r}`).join(', ')) : null,
    org.decisions.length ? h('div', {class: 'stack-sm'}, h('h4', null, 'Proposals'),
      org.decisions.map((d) => decisionBlock(org, d))) : empty('No proposals yet.'),
    membership.length ? h('div', {class: 'stack-sm'}, h('h4', null, org.member ? 'Membership' : 'Join'),
      choiceList(membership)) : null,
    proposals.length ? h('details', {class: 'section', open: ui.sections[`propose-${org.id}`] || false,
      ontoggle: (event) => { ui.sections[`propose-${org.id}`] = event.target.open; }},
      h('summary', null, h('span', null, `Propose something`, h('span', {class: 'muted'}, ` · ${proposals.length}`))),
      h('div', {class: 'body'}, choiceList(proposals, null, (c) => cap(c.label.replace(`Propose in ${org.name}: `, ''))))) : null),
  `${cap(org.purpose)} of ${org.members} in ${org.town} · founded cycle ${org.founded} · ${ruleText}`);
}

function decisionBlock(org, decision) {
  const choices = choicesWhere((type, p) => ['vote', 'enact'].includes(type) && p.institution === org.id && p.proposal === decision.id);
  const status = decision.open ? h('span', {class: 'tag open'}, `open until cycle ${decision.expires}`) : h('span', {class: 'tag'}, decision.status);
  const vote = decision.your_vote === null || decision.your_vote === undefined ? null
    : h('span', {class: 'tag'}, `you voted ${decision.your_vote ? 'for' : 'against'}`);
  return h('div', {class: 'result', style: {display: 'block'}},
    h('div', {class: 'spread'}, h('strong', null, `${decision.id}. ${cap(decision.about)}`), h('span', {class: 'row'}, status, vote)),
    h('div', {class: 'small secondary'}, `Proposed by ${decision.yours ? 'you' : decision.proposer} · ${decision.yes} for, ${decision.no} against`
      + ` of ${decision.voters} voters${decision.can_vote ? ' · you may vote' : ''}`),
    choices.length ? choiceList(choices, null, (c) => c.type === 'vote' ? `Vote ${c.params.approve ? 'for' : 'against'}` : 'Carry it out') : null);
}

// ----- Timeline ---------------------------------------------------------------------

function timelinePanel(s) {
  const tl = ui.timeline;
  if (!tl || tl.version !== s.version) return card('Timeline', empty('Gathering the record…'));
  if (tl.error) return card('Timeline', empty(tl.error));
  return h('div', null, pricesCard(tl.prices), historyCard(tl));
}

function pricesCard(series) {
  if (!series || !series.points.length) return card('Prices since you arrived', empty('No prices recorded yet.'));
  const legend = h('div', {class: 'legend'}, series.towns.map((t) => h('span', null,
    h('span', {class: `swatch line town-${t.slot}`}), `${t.name}${t.id === series.home ? ' (home)' : ''}`)));
  return card('Posted prices since you arrived', h('div', null, legend,
    h('div', {class: 'charts'}, GOODS.map((good) => lineChart(series, good))), priceNumbers(series)),
  'What each market sells at, season by season. Hover for values.');
}

function niceTicks(lo, hi, count) {
  if (!(hi > lo)) { const pad = Math.max(0.1, Math.abs(lo) * 0.1); lo -= pad; hi += pad; }
  const raw = (hi - lo) / count;
  const magnitude = 10 ** Math.floor(Math.log10(raw));
  const norm = raw / magnitude;
  const step = (norm < 1.5 ? 1 : norm < 3 ? 2 : norm < 7 ? 5 : 10) * magnitude;
  const ticks = [];
  for (let v = Math.max(0, Math.floor(lo / step) * step); v <= Math.ceil(hi / step) * step + step / 2; v += step) {
    ticks.push(Math.round(v / step) * step);
  }
  return ticks;
}

function lineChart(series, good) {
  const W = 300, H = 190, L = 34, R = 40, T = 10, B = 24;
  const points = series.points, towns = series.towns;
  const value = (point, town) => (point.prices[town.id] || {})[good];
  const values = points.flatMap((p) => towns.map((t) => value(p, t))).filter((v) => v !== undefined && v !== null);
  if (!values.length) return h('div', {class: 'chart'}, h('h3', null, cap(good)), empty('No prices yet.'));
  const ticks = niceTicks(Math.min(...values), Math.max(...values), 4);
  const lo = ticks[0], hi = ticks[ticks.length - 1];
  const t0 = points[0].tick, t1 = points[points.length - 1].tick;
  const x = (tick) => t1 === t0 ? (L + W - R) / 2 : L + (tick - t0) / (t1 - t0) * (W - L - R);
  const y = (v) => T + (hi - v) / ((hi - lo) || 1) * (H - T - B);
  const svg = h('svg:svg', {viewBox: `0 0 ${W} ${H}`, role: 'img', 'aria-label': `${cap(good)} prices by town since you arrived`});
  for (const tick of ticks) {
    svg.append(h('svg:line', {class: tick === lo ? 'baseline' : 'gridline', x1: L, x2: W - R, y1: y(tick), y2: y(tick)}));
    svg.append(h('svg:text', {class: 'tick-label', x: L - 6, y: y(tick) + 3.5, 'text-anchor': 'end'}, fmt(tick)));
  }
  const first = points[0], last = points[points.length - 1];
  svg.append(h('svg:text', {class: 'tick-label', x: x(first.tick), y: H - 6, 'text-anchor': t1 === t0 ? 'middle' : 'start'}, `Y${first.year} S${first.season}`));
  if (t1 !== t0) svg.append(h('svg:text', {class: 'tick-label', x: x(last.tick), y: H - 6, 'text-anchor': 'end'}, `Y${last.year} S${last.season}`));
  const ends = [];
  for (const town of towns) {
    const drawn = points.filter((p) => value(p, town) !== undefined && value(p, town) !== null);
    if (!drawn.length) continue;
    const d = drawn.map((p, i) => `${i ? 'L' : 'M'}${x(p.tick).toFixed(1)} ${y(value(p, town)).toFixed(1)}`).join(' ');
    svg.append(h('svg:path', {class: `series town-${town.slot}`, d}));
    const end = drawn[drawn.length - 1];
    ends.push({town, x: x(end.tick), y: y(value(end, town)), v: value(end, town)});
  }
  for (const end of ends) svg.append(h('svg:circle', {class: `end town-${end.town.slot}`, cx: end.x, cy: end.y, r: 4}));
  let previous = -Infinity;  // label the end values that do not collide; the legend and tooltip carry the rest
  for (const end of ends.slice().sort((a, b) => a.y - b.y)) {
    if (end.y - previous < 13) continue;
    svg.append(h('svg:text', {class: 'end-label', x: end.x + 7, y: end.y + 3.5}, fmt(end.v)));
    previous = end.y;
  }
  const cross = h('svg:line', {class: 'crosshair', y1: T, y2: H - B, visibility: 'hidden'});
  const marks = towns.map((town) => h('svg:circle', {class: `end town-${town.slot}`, r: 4, visibility: 'hidden'}));
  svg.append(cross, ...marks);
  const tip = h('div', {class: 'tooltip', hidden: true});
  const hit = h('svg:rect', {class: 'hit', x: L - 6, y: T, width: W - L - R + 12, height: H - T - B});
  const hide = () => { tip.hidden = true; cross.setAttribute('visibility', 'hidden'); marks.forEach((m) => m.setAttribute('visibility', 'hidden')); };
  hit.addEventListener('pointerleave', hide);
  hit.addEventListener('pointermove', (event) => {
    const box = svg.getBoundingClientRect();
    const scale = box.width / W;
    const px = (event.clientX - box.left) / scale;
    let best = points[0];
    for (const p of points) if (Math.abs(x(p.tick) - px) < Math.abs(x(best.tick) - px)) best = p;
    cross.setAttribute('x1', x(best.tick)); cross.setAttribute('x2', x(best.tick)); cross.setAttribute('visibility', 'visible');
    towns.forEach((town, i) => {
      const v = value(best, town);
      if (v === undefined || v === null) { marks[i].setAttribute('visibility', 'hidden'); return; }
      marks[i].setAttribute('cx', x(best.tick)); marks[i].setAttribute('cy', y(v)); marks[i].setAttribute('visibility', 'visible');
    });
    tip.replaceChildren(h('div', {class: 't'}, `${when(best)} · cycle ${best.tick}`),
      ...towns.map((town) => h('div', {class: 'r'}, h('span', null, h('span', {class: `swatch line town-${town.slot}`}), town.name),
        h('span', {class: 'v'}, fmt(value(best, town))))));
    tip.hidden = false;
    const left = x(best.tick) * scale;
    tip.style.left = `${Math.min(Math.max(0, left + 12), box.width - 150)}px`;
    tip.style.top = `${T * scale + 8}px`;
  });
  svg.append(hit);
  return h('div', {class: 'chart'}, h('h3', null, cap(good)), svg, tip);
}

function priceNumbers(series) {
  const headers = [['Cycle'], ...GOODS.flatMap((g) => series.towns.map((t) => [`${cap(g)} · ${t.name}`, true]))];
  return h('details', {class: 'section', style: {marginTop: '1rem'}},
    h('summary', null, h('span', null, 'Show the numbers')),
    h('div', {class: 'body'}, table(headers, series.points.slice().reverse().map((p) =>
      [`${when(p)} (${p.tick})`, ...GOODS.flatMap((g) => series.towns.map((t) => fmt((p.prices[t.id] || {})[g])))]))));
}

function historyCard(tl) {
  const toggle = h('label', {class: 'row small secondary'},
    h('input', {type: 'checkbox', checked: ui.showRoutine, onchange: (event) => { ui.showRoutine = event.target.checked; render(); }}),
    'Show everyday activity');
  return card('Your history', h('div', {class: 'stack'},
    tl.cycles.length ? tl.cycles.map((cycle) => h('div', {class: `cycle${cycle.actions.length ? ' has-action' : ''}`},
      h('div', {class: 'when'}, when(cycle), h('span', null, ` · cycle ${cycle.tick} · ${cycle.place || 'on the road'}`)),
      cycle.actions.map(resultRow),
      eventList(cycle.events, ui.showRoutine)))
      : empty('Nothing has happened yet.'),
    tl.more ? h('button', {class: 'btn', onclick: () => { ui.timelineLimit += 40; render(); }},
      'Show earlier seasons') : null),
  'What you did and what happened where you lived, newest first.', toggle);
}

function resultRow(result) {
  const waited = result.type === 'wait';
  return h('div', {class: 'result'},
    h('span', {class: `mark ${waited ? 'wait' : result.success ? 'ok' : 'no'}`, 'aria-label': result.success ? 'done' : 'refused'},
      waited ? '·' : result.success ? '✓' : '✕'),
    h('div', null, result.text, result.success ? null : h('div', {class: 'small secondary'}, `Refused: ${result.code}`)));
}

function eventList(events, showRoutine) {
  const shown = events.filter((e) => showRoutine || !e.routine);
  const hidden = events.length - shown.length;
  return h('div', null,
    shown.length ? h('ul', {class: 'events'}, shown.map((e) => h('li', {class: e.yours ? 'yours' : e.routine ? 'routine' : null},
      h('span', {class: 'kind'}, e.kind), e.text))) : null,
    hidden ? h('p', {class: 'small muted'}, `${hidden} everyday entr${hidden === 1 ? 'y' : 'ies'} folded away.`) : null);
}

// ----- Journal ----------------------------------------------------------------------

function journalPanel(s) {
  const j = s.journal;
  if (!j) return card('Journal', empty('No journal yet.'));
  const coins = j.coins;
  return h('div', null,
    card('Coins', h('div', {class: 'stack'},
      h('p', null, `${fmt(coins.start)} on arrival, ${fmt(coins.now)} now.`),
      h('div', {class: 'grid-2'}, flowTable('Earned', coins.income), flowTable('Spent', coins.spending)),
      Math.abs(coins.unexplained) > 0.005 ? h('p', {class: 'small secondary'}, `Other changes: ${signed(coins.unexplained)} coins.`) : null),
    'Built from the world\'s own records; it survives saving, loading and replay.'),
    j.people.length > 1 ? card('Your household', table([['Name'], ['From cycle', true], ['Until', true]],
      j.people.map((p) => [p.name, String(p.since), p.until === null ? 'now' : String(p.until)]))) : null,
    card('Work', h('div', {class: 'stack'},
      j.worked.length ? table([['Cycle', true], ['Employer'], ['Delivered'], ['Paid', true]],
        j.worked.slice().reverse().map((w) => [String(w.tick), w.employer, `${w.amount} ${w.resource}`, fmt(w.coins)]))
        : empty('You have not worked a paid job.'),
      j.hired.length ? table([['Your job'], ['Work'], ['Delivered', true], ['Paid', true], ['Workers'], ['Status']],
        j.hired.map((job) => [String(job.order), `${job.quantity ?? '?'} ${job.resource || ''}`, String(job.delivered), fmt(job.paid),
          Object.entries(job.workers).map(([name, units]) => `${name} (${units})`).join(', ') || 'nobody yet', job.status || 'open']))
        : null)),
    card('Organizations', j.memberships.length ? table([['Name'], ['Since cycle', true], ['How'], ['Now']],
      j.memberships.map((m) => [m.name, String(m.joined), m.founded ? 'founded' : 'joined', m.member_now ? 'member' : 'left']))
      : empty('You have not joined or founded an organization.')),
    card('Feelings', j.relationships.length ? table([['Person'], ['Your trust', true]],
      j.relationships.map((r) => [r.name, signed(r.your_trust)])) : empty('You have no strong feelings about anyone yet.'),
    'Only your own; nobody can read how others regard you.'),
    (j.contests.won.length || j.contests.lost.length) ? card('Contested goods', h('ul', {class: 'events'},
      j.contests.won.map((c) => h('li', null, `Cycle ${c.tick}: you got ${c.what} before ${c.over.join(', ')}.`)),
      j.contests.lost.map((c) => h('li', null, `Cycle ${c.tick}: ${c.to.join(', ')} got ${c.what} before you.`)))) : null,
    j.refusals.length ? card('Refused choices', table([['Cycle', true], ['Action'], ['Why']],
      j.refusals.slice().reverse().map((r) => [String(r.tick), r.type, r.message]))) : null,
    card('Every transaction', j.transactions.length ? table([['Cycle', true], ['What'], ['Coins', true]],
      j.transactions.slice().reverse().map((t) => [String(t.tick), t.text, t.coins ? signed(t.coins) : '']))
      : empty('Nothing yet.'), 'Newest first.'));
}

// ----- The season report ------------------------------------------------------------

function seasonRail(s) {
  const turn = s.last_turn;
  if (turn) return h('aside', {class: 'season'}, turnCard(turn));
  if (s.latest) {
    const c = s.latest;
    return h('aside', {class: 'season'}, card(`Latest: ${when(c)}`, h('div', {class: 'stack'},
      h('p', {class: 'small secondary'}, `Cycle ${c.tick} · ${c.place || 'on the road'}`),
      c.actions.map(resultRow), eventList(c.events, ui.railRoutine), railToggle()),
    'What you have seen most recently.'));
  }
  return h('aside', {class: 'season'}, card('This season', h('p', {class: 'secondary'},
    'Choose what to do. Everyone else in the region is deciding too.')));
}

function railToggle() {
  return h('label', {class: 'row small secondary'},
    h('input', {type: 'checkbox', checked: ui.railRoutine, onchange: (event) => { ui.railRoutine = event.target.checked; render(); }}),
    'Show everyday activity');
}

function turnCard(turn) {
  const title = turn.cycles === 1 ? `${when(turn.start)}` : `${turn.cycles} seasons: ${when(turn.start)} to ${when(turn.end)}`;
  const grouped = GROUPS.map(([key, label]) => [label, turn.changes.filter((c) => c.group === key)]).filter(([, list]) => list.length);
  return card(title, h('div', {class: 'stack'},
    turn.cycles > 1 ? h('p', {class: 'small secondary'}, `You waited; ${turn.results.filter((r) => !r.success).length} refusals.`)
      : turn.results.map(resultRow),
    turn.note ? h('p', {class: 'small secondary'}, turn.note) : null,
    grouped.length ? h('div', {class: 'stack-sm'}, h('h4', null, 'What changed'),
      grouped.map(([label, list]) => h('div', null, h('div', {class: 'small muted'}, label),
        h('ul', {class: 'changes'}, list.map(changeRow))))) : h('p', {class: 'small secondary'}, 'Nothing you can see changed.'),
    turn.events.length ? h('div', {class: 'stack-sm'}, h('h4', null, 'Around you'),
      eventList(turn.events, ui.railRoutine), railToggle()) : null),
  'Your choice resolved with everyone else\'s.');
}

function changeRow(change) {
  if (change.text) return h('li', null, h('span', {class: 'text'}, change.text));
  const tone = change.good === null || change.good === undefined ? 'neutral' : change.good ? 'good' : 'bad';
  const arrow = change.direction === 'up' ? '▲' : '▼';
  return h('li', null,
    h('span', {class: 'text'}, change.label, h('span', {class: 'muted'}, ` ${fmt(change.before)} → ${fmt(change.after)}`)),
    h('span', {class: `delta ${tone}`, title: tone === 'neutral' ? null : tone === 'good' ? 'better for you' : 'worse for you'},
      `${arrow} ${signed(change.delta)}`));
}

// ----- Saving, loading and new games ------------------------------------------------

function openGame() {
  ui.dialog = true;
  ui.saves = null;
  ui.exported = null;
  renderDialog();
  refreshSaves();
}

async function refreshSaves() {
  try {
    ui.saves = await api('GET', 'saves');
  } catch (error) {
    ui.saves = {saves: [], folder: '', error: error.message};
  }
  renderDialog();
}

function closeGame() {
  ui.dialog = false;
  const dialog = document.getElementById('game-dialog');
  if (dialog) dialog.close();
}

function renderDialog() {
  let dialog = document.getElementById('game-dialog');
  if (!ui.dialog) return;
  if (!dialog) {
    dialog = h('dialog', {id: 'game-dialog', 'aria-labelledby': 'game-title'});
    dialog.addEventListener('close', () => { ui.dialog = false; dialog.remove(); });
    document.body.append(dialog);
    dialog.replaceChildren(...dialogContent());
    dialog.showModal();
    return;
  }
  const active = document.activeElement && dialog.contains(document.activeElement) ? document.activeElement.id : null;
  const drafts = {};
  for (const input of dialog.querySelectorAll('input[id], select[id]')) drafts[input.id] = input.value;
  dialog.replaceChildren(...dialogContent());
  for (const [id, value] of Object.entries(drafts)) { const input = dialog.querySelector(`#${id}`); if (input) input.value = value; }
  if (active) { const again = dialog.querySelector(`#${active}`); if (again) again.focus(); }
}

function confirmLeave() {
  return !ui.state.unsaved || window.confirm('This game has unsaved play. It will be kept as "autosave". Leave it?');
}

const PAIRS = {
  matched: ['', 'The checkpoint and its recorded inputs were saved together.'],
  unverified: ['inputs unverified', 'Saved by the terminal or an earlier version: the inputs are not stamped with this checkpoint.'],
  mismatched: ['inputs differ', 'The inputs were not saved with this checkpoint (an interrupted save?). Replay rebuilds what the inputs record.'],
  'unreadable inputs': ['inputs unreadable', 'The recorded inputs cannot be read; only the checkpoint can be resumed.'],
  'no inputs': ['no inputs', 'There are no recorded inputs; only the checkpoint can be resumed.'],
};

function kept(response) {
  return response.kept ? ` Your unsaved play was kept as "${response.kept}".` : '';
}

function dialogContent() {
  const s = ui.state;
  const suggested = s.slot || (s.over ? 'game' : s.character.name.toLowerCase().replace(/[^a-z0-9_-]+/g, '-').replace(/^-+|-+$/g, '') || 'game');
  const slot = h('input', {type: 'text', id: 'save-slot', value: suggested, maxlength: '40', 'aria-label': 'Save name'});
  const save = () => run('Saving…', async () => {
    const response = await api('POST', 'save', {version: ui.state.version, slot: slot.value.trim()});
    adopt(response.state);
    toast(`Saved to ${response.saved}`, 'good', 9000);
    await refreshSaves();
  });
  const load = (name, method) => {
    if (!confirmLeave()) return;
    run(method === 'replay' ? 'Replaying the recorded inputs…' : 'Loading…', async () => {
      const response = await api('POST', 'load', {version: ui.state.version, slot: name, method});
      resetFor(response.state);
      closeGame();
      toast((method === 'replay' ? `Rebuilt ${name} from its recorded inputs.` : `Resumed ${name}.`) + kept(response), 'good', 9000);
    });
  };
  const fields = {
    name: h('input', {type: 'text', id: 'new-name', value: 'Wanderer', maxlength: '40'}),
    home: h('select', {id: 'new-home'}, s.towns.map((town) => h('option', {value: town}, town))),
    seed: h('input', {type: 'number', id: 'new-seed', value: '42', min: '0', step: '1'}),
    style: h('select', {id: 'new-style'}, ['balanced', 'personal', 'collective'].map((p) => h('option', {value: p}, p))),
    years: h('input', {type: 'number', id: 'new-years', value: '0', min: '0', max: '200', step: '1'}),
  };
  const start = () => {
    if (!confirmLeave()) return;
    const number = (input) => Number.isInteger(Number(input.value)) && input.value.trim() !== '' ? Number(input.value) : input.value;
    run('Founding the world…', async () => {
      const response = await api('POST', 'new', {version: ui.state.version, name: fields.name.value, home: fields.home.value,
        seed: number(fields.seed), policy_style: fields.style.value, years: number(fields.years)});
      resetFor(response.state);
      closeGame();
      toast(`You arrive in ${response.state.character.town} as ${response.state.character.name}.` + kept(response), 'good', 9000);
    });
  };
  const exportReport = () => run('Writing the report…', async () => {
    ui.exported = await api('POST', 'export');
    renderDialog();
  });
  const saves = ui.saves;
  return [
    h('div', {class: 'dialog-head'}, h('h2', {id: 'game-title'}, 'Save & load'),
      h('button', {class: 'btn ghost', onclick: closeGame, 'aria-label': 'Close'}, 'Close')),
    h('div', {class: 'dialog-body stack'},
      s.over ? null : h('section', {class: 'stack-sm'}, h('h3', null, 'Save this game'),
        h('p', {class: 'small secondary'}, 'A checkpoint between turns, which resumes exactly, and the inputs that rebuild it. '
          + 'If the server stops with unsaved play, it is saved as "autosave".'),
        h('div', {class: 'form-row'}, h('label', {class: 'field wide'}, 'Save name', slot),
          h('button', {class: 'btn primary', disabled: !!ui.busy, onclick: save}, 'Save'))),
      h('section', {class: 'stack-sm'}, h('h3', null, 'Saved games'),
        !saves ? empty('Looking for saves…') : saves.error ? empty(saves.error) : saves.saves.length ? table(
          [['Name'], ['Player'], ['Cycle', true], ['Saved'], ['']],
          saves.saves.map((entry) => [h('span', null, entry.slot, PAIRS[entry.pair] && PAIRS[entry.pair][0]
            ? h('span', {class: 'tag', title: PAIRS[entry.pair][1], style: {marginLeft: '.4rem'}}, PAIRS[entry.pair][0]) : null),
            entry.player || '–', entry.tick === null ? '–' : String(entry.tick),
            entry.saved.replace('T', ' '),
            h('span', {class: 'row'},
              h('button', {class: 'btn small', disabled: !!ui.busy, onclick: () => load(entry.slot, 'checkpoint'),
                title: 'Resume the checkpoint exactly where it was saved.'}, 'Resume'),
              entry.replayable ? h('button', {class: 'btn small ghost', disabled: !!ui.busy, onclick: () => load(entry.slot, 'replay'),
                title: 'Rebuild the session from its settings and your recorded inputs alone.'}, 'Replay') : null)]))
          : empty('No saves yet.'),
        saves && saves.folder ? h('p', {class: 'small muted'}, `In ${saves.folder}`) : null),
      h('section', {class: 'stack-sm'}, h('h3', null, 'Start a new life'),
        h('p', {class: 'small secondary'}, 'A new society from a seed. It can run on its own for some years before you arrive.'),
        h('div', {class: 'form-row'},
          h('label', {class: 'field wide'}, 'Your name', fields.name), h('label', {class: 'field'}, 'Arrive in', fields.home),
          h('label', {class: 'field'}, 'Seed', fields.seed), h('label', {class: 'field'}, 'Priorities', fields.style),
          h('label', {class: 'field'}, 'Years before you', fields.years),
          h('button', {class: 'btn primary', disabled: !!ui.busy, onclick: start}, 'Start'))),
      h('section', {class: 'stack-sm'}, h('h3', null, 'The historian\'s report'),
        h('p', {class: 'small secondary'}, 'The full record of this world as an offline report, as the terminal writes it on quitting. '
          + 'It shows more than anyone inside the world can know.'),
        h('div', {class: 'row'}, h('button', {class: 'btn', disabled: !!ui.busy, onclick: exportReport}, 'Write the report'),
          ui.exported ? h('a', {href: `/report?token=${encodeURIComponent(TOKEN)}`, target: '_blank', rel: 'noopener'}, 'Open it') : null),
        ui.exported ? h('p', {class: 'small muted'}, `Written to ${ui.exported.folder}`) : null)),
  ];
}

function resetFor(state) {
  ui.person = null; ui.topics = null; ui.timeline = null; ui.timelineLimit = 40; ui.town = null;
  ui.tab = state.over ? 'journal' : 'act';
  adopt(state);
}

// ----- Start ---------------------------------------------------------------------------

async function start() {
  const [tab, person] = decodeURIComponent(location.hash.slice(1)).split(':');  // #people:3 opens a conversation
  if (TABS.some(([id]) => id === tab)) ui.tab = tab;
  if (person && /^\d+$/.test(person)) ui.person = Number(person);
  try {
    adopt(await api('GET', 'state'));
    render();
    if (tab === 'saves') openGame();  // #saves opens Save & load
  } catch (error) {
    document.getElementById('app').replaceChildren(h('p', {class: 'loading'}, error.message));
  }
}

start();
