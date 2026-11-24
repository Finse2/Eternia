"""v0.8: what a human player sees and can do.

A player is an ordinary person in the world. Everything here is built from the
player's own observation, the same detached view every autonomous person
receives: their inventory and needs, posted prices, public job notices, local
offers, organizations and their open proposals. Nothing reveals another
person's private holdings, goals or feelings.

Choices are proposals, exactly like an autonomous person's. A menu entry offers
a default proposal and, where it makes sense, fields the player can change: an
amount, a price, a wage, a name. Entries whose rules read only public facts or
the player's own state are checked against the world's dry-run validation at the
start of the cycle. Entries that depend on someone else's private circumstances
(whether a neighbor still has the goods they offered, wants help, or trusts you)
are offered from public information alone and marked as such: the cycle decides.
"""
from copy import deepcopy
import math

from .market import CONSIGNMENT_LIMIT, bid_price, offered_wage

GOODS = ('food', 'wood', 'iron')
SKILL_FOR = {'food': 'foraging', 'wood': 'woodcutting', 'iron': 'mining'}
PURPOSE_LABELS = {'cooperative': 'Cooperative', 'guild': 'Guild', 'council': 'Council'}
RECIPES = {'house': {'wood': 12., 'iron': 2., 'coins': 8.}, 'workshop': {'wood': 18., 'iron': 6., 'coins': 15.}}
GRANARY_COSTS = {'wood': 10., 'iron': 2., 'coins': 6.}
# Their outcome depends on another person's private state, which a player cannot check in advance.
UNCHECKED = {'accept', 'teach', 'collaborate'}
SECTIONS = ('Needs', 'Work', 'Market', 'Trade and hiring', 'Building and learning',
            'Organizations', 'Politics', 'Travel')


def money(value):
    return f'{round(value, 2):g}'


def _field(name, low, high, default, kind='int', label=None, nested=False):
    return dict(name=name, label=label or name.replace('_', ' '), kind=kind, low=low, high=high,
                default=default, nested=nested)


def _choice(section, label, player, kind, params=None, fields=(), checked=None):
    return dict(section=section, label=label, fields=list(fields),
                checked=kind not in UNCHECKED if checked is None else checked,
                proposal={'actor': player, 'type': kind, 'params': deepcopy(params or {})})


def customize(choice, text=''):
    """The choice's proposal with the player's values for its fields, in order."""
    proposal = deepcopy(choice['proposal'])
    fields, text = choice['fields'], (text or '').strip()
    if not text:
        return proposal
    if not fields:
        raise ValueError('This choice has nothing to change.')
    if fields[0]['kind'] == 'text':
        values = [text]
    else:
        values = text.split()
        if len(values) > len(fields):
            raise ValueError('This choice takes ' + ', '.join(f['label'] for f in fields) + '.')
    for field, raw in zip(fields, values):
        if field['kind'] == 'text':
            value = raw.strip()
            if not 0 < len(value) <= field['high']:
                raise ValueError(f'The {field["label"]} must be 1 to {field["high"]} characters.')
        else:
            try:
                value = int(raw) if field['kind'] == 'int' else round(float(raw), 2)
            except ValueError:
                raise ValueError(f'The {field["label"]} must be a {"whole " if field["kind"] == "int" else ""}number.') from None
            if not (math.isfinite(value) and field['low'] <= value <= field['high']):
                raise ValueError(f'The {field["label"]} must be from {money(field["low"])} to {money(field["high"])}.')
        target = proposal['params']['params'] if field['nested'] else proposal['params']
        target[field['name']] = value
    return proposal


def hint(choice):
    """How a choice's fields can be changed, for the menu."""
    parts = []
    for field in choice['fields']:
        if field['kind'] == 'text':
            parts.append(f'{field["label"]}: any text')
        else:
            parts.append(f'{field["label"]} {money(field["low"])}-{money(field["high"])}')
    return ('[' + ', '.join(parts) + ']') if parts else ''


# ----- Describing the world in words -------------------------------------

