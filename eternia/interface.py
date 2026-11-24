"""v0.8 Stage 4: what the browser shows, built in Python from what the player knows.

The browser only draws. Every number it shows, prices and wages included, is
computed here or by the world, and every change goes through PlayableSession:
a menu choice becomes the same proposal, and a question the same conversation,
that the terminal would send, so saving, loading and replay are unchanged.

Views come from the player's own observation, their journal and public
records: posted prices, job notices, and what happened in the town where the
player lived at the time. They show nothing a person in the world could not
know, and building one changes nothing: no state, no random draws.
"""
import bisect
from copy import deepcopy
import math
import weakref

from . import player as player_view
from .market import bid_price
from .player_history import household, journal

GOODS = ('food', 'wood', 'iron')
RESOURCES = ('food', 'wood', 'iron', 'coins')
ROUTINE_KINDS = ('action', 'conflict')  # everyday entries; the timeline shows them on request
CLOSED_DECISIONS = 6                    # past decisions shown for each organization
TIMELINE_LIMIT = 40                     # cycles of history sent at once


def clean(value):
    """A JSON-safe copy: string keys, lists for tuples and sets, no infinities."""
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    if isinstance(value, (set, frozenset)):
        return [clean(v) for v in sorted(value, key=str)]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    return str(value)


def clock(world):
    per_year = world.ticks_per_year
    return dict(tick=world.tick, year=world.tick // per_year, season=world.tick % per_year + 1,
                ticks_per_year=per_year)


