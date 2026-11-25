"""v0.8 Stage 3: what people know beyond their own eyes, and how it travels.

A claim is something a person experienced, witnessed or was told: an employer's
pay, a lost shipment, a famine, a death, help received. Each claim records who
first knew it, who passed it on, when it was observed and when it was heard,
how many retellings it has been through, and how confident its holder is.

Claims are never broadcast. They pass between two people at a time: each
cycle a person may tell one acquaintance in their own town one piece of news
that person has not heard, and only if they do not distrust them. News reaches
another town only with someone who moves there, with a merchant's market
contact, or with a player. Each retelling loses some confidence.

Hearing how someone treats people moves the hearer's trust in them a little,
in proportion to the hearer's confidence in the claim; a merchant who hears of
lost shipments on a route asks a larger margin before using it. Everything here
is deterministic: no random draws, so replay and checkpoints are exact.

Since v0.9 Stage 2 a person also knows what they themselves need and cannot get
(``note_needs``): two iron for a house, say, and what they would pay. They keep
that claim current while the need lasts and drop it once it is met; everyone
they told keeps the version they heard, which ages and can be out of date. Who
needs what is passed on only when a teller has no fresher news of events, and
is forgotten first when memory is full, so it never displaces other news.
"""
from copy import deepcopy

LIMIT = 30            # claims a person keeps; the oldest heard are forgotten first
STALE = 16            # cycles after which news is too old to pass on
RELAY = .8            # confidence kept at each retelling
DOUBT = .5            # further discount when the hearer distrusts the teller
WARY = -.3            # nobody confides in someone they trust this little
DEAF = -.6            # nor listens to them
HEARSAY_TRUST = .02   # trust moved by hearing of someone's conduct, scaled by confidence
VALENCE = {'underpaid': -1., 'paid_fairly': .5, 'helped': .5, 'took_last': 0.}


def _key(kind, place, subject, act, stamp):
    return [kind, place, subject, act, stamp]


def _names(world):
    people = {a.id: a.name for a in world.agents}
    for snapshot in world.snapshots:
        for person in snapshot.get('agents', []):
            people.setdefault(person['id'], person['name'])
    return people, {s.id: s.name for s in world.settlements}


def knows(world, holder):
    return world.knowledge.get(holder, [])


def remember(world, holder, item):
    """Keep a claim; the newest, surest version of the same news wins. Returns True if it was news."""
    store = world.knowledge.setdefault(holder, [])
    for index, old in enumerate(store):
        if old['key'] == item['key']:
            if item['confidence'] > old['confidence'] + 1e-9:
                store[index] = item
            return False
    store.append(item)
    _forget_needs_first(store)
    if len(store) > LIMIT:
        store.sort(key=lambda c: (c['learned'], c['observed']))
        del store[:len(store) - LIMIT]
    return any(c is item for c in store)


def _forget_needs_first(store):
    """Over the limit, who needs what is forgotten before any news of events, oldest heard first."""
    excess = len(store) - LIMIT
    if excess <= 0:
        return
    needs = sorted((c for c in store if c['kind'] == 'need'), key=lambda c: (c['learned'], c['observed']))
    for claim in needs[:excess]:
        store.remove(claim)


def firsthand(world, holder, kind, *, place=None, subject=None, facts=None, stamp=None, via=None, subject_name=None):
    """Something the holder experienced or saw for themselves this cycle."""
    people, towns = _names(world)
    facts = dict(facts or {})
    item = dict(kind=kind, place=place, place_name=towns.get(place), subject=subject,
                subject_name=subject_name or people.get(subject), facts=facts, observed=world.tick,
                origin=holder, origin_name=people.get(holder), source=None, source_name=None, via=via,
                learned=world.tick, hops=0, confidence=1.,
                key=_key(kind, place, subject, facts.get('act', facts.get('outcome')),
                         world.tick if stamp is None else stamp))
    return remember(world, holder, item)


def relay(world, teller, hearer, item):
    """The teller passes a claim to the hearer, under the same rules for everyone."""
    tellers = {a.id: a for a in world.agents}
    listener = tellers.get(hearer)
    if listener is None or teller not in tellers or item.get('subject') == hearer:
        return False
    regard = listener.trust.get(teller, 0.)
    if regard <= DEAF:
        return False
    told = deepcopy(item)
    told.update(source=teller, source_name=tellers[teller].name, learned=world.tick, hops=item['hops'] + 1,
                confidence=round(item['confidence'] * RELAY * (DOUBT if regard < 0 else 1.), 4))
    fresh = remember(world, hearer, told)
    subject = item.get('subject')
    if fresh and item['kind'] == 'conduct' and subject in tellers and subject not in (hearer, teller):
        change = VALENCE.get(item['facts'].get('act'), 0.) * HEARSAY_TRUST * told['confidence']
        if change:
            world._adjust_trust(hearer, subject, change)
    return fresh


def news_for(world, teller, hearer, *, limit=1):
    """What the teller would pass on: fresh claims the hearer has not heard, newest first."""
    heard = {tuple(map(str, c['key'])) for c in knows(world, hearer)}
    fresh = [c for c in knows(world, teller)
             if world.tick - c['observed'] <= STALE and c.get('subject') != hearer
             and tuple(map(str, c['key'])) not in heard]
    # News of events first; who needs what only when there is nothing fresher to tell.
    fresh.sort(key=lambda c: (c['kind'] == 'need', -c['observed'], -c['confidence'], str(c['key'])))
    return fresh[:limit]