def _names(observation):
    towns = {observation['settlement']['id']: observation['settlement']['name']}
    towns.update({n['id']: n['name'] for n in observation.get('neighbors', [])})
    people = {p['id']: p['name'] for p in observation.get('peers', [])}
    people[observation['actor']['id']] = 'you'
    institutions = {i['id']: i['name'] for i in observation.get('institutions', [])}
    return towns, people, institutions


def employer_name(employer, observation):
    towns, people, institutions = _names(observation)
    kind, identity = employer.get('kind'), employer.get('id')
    if kind == 'municipal':
        return f'the {towns.get(identity, "town")} council'
    if kind == 'institution':
        return institutions.get(identity, 'an organization')
    return people.get(identity, 'a private employer')


def describe_decision(decision, observation):
    """A proposal in plain words."""
    towns, people, _ = _names(observation)
    kind, params = decision['kind'], decision.get('params', {})
    if kind == 'tax_rate':
        return 'ending the levy' if not params.get('value') else f'a levy of {params["value"]:.0%} of members\' coins'
    if kind == 'communal_labor':
        return f'communal labor of {params.get("value", 0):.0%}'
    if kind == 'granary':
        return 'building a communal granary'
    if kind == 'distribute_food':
        if params.get('destination') == 'member':
            return f'{money(params["amount"])} food for {people.get(params.get("member"), "a member")}'
        return f'releasing {money(params["amount"])} food to the town'
    if kind in ('work_order', 'commission'):
        label = 'public work' if kind == 'work_order' else 'a paid commission'
        return f'{label}: {params["quantity"]} {params["resource"]} at {money(params["unit_wage"])} each'
    if kind == 'trade_terms':
        verb, preposition = ('exporting', 'to') if params['direction'] == 'export' else ('importing', 'from')
        return (f'{verb} {params["resource"]} {preposition} {towns.get(params["destination"], "a neighbor")}: '
                f'up to {params["quota"]} at {money(params["unit_price"])} each')
    if kind == 'embargo':
        place = towns.get(params.get('destination'), 'a neighbor')
        return f'an embargo on {place}' if params.get('enabled') else f'lifting the embargo on {place}'
    if kind == 'specialization':
        return f'specializing in {params.get("resource")}'
    if kind == 'migration_policy':
        return 'opening the town to newcomers' if params.get('open') else 'closing the town to newcomers'
    if kind == 'repair_route':
        return f'repairing road {params.get("link")}'
    if kind == 'route_access':
        return f'{"closing" if params.get("closed") else "reopening"} road {params.get("link")}'
    return kind.replace('_', ' ')


def tally(decision):
    votes = decision.get('votes', {}).values()
    yes = sum(v.get('approve') is True for v in votes)
    return yes, sum(v.get('approve') is False for v in votes)


