"""v0.9 Stage 1: what stands between a person and their goal, judged from their own view.

A need is something the next step toward a person's goal consumes and they do
not have: wood and iron for a house, a unit of each to study carpentry or run an
Aether experiment, food toward a reserve they want to keep (see
``goal_engine.next_step``). Survival is not a need here: hunger is answered
before any goal, by eating or buying a meal.

For each need the person weighs the ways the rules already offer to close it:
gather it themselves, buy it at the posted price, or ask others to supply it with
a paid job whose wages they escrow from their own coins. A job is a public notice
in their town and the neighboring ones, so a private obstacle becomes an
opportunity anyone nearby can take, a player or anyone else. Everything here is
read from the person's own observation; nothing reads another person's state.
"""
import math

from .goal_engine import next_step
from .market import bid_price, offered_wage

SKILLS = {'food': 'foraging', 'wood': 'woodcutting', 'iron': 'mining'}
STALE = 8             # cycles (two years) after which news of a need is too old to act on
WARY = -.3            # trust at or below which a person will not deal with someone
KINDNESS_LIMIT = .3   # the most below the market's price a person will sell to someone they want to help
TRUST_PREMIUM = 1.    # coins a unit a buyer would pay to deal with someone they trust fully
FETCH_GAIN = 2.       # coins goods fetched from another town must be expected to earn, as a shipment must
LOSS_MEMORY = 8       # cycles a lost shipment on a road raises that margin, as for consignments
HEARD_LOSS = .5       # weight of a loss someone else suffered on that road
FOLLOW_THROUGH = 8    # cycles after gathering or fetching goods for a need that the news still counts as current
FAIR_LIMIT = 1.5      # a goal's materials are worth buying up to 1.5x their base price
WILLING_STEP = .1     # v0.9 Stage 4, when willingness rises: a tenth more for each cycle the goal has stalled,
WILLING_LIMIT = 2.    # up to twice that fair price
FOOD_RESERVE = 3      # meals a person keeps before spending on anything else
ORDER = ('iron', 'wood', 'food')  # the order needs are weighed in


def step_of(observation):
    """The next step of the observed person's goal, or None."""
    actor = observation['actor']
    available = actor.get('available_inventory', actor['inventory'])
    return next_step(actor.get('goal', {}), skills=actor.get('skills', []), structures=actor.get('structures', {}),
                     knowledge=actor.get('knowledge', 0), food=available.get('food', 0.),
                     recipes=observation.get('rules', {}).get('recipes', {}))


def base_of(observation, resource):
    prices = observation.get('prices') or {}
    local = (prices.get('posted') or {}).get(prices.get('home'), {}) or observation.get('rules', {}).get('prices', {})
    return prices.get('base', {}).get(resource, local.get(resource, 1.))


def willingness(observation, resource):
    """The most a person would pay a unit for what their goal's next step lacks.

    A fair price, 1.5 times the base. Where the world lets willingness rise
    (``rules['rising_willingness']``, v0.9 Stage 4), a goal that has stalled makes
    its materials worth more to the person: a tenth more of the fair price for
    each cycle without progress, up to twice the fair price. A person knows how
    long their own goal has stalled; nothing else is read.
    """
    fair = round(FAIR_LIMIT * base_of(observation, resource), 2)
    if not observation.get('rules', {}).get('rising_willingness'):
        return fair
    tick = observation.get('tick', 0)
    stalled = max(0, tick - (observation['actor'].get('mind') or {}).get('best_tick', tick))
    return round(fair * min(WILLING_LIMIT, 1 + WILLING_STEP * stalled), 2)