def note_needs(world, holder, needs, place):
    """v0.9 Stage 2: the holder's own unmet needs, kept current; needs that ended are dropped.

    ``needs`` maps (resource, step) to facts: the amount missing, the step it
    serves, the most they would pay to buy it, and the job they have posted for
    it, if any. A need keeps one key from when it began, so a neighbor who
    heard of it once is not told again; its facts and date are refreshed while
    it lasts, and others keep the version they heard.
    """
    store = world.knowledge.setdefault(holder, [])
    own = {(c['facts'].get('resource'), c['facts'].get('step')): c for c in store
           if c['kind'] == 'need' and c['source'] is None and c['subject'] == holder}
    for key, claim in own.items():
        if key not in needs or claim['place'] != place:
            store.remove(claim)  # met, given up, or left behind in another town
    for (resource, step), facts in sorted(needs.items()):
        claim = own.get((resource, step))
        if claim is not None and claim['place'] == place:
            claim['facts'] = dict(facts, act=f'{step} {resource}')
            claim['observed'] = claim['learned'] = world.tick
        else:
            firsthand(world, holder, 'need', place=place, subject=holder,
                      facts=dict(facts, act=f'{step} {resource}'), stamp=world.tick)


def spread(world, players=()):
    """Each cycle, everyone who is at home may tell one neighbor one piece of news.

    The neighbor is chosen in turn (by cycle and identity), not at random, so the
    world's random sequence and replay stay untouched. Players choose for
    themselves what to tell; they only listen here.
    """
    present = sorted((a for a in world.agents if not world.is_traveling(a.id)), key=lambda a: a.id)
    for teller in present:
        if teller.id in players:
            continue
        neighbors = [a for a in present if a.home == teller.home and a.id != teller.id]
        if not neighbors:
            continue
        hearer = neighbors[(world.tick + teller.id) % len(neighbors)]
        if teller.trust.get(hearer.id, 0.) <= WARY:
            continue
        for item in news_for(world, teller.id, hearer.id):
            relay(world, teller.id, hearer.id, item)


# ----- Words --------------------------------------------------------------

def age(cycles):
    if cycles <= 0:
        return 'this season'
    if cycles == 1:
        return 'last season'
    if cycles < 4:
        return f'{cycles} seasons ago'
    if cycles < 8:
        return 'about a year ago'
    return f'about {cycles // 4} years ago'


def provenance(item, now):
    """Where a holder's knowledge came from, in their words."""
    seen = age(now - item['observed'])
    if item['source'] is None:
        return f'I heard it from {item["via"]} {seen}' if item.get('via') else f'I saw it myself {seen}'
    parts = [f'{item["source_name"]} told me {age(now - item["learned"])}']
    if seen != age(now - item['learned']):
        parts.append(f'it happened {seen}')
    if item['hops'] > 1 and item.get('origin_name'):
        parts.append(f'{item["origin_name"]} knew it first')
    if item['confidence'] < .5:
        parts.append("I'm not sure it's true")
    return '; '.join(parts)


def describe(item, *, speaker=None):
    """The claim itself in plain words, from the holder's point of view."""
    facts, who, place = item['facts'], item.get('subject_name') or 'someone', item.get('place_name') or 'somewhere'
    me = speaker is not None and item['source'] is None and item['origin'] == speaker
    kind = item['kind']
    if kind == 'conduct':
        act = facts.get('act')
        if act in ('underpaid', 'paid_fairly'):
            whom = 'me' if me else (item.get('origin_name') or 'a worker')
            judgment = ('well under what the market pays' if act == 'underpaid' else 'a fair wage')
            return (f'{who} paid {whom} {facts.get("wage", 0):g} coins a unit for {facts.get("resource", "work")}, '
                    f'{judgment}')
        if act == 'helped':
            whom = 'me' if me else (item.get('origin_name') or 'someone')
            return f'{who} {facts.get("how", "helped")} {whom}'
        if act == 'took_last':
            whom = 'me' if me else (item.get('origin_name') or 'someone')
            return f'{who} got the last {facts.get("what", "goods")} in {place} before {whom}'
    if kind == 'shipment':
        owner = ('my' if speaker is not None and item.get('subject') == speaker
                 else f'{item["subject_name"]}\'s' if item.get('subject_name') else 'a')
        if facts.get('outcome') == 'lost':
            return (f'{owner} shipment of {facts.get("resource", "goods")} to {facts.get("destination_name", "a neighbor")} '
                    f'was lost: {facts.get("reason", "on the road")}')
        return (f'{owner} shipment of {facts.get("resource", "goods")} reached {facts.get("destination_name", "a neighbor")}'
                f' and fetched {facts.get("unit_price", 0):g} a unit')
    if kind == 'famine':
        return f'{place} ran short of food and people there went hungry'
    if kind == 'hardship':
        return f'{who} went {"without food for weeks" if facts.get("what") == "starving" else "hungry"} in {place}'
    if kind == 'death':
        return f'{who} died in {place} ({facts.get("cause", "old age")})'
    if kind == 'arrival':
        return f'{who} came to live in {place}'
    if kind == 'decision':
        body = facts.get('institution_name', 'an organization')
        return f'{body}{"" if place in body else " in " + place} carried out {facts.get("what", "a decision")}'
    if kind == 'need':
        from .goal_engine import describe_step
        me = speaker is not None and item.get('subject') == speaker
        text = (f'{"I need" if me else who + " needs"} {facts.get("amount", 0):g} {facts.get("resource", "goods")} '
                f'{describe_step(facts.get("step", ""))}')
        parts = []
        if facts.get('wage') is not None:
            parts.append(f'paying {facts["wage"]:g} a unit to have it gathered'
                         + (f' (job {facts["job"]})' if facts.get('job') is not None else ''))
        if facts.get('price') is not None:
            parts.append(f'ready to buy it at up to {facts["price"]:g} a unit')
        if parts:
            text += f'; {"I am" if me else (who.split()[0] if who else "they") + " is"} ' + ' and '.join(parts)
        return text
    return f'something happened in {place}'