def situation(observation):
    """Plain-text lines describing the player's circumstances."""
    actor, town = observation['actor'], observation['settlement']
    me, tick = actor['id'], observation.get('tick', 0)
    inventory = actor['inventory']
    lines = [f'Year {observation.get("year", 0)}, cycle {tick}. You are {actor["name"]}, living in {town["name"]}.',
             'Food {food:g} | Wood {wood:g} | Iron {iron:g} | Coins {coins:.2f}'.format(**inventory)
             + f' | Hunger {actor.get("hunger", 0):.0f}/100 | Energy {actor.get("energy", 100):.0f}/100',
             'Skills: ' + ', '.join(actor.get('skills', []))
             + (f' | Aether knowledge {actor["knowledge"]}' if actor.get('knowledge') else '')]
    lines.extend(_needs_advice(observation))
    prices = observation.get('prices', {}).get('posted', {})
    share = observation.get('prices', {}).get('bid_share', .8)
    if prices.get(town['id']):
        local = prices[town['id']]
        lines.append(f'Market here (buy / sell), stock: ' + ' | '.join(
            f'{good} {money(local[good])} / {money(local[good] * share)} ({money(town.get(good, 0))})' for good in GOODS)
            + f' | the market holds {money(town.get("treasury", 0))} coins')
    towns, people, _ = _names(observation)
    for neighbor in observation.get('neighbors', []):
        if neighbor['id'] in prices:
            there = prices[neighbor['id']]
            lines.append(f'{neighbor["name"]} buys at: ' + ' | '.join(
                f'{good} {money(there[good] * share)}' for good in GOODS))
    municipality = observation.get('municipality', {})
    for order in municipality.get('work_orders', []):
        mine = order['employer'] == {'kind': 'person', 'id': me}
        lines.append(f'Job {order["id"]} ({"yours" if mine else employer_name(order["employer"], observation)}): '
                     f'{order["remaining"]} of {order["quantity"]} {order["resource"]} left at '
                     f'{money(order["unit_wage"])} coins each')
    for order in municipality.get('job_board', []):
        if order['settlement'] != town['id']:
            lines.append(f'Job {order["id"]} in {towns.get(order["settlement"], "a neighbor")}: '
                         f'{order["remaining"]} {order["resource"]} at {money(order["unit_wage"])} each')
    for offer in observation.get('market', []):
        mine = offer['actor'] == me
        who = 'You' if mine else people.get(offer['actor'], 'A neighbor')
        lines.append(f'Offer {offer["id"]}: {who} {offer["direction"] if mine else offer["direction"] + "s"} '
                     f'{offer["amount"]} {offer["resource"]} at {money(offer["unit_price"])} each '
                     f'(until cycle {offer["expires"]})')
    memberships = set(observation.get('memberships', []))
    for institution in observation.get('institutions', []):
        if institution.get('settlement_id') != town['id'] or not institution.get('active', True):
            continue
        member = institution['id'] in memberships
        rules = institution.get('rules', {})
        note = f', levy {rules["tax_rate"]:.0%}' if rules.get('tax_rate') else ''
        if member:
            shared = institution.get('available_inventory', {})
            note += ' | shared: ' + ', '.join(f'{money(shared.get(r, 0))} {r}' for r in ('food', 'wood', 'iron', 'coins'))
        lines.append(f'{"Your organization" if member else "Organization"}: {institution["name"]}, a '
                     f'{institution.get("purpose", "group")} of {len(institution.get("members", []))}{note}')
        if member:
            for decision in institution.get('decisions', []):
                if decision.get('status') == 'open' and decision.get('expires', 0) > tick:
                    yes, no = tally(decision)
                    lines.append(f'  Proposal {decision["id"]}: {describe_decision(decision, observation)} '
                                 f'({yes} for, {no} against; open until cycle {decision["expires"]})')
    lines.extend(_building_advice(observation))
    return lines


def _needs_advice(observation):
    actor, lines = observation['actor'], []
    hunger = actor.get('hunger', 0)
    if hunger >= 100:
        lines.append('You are starving. Eat soon: two years without food is fatal, for you as for anyone.')
    elif hunger >= 60:
        lines.append('You are getting hungry; hunger rises every season until you eat.')
    if actor.get('journey'):
        lines.append('You are on the road and can only wait until you arrive.')
    return lines


def _building_advice(observation):
    actor = observation['actor']
    inventory = actor['inventory']
    if 'carpentry' not in actor.get('skills', []):
        return ['Building needs carpentry, which you can study (1 wood, 1 iron) or be taught.']
    if not actor.get('structures', {}).get('house'):
        lacking = {r: n - inventory.get(r, 0) for r, n in RECIPES['house'].items() if inventory.get(r, 0) < n}
        return ['A house needs 12 wood, 2 iron and 8 coins' + (
            '; you lack ' + ', '.join(f'{money(n)} {r}' for r, n in lacking.items()) if lacking else '; you have them') + '.']
    return []


def advice(observation):
    """The reminders the situation gives: hunger, the road, and what building needs."""
    return _needs_advice(observation) + _building_advice(observation)


# ----- What the player can choose -----------------------------------------

