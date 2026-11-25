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
    available = actor.get('available_inventory', actor['inventory'])
    skills, deposits = set(actor.get('skills', [])), town.get('deposits', {})
    # Keep a few meals, and while a house is the goal, the coins the house itself will cost.
    house = observation.get('rules', {}).get('recipes', {}).get('house', {}).get('coins', 0.)
    reserve = (house if step['step'] in ('house', 'carpentry') else 0.) + FOOD_RESERVE * local.get('food', 1.)
    spare = max(0., available.get('coins', 0.) - reserve)
    out = []
    for resource in ORDER:
        required = step['materials'].get(resource, 0.)
        missing = math.ceil(required - available.get(resource, 0.) - 1e-9)
        if missing < 1:
            continue
        price = local.get(resource, 1.)
        supply = math.floor(deposits.get(resource, 0.) + 1e-9)
        wage = offered_wage(price)
        # Retail sells at most eight units an action, from the market's stock.
        units = min(8, missing, math.floor(town.get(resource, 0.) + 1e-9))
        out.append(dict(resource=resource, amount=missing, step=step['step'],
                        gather=SKILLS[resource] in skills and supply >= 1,
                        buy=units >= 1 and price <= FAIR_LIMIT * base.get(resource, price)
                        and spare + 1e-9 >= units * price,
                        supply=supply, price=price, bid=bid_price(price), wage=wage,
                        hire=min(missing, supply, 24, math.floor((spare + 1e-9) / wage))))
    return out


def opening(observation):
    """The job a person would post for their most pressing need they cannot close themselves, or None.

    A need is offered as work only when the person can neither gather it here nor
    buy it now at a fair price (buying is quicker), someone else could gather it
    (the deposits exist), and they can pay at least one unit's wage. A food
    reserve is put out as work only when food is dearer than its base price.
    """
    prices = observation.get('prices') or {}
    base = prices.get('base', {})
    for need in needs(observation):
        if need['gather'] or need['buy'] or need['hire'] < 1:
            continue
        if need['resource'] == 'food' and need['price'] <= base.get('food', 1.):
            continue
        return dict(need, quantity=need['hire'])
    return None