def when(tick, per_year):
    return dict(tick=tick, year=tick // per_year, season=tick % per_year + 1)


# ----- Choices ------------------------------------------------------------

def menu(session):
    """The player's menu, numbered as the terminal numbers it (from 0 here)."""
    out = []
    for index, choice in enumerate(session.options()):
        proposal = choice['proposal']
        out.append(dict(index=index, section=choice['section'], label=choice['label'],
                        fields=deepcopy(choice['fields']), checked=choice['checked'],
                        type=proposal['type'], params=deepcopy(proposal['params'])))
    return out


def customized(choice, values):
    """A choice's proposal with one value per field, under the terminal's own rules.

    No values keeps the choice as offered. Values are passed to player.customize,
    which checks each against its field's range exactly as the terminal does.
    """
    fields = choice['fields']
    if not values:
        return deepcopy(choice['proposal'])
    if not fields:
        raise ValueError('This choice has nothing to change.')
    if not isinstance(values, list) or len(values) != len(fields):
        raise ValueError('Give one value for each of: ' + ', '.join(f['label'] for f in fields) + '.')
    texts = []
    for field, value in zip(fields, values):
        text = str(value).strip() if type(value) in (str, int, float) else ''
        if not text:
            raise ValueError(f'Fill in the {field["label"]}.')
        if field['kind'] != 'text' and len(text.split()) != 1:
            raise ValueError(f'The {field["label"]} must be a number.')
        texts.append(text)
    if fields[0]['kind'] == 'text':
        return player_view.customize(choice, texts[0])
    return player_view.customize(choice, ' '.join(texts))


# ----- The player and their surroundings -----------------------------------

def _quotes(posted):
    """What a town's market charts: the posted price you pay, and the 80% it pays you."""
    return {good: dict(buy=posted[good], sell=bid_price(posted[good])) for good in GOODS if good in posted}


def _feeling(trust):
    if trust >= .3:
        return 'you trust them'
    if trust > .05:
        return 'you like them'
    if trust <= -.3:
        return 'you distrust them'
    if trust < -.05:
        return 'you are wary of them'
    return 'no strong feeling'


def _hunger(hunger):
    """The same thresholds the situation's advice uses."""
    return 'starving' if hunger >= 100 else 'hungry' if hunger >= 60 else 'fed'


def _names(world, observation):
    towns = {s.id: s.name for s in world.settlements}  # town names are common knowledge
    people = {p['id']: p['name'] for p in observation.get('peers', [])}
    people[observation['actor']['id']] = 'you'
    institutions = {i['id']: i['name'] for i in observation.get('institutions', [])}
    return towns, people, institutions


def _character(session, observation):
    world, actor = session.world, observation['actor']
    towns, _, institutions = _names(world, observation)
    journey = actor.get('journey') or None
    road = None
    if journey:
        road = dict(origin=towns.get(journey.get('origin')), destination=towns.get(journey.get('destination')),
                    returning=bool(journey.get('returning')))
    inventory = {r: actor['inventory'].get(r, 0.) for r in RESOURCES}
    available = actor.get('available_inventory', inventory)
    return dict(id=actor['id'], name=actor['name'], role=actor.get('role'), age=actor.get('age'),
                generation=actor.get('generation', 0), lineage=actor.get('lineage'),
                town=observation['settlement']['name'], town_id=observation['settlement']['id'],
                inventory=inventory, available={r: available.get(r, 0.) for r in RESOURCES},
                hunger=actor.get('hunger', 0.), energy=actor.get('energy', 100.),
                hunger_level=_hunger(actor.get('hunger', 0.)),
                skills=sorted(actor.get('skills', [])), structures=dict(actor.get('structures', {})),
                knowledge=actor.get('knowledge', 0), reputation=actor.get('reputation', .5),
                earnings=observation.get('municipality', {}).get('earnings', 0.),
                memberships=[institutions.get(i, 'an organization') for i in observation.get('memberships', [])],
                journey=road, advice=player_view.advice(observation), household=household(world))


def _town(entry, posted):
    out = dict(id=entry['id'], name=entry['name'], x=entry.get('x'), y=entry.get('y'),
               population=entry.get('population', 0), stock={g: entry.get(g, 0.) for g in GOODS},
               treasury=entry.get('treasury', 0.), deposits={g: entry.get('deposits', {}).get(g, 0.) for g in GOODS},
               prices=_quotes(posted.get(entry['id'], {})))
    if 'distance' in entry:
        out.update(distance=entry['distance'], migration_open=entry.get('migration_open', True))
    return out


def _job(order, observation, towns):
    me = observation['actor']['id']
    mine = order['employer'] == {'kind': 'person', 'id': me}
    return dict(id=order['id'], town=towns.get(order['settlement']), town_id=order['settlement'],
                employer='you' if mine else player_view.employer_name(order['employer'], observation), mine=mine,
                resource=order['resource'], quantity=order['quantity'], remaining=order['remaining'],
                unit_wage=order['unit_wage'], expires=order['expires'])


def _world(session, observation):
    world = session.world
    towns, people, institutions = _names(world, observation)
    posted = observation.get('prices', {}).get('posted', {})
    here = _town(observation['settlement'], posted)
    here['policies'] = deepcopy(observation.get('settlement_policies', {}))
    here['policies']['trade_partners'] = [towns.get(t, str(t)) if type(t) is int else str(t)
                                          for t in here['policies'].get('trade_partners', [])]
    board = observation.get('municipality', {}).get('job_board', [])
    paths = observation.get('physical', {}).get('paths', {})
    neighbors = []
    for entry in observation.get('neighbors', []):
        town = _town(entry, posted)
        path = paths.get(entry['id']) or paths.get(str(entry['id']))
        town['path'] = None if not path else {k: path.get(k) for k in ('duration', 'supplies', 'risk', 'capacity')}
        town['jobs'] = [_job(o, observation, towns) for o in board if o['settlement'] == entry['id']]
        neighbors.append(town)
    roads = []
    for link in observation.get('physical', {}).get('links', []):
        owner = link.get('owner')
        roads.append(dict(id=link['id'], a=link['a'], b=link['b'], between=[towns.get(link['a']), towns.get(link['b'])],
                          terrain=link.get('terrain'), distance=link.get('distance'), condition=link.get('condition'),
                          capacity=link.get('capacity'), risk=link.get('risk'), closed=bool(link.get('closed')),
                          owner=None if owner is None else institutions.get(owner, 'an organization'),
                          local=here['id'] in (link['a'], link['b'])))
    # Each visible town keeps one series slot (by identity, never by rank) on the map and in the charts.
    for slot, town in enumerate(sorted([here, *neighbors], key=lambda t: t['id']), 1):
        town['slot'] = slot
    offers = []
    for offer in observation.get('market', []):
        mine = offer['actor'] == observation['actor']['id']
        offers.append(dict(id=offer['id'], mine=mine, who='you' if mine else people.get(offer['actor'], 'a neighbor'),
                           direction=offer['direction'], resource=offer['resource'], amount=offer['amount'],
                           unit_price=offer['unit_price'], expires=offer['expires']))
    jobs = [_job(o, observation, towns) for o in observation.get('municipality', {}).get('work_orders', [])]
    return dict(town=here, neighbors=neighbors, roads=roads, jobs=jobs,
                jobs_elsewhere=[_job(o, observation, towns) for o in board], offers=offers)


def _organizations(observation, towns, people):
    me, tick = observation['actor']['id'], observation.get('tick', 0)
    home = observation['settlement']['id']
    memberships = set(observation.get('memberships', []))
    authorities = observation.get('municipality', {}).get('authorities', {})
    out = []
    for institution in observation.get('institutions', []):
        decisions = []
        for decision in institution.get('decisions', []):
            yes, no = player_view.tally(decision)
            votes = {str(k): v for k, v in decision.get('votes', {}).items()}
            current = decision.get('status') == 'open' and decision.get('expires', 0) > tick
            status = 'open' if current else ('lapsed' if decision.get('status') == 'open' else decision.get('status'))
            mine = votes.get(str(me))
            decisions.append(dict(id=decision['id'], kind=decision['kind'], about=player_view.describe_decision(decision, observation),
                                  status=status, open=current, yes=yes, no=no, created=decision.get('created'),
                                  expires=decision.get('expires'), voters=len(decision.get('electorate', [])),
                                  proposer=people.get(decision.get('proposer'), 'a former member'),
                                  yours=decision.get('proposer') == me, can_vote=me in decision.get('electorate', []),
                                  your_vote=None if mine is None else mine.get('approve')))
        shown = [d for d in decisions if d['open']]
        shown += sorted((d for d in decisions if not d['open']), key=lambda d: -(d['created'] or 0))[:CLOSED_DECISIONS]
        rules = institution.get('rules', {})
        embargoes = [towns.get(int(t) if str(t).isdigit() else t, str(t))
                     for t, on in rules.get('embargoes', {}).items() if on is True]
        identity = institution['id']
        out.append(dict(id=identity, name=institution['name'], purpose=institution.get('purpose', 'group'),
                        town=towns.get(institution.get('settlement_id')), local=institution.get('settlement_id') == home,
                        active=institution.get('active', True), founded=institution.get('founded'),
                        members=len(institution.get('members', [])), member=identity in memberships,
                        authority=bool(authorities.get(identity, authorities.get(str(identity), False))),
                        levy=rules.get('tax_rate', 0.), communal_labor=rules.get('communal_labor', 0.),
                        embargoes=embargoes,
                        shared=({r: institution.get('available_inventory', {}).get(r, 0.) for r in RESOURCES}
                                if identity in memberships else None),
                        decisions=shown))
    out.sort(key=lambda i: (not i['local'], not i['member'], not i['active'], i['id']))
    return out


def _people(session, observation):
    world, person = session.world, session.person
    talks = getattr(world, '_talks', {})
    out = []
    if observation['actor'].get('journey'):
        return out  # nobody walks beside a traveller to talk
    for peer in observation.get('peers', []):
        count = talks.get(peer['id'])
        used = count['count'] if count and count['tick'] == world.tick else 0
        trust = round(person.trust.get(peer['id'], 0.), 3)  # the player's own feelings
        out.append(dict(id=peer['id'], name=peer['name'], role=peer.get('role', ''), reputation=peer.get('reputation'),
                        structures=dict(peer.get('structures', {})), your_trust=trust, feeling=_feeling(trust),
                        answers_left=max(0, world.TALK_LIMIT - used)))
    return out


def conversations(world):
    """Everything the player's household has asked and been told, oldest first."""
    people = household(world)
    mine = {p['id'] for p in people}
    names = {a.id: a.name for a in world.agents}
    for snapshot in world.snapshots:
        for agent in snapshot.get('agents', []):
            names.setdefault(agent['id'], agent['name'])
    return [dict(**when(e['tick'], world.ticks_per_year), partner=e['partner'], partner_name=names.get(e['partner'], 'someone'),
                 topic=e['topic'], lines=list(e['lines']), learned=len(e.get('learned', [])))
            for e in world.player_log if e['event'] == 'talk' and e['actor'] in mine]


def topics(session, partner):
    """What the player can ask or tell one person here; asking takes no season."""
    if not any(p['id'] == partner for p in session.partners()):
        raise ValueError('That person is not here to talk to.')
    return [dict(index=index, label=t['label'], fields=deepcopy(t['fields']), topic=t['proposal']['type'])
            for index, t in enumerate(session.conversation(partner))]


def state(session):
    """Everything the browser shows, in one JSON-safe view."""
    world = session.world
    out = dict(clock=clock(world), over=session.player_id is None,
               settings=dict(seed=world.seed, policy_style=world.policy_style),
               towns=[s.name for s in world.settlements], latest=None)
    history = timeline(session, limit=1, prices=False)
    out['latest'] = history['cycles'][0] if history['cycles'] else None
    if out['over']:
        out['journal'] = journal(world) if world.player_log else None
        out['conversations'] = conversations(world)
        return clean(out)
    observation = session.observation()
    towns, people, _ = _names(world, observation)
    out.update(character=_character(session, observation), world=_world(session, observation),
               organizations=_organizations(observation, towns, people), people=_people(session, observation),
               menu=menu(session), journal=journal(world), conversations=conversations(world),
               talk_limit=world.TALK_LIMIT)
    return clean(out)


# ----- What changed --------------------------------------------------------

def digest(session):
    """The handful of public facts and personal holdings a turn's changes are measured on."""
    if session.player_id is None:
        return None
    observation = session.observation()
    world, actor, town = session.world, observation['actor'], observation['settlement']
    towns, people, _ = _names(world, observation)
    posted = observation.get('prices', {}).get('posted', {})
    decisions, organizations = {}, {}
    memberships = set(observation.get('memberships', []))
    for institution in observation.get('institutions', []):
        if institution.get('settlement_id') != town['id']:
            continue
        organizations[institution['id']] = dict(name=institution['name'], members=len(institution.get('members', [])),
                                                member=institution['id'] in memberships,
                                                active=institution.get('active', True),
                                                levy=institution.get('rules', {}).get('tax_rate', 0.))
        for decision in institution.get('decisions', []):
            decisions[(institution['id'], decision['id'])] = dict(
                organization=institution['name'], about=player_view.describe_decision(decision, observation),
                status=decision.get('status'), yours=decision.get('proposer') == actor['id'])
    return dict(
        name=actor['name'], town=town['name'],
        you={**{r: actor['inventory'].get(r, 0.) for r in RESOURCES},
             'hunger': actor.get('hunger', 0.), 'energy': actor.get('energy', 100.)},
        skills=sorted(actor.get('skills', [])), structures=dict(actor.get('structures', {})),
        knowledge=actor.get('knowledge', 0), traveling=bool(actor.get('journey')),
        prices={towns[t]: dict(p) for t, p in posted.items() if t in towns},
        stock={g: town.get(g, 0.) for g in GOODS}, treasury=town.get('treasury', 0.),
        population={town['name']: town.get('population', 0),
                    **{n['name']: n.get('population', 0) for n in observation.get('neighbors', [])}},
        policies={k: deepcopy(v) for k, v in observation.get('settlement_policies', {}).items()
                  if k in ('tax_rate', 'communal_labor', 'specialization', 'migration_open', 'granary_capacity')},
        jobs={o['id']: _job(o, observation, towns) for o in observation.get('municipality', {}).get('work_orders', [])},
        organizations=organizations, decisions=decisions)


def _number(group, label, before, after, unit='', good_when='up'):
    delta = round(after - before, 6)
    return dict(group=group, label=label, before=before, after=after, delta=delta, unit=unit,
                direction='up' if delta > 0 else 'down', good=(delta > 0) == (good_when == 'up') if good_when else None)


def changes(before, after):
    """How the player's world changed between two digests, in the player's terms."""
    if before is None:
        return []
    if after is None:
        return [dict(group='you', text='Your household has ended; no heir remains to continue.')]
    out = []
    if after['name'] != before['name']:
        out.append(dict(group='you', text=f'{before["name"]} is gone; you continue as {after["name"]}, the heir.'))
    for key, label, good in (('food', 'Food', 'up'), ('wood', 'Wood', 'up'), ('iron', 'Iron', 'up'),
                             ('coins', 'Coins', 'up'), ('hunger', 'Hunger', 'down'), ('energy', 'Energy', 'up')):
        if abs(after['you'][key] - before['you'][key]) >= .005:
            out.append(_number('you', label, before['you'][key], after['you'][key], good_when=good))
    for skill in sorted(set(after['skills']) - set(before['skills'])):
        out.append(dict(group='you', text=f'You learned {skill}.'))
    for structure, count in sorted(after['structures'].items()):
        if count > before['structures'].get(structure, 0):
            out.append(dict(group='you', text=f'You now own {count} {structure}{"s" if count != 1 else ""}.'))
    if after['knowledge'] != before['knowledge']:
        out.append(dict(group='you', text=f'Your Aether knowledge is now {after["knowledge"]}.'))
    if after['traveling'] != before['traveling']:
        out.append(dict(group='you', text='You set out on the road.' if after['traveling'] else
                        f'You arrived in {after["town"]}.'))
    if after['town'] != before['town']:
        out.append(dict(group='town', text=f'You now live in {after["town"]}.'))
    shared = set(before['prices']) & set(after['prices'])
    for town in sorted(shared, key=lambda name: (name != after['town'], name)):  # home first
        for good in GOODS:
            old, new = before['prices'][town].get(good), after['prices'][town].get(good)
            if old is not None and new is not None and abs(new - old) >= .005:
                out.append(_number('prices', f'{good.capitalize()} in {town}', old, new, unit='coins', good_when=None))
    for town in sorted(set(before['population']) & set(after['population'])):
        if before['population'][town] != after['population'][town]:
            out.append(_number('town', f'{town} population', before['population'][town], after['population'][town],
                               good_when=None))
    if after['town'] == before['town']:
        for good in GOODS:
            if abs(after['stock'][good] - before['stock'][good]) >= .005:
                out.append(_number('town', f'{after["town"]} market {good}', before['stock'][good], after['stock'][good],
                                   good_when=None))
        if abs(after['treasury'] - before['treasury']) >= .005:
            out.append(_number('town', f'{after["town"]} market coins', before['treasury'], after['treasury'],
                               good_when=None))
        for key, label in (('tax_rate', 'levy'), ('communal_labor', 'communal labor'),
                           ('specialization', 'specialization'), ('migration_open', 'open to newcomers'),
                           ('granary_capacity', 'granary capacity')):
            if after['policies'].get(key) != before['policies'].get(key):
                out.append(dict(group='politics', text=f'{after["town"]} {label}: '
                                                       f'{_policy(key, before["policies"].get(key))} → '
                                                       f'{_policy(key, after["policies"].get(key))}'))
        for identity, job in after['jobs'].items():
            if identity not in before['jobs']:
                out.append(dict(group='jobs', text=f'New job {identity} from {job["employer"]}: {job["remaining"]} '
                                                   f'{job["resource"]} at {player_view.money(job["unit_wage"])} each'))
            elif job['remaining'] != before['jobs'][identity]['remaining']:
                out.append(dict(group='jobs', text=f'Job {identity} ({job["employer"]}): {job["remaining"]} of '
                                                   f'{job["quantity"]} {job["resource"]} left'))
        for identity, job in before['jobs'].items():
            if identity not in after['jobs']:
                out.append(dict(group='jobs', text=f'Job {identity} from {job["employer"]} closed'))
        for identity, organization in after['organizations'].items():
            old = before['organizations'].get(identity)
            if old is None:
                out.append(dict(group='politics', text=f'{organization["name"]} was founded.'))
                continue
            if organization['member'] != old['member']:
                out.append(dict(group='politics', text=('You are now a member of ' if organization['member']
                                                        else 'You are no longer a member of ') + organization['name'] + '.'))
            if organization['members'] != old['members']:
                out.append(_number('politics', f'{organization["name"]} members', old['members'],
                                   organization['members'], good_when=None))
            if organization['active'] != old['active']:
                out.append(dict(group='politics', text=f'{organization["name"]} '
                                                       f'{"revived" if organization["active"] else "dissolved"}.'))
        for key, decision in sorted(after['decisions'].items()):
            old = before['decisions'].get(key)
            if old is None:
                out.append(dict(group='politics', text=f'New {"proposal of yours" if decision["yours"] else "proposal"} '
                                                       f'{key[1]} in {decision["organization"]}: {decision["about"]}'))
            elif old['status'] != decision['status']:
                out.append(dict(group='politics', text=f'{"Your proposal" if decision["yours"] else "Proposal"} '
                                                       f'{key[1]} in {decision["organization"]} ({decision["about"]}) '
                                                       f'is now {decision["status"]}'))
    return out


def _policy(key, value):
    if value is None:
        return 'none'
    if isinstance(value, bool):
        return 'yes' if value else 'no'
    if key in ('tax_rate', 'communal_labor') and isinstance(value, (int, float)):
        return f'{value:.0%}'
    if isinstance(value, float):
        return player_view.money(value)
    return str(value)


# ----- History ---------------------------------------------------------------

def routine(event):
    """Everyday entries (actions, conflicts, single votes) that a view may fold away."""
    kind = event.get('kind')
    return kind in ROUTINE_KINDS or (kind == 'institution' and ' voted ' in event.get('message', ''))


class _History:
    """An index of what concerns the player's household, read incrementally from the world's logs.

    The event log and the action audit only grow between cycles, so each view
    reads just the entries added since the last one. The index is rebuilt from
    the start if the household changes (an heir takes over) or a log no longer
    ends with the entry it last read, as after a cycle rolled back. It lives
    outside the world: building it changes nothing and is never saved.
    """

    def __init__(self, world, people):
        self.key = tuple(p['id'] for p in people)
        self.ids, self.names = {p['id'] for p in people}, {p['name'] for p in people}
        self.start = people[0]['since']
        self.read = {'action_log': 0, 'events': 0}
        self.last = {'action_log': None, 'events': None}
        self.actions, self.events, self.moves = {}, {}, []  # by cycle; moves are (cycle, order, position, town)

    def current(self, world, people):
        if tuple(p['id'] for p in people) != self.key:
            return False
        for name in ('action_log', 'events'):
            log, seen = getattr(world, name), self.read[name]
            if len(log) < seen or (seen and log[seen - 1] is not self.last[name]):
                return False
        return True

    def update(self, world):
        log = world.action_log
        for position in range(self.read['action_log'], len(log)):
            audit = log[position]
            action = audit['action']
            if audit['tick'] < self.start or action.get('actor') not in self.ids:
                continue
            self.actions.setdefault(audit['tick'], []).append(audit)
            if action.get('type') == 'migrate' and audit['result'].get('success'):
                self.moves.append((audit['tick'] + 1, 1, position, None))  # they set out at the end of that cycle
        log = world.events
        for position in range(self.read['events'], len(log)):
            event = log[position]
            tick = event.get('tick', 0)
            if tick < self.start:
                continue
            if event.get('settlement') or self.yours(event):
                self.events.setdefault(tick, []).append(event)
            if event.get('kind') in ('arrival', 'player') and event.get('agent') in self.names and event.get('settlement'):
                self.moves.append((tick, 2, position, event['settlement']))
        for name in ('action_log', 'events'):
            log = getattr(world, name)
            self.read[name], self.last[name] = len(log), (log[-1] if log else None)
        return self

    def yours(self, event):
        return event.get('agent') in self.names or event.get('actor_id') in self.ids or bool(event.get('player'))

    def residence(self, world):
        """Where the household lived from each cycle on: (cycle, town name, or None on the road)."""
        joined = [(entry['tick'], 0, position, world.settlements[entry['home']].name)
                  for position, entry in enumerate(world.player_log) if entry['event'] == 'joined']
        return [(tick, place) for tick, _, _, place in sorted(joined + self.moves, key=lambda m: m[:3])]


_INDEXES = weakref.WeakKeyDictionary()


def _history(world, people):
    index = _INDEXES.get(world)
    if index is None or not index.current(world, people):
        index = _INDEXES[world] = _History(world, people)
    return index.update(world)


def timeline(session, limit=TIMELINE_LIMIT, prices=True):
    """The player's history cycle by cycle, newest first, and the prices they could see since arriving.

    Each cycle holds what the household chose and what became of it, and what
    happened in the town where they lived then, or to them. Routine entries
    (everyday actions, conflicts and individual votes) are marked so a view can
    fold them away. Only the cycles asked for are assembled; ``more`` says
    whether earlier ones exist.
    """
    world = session.world
    people = household(world)
    per_year = world.ticks_per_year
    if not people:
        return dict(cycles=[], more=False, limit=limit, prices=None)
    index = _history(world, people)
    moves = index.residence(world)
    since = [tick for tick, _ in moves]

    def where(tick):
        position = bisect.bisect_right(since, tick)
        return moves[position - 1][1] if position else None

    cycles, more = [], False
    for tick in sorted(set(index.actions) | set(index.events), reverse=True):
        place, seen = where(tick), set()
        entry = dict(**when(tick, per_year), place=place, actions=[], events=[])
        for audit in index.actions.get(tick, ()):
            result = audit['result']
            entry['actions'].append(dict(type=audit['action'].get('type'), success=result.get('success'),
                                         code=result.get('code'), text=result.get('message')))
            seen.add(result.get('message'))
        for event in index.events.get(tick, ()):
            yours = index.yours(event)
            if (not yours and (place is None or event.get('settlement') != place)) or event['message'] in seen:
                continue
            seen.add(event['message'])
            entry['events'].append(dict(kind=event.get('kind'), text=event['message'], yours=yours,
                                        routine=routine(event) and not yours))
        if not entry['actions'] and not entry['events']:
            continue
        if len(cycles) >= max(1, limit):
            more = True
            break
        cycles.append(entry)
    series = None
    if prices and session.player_id is not None:
        # Posted prices are public notices at home and in neighboring towns; shown since the player arrived.
        observation = session.observation()
        visible = sorted({observation['settlement']['id'], *(n['id'] for n in observation.get('neighbors', []))})
        towns = {s.id: s.name for s in world.settlements}
        history = world.price_history
        first = bisect.bisect_left([entry['tick'] for entry in history], index.start)
        series = dict(home=observation['settlement']['id'],
                      towns=[dict(id=t, name=towns[t], slot=position + 1) for position, t in enumerate(visible)],
                      points=[dict(**when(entry['tick'], per_year),
                                   prices={t: {g: entry['prices'][t][g] for g in GOODS}
                                           for t in visible if t in entry['prices']})
                              for entry in history[first:]])
    return dict(cycles=cycles, more=more, limit=limit, prices=series)
