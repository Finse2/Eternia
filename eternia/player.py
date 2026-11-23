"""v0.8: what a human player sees and can do.

A player is an ordinary person in the world. Everything here is built from the
player's own observation, the same detached view every autonomous person
receives: their inventory and needs, posted prices, public job notices, local
organizations and recent local events. Nothing reveals another person's private
holdings or the hidden world state.

Choices are proposals, exactly like an autonomous person's. Each listed option
passes the world's own dry-run validation at the start of the cycle; the cycle
itself can still turn it down, for example if a neighbor claims the last units.
"""
import math

GOODS = ('food', 'wood', 'iron')


def _proposal(player, kind, **params):
    return {'actor': player, 'type': kind, 'params': params}


def situation(observation):
    """Plain-text lines describing the player's circumstances."""
    actor, town = observation['actor'], observation['settlement']
    inventory = actor['inventory']
    lines = [f'Year {observation.get("year", 0)}, cycle {observation.get("tick", 0)}. '
             f'You are {actor["name"]}, living in {town["name"]}.',
             'Food {food:g} | Wood {wood:g} | Iron {iron:g} | Coins {coins:.2f}'.format(**inventory)
             + f' | Hunger {actor.get("hunger", 0):.0f}/100 | Energy {actor.get("energy", 100):.0f}/100',
             'Skills: ' + ', '.join(actor.get('skills', []))]
    hunger = actor.get('hunger', 0)
    if hunger >= 100:
        lines.append('You are starving. Eat soon: two years without food is fatal, for you as for anyone.')
    elif hunger >= 60:
        lines.append('You are getting hungry; hunger rises every season until you eat.')
    prices = observation.get('prices', {}).get('posted', {}).get(town['id'])
    if prices:
        share = observation['prices'].get('bid_share', .8)
        lines.append('Market here (buy / sell): ' + ' | '.join(
            f'{good} {prices[good]:g} / {round(prices[good] * share, 2):g}' for good in GOODS))
    jobs = observation.get('municipality', {}).get('work_orders', [])
    for order in jobs:
        lines.append(f'Job {order["id"]}: {order["remaining"]} {order["resource"]} at {order["unit_wage"]:g} coins each')
    memberships = set(observation.get('memberships', []))
    for institution in observation.get('institutions', []):
        if institution.get('settlement_id') == town['id'] and institution.get('active', True):
            mark = ' (member)' if institution['id'] in memberships else ''
            lines.append(f'Organization: {institution["name"]}, a {institution.get("purpose", "group")} '
                         f'of {len(institution.get("members", []))}{mark}')
    return lines


def candidate_actions(observation):
    """(label, proposal) pairs a player might reasonably take, before validation."""
    actor, town = observation['actor'], observation['settlement']
    player, inventory = actor['id'], actor.get('available_inventory', actor['inventory'])
    energy, hunger = actor.get('energy', 100), actor.get('hunger', 0)
    deposits = town.get('deposits', {})
    out = [('Wait and watch what happens', _proposal(player, 'wait'))]
    if inventory.get('food', 0) >= 1 and hunger > 0:
        out.append(('Eat a meal', _proposal(player, 'eat')))
    if energy < 100:
        out.append(('Rest', _proposal(player, 'rest')))
    for good in GOODS:
        amount = min(8, math.floor(deposits.get(good, 0)), math.floor(energy / 2))
        if amount >= 1:
            out.append((f'Gather {amount} {good} ({amount * 2} energy)',
                        _proposal(player, 'gather', resource=good, amount=amount)))
    prices = observation.get('prices', {}).get('posted', {}).get(town['id'], {})
    share = observation.get('prices', {}).get('bid_share', .8)
    for good in GOODS:
        if good not in prices:
            continue
        buy = min(8, math.floor(town.get(good, 0)), math.floor((inventory.get('coins', 0) + 1e-9) / prices[good]))
        if buy >= 1:
            out.append((f'Buy {buy} {good} at {prices[good]:g} each',
                        _proposal(player, 'trade', resource=good, amount=buy, direction='buy')))
        sell = min(8, math.floor(inventory.get(good, 0) + 1e-9))
        if sell >= 1:
            out.append((f'Sell {sell} {good} at {round(prices[good] * share, 2):g} each',
                        _proposal(player, 'trade', resource=good, amount=sell, direction='sell')))
    for order in observation.get('municipality', {}).get('work_orders', []):
        amount = min(8, order['remaining'], math.floor(deposits.get(order['resource'], 0)), math.floor(energy / 2))
        if amount >= 1:
            out.append((f'Work job {order["id"]}: deliver {amount} {order["resource"]} for '
                        f'{amount * order["unit_wage"]:g} coins', _proposal(player, 'work', order=order['id'], amount=amount)))
    memberships = set(observation.get('memberships', []))
    for institution in observation.get('institutions', []):
        if institution.get('settlement_id') != town['id'] or not institution.get('active', True):
            continue
        if institution['id'] not in memberships:
            out.append((f'Join {institution["name"]}', _proposal(player, 'join_institution', institution=institution['id'])))
            continue
        for decision in institution.get('decisions', []):
            if (decision.get('status') == 'open' and player in decision.get('electorate', [])
                    and str(player) not in {str(v) for v in decision.get('votes', {})}):
                for approve, word in ((True, 'for'), (False, 'against')):
                    out.append((f'Vote {word} {decision["kind"].replace("_", " ")} {decision["id"]} in {institution["name"]}',
                                _proposal(player, 'vote', institution=institution['id'], proposal=decision['id'],
                                          approve=approve)))
    for neighbor in observation.get('neighbors', []):
        out.append((f'Move to {neighbor["name"]}', _proposal(player, 'migrate', destination=neighbor['id'])))
    return out


def options(world, player):
    """Choices that pass the world's dry-run validation right now; validation never changes the world."""
    observation = world.observe(player)
    return [dict(label=label, proposal=proposal) for label, proposal in candidate_actions(observation)
            if world.action_engine.validate(proposal).success]