def needs(observation):
    """What the next step toward the person's goal lacks, with the ways they could close each gap.

    Each need names the resource, the units missing, the step it blocks, and:
    ``gather``  whether they could gather some here themselves (skill and accessible deposits);
    ``buy``     whether they could buy it now: stocked, at a fair price, and affordable;
    ``fair``    the most they would pay a unit: a fair price, 1.5 times the base, or more for a stalled
                goal where willingness rises (``willingness``);
    ``offer``   a neighbor's standing offer to sell it at a fair price, and the units they would take;
    ``pending`` units their own open job will still bring;
    ``supply``  units anyone could gather here for a job, since paid work draws on the same deposits;
    ``wage``    the wage an employer offers here, a fixed share of the posted price;
    ``hire``    units they could pay a job for now, keeping a few meals and the step's own coins.
    """
    actor, town = observation['actor'], observation['settlement']
    step = step_of(observation)
    if step is None:
        return []
    prices = observation.get('prices') or {}
    local = (prices.get('posted') or {}).get(prices.get('home'), {}) or observation.get('rules', {}).get('prices', {})
    base = prices.get('base', {})
    if not local:
        return []
    me, tick = actor['id'], observation.get('tick', 0)
    available = actor.get('available_inventory', actor['inventory'])
    skills, deposits = set(actor.get('skills', [])), town.get('deposits', {})
    # Keep a few meals, and while a house is the goal, the coins the house itself will cost.
    house = observation.get('rules', {}).get('recipes', {}).get('house', {}).get('coins', 0.)
    reserve = (house if step['step'] in ('house', 'carpentry') else 0.) + FOOD_RESERVE * local.get('food', 1.)
    spare = max(0., available.get('coins', 0.) - reserve)
    jobs = observation.get('municipality', {}).get('work_orders', [])
    out = []
    for resource in ORDER:
        required = step['materials'].get(resource, 0.)
        missing = math.ceil(required - available.get(resource, 0.) - 1e-9)
        if missing < 1:
            continue
        price = local.get(resource, 1.)
        fair = willingness(observation, resource)
        supply = math.floor(deposits.get(resource, 0.) + 1e-9)
        wage = offered_wage(price)
        pending = sum(o['remaining'] for o in jobs if o['employer'] == {'kind': 'person', 'id': me}
                      and o['resource'] == resource and o.get('status', 'open') == 'open')
        # Retail sells at most eight units an action, from the market's stock.
        units = min(8, missing, math.floor(town.get(resource, 0.) + 1e-9))
        offer = None
        if 'trading' in skills:
            # v0.9 Stage 3: between fair offers, a little more is worth paying to deal with someone trusted,
            # and nobody buys from someone they distrust.
            trust = actor.get('trust', {})
            for standing in sorted(observation.get('market', []),
                                   key=lambda o: (o['unit_price'] - TRUST_PREMIUM * max(0., trust_in(trust, o['actor'])),
                                                  o['id'])):
                if (standing['direction'] != 'sell' or standing['resource'] != resource or standing['actor'] == me
                        or not standing['created'] < tick < standing['expires'] or standing['unit_price'] > fair + 1e-9
                        or trust_in(trust, standing['actor']) <= WARY):
                    continue
                take = min(missing - pending, standing['amount'], math.floor((spare + 1e-9) / standing['unit_price']))
                if take >= 1:
                    offer = dict(id=standing['id'], actor=standing['actor'], unit_price=standing['unit_price'], units=take)
                break  # the best fair offer decides
        out.append(dict(resource=resource, amount=missing, step=step['step'],
                        gather=SKILLS[resource] in skills and supply >= 1,
                        buy=units >= 1 and price <= fair + 1e-9 and spare + 1e-9 >= units * price,
                        fair=fair, offer=offer, pending=pending, spare=spare,
                        supply=supply, price=price, bid=bid_price(price), wage=wage,
                        hire=min(missing, supply, 24, math.floor((spare + 1e-9) / wage))))
    return out


def opening(observation, *, hiring=True):
    """How a person would close their most pressing need they cannot meet themselves, or None.

    In order: a neighbor's standing offer to sell it at a fair price, which they
    take up at once; otherwise, if they may post a job (one open job at a time),
    paid work. A job is posted only when someone else could gather the goods here
    (the deposits exist) and they can pay at least one unit's wage. A need they can
    gather themselves or buy now at a fair price is left to that. A food reserve is
    put out as work only when food is dearer than its base price.
    """
    prices = observation.get('prices') or {}
    base = prices.get('base', {})
    for need in needs(observation):
        if need['gather'] or need['buy']:
            continue
        if need['offer']:
            return dict(need, route='accept', quantity=need['offer']['units'])
        if not hiring or need['hire'] < 1 or need['pending']:
            continue
        if need['resource'] == 'food' and need['price'] <= base.get('food', 1.):
            continue
        return dict(need, route='hire', quantity=need['hire'])
    return None


def unmet(observation):
    """The needs a person knows they cannot meet themselves right now, as they would describe them.

    Keyed by (resource, step): the units missing, the step, the most they would
    pay a unit (if they can afford one), and the job they have posted for it.
    These become what they know and may tell others (``social_memory.note_needs``).
    """
    me = observation['actor']['id']
    jobs = observation.get('municipality', {}).get('work_orders', [])
    out = {}
    for need in needs(observation):
        if need['gather'] or need['buy'] or need['offer']:
            continue
        job = next((o for o in jobs if o['employer'] == {'kind': 'person', 'id': me}
                    and o['resource'] == need['resource']), None)
        out[(need['resource'], need['step'])] = dict(
            resource=need['resource'], amount=need['amount'], step=need['step'],
            # The most they would pay, or as much of it as they could, once they can pay a fair price.
            price=(round(min(need['fair'], need['spare']), 2)
                   if need['spare'] + 1e-9 >= FAIR_LIMIT * base_of(observation, need['resource']) else None),
            wage=job['unit_wage'] if job else None, job=job['id'] if job else None)
    return out