def _economy(observation, out):
    actor, town = observation['actor'], observation['settlement']
    me, tick = actor['id'], observation.get('tick', 0)
    have = actor.get('available_inventory', actor['inventory'])
    energy, hunger = actor.get('energy', 100), actor.get('hunger', 0)
    deposits = town.get('deposits', {})
    skills = set(actor.get('skills', []))
    out.append(_choice('Needs', 'Wait and watch what happens', me, 'wait'))
    if have.get('food', 0) >= 1 and hunger > 0:
        out.append(_choice('Needs', 'Eat a meal (1 food)', me, 'eat'))
    if energy < 100:
        out.append(_choice('Needs', 'Rest', me, 'rest'))
    for good in GOODS:
        amount = min(8, math.floor(deposits.get(good, 0)), math.floor(energy / 2))
        if amount >= 1 and SKILL_FOR[good] in skills:
            out.append(_choice('Work', f'Gather {amount} {good} (2 energy each)', me, 'gather',
                               {'resource': good, 'amount': amount}, [_field('amount', 1, amount, amount)]))
    for order in observation.get('municipality', {}).get('work_orders', []):
        amount = min(8, order['remaining'], math.floor(deposits.get(order['resource'], 0)), math.floor(energy / 2))
        if amount >= 1 and order['employer'] != {'kind': 'person', 'id': me}:
            out.append(_choice('Work', f'Work job {order["id"]} for {employer_name(order["employer"], observation)}: '
                                       f'deliver {amount} {order["resource"]} for {money(amount * order["unit_wage"])} coins',
                               me, 'work', {'order': order['id'], 'amount': amount}, [_field('amount', 1, amount, amount)]))

    prices = observation.get('prices', {}).get('posted', {})
    local = prices.get(town['id'], {})
    for good in GOODS:
        if good not in local:
            continue
        ask, bid = local[good], bid_price(local[good])
        buy = min(8, math.floor(town.get(good, 0)), math.floor((have.get('coins', 0) + 1e-9) / ask))
        if buy >= 1:
            out.append(_choice('Market', f'Buy {buy} {good} at {money(ask)} each ({money(buy * ask)} coins)', me, 'trade',
                               {'resource': good, 'amount': buy, 'direction': 'buy'}, [_field('amount', 1, buy, buy)]))
        sell = min(8, math.floor(have.get(good, 0) + 1e-9), math.floor((town.get('treasury', 0) + 1e-9) / bid))
        if sell >= 1:
            out.append(_choice('Market', f'Sell {sell} {good} at {money(bid)} each ({money(sell * bid)} coins)', me, 'trade',
                               {'resource': good, 'amount': sell, 'direction': 'sell'}, [_field('amount', 1, sell, sell)]))
    _, people, _ = _names(observation)
    for offer in observation.get('market', []):
        if offer['actor'] == me or not offer['created'] < tick < offer['expires'] or 'trading' not in skills:
            continue
        who, price = people.get(offer['actor'], 'a neighbor'), offer['unit_price']
        if offer['direction'] == 'sell':
            amount = min(offer['amount'], math.floor((have.get('coins', 0) + 1e-9) / price))
            label = f'Buy {amount} {offer["resource"]} from {who} at {money(price)} each (if they still have it)'
        else:
            amount = min(offer['amount'], math.floor(have.get(offer['resource'], 0) + 1e-9))
            label = f'Sell {amount} {offer["resource"]} to {who} at {money(price)} each (if they can still pay)'
        if amount >= 1:
            out.append(_choice('Market', label, me, 'accept', {'offer_id': offer['id'], 'amount': amount},
                               [_field('amount', 1, amount, amount)]))

    if 'trading' in skills and local:
        for good in GOODS:
            held = math.floor(have.get(good, 0) + 1e-9)
            if held >= 1:
                price = round(local[good] * .95, 2)
                out.append(_choice('Trade and hiring', f'Offer neighbors {held} {good} at {money(price)} each (for 4 cycles)',
                                   me, 'offer', {'resource': good, 'amount': held, 'direction': 'sell', 'unit_price': price},
                                   [_field('amount', 1, held, held), _field('unit_price', .1, 100, price, 'float', 'price')]))
            price = round(max(.1, (local[good] + bid_price(local[good])) / 2), 2)
            amount = min(8, math.floor((have.get('coins', 0) + 1e-9) / price))
            if amount >= 1:
                out.append(_choice('Trade and hiring', f'Offer to buy {amount} {good} from neighbors at {money(price)} each',
                                   me, 'offer', {'resource': good, 'amount': amount, 'direction': 'buy', 'unit_price': price},
                                   [_field('amount', 1, 1000, amount), _field('unit_price', .1, 100, price, 'float', 'price')]))
        paths = observation.get('physical', {}).get('paths', {})
        for neighbor in observation.get('neighbors', []):
            there, path = prices.get(neighbor['id']), paths.get(str(neighbor['id']), paths.get(neighbor['id']))
            if not there or not path:
                continue
            supplies = path.get('supplies', 0)
            for good in GOODS:
                held = have.get(good, 0) - (supplies if good == 'food' else 0)
                room = path.get('capacity', CONSIGNMENT_LIMIT) - supplies  # the road's public capacity
                amount = min(CONSIGNMENT_LIMIT, math.floor(held + 1e-9), math.floor(room + 1e-9))
                if amount < 1 or have.get('food', 0) + 1e-9 < supplies:
                    continue
                unit = bid_price(there[good])
                out.append(_choice('Trade and hiring',
                                   f'Ship {amount} {good} to {neighbor["name"]}\'s market for {money(unit)} each '
                                   f'({money(amount * unit)} coins on delivery in about {path["duration"]} cycles, '
                                   f'{money(supplies)} food for the road; here it sells for {money(bid_price(local[good]))})',
                                   me, 'consign', {'resource': good, 'amount': amount, 'destination': neighbor['id']},
                                   [_field('amount', 1, amount, amount)]))
    if local and not any(o['employer'] == {'kind': 'person', 'id': me} and o['status'] == 'open'
                         for o in observation.get('municipality', {}).get('work_orders', [])):
        for good in GOODS:
            wage = offered_wage(local[good])
            quantity = min(8, math.floor((have.get('coins', 0) + 1e-9) / wage))
            if quantity >= 1:
                out.append(_choice('Trade and hiring',
                                   f'Hire workers to gather {quantity} {good} for you at {money(wage)} each '
                                   f'({money(quantity * wage)} coins held in escrow until delivered)',
                                   me, 'hire', {'resource': good, 'quantity': quantity, 'unit_wage': wage},
                                   [_field('quantity', 1, 24, quantity), _field('unit_wage', .1, 5, wage, 'float', 'wage')]))

    if 'carpentry' not in skills:
        out.append(_choice('Building and learning', 'Study carpentry (1 wood, 1 iron)', me, 'research', {'topic': 'carpentry'}))
    if actor.get('knowledge', 0) < 2:
        out.append(_choice('Building and learning', 'Experiment with the Aether (1 wood, 1 iron)', me, 'research',
                           {'topic': 'aether'}))
    for structure, costs in RECIPES.items():
        out.append(_choice('Building and learning', f'Build a {structure} (' + ', '.join(
            f'{money(n)} {r}' for r, n in costs.items()) + ')', me, 'build', {'structure': structure}))
    for peer in observation.get('peers', []):
        if 'carpentry' in skills:
            out.append(_choice('Building and learning', f'Teach carpentry to {peer["name"]} (5 energy; if they want it)',
                               me, 'teach', {'target': peer['id'], 'topic': 'carpentry'}))
        if actor.get('knowledge', 0) >= 1:
            out.append(_choice('Building and learning', f'Share your Aether knowledge with {peer["name"]} (5 energy)',
                               me, 'teach', {'target': peer['id'], 'topic': 'aether'}))
        if peer.get('role') == 'builder' and peer.get('labor_credit', 0) < 15:
            out.append(_choice('Building and learning', f'Help {peer["name"]} build (5 energy; if they want help)',
                               me, 'collaborate', {'target': peer['id']}))


