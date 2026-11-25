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
FAIR_LIMIT = 1.5      # a goal's materials are worth buying up to 1.5x their base price
FOOD_RESERVE = 3      # meals a person keeps before spending on anything else
ORDER = ('iron', 'wood', 'food')  # the order needs are weighed in


def step_of(observation):
    """The next step of the observed person's goal, or None."""
    actor = observation['actor']
    available = actor.get('available_inventory', actor['inventory'])
    return next_step(actor.get('goal', {}), skills=actor.get('skills', []), structures=actor.get('structures', {}),
                     knowledge=actor.get('knowledge', 0), food=available.get('food', 0.),
                     recipes=observation.get('rules', {}).get('recipes', {}))


def needs(observation):
    """What the next step toward the person's goal lacks, with the ways they could close each gap.

    Each need names the resource, the units missing, the step it blocks, and:
    ``gather``  whether they could gather some here themselves (skill and accessible deposits);
    ``buy``     whether they could buy it now: stocked, at a fair price, and affordable;
    ``fair``    the most they would pay a unit: a fair price, 1.5 times the base;
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
        fair = round(FAIR_LIMIT * base.get(resource, price), 2)
        supply = math.floor(deposits.get(resource, 0.) + 1e-9)
        wage = offered_wage(price)
        pending = sum(o['remaining'] for o in jobs if o['employer'] == {'kind': 'person', 'id': me}
                      and o['resource'] == resource and o.get('status', 'open') == 'open')
        # Retail sells at most eight units an action, from the market's stock.
        units = min(8, missing, math.floor(town.get(resource, 0.) + 1e-9))
        offer = None
        if 'trading' in skills:
            for standing in sorted(observation.get('market', []), key=lambda o: (o['unit_price'], o['id'])):
                if (standing['direction'] != 'sell' or standing['resource'] != resource or standing['actor'] == me
                        or not standing['created'] < tick < standing['expires'] or standing['unit_price'] > fair + 1e-9):
                    continue
                take = min(missing - pending, standing['amount'], math.floor((spare + 1e-9) / standing['unit_price']))
                if take >= 1:
                    offer = dict(id=standing['id'], actor=standing['actor'], unit_price=standing['unit_price'], units=take)
                break  # the cheapest fair offer decides
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
            price=need['fair'] if need['spare'] + 1e-9 >= need['fair'] else None,
            wage=job['unit_wage'] if job else None, job=job['id'] if job else None)
    return out