def trust_in(trust, person):
    return trust.get(person, trust.get(str(person), 0.))


def kindness(actor, person):
    """How far below the market a person would go to meet someone's need: more for someone they trust,
    and more the more they care about belonging; never more than 30%."""
    belonging = (actor.get('mind') or {}).get('motivations', {}).get('belonging', .4)
    return round(min(KINDNESS_LIMIT, .4 * max(0., trust_in(actor.get('trust', {}), person))
                     + .5 * max(0., belonging - .4)), 4)


def _losses(observation, town):
    """Shipments to or from a neighboring town lost lately: one's own in full, others' heard of at half weight."""
    actor, tick = observation['actor'], observation.get('tick', 0)
    lost = 0.
    for memory in actor.get('memory', []):
        if (memory.get('kind') in ('consignment', 'procurement') and memory.get('gain', 0) < 0
                and memory.get('destination', memory.get('source')) == town and tick - memory.get('tick', -100) <= LOSS_MEMORY):
            lost += 1
    for claim in actor.get('claims', []):
        facts = claim.get('facts', {})
        if (claim.get('kind') == 'shipment' and facts.get('outcome') == 'lost' and claim.get('subject') != actor['id']
                and facts.get('destination') == town and tick - claim.get('observed', -100) <= LOSS_MEMORY):
            lost += HEARD_LOSS * claim.get('confidence', 1.)
    return lost


def _fetch(observation, resource, wanted, spare):
    """v0.9 Stage 3: the best purchase of a good at a neighboring market, carried home, for needs heard of here.

    ``wanted`` lists (units, price, confidence) for each need. The goods and the
    provisions for the road are paid for at that market's posted prices when the
    caravan leaves; each need is worth its price only if the caravan arrives and
    the news was true. It must be expected to earn ``FETCH_GAIN`` coins beyond
    its cost, more after recent losses on that road, like a shipment.
    """
    posted = (observation.get('prices') or {}).get('posted') or {}
    paths = observation.get('physical', {}).get('paths', {})
    best = None
    for neighbor in observation.get('neighbors', []):
        there = posted.get(neighbor['id'], posted.get(str(neighbor['id'])))
        path = paths.get(neighbor['id'], paths.get(str(neighbor['id'])))
        if not there or not path or resource not in there:
            continue
        ask, food, supplies = there[resource], there.get('food', 1.), path.get('supplies', 0.)
        stock = neighbor.get(resource, 0.) - (supplies if resource == 'food' else 0.)
        units = min(8, sum(n for n, _, _ in wanted), math.floor(path.get('capacity', 0.) - supplies + 1e-9),
                    math.floor(stock + 1e-9), math.floor((spare - supplies * food + 1e-9) / ask) if ask > 0 else 0)
        if units < 1 or neighbor.get('food', 0.) + 1e-9 < supplies + (units if resource == 'food' else 0):
            continue
        risk, left, worth = min(1., max(0., path.get('risk', 0.))), units, 0.
        for amount, price, confidence in sorted(wanted, key=lambda w: -w[1] * w[2]):
            take = min(amount, left)
            worth, left = worth + take * price * confidence, left - take
        cost = units * ask + supplies * food
        gain = round((1 - risk) * worth - cost, 2)
        required = FETCH_GAIN * (1 + 2 * _losses(observation, neighbor['id']))
        if gain + 1e-9 >= required and (best is None or gain > best['gain']):
            best = dict(source=neighbor['id'], source_name=neighbor.get('name'), units=units, unit_price=ask,
                        cost=round(cost, 2), duration=path.get('duration'), risk=round(risk, 4), gain=gain)
    return best