def _organizations(observation, out):
    actor, town = observation['actor'], observation['settlement']
    me, tick = actor['id'], observation.get('tick', 0)
    have = actor.get('available_inventory', actor['inventory'])
    memberships = set(observation.get('memberships', []))
    institutions = observation.get('institutions', [])
    local = [i for i in institutions if i.get('settlement_id') == town['id'] and i.get('active', True)]
    taken = {i['name'] for i in institutions}
    first = actor['name'].split()[0]
    for purpose, label in PURPOSE_LABELS.items():
        name = f'{town["name"]} {label} of {first}'
        number = 2
        while name in taken:
            name, number = f'{town["name"]} {label} of {first} {number}', number + 1
        out.append(_choice('Organizations', f'Found a {purpose} named "{name}" (2 coins, 2 energy)', me,
                           'form_institution', {'name': name, 'purpose': purpose},
                           [_field('name', 1, 64, name, 'text')]))
    for institution in local:
        identity, name = institution['id'], institution['name']
        if identity not in memberships:
            out.append(_choice('Organizations', f'Join {name}, a {institution.get("purpose", "group")} of '
                                                f'{len(institution.get("members", []))}', me, 'join_institution',
                               {'institution': identity}))
            continue
        out.append(_choice('Organizations', f'Leave {name}', me, 'leave_institution', {'institution': identity}))
        for resource in ('coins', 'food', 'wood', 'iron'):
            held = round(have.get(resource, 0), 2)
            if held >= .1:
                amount = round(min(held, 5.), 2)
                out.append(_choice('Organizations', f'Give {money(amount)} {resource} to {name}', me, 'contribute',
                                   {'institution': identity, 'resource': resource, 'amount': amount},
                                   [_field('amount', .1, held, amount, 'float')]))
        _politics(observation, institution, out)