def prospects(observation):
    """v0.9 Stage 3: needs the person has heard of, judged as chances to help, from what they know and can do.

    Each heard need is weighed on:
    ``capability``     goods they can spare beyond their own goal and meals, the skill and local deposits to
                       gather some, or, for a merchant, the coins to buy them at a neighboring market and have
                       them carried here;
    ``profitability``  the price the needy person said they would pay, against what selling the same goods to
                       the market here would bring (if the market can pay), less the kindness they feel; goods
                       fetched from elsewhere must also cover their price there, the road and its risk;
    ``relationships``  no dealing with someone they distrust; more kindness toward someone they trust; less
                       faith in what someone says they need after leaving one's own offers to them untaken;
    ``risk``           news that is too old, was corrected, or comes with no price the buyer could pay; buyers
                       who are not here, who are already paying for the work, or whom they have heard someone
                       else supplied, are passed over; less certain news is worth less (``expected``).
    Each entry has a ``route`` (``offer`` goods they hold, ``gather`` some first, or ``fetch`` them from a
    neighboring market, with the ``fetch`` plan) with the ``units`` and the coins it is ``expected`` to bring
    beyond the market, or a ``reason`` to decline.
    """
    actor, town = observation['actor'], observation['settlement']
    me, tick = actor['id'], observation.get('tick', 0)
    prices = observation.get('prices') or {}
    local = (prices.get('posted') or {}).get(prices.get('home'), {}) or observation.get('rules', {}).get('prices', {})
    if not local:
        return []
    peers = {p['id']: p for p in observation.get('peers', [])}
    available = actor.get('available_inventory', actor['inventory'])
    skills, energy = set(actor.get('skills', [])), actor.get('energy', 100)
    deposits, treasury = town.get('deposits', {}), town.get('treasury', 0.)
    step = step_of(observation)
    keep = dict(step['materials']) if step else {}
    keep['food'] = max(keep.get('food', 0.), FOOD_RESERVE)
    house = observation.get('rules', {}).get('recipes', {}).get('house', {}).get('coins', 0.)
    spare = max(0., available.get('coins', 0.) - (house if step and step['step'] in ('house', 'carpentry') else 0.)
                - FOOD_RESERVE * local.get('food', 1.))
    market = [o for o in observation.get('market', []) if o['direction'] == 'sell']
    selling = [o for o in market if o['actor'] == me]
    jobs = observation.get('municipality', {}).get('work_orders', [])
    claims = actor.get('claims', [])
    supplies = [c for c in claims if c['kind'] == 'conduct' and c['facts'].get('act') == 'supplied']
    coming = {}
    for journey in actor.get('incoming', []):
        for resource, amount in journey['cargo'].items():
            coming[resource] = coming.get(resource, 0.) + amount
    # v0.9 Stage 4: goods I gathered or fetched for someone's need lately, and when I had them in hand.
    pledged = {}
    for memory in actor.get('memory', []):
        action, result = memory.get('action') or {}, memory.get('result') or {}
        purpose = (action.get('params') or {}).get('purpose') if action else memory.get('purpose')
        if not isinstance(purpose, dict) or purpose.get('kind') != 'need':
            continue
        if action and not (result.get('success') and action.get('type') in ('gather', 'procure')):
            continue
        resource = action['params'].get('resource') if action else memory.get('resource')
        if tick - memory.get('tick', -100) <= FOLLOW_THROUGH:
            key = (purpose['subject'], resource)
            pledged[key] = max(pledged.get(key, -1), memory['tick'])
    untaken = {}  # people who left my own offers for their needs untaken lately
    for claim in claims:
        if (claim['kind'] == 'need' and claim['facts'].get('gone') and claim.get('origin') == me
                and tick - claim['observed'] <= 2 * STALE):
            untaken[claim['subject']] = untaken.get(claim['subject'], 0) + 1
    out, seen, unsupplied = [], set(), {}
    for claim in sorted(claims, key=lambda c: (-c['observed'], str(c['key']))):
        if claim['kind'] != 'need' or claim.get('subject') == me:
            continue
        facts, subject = claim['facts'], claim['subject']
        resource, price = facts.get('resource'), facts.get('price')
        if (subject, resource) in seen:
            continue
        seen.add((subject, resource))
        doubt = untaken.get(subject, 0) if not facts.get('gone') else 0
        # Having gathered or fetched the goods for this news, I hold to it until I offer them, for a while.
        committed = (subject, resource) in pledged and pledged[(subject, resource)] >= claim['observed']
        entry = dict(subject=subject, name=claim.get('subject_name'), resource=resource, amount=facts.get('amount', 0),
                     step=facts.get('step'), price=price, age=tick - claim['observed'],
                     confidence=round(claim['confidence'] * .5 ** doubt, 4), doubt=doubt, committed=committed,
                     source=claim.get('source_name'), route=None, units=0, reason=None, code=None)
        out.append(entry)
        trust = trust_in(actor.get('trust', {}), subject)
        if facts.get('gone'):
            entry.update(code='corrected', reason='they did not take up an offer; they may no longer need it')
            continue
        if entry['age'] > STALE and not committed:
            entry.update(code='too_old', reason='the news is too old to act on')
            continue
        if subject not in peers:
            entry.update(code='absent', reason='they are not here')
            continue
        if price is None:
            entry.update(code='no_price', reason='they said nothing they could pay')
            continue
        if trust <= WARY:
            entry.update(code='distrust', reason='I do not trust them')
            continue
        if any(o['resource'] == resource and (o.get('purpose') or {}).get('subject') == subject for o in selling):
            entry.update(code='already_offered', reason='I already have it on offer to them')
            continue
        # What I have heard since, or can see posted: someone supplied them, they are paying for the
        # work, or someone else has already offered them the goods.
        given = [c for c in supplies if c['facts'].get('buyer') == subject and c['facts'].get('resource') == resource
                 and c['facts'].get('step') == entry['step'] and c['observed'] >= claim['observed']]
        hired = sum(o['remaining'] for o in jobs if o['employer'] == {'kind': 'person', 'id': subject}
                    and o['resource'] == resource)
        offered = [o for o in market if o['actor'] != me and o['resource'] == resource
                   and (o.get('purpose') or {}).get('subject') == subject]
        wanted = (entry['amount'] - sum(c['facts'].get('amount', 0) for c in given) - hired
                  - sum(o['amount'] for o in offered))
        if wanted < 1:
            entry.update(code='supplied' if given else 'hired' if hired else 'offered_by_others',
                         reason=(f'I heard {given[0]["subject_name"]} supplied them' if given
                                 else 'they are paying someone to gather it' if hired
                                 else 'someone else has offered it to them'))
            continue
        bid = bid_price(local.get(resource, 1.))
        market_can_pay = math.floor((treasury + 1e-9) / bid) >= 1 if bid > 0 else False
        reservation = bid if market_can_pay else 0.
        entry.update(market=bid if market_can_pay else None, kindness=kindness(actor, subject))
        floor_price = round(reservation * (1 - entry['kindness']), 2)
        if price + 1e-9 < floor_price or (price <= reservation + 1e-9 and not entry['kindness']):
            entry.update(code='market_pays_more', reason=(
                f'the market pays {bid:g} for {resource}, '
                f'{"more than" if price + 1e-9 < bid else "as much as"} the {price:g} they would pay'))
            continue
        entry['gain'] = round(price - reservation, 4)
        surplus = math.floor(available.get(resource, 0.) - keep.get(resource, 0.) + 1e-9)
        gatherable = (min(8, math.floor(deposits.get(resource, 0.) + 1e-9), math.floor(energy / 2))
                      if SKILLS[resource] in skills else 0)
        if surplus >= 1:
            if selling:
                entry.update(code='other_offer', reason='I already have goods on offer')  # one standing offer to sell at a time
                continue
            entry.update(route='offer', units=min(wanted, surplus))
        elif coming.get(resource, 0.) >= 1:
            entry.update(code='on_the_way', reason=f'I have {coming[resource]:g} {resource} on the way here')
            continue
        elif gatherable >= 1:
            # Gather enough that, keeping what I need myself, some is left to offer them.
            units = min(gatherable, math.ceil(keep.get(resource, 0.) + wanted - available.get(resource, 0.) - 1e-9))
            if available.get(resource, 0.) + units - keep.get(resource, 0.) < 1 - 1e-9:
                entry.update(code='no_goods', reason=f'I would need all the {resource} I could gather myself')
                continue
            entry.update(route='gather', units=units)
        else:
            entry.update(code='no_goods', reason=f'I have no {resource} to spare and cannot gather it here')
            unsupplied.setdefault(resource, []).append((entry, wanted))
            continue
        entry['expected'] = round(entry['confidence'] * entry['units'] * entry['gain'], 2)
    # A merchant may buy goods nobody here can spare or gather at a neighboring market, for every need
    # for them heard of here, as merchants alone arrange shipments between towns; never while short of
    # the same goods for their own goal.
    merchant = actor.get('role') == 'merchant' or (actor.get('goal') or {}).get('kind') == 'profit'
    if 'trading' in skills and merchant and not actor.get('journey'):
        for resource, group in sorted(unsupplied.items()):
            if available.get(resource, 0.) + 1e-9 < keep.get(resource, 0.):
                for entry, _ in group:
                    entry.update(code='no_goods', reason=f'I need {resource} myself first')
                continue
            plan = _fetch(observation, resource, [(w, e['price'], e['confidence']) for e, w in group], spare)
            if plan is None:
                for entry, _ in group:
                    entry.update(code='fetch_would_not_pay',
                                 reason=entry['reason'] + ', and bringing it from another town would not pay')
                continue
            for entry, wanted in group:
                entry.update(route='fetch', units=min(wanted, plan['units']), fetch=plan, reason=None, code=None,
                             expected=plan['gain'])
    return out