def _politics(observation, institution, out):
    actor, town = observation['actor'], observation['settlement']
    me, tick = actor['id'], observation.get('tick', 0)
    identity, name, purpose = institution['id'], institution['name'], institution.get('purpose')
    council = purpose == 'council'
    for decision in institution.get('decisions', []):
        if decision.get('status') != 'open' or decision.get('expires', 0) <= tick:
            continue
        words, (yes, no) = describe_decision(decision, observation), tally(decision)
        voted = str(me) in {str(v) for v in decision.get('votes', {})}
        if me in decision.get('electorate', []) and not voted:
            for approve, side in ((True, 'for'), (False, 'against')):
                out.append(_choice('Politics', f'Vote {side} proposal {decision["id"]} in {name}: {words} '
                                               f'({yes} for, {no} against so far)', me, 'vote',
                                   {'institution': identity, 'proposal': decision['id'], 'approve': approve}))
        out.append(_choice('Politics', f'Carry out approved proposal {decision["id"]} in {name}: {words}', me, 'enact',
                           {'institution': identity, 'proposal': decision['id']}))

    def propose(label, kind, params, fields=()):
        out.append(_choice('Politics', f'Propose in {name}: {label}', me, 'propose',
                           {'institution': identity, 'kind': kind, 'params': params},
                           [dict(f, nested=True) for f in fields]))

    rate = institution.get('rules', {}).get('tax_rate', 0)
    if rate:
        propose(f'ending the levy (now {rate:.0%})', 'tax_rate', {'value': 0})
    propose('a levy of 5% of members\' coins each year' if not rate else 'a different levy', 'tax_rate',
            {'value': .05 if not rate else rate}, [_field('value', 0, .15, .05 if not rate else rate, 'float', 'rate')])
    shared = institution.get('available_inventory', {})
    food = math.floor(shared.get('food', 0) + 1e-9)
    if food >= 1:
        amount = min(3, food)
        propose(f'giving you {amount} food from the shared stores', 'distribute_food',
                {'destination': 'member', 'member': me, 'amount': amount}, [_field('amount', 1, food, amount)])
        propose(f'releasing {food} food to {town["name"]}', 'distribute_food',
                {'destination': 'settlement', 'amount': food}, [_field('amount', 1, food, food)])
    propose('building a communal granary (10 wood, 2 iron, 6 coins from shared holdings)', 'granary', {})
    prices = observation.get('prices', {}).get('posted', {})
    local = prices.get(town['id'], {})
    for good in GOODS:
        if good not in local:
            continue
        wage = offered_wage(local[good])
        if council:
            propose(f'public work: 8 {good} at {money(wage)} each, paid from the town treasury', 'work_order',
                    {'resource': good, 'quantity': 8, 'unit_wage': wage},
                    [_field('quantity', 1, 24, 8), _field('unit_wage', .1, 5, wage, 'float', 'wage')])
        else:
            propose(f'a commission: 8 {good} at {money(wage)} each, paid from shared coins', 'commission',
                    {'resource': good, 'quantity': 8, 'unit_wage': wage},
                    [_field('quantity', 1, 24, 8), _field('unit_wage', .1, 5, wage, 'float', 'wage')])
    if council:
        propose('communal labor of 10%', 'communal_labor', {'value': .1}, [_field('value', 0, .3, .1, 'float', 'share')])
        policies = observation.get('settlement_policies', {})
        for good in GOODS:
            if policies.get('specialization') != good:
                propose(f'specializing {town["name"]} in {good}', 'specialization', {'resource': good})
        open_now = policies.get('migration_open', True)
        propose('closing the town to newcomers' if open_now else 'reopening the town to newcomers',
                'migration_policy', {'open': not open_now})
    embargoes = institution.get('rules', {}).get('embargoes', {})
    for neighbor in observation.get('neighbors', []):
        blocked = embargoes.get(neighbor['id'], embargoes.get(str(neighbor['id']), False)) is True
        propose(f'lifting the embargo on {neighbor["name"]}' if blocked else
                f'an embargo on trade with {neighbor["name"]} (also stops private shipments between the towns)',
                'embargo', {'destination': neighbor['id'], 'enabled': not blocked})
        there = prices.get(neighbor['id'], {})
        if not council:
            continue
        for good in GOODS:
            if good not in there or good not in local:
                continue
            if there[good] > local[good] * 1.1:
                direction = 'export'
            elif there[good] < local[good] * .9:
                direction = 'import'
            else:
                continue
            price = round((there[good] + local[good]) / 2, 2)
            words = f'exporting {good} to' if direction == 'export' else f'importing {good} from'
            propose(f'{words} {neighbor["name"]}: up to 8 at {money(price)} each', 'trade_terms',
                    {'destination': neighbor['id'], 'resource': good, 'direction': direction,
                     'unit_price': price, 'quota': 8},
                    [_field('unit_price', .1, 20, price, 'float', 'price'), _field('quota', 1, 40, 8)])
    towns = {neighbor['id']: neighbor['name'] for neighbor in observation.get('neighbors', [])}
    for link in observation.get('physical', {}).get('links', []):
        if town['id'] not in (link['a'], link['b']):
            continue
        other = towns.get(link['b'] if link['a'] == town['id'] else link['a'], 'a neighbor')
        if link.get('owner') in (None, identity) and link.get('condition', 1) < .95:
            propose(f'repairing the {link["terrain"]} road to {other} (condition {link["condition"]:.0%})',
                    'repair_route', {'link': link['id']})
        if link.get('owner') == identity:
            propose(f'{"reopening" if link.get("closed") else "closing"} the road to {other}', 'route_access',
                    {'link': link['id'], 'closed': not link.get('closed')})


def _caravans(observation, out):
    """Contract caravans an organization you belong to may send; quotes are public."""
    me = observation['actor']['id']
    towns, _, institutions = _names(observation)
    routes = {r['id']: r for r in observation.get('regional', {}).get('routes', [])}
    for quote in observation.get('physical', {}).get('dispatch_options', []):
        route = routes.get(quote['route'], {})
        amount = quote['amount']
        out.append(_choice('Politics', f'Send a caravan of {money(amount)} {route.get("resource", "goods")} to '
                                       f'{towns.get(route.get("importer"), "the importer")} under contract {quote["route"]} '
                                       f'for {institutions.get(route.get("exporter_institution"), "your organization")} '
                                       f'at {money(route.get("unit_price", 0))} each ({money(quote["supplies"])} food for '
                                       f'the road, {quote["duration"]} cycles)', me, 'dispatch_caravan',
                           {'route': quote['route'], 'amount': amount},
                           [_field('amount', .1, amount, amount, 'float')]))


def _travel(observation, out):
    me = observation['actor']['id']
    board = observation.get('municipality', {}).get('job_board', [])
    paths = observation.get('physical', {}).get('paths', {})
    for neighbor in observation.get('neighbors', []):
        path = paths.get(str(neighbor['id']), paths.get(neighbor['id'])) or {}
        jobs = [o for o in board if o['settlement'] == neighbor['id']]
        detail = (f' (about {path["duration"]} cycles on the road; take {money(path.get("supplies", 0))} food or more)'
                  if path else '')
        if jobs:
            best = max(jobs, key=lambda o: o['unit_wage'])
            detail += f'; job there: {best["remaining"]} {best["resource"]} at {money(best["unit_wage"])} each'
        out.append(_choice('Travel', f'Move to {neighbor["name"]}{detail}', me, 'migrate', {'destination': neighbor['id']}))


def candidate_actions(observation):
    """Every choice a player might take, by section, before validation."""
    out = []
    if observation['actor'].get('journey'):
        return [_choice('Needs', 'Keep travelling', observation['actor']['id'], 'wait')]
    _economy(observation, out)
    _organizations(observation, out)
    _caravans(observation, out)
    _travel(observation, out)
    order = {section: index for index, section in enumerate(SECTIONS)}
    return sorted(out, key=lambda choice: order[choice['section']])  # stable within a section


def options(world, player):
    """The menu: checked choices pass the world's dry-run validation now; a dry run changes nothing."""
    observation = world.observe(player)
    return [choice for choice in candidate_actions(observation)
            if not choice['checked'] or world.action_engine.validate(choice['proposal']).success]


# ----- Talking to people (v0.8 Stage 3) -------------------------------------

def partners(observation):
    """People here to talk to: neighbors in town who are not on the road."""
    return [dict(id=p['id'], name=p['name'], role=p.get('role', '')) for p in observation.get('peers', [])]


def _ask(label, topic, args=None, fields=()):
    return dict(section='Talk', label=label, fields=list(fields), checked=False,
                proposal={'type': topic, 'params': dict(args or {})})


def conversation(observation, partner):
    """What the player can ask or tell one neighbor. Asking takes no season; it changes only what people know."""
    from .social_memory import describe
    actor, town = observation['actor'], observation['settlement']
    peer = next((p for p in observation.get('peers', []) if p['id'] == partner), None)
    if peer is None:
        return []
    first = peer['name'].split()[0]
    out = [_ask(f'Ask {first} about work', 'work'), _ask('Ask what has been happening', 'news'),
           _ask('Ask about trade and the roads', 'trade'), _ask('Ask about local politics', 'politics'),
           _ask(f'Ask how {first} is doing and what they want', 'themselves'),
           _ask(f'Ask what {first} thinks of you', 'person', {'person': actor['id']})]
    for other in observation.get('peers', []):
        if other['id'] != partner:
            out.append(_ask(f'Ask what {first} thinks of {other["name"]}', 'person', {'person': other['id']}))
    for institution in observation.get('institutions', []):
        if institution.get('settlement_id') != town['id'] or not institution.get('active', True):
            continue
        for decision in institution.get('decisions', []):
            if decision.get('status') == 'open' and decision.get('expires', 0) > observation.get('tick', 0):
                out.append(_ask(f'Ask how {first} would vote on proposal {decision["id"]} in {institution["name"]}: '
                                f'{describe_decision(decision, observation)}', 'proposal',
                                {'institution': institution['id'], 'proposal': decision['id']}))
        if actor['id'] in institution.get('members', []) and partner not in institution.get('members', []):
            out.append(_ask(f'Ask {first} to join {institution["name"]}', 'join', {'institution': institution['id']}))
    local = observation.get('prices', {}).get('posted', {}).get(town['id'], {})
    for good in GOODS:
        if good in local:
            wage = offered_wage(local[good])
            out.append(_ask(f'Ask if {first} would work for you gathering {good} at {money(wage)} a unit',
                            'work_for_you', {'resource': good, 'wage': wage},
                            [_field('wage', .1, 5, wage, 'float')]))
    if 'carpentry' not in actor.get('skills', []):
        out.append(_ask(f'Ask if {first} could teach you carpentry', 'teach', {'topic': 'carpentry'}))
    if actor.get('knowledge', 0) < 2:
        out.append(_ask(f'Ask if {first} could teach you about the Aether', 'teach', {'topic': 'aether'}))
    claims = sorted((c for c in actor.get('claims', []) if c.get('subject') != partner),
                    key=lambda c: (-c['observed'], str(c['key'])))
    for claim in claims[:6]:
        out.append(_ask(f'Tell {first}: {describe(claim, speaker=actor["id"])}', 'tell', {'claim': claim['key']}))
    return out
