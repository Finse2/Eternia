"""Observation-only v0.7 choices, including the price of collective work.

Job valuation uses only public facts: a notice's terms and claimed units,
neighbors' accessible deposits, and the public route quote. It is a programmed
expected-value estimate, not foresight; other workers may arrive first.

Market choices use the posted prices at home and in neighboring towns. People
buy food they cannot gather, buy goal materials at reasonable prices, sell
surpluses, and compare a funded job with gathering and selling the same goods.
Merchants consign goods to a neighboring market only when the expected payment,
after journey risk, beats the goods' value at home plus the provisions eaten.
"""
from copy import deepcopy
import math

from .logistics_engine import ROAD_COSTS
from .logistics_policy import LogisticsPolicy
from .market import CONSIGNMENT_LIMIT, GOODS, bid_price, offered_wage
from .regional_policy import _get
from .society_policy import CommunityPolicy

STYLES = ('balanced', 'personal', 'collective')
SKILLS = {'food': 'foraging', 'wood': 'woodcutting', 'iron': 'mining'}
WORKING_SHARE = .75  # turns left after eating and resting
MIN_MOVE_GAIN = 3.   # coins a move must be worth after every estimated cost
FOOD_RESERVE = 3     # meals a person keeps before selling food or spending on other things
FAIR_LIMIT = 1.5     # buy goal materials up to 1.5x their base price; hire for less above it
SELL_FLOOR = 1.      # sell surpluses only while the posted price is at least the base price
GATHER_FOR_SALE = 1.25  # gather to sell when the posted price is 25% above base
MIN_TRADE_GAIN = 2.  # coins a shipment must be expected to earn after every cost and risk
LOSS_MEMORY = 8      # cycles a losing shipment raises the margin a merchant requires on that route


def market_view(observation):
    """Posted prices from an observation, or None outside the market economy."""
    prices = observation.get('prices')
    if not prices or prices.get('home') is None:
        return None
    home = prices['home']
    posted = prices.get('posted', {})
    local = _get(posted, home)
    if not local:
        return None
    return dict(home=home, posted=posted, ask=local, base=prices.get('base', {}),
                bid={resource: bid_price(price) for resource, price in local.items()})


def shipment_gain(*, amount, destination_bid, unit_cost, supplies, food_price, risk):
    """Expected coins from a consignment: paid only on safe delivery, costs paid either way."""
    return (1 - risk) * amount * destination_bid - amount * unit_cost - supplies * food_price


def job_value(order, *, tick, energy, regen, deposit, delay=0, risk=0.):
    """Expected (coins, units) from a public order if work can start after ``delay`` ticks.

    Claims observed since the order became workable are projected forward as
    competition. A notice nobody could work yet has no evidence and no value.
    """
    start = tick + delay
    work_ticks = order['expires'] - start
    observed = tick - order['created'] - 1
    if work_ticks < 1 or (delay and observed < 1):
        return 0., 0.
    claim_rate = (order['quantity'] - order['remaining']) / max(1, observed)
    remaining = order['remaining'] - claim_rate * delay
    accessible = deposit - claim_rate * delay
    labor = WORKING_SHARE * min(8 * work_ticks, (max(0., energy) + regen * work_ticks) / 2)
    units = max(0., min(remaining, accessible, labor))
    return units * order['unit_wage'] * (1 - risk), units


class EconomicPolicy(LogisticsPolicy):
    name = 'economic agency under a municipal charter'

    def __init__(self, style='balanced'):
        super().__init__()
        if style not in STYLES:
            raise ValueError('Unknown economic policy style')
        self.style = style

    @staticmethod
    def _mine(order, actor):
        return order.get('employer') == {'kind': 'person', 'id': actor['id']}

    @staticmethod
    def _goal_materials(actor, recipes):
        """Materials the person's own goal consumes next."""
        goal = actor.get('goal', {})
        if (goal.get('kind') == 'houses' and 'carpentry' in actor.get('skills', [])
                and actor.get('structures', {}).get('house', 0) < goal.get('target', 3)):
            return {r: v for r, v in recipes.get('house', {}).items() if r != 'coins'}
        if goal.get('kind') == 'knowledge' and actor.get('knowledge', 0) < goal.get('target', 2):
            return {'wood': 1., 'iron': 1.}  # one research attempt
        return {}

    @staticmethod
    def _wants_coins(actor):
        goal = actor.get('goal', {})
        return goal.get('kind') in ('wealth', 'profit') and actor['inventory'].get('coins', 0) < goal.get('target', 60)

    def _keep(self, actor, recipes, resource):
        """Units a person keeps for meals and their own goal before selling."""
        goal = actor.get('goal', {})
        if resource == 'food':
            return max(FOOD_RESERVE, goal.get('target', 0) if goal.get('kind') == 'food' else 0)
        return self._goal_materials(actor, recipes).get(resource, 0)

    def _food_purchase(self, observation, market, *, urgent):
        actor, town = observation['actor'], observation['settlement']
        available = actor.get('available_inventory', actor['inventory'])
        food, ask = available.get('food', 0), market['ask']['food']
        if not urgent:
            gatherable = 'foraging' in actor.get('skills', []) and town.get('deposits', {}).get('food', 0) >= 1
            if food >= 2 or gatherable:
                return None
        amount = min(8, math.ceil(FOOD_RESERVE - food - 1e-9), math.floor(town.get('food', 0)),
                     math.floor((available.get('coins', 0) + 1e-9) / ask))
        if amount < 1:
            return None
        proposal = dict(actor=actor['id'], type='trade', location=town['id'],
                        params={'resource': 'food', 'amount': amount, 'direction': 'buy'})
        if urgent:
            return (110 + actor.get('hunger', 0), proposal,
                    f'Hungry with no food to hand: buy {amount} food at the posted {ask:g} coins each.')
        fair = ask <= FAIR_LIMIT * market['base'].get('food', 1.)
        return (64 if fair else 50, proposal,
                f'Buy {amount} food at {ask:g} coins each to keep a few meals; no food can be gathered here.')

    def _market_candidates(self, observation, market, orders):
        """Purchases, sales and gathering for sale at the posted local prices."""
        actor, town = observation['actor'], observation['settlement']
        available = actor.get('available_inventory', actor['inventory'])
        recipes = observation.get('rules', {}).get('recipes', {})
        skills, energy = set(actor.get('skills', [])), actor.get('energy', 100)
        ask, bid, base = market['ask'], market['bid'], market['base']
        treasury, deposits = town.get('treasury', 0), town.get('deposits', {})
        wants_coins = self._wants_coins(actor)
        food_budget = FOOD_RESERVE * ask['food']
        candidates = []
        food = self._food_purchase(observation, market, urgent=False)
        if food:
            value, proposal, reason = food
            candidates.append(('trade', proposal['params'], value, reason, 1))

        # Goal materials that cannot be gathered here: buy at a reasonable price,
        # keeping coins for the goal's own cost and a few meals.
        needs = self._goal_materials(actor, recipes)
        goal = actor.get('goal', {})
        reserve = (recipes.get('house', {}).get('coins', 0) if goal.get('kind') == 'houses' else 0) + food_budget
        for resource in ('iron', 'wood'):
            missing = math.ceil(needs.get(resource, 0) - available.get(resource, 0) - 1e-9)
            if missing < 1 or (SKILLS[resource] in skills and deposits.get(resource, 0) >= missing):
                continue
            amount = min(8, missing, math.floor(town.get(resource, 0)))
            price = ask[resource]
            if (amount >= 1 and price <= FAIR_LIMIT * base.get(resource, price)
                    and available.get('coins', 0) + 1e-9 >= amount * price + reserve):
                candidates.append(('trade', {'resource': resource, 'amount': amount, 'direction': 'buy'}, 78,
                                   f'Buy {amount} {resource} at the posted {price:g} coins each; my goal needs it '
                                   'and buying is faster than hiring.', 1))

        for resource in GOODS:
            price, offer = ask[resource], bid[resource]
            if offer <= 0:
                continue
            payable = math.floor((treasury + 1e-9) / offer)
            surplus = math.floor(available.get(resource, 0) - self._keep(actor, recipes, resource) + 1e-9)
            if surplus >= 1 and price >= SELL_FLOOR * base.get(resource, price) and payable >= 1:
                amount = min(8, surplus, payable)
                candidates.append(('trade', {'resource': resource, 'amount': amount, 'direction': 'sell'},
                                   57 + (9 if wants_coins else 0),
                                   f'Sell {amount} surplus {resource} to the market at {offer:g} coins each.', 1))
            # Gather to sell when the local price is high and the market can pay.
            units = min(8, math.floor(deposits.get(resource, 0)), math.floor(energy / 2), payable)
            if (SKILLS[resource] in skills and units >= 1 and surplus < 8
                    and price >= GATHER_FOR_SALE * base.get(resource, price)):
                wage = max((o['unit_wage'] for o in orders if o['resource'] == resource
                            and not self._mine(o, actor)), default=None)
                note = (f' A funded job pays only {wage:g} per unit; gathering and selling pays more.'
                        if wage is not None and wage < offer / 2 else '')
                candidates.append(('gather', {'resource': resource, 'amount': units},
                                   52 + (8 if wants_coins else 0),
                                   f'Gather {units} {resource} to sell at {offer:g} coins each; it is scarce here.' + note,
                                   units * 2))
        return candidates

    def _consignment_candidates(self, observation, market):
        """A merchant's most profitable shipment to a neighboring market, if any."""
        actor, town = observation['actor'], observation['settlement']
        goal = actor.get('goal', {})
        if actor.get('role') != 'merchant' and goal.get('kind') != 'profit':
            return []
        available = actor.get('available_inventory', actor['inventory'])
        tick, home = observation.get('tick', 0), market['home']
        paths = observation.get('physical', {}).get('paths', {})
        neighbors = {n['id']: n for n in observation.get('neighbors', [])}
        losses = {}
        for memory in actor.get('memory', []):
            if (memory.get('kind') == 'consignment' and memory.get('gain', 0) < 0
                    and tick - memory.get('tick', -100) <= LOSS_MEMORY):
                losses[memory.get('destination')] = losses.get(memory.get('destination'), 0) + 1
        food_price, own_food = market['ask']['food'], available.get('food', 0)
        coins = available.get('coins', 0) - FOOD_RESERVE * food_price
        best = None
        for destination, prices in market['posted'].items():
            destination = int(destination)
            path = _get(paths, destination)
            if destination == home or destination not in neighbors or not path:
                continue
            supplies = path.get('supplies', path.get('duration', 0) * .5 + 1)
            risk = min(1., max(0., path.get('risk', 0)))
            room = math.floor(path.get('capacity', 0) - supplies)
            required = MIN_TRADE_GAIN * (1 + 2 * losses.get(destination, 0))
            for resource in GOODS:
                offer = bid_price(prices[resource])
                payable = math.floor((neighbors[destination].get('treasury', 0) + 1e-9) / offer) if offer > 0 else 0
                spare = own_food - supplies - FOOD_RESERVE
                held = math.floor((spare if resource == 'food' else available.get(resource, 0)) + 1e-9)
                fed = spare >= 0
                plan = None
                provisions = ('trade', {'resource': 'food', 'direction': 'buy',
                                        'amount': min(8, math.ceil(-spare - 1e-9))})
                amount = min(CONSIGNMENT_LIMIT, held, room, payable)
                if amount >= 1:
                    gain = shipment_gain(amount=amount, destination_bid=offer, unit_cost=market['bid'][resource],
                                         supplies=supplies, food_price=food_price, risk=risk)
                    # Goods in hand ship now; without food for the road, buy provisions first.
                    plan = (('consign', {'resource': resource, 'amount': amount, 'destination': destination}, gain, 90, 4)
                            if fed else (*provisions, gain, 84, 1))
                elif held < 1:
                    cost = market['ask'][resource]
                    bought = min(8, room, payable, math.floor(observation['settlement'].get(resource, 0)),
                                 math.floor(max(0., coins) / cost))
                    # Bought food also feeds the journey; only the rest is cargo.
                    cargo = min(bought, math.floor(own_food + bought - supplies - FOOD_RESERVE + 1e-9)) \
                        if resource == 'food' else bought
                    if cargo >= 1:
                        gain = shipment_gain(amount=cargo, destination_bid=offer, unit_cost=cost,
                                             supplies=supplies, food_price=food_price, risk=risk)
                        plan = ((*provisions, gain, 84, 1) if resource != 'food' and not fed else
                                ('trade', {'resource': resource, 'amount': bought, 'direction': 'buy'}, gain, 86, 1))
                if plan and plan[2] >= required and (best is None or plan[2] > best[2]):
                    best = (*plan, destination, resource, offer, risk)
        if best is None:
            return []
        kind, params, gain, base_value, cost, destination, resource, offer, risk = best
        name = neighbors[destination].get('name', f'settlement {destination}')
        summary = (f'{name} buys {resource} at {offer:g} coins each; after {risk:.0%} journey risk and provisions '
                   f'a shipment should earn about {gain:.1f} coins.')
        explanation = {'consign': 'Consign goods to a dearer market. ',
                       'trade': 'Buy goods to consign to a dearer market. '
                       if params.get('resource') == resource else 'Buy provisions for a profitable shipment. '}[kind]
        return [(kind, params, base_value + min(8, gain * .3), explanation + summary, cost)]

    def _council_trade(self, observation, market, council, tick):
        """Price-based municipal trade terms, votes, enactment and caravan dispatch for one council."""
        town, home = observation['settlement'], market['home']
        identifier, members = council['id'], council.get('members', [])
        authorities = observation.get('municipality', {}).get('authorities', {})
        neighbors = {n['id']: n for n in observation.get('neighbors', [])}
        paths = observation.get('physical', {}).get('paths', {})
        routes = observation.get('regional', {}).get('routes', [])
        institutions = observation.get('institutions', [])
        candidates = []

        def risk(partner):
            path = _get(paths, partner)
            return min(1., max(0., path.get('risk', 1.))) if path else None

        def need(state, resource):
            return self._resource_target(state, resource) - state.get(resource, 0)

        def acceptable(params):
            partner, resource = params.get('destination'), params.get('resource')
            price, hazard = params.get('unit_price', 0), risk(params.get('destination'))
            if partner not in neighbors or resource not in GOODS or hazard is None or not price:
                return False
            if params.get('direction') == 'import':
                # Pay only on delivery, and never more than our market pays a local seller.
                return (need(town, resource) >= 1 and price <= market['bid'][resource] + 1e-9
                        and town.get('treasury', 0) >= min(params.get('quota', 1), 4) * price)
            return ((1 - hazard) * price >= market['ask'][resource] - 1e-9
                    and town.get(resource, 0) > self._export_reserve(town, resource))

        def contracted(params):
            sponsor = 'importer_institution' if params['direction'] == 'import' else 'exporter_institution'
            partner = 'exporter' if params['direction'] == 'import' else 'importer'
            return any(r.get(sponsor) == identifier and r.get(partner) == params['destination']
                       and r.get('resource') == params['resource'] and r.get('status') in ('active', 'suspended')
                       and r.get('expires', tick) > tick + 3 for r in routes)

        def reciprocal(params):
            for other in institutions:
                if other.get('settlement_id') != params['destination'] or not _get(authorities, other['id'], False):
                    continue
                for decision in other.get('decisions', []):
                    terms = decision.get('params', {})
                    if (decision.get('kind') == 'trade_terms' and decision.get('status') == 'open'
                            and terms.get('destination') == home and terms.get('resource') == params['resource']
                            and terms.get('unit_price') == params['unit_price'] and terms.get('quota') == params['quota']
                            and terms.get('direction') != params['direction']):
                        yield other, decision

        decisions = [d for d in council.get('decisions', []) if d['status'] == 'open' and d['expires'] > tick]
        for decision in decisions:
            if decision['kind'] != 'trade_terms':
                continue
            params, approve = decision['params'], acceptable(decision['params'])
            if observation['actor']['id'] in decision.get('electorate', []) and _get(decision.get('votes', {}), observation['actor']['id']) is None:
                candidates.append(('vote', {'institution': identifier, 'proposal': decision['id'], 'approve': approve},
                                   92, 'Judge municipal trade terms against our posted prices and the journey risk.', 0))
            if (approve and not contracted(params) and self._approved(decision, members, tick)
                    and any(self._approved(d, o.get('members', []), tick) for o, d in reciprocal(params))):
                candidates.append(('enact', {'institution': identifier, 'proposal': decision['id']}, 100,
                                   'Open a trade contract both councils approved at a price that profits each town.', 2))

        negotiating = {(d['params'].get('destination'), d['params'].get('resource'))
                       for d in decisions if d['kind'] == 'trade_terms'}
        if len(members) >= 2:
            best = None
            # Answer a neighbor's terms addressed to us when they profit this town.
            for other in institutions:
                partner = other.get('settlement_id')
                if partner not in neighbors or not _get(authorities, other['id'], False):
                    continue
                for decision in other.get('decisions', []):
                    terms = decision.get('params', {})
                    if (decision.get('kind') != 'trade_terms' or decision.get('status') != 'open'
                            or decision.get('expires', tick) <= tick or terms.get('destination') != home
                            or (partner, terms.get('resource')) in negotiating):
                        continue
                    response = {**terms, 'destination': partner,
                                'direction': 'import' if terms.get('direction') == 'export' else 'export'}
                    if acceptable(response) and not contracted(response):
                        best = max(best or (0, None), (10 ** 6, response), key=lambda item: item[0])
            # Otherwise offer terms where posted prices leave room for both towns,
            # one initiative at a time.
            for partner, neighbor in ([] if negotiating else sorted(neighbors.items())):
                hazard = risk(partner)
                prices = _get(market['posted'], partner)
                if hazard is None or hazard > .45 or not prices or not any(
                        o.get('settlement_id') == partner and _get(authorities, o['id'], False) for o in institutions):
                    continue
                for resource in GOODS:
                    far_ask, far_bid = prices[resource], bid_price(prices[resource])
                    if need(town, resource) >= 1 and neighbor.get(resource, 0) > self._export_reserve(neighbor, resource):
                        direction, low, high = 'import', far_ask / (1 - hazard), market['bid'][resource]
                        quota = min(20, max(1, math.ceil(need(town, resource))))
                    elif need(neighbor, resource) >= 1 and town.get(resource, 0) > self._export_reserve(town, resource):
                        direction, low, high = 'export', market['ask'][resource] / (1 - hazard), far_bid
                        quota = min(20, max(1, math.ceil(need(neighbor, resource))))
                    else:
                        continue
                    price = round((low + high) / 2, 2)
                    params = {'destination': partner, 'resource': resource, 'direction': direction,
                              'unit_price': price, 'quota': quota}
                    if high - low >= .1 and acceptable(params) and not contracted(params):
                        best = max(best or (0, None), ((high - low) * quota, params), key=lambda item: item[0])
            if best:
                params = best[1]
                candidates.append(('propose', {'institution': identifier, 'kind': 'trade_terms', 'params': params}, 86,
                                   f'Propose to {params["direction"]} {params["quota"]} {params["resource"]} at '
                                   f'{params["unit_price"]:g} coins each: posted prices leave a margin for both towns.', 1))

        contracts = {r['id']: r for r in routes}
        for option in observation.get('physical', {}).get('dispatch_options', []):
            route = contracts.get(option.get('route'))
            if route is None or route.get('exporter_institution') != identifier:
                continue
            gain = shipment_gain(amount=option['amount'], destination_bid=route['unit_price'],
                                 unit_cost=market['bid'][route['resource']], supplies=option.get('supplies', 0),
                                 food_price=market['ask']['food'], risk=option.get('risk', 1))
            if gain >= 0 and option.get('risk', 1) <= .45:
                candidates.append(('dispatch_caravan', {'route': route['id'], 'amount': option['amount']},
                                   93 + min(6, gain * .2),
                                   f'Dispatch {option["amount"]:g} {route["resource"]} under contract {route["id"]}; '
                                   f'the agreed price beats its value here by about {gain:.1f} coins after risk.', 4))
        return candidates

    def _profitable_dispatch(self, observation, proposal, market):
        """Institutional caravans: sell municipal goods abroad only above their value at home."""
        option = next((o for o in observation.get('physical', {}).get('dispatch_options', [])
                       if o.get('route') == proposal['params'].get('route')), None)
        route = next((r for r in observation.get('regional', {}).get('routes', [])
                      if r.get('id') == proposal['params'].get('route')), None)
        if not option or not route:
            return False
        gain = shipment_gain(amount=proposal['params']['amount'], destination_bid=route['unit_price'],
                             unit_cost=market['bid'][route['resource']], supplies=option.get('supplies', 0),
                             food_price=market['ask']['food'], risk=option.get('risk', 0))
        return gain >= 0

    def _best_move(self, observation, collective, local_value):
        """The most valuable funded job elsewhere, net of travel, risk and leaving home."""
        actor, town = observation['actor'], observation['settlement']
        board = observation.get('municipality', {}).get('job_board', [])
        paths = observation.get('physical', {}).get('paths', {})
        neighbors = {n['id']: n for n in observation.get('neighbors', [])}
        prices = observation.get('rules', {}).get('prices', {'food': 1.})
        tick, energy = observation.get('tick', 0), actor.get('energy', 100)
        regen = 24 / max(1, observation.get('ticks_per_year', 4))
        openness = max(0., min(1., actor.get('openness', .5)))
        ties = len(actor.get('memberships', []))
        best = None
        if town.get('population', 0) <= 10 or any(self._mine(o, actor) for o in
                                                    observation.get('municipality', {}).get('work_orders', [])):
            # The population floor forbids leaving; an open private job needs its employer present.
            return None
        for order in board:
            neighbor, path = neighbors.get(order['settlement']), _get(paths, order['settlement'])
            if (neighbor is None or not path or path.get('capacity', 0) < 1
                    or neighbor.get('permissions', {}).get('migrate', True) is False
                    or SKILLS[order['resource']] not in actor.get('skills', []) or self._mine(order, actor)):
                continue
            duration, risk = path['duration'], min(1., max(0., path.get('risk', 0)))
            gross, units = job_value(order, tick=tick, energy=energy - 12 - duration, regen=regen,
                                     deposit=neighbor.get('deposits', {}).get(order['resource'], 0),
                                     delay=duration, risk=risk)
            provisions = duration * .5 * prices.get('food', 1.)
            attachment = 4 + 3 * ties * (1 + collective) + 8 * (1 - openness)
            net = gross - provisions - attachment - local_value
            if net >= MIN_MOVE_GAIN and (best is None or net > best['net']):
                best = dict(order=order, destination=neighbor, duration=duration, risk=risk,
                            units=units, gross=gross, net=net, food=duration + 2.)
        return best

    def propose(self, observation):
        actor, town = observation['actor'], observation['settlement']
        available = actor.get('available_inventory', actor['inventory'])
        municipality = observation.get('municipality', {})
        authorities = municipality.get('authorities', {})
        orders = municipality.get('work_orders', [])
        tick = observation.get('tick', 0)
        fallback = super().propose(observation)
        reason = self.reason
        hunger, energy = actor.get('hunger', 0), actor.get('energy', 100)
        market = market_view(observation)
        if actor.get('journey') or fallback['type'] == 'eat':
            return fallback
        if (hunger >= 35 and available.get('food', 0) < 1) or hunger >= 65:
            feeds = fallback['type'] == 'accept' or (fallback['type'] == 'gather'
                                                    and fallback['params'].get('resource') == 'food')
            purchase = self._food_purchase(observation, market, urgent=True) if market and not feeds else None
            if purchase:
                _, proposal, self.reason = purchase
                return deepcopy(proposal)
            return fallback
        if energy < 15:
            return fallback
        if market and fallback['type'] == 'dispatch_caravan' and not self._profitable_dispatch(
                observation, fallback, market):
            helper = CommunityPolicy()
            fallback = helper.propose(observation)
            reason = 'Decline an institutional shipment worth less abroad than at home. ' + helper.reason

        organizations = [i for i in observation.get('institutions', [])
                         if i.get('active', True) and i['settlement_id'] == town['id']]
        councils = sorted((i for i in organizations if i.get('purpose') == 'council'),
                          key=lambda i: (-len(i['members']), i['id']))
        member_councils = [i for i in councils if actor['id'] in i['members']]
        # Suppress an old policy's proposed use of municipal resources when the
        # new charter denies authority. This changes proposals, never world rules.
        if fallback['type'] == 'propose' and fallback.get('params', {}).get('kind') in (
                'trade_terms', 'specialization', 'communal_labor', 'migration_policy', 'route_access'):
            target = fallback['params'].get('institution')
            if not _get(authorities, target, False):
                helper = CommunityPolicy()
                fallback = helper.propose(observation)
                reason = helper.reason

        scores = {'gather': 48, 'offer': 46, 'accept': 59, 'build': 82, 'research': 68,
                  'rest': 12, 'migrate': 72, 'enact': 87, 'vote': 78,
                  'propose': 68, 'contribute': 65, 'teach': 20, 'collaborate': 25,
                  'form_institution': 60, 'join_institution': 61, 'leave_institution': 75}
        score = scores.get(fallback['type'], 0)
        collective = {'personal': 0., 'balanced': .5, 'collective': 1.}[self.style]
        if fallback['type'] in ('contribute', 'teach', 'collaborate', 'dispatch_caravan'):
            score += collective * 30
        choices = [(score, fallback, reason)]
        skills = set(actor.get('skills', []))
        permissions = town.get('permissions', {})
        recent_failures = {self._signature(m['action']) for m in actor.get('memory', [])[-16:]
                           if m.get('action') and m.get('result', {}).get('success') is False
                           and tick - m.get('tick', -100) <= 2}

        def consider(kind, params, value, explanation, cost=0):
            if permissions.get(kind, True) is False or energy < cost:
                return
            proposal = dict(actor=actor['id'], type=kind, location=town['id'], params=params)
            if self._signature(proposal) not in recent_failures:
                choices.append((value, proposal, explanation))

        if not councils and available.get('coins', 0) >= 2:
            consider('form_institution', {'name': town['name'] + ' Municipal Council', 'purpose': 'council'},
                     74, 'Seek a local council before authorizing town resources.', 2)
        elif councils and actor['id'] not in councils[0]['members']:
            consider('join_institution', {'institution': councils[0]['id']}, 75,
                     'Join a local council so municipal decisions can represent a majority.', 1)

        for order in orders:
            resource = order['resource']
            skill = SKILLS[resource]
            amount = min(8, order['remaining'], math.floor(town.get('deposits', {}).get(resource, 0)),
                         math.floor(energy / 2))
            if skill in skills and amount >= 1 and not self._mine(order, actor):
                if market:
                    # Gathering and selling takes two actions for the same units.
                    offer = market['bid'][resource]
                    sellable = min(amount, math.floor((town.get('treasury', 0) + 1e-9) / offer)) if offer > 0 else 0
                    if sellable * offer / 2 > amount * order['unit_wage'] + 1e-9:
                        continue  # decline: the local market pays more for the same effort
                private_need = max(0., actor.get('goal', {}).get('target', 60) - actor['inventory']['coins'])
                paid_score = 98 - collective * 32 + min(6, amount * order['unit_wage'] * .3)
                if actor.get('goal', {}).get('kind') in ('wealth', 'profit') and private_need > 0:
                    paid_score += 9
                consider('work', {'order': order['id'], 'amount': amount}, paid_score,
                         f'Earn {amount * order["unit_wage"]:g} funded coins by delivering {resource}; '
                         'compare this pay with voluntary collective work.', amount * 2)

        # Paid work elsewhere: worth a journey only if it beats staying.
        rules = observation.get('rules', {})
        prices = rules.get('prices', {'food': 1., 'wood': 2., 'iron': 4.})
        regen = 24 / max(1, observation.get('ticks_per_year', 4))
        local_value = max((job_value(o, tick=tick, energy=energy, regen=regen,
                                     deposit=town.get('deposits', {}).get(o['resource'], 0))[0]
                           for o in orders if SKILLS[o['resource']] in skills and not self._mine(o, actor)),
                          default=0.)
        move = self._best_move(observation, collective, local_value)
        if move:
            order, place = move['order'], move['destination']
            summary = (f'{place["name"]} pays {order["unit_wage"]:g} coins per {order["resource"]}; about '
                       f'{move["units"]:.0f} units should remain after a {move["duration"]}-tick journey with '
                       f'{move["risk"]:.0%} turn-back risk, worth about {move["net"]:.1f} coins more than staying.')
            goal = actor.get('goal', {})
            short = goal.get('kind') in ('wealth', 'profit') and actor['inventory']['coins'] < goal.get('target', 60)
            # Priority grows with the stake: a large opportunity outranks a routine
            # vote, though not enacting spending that members already approved.
            value = 84 + min(20, move['net'] * .6) + (6 if short else 0)
            food = available.get('food', 0)
            if food + 1e-9 >= move['food']:
                consider('migrate', {'destination': place['id']}, value, 'Move for paid work: ' + summary, 12)
            else:
                needed = math.ceil(move['food'] - food - 1e-9)
                # Two extra units cover meals eaten while still preparing.
                amount = min(8, needed + 2, math.floor(town.get('deposits', {}).get('food', 0)), math.floor(energy / 2))
                if 'foraging' in skills and amount >= 1:
                    consider('gather', {'resource': 'food', 'amount': amount}, value - 4,
                             'Gather journey provisions before moving for paid work. ' + summary, amount * 2)
                elif (needed <= 8 and town.get('food', 0) >= needed
                      and available.get('coins', 0) >= needed * prices.get('food', 1.)):
                    consider('trade', {'resource': 'food', 'amount': needed, 'direction': 'buy'}, value - 4,
                             'Buy journey provisions before moving for paid work. ' + summary, 1)

        # Hire for what my own goal needs but I cannot gather myself. Wages are
        # escrowed from my coins, so keep what the goal itself will still cost.
        needs = self._goal_materials(actor, rules.get('recipes', {}))
        if needs and not any(self._mine(o, actor) for o in orders):
            reserve = rules.get('recipes', {}).get('house', {}).get('coins', 0) if actor.get('goal', {}).get('kind') == 'houses' else 0
            reserve += FOOD_RESERVE * prices.get('food', 1.) if market else 0  # save wages for meals
            for resource in ('iron', 'wood', 'food'):
                missing = math.ceil(needs.get(resource, 0) - available.get(resource, 0) - 1e-9)
                if missing < 1 or SKILLS[resource] in skills:
                    continue
                wage = offered_wage(prices.get(resource, 1.))
                if available.get('coins', 0) + 1e-9 >= missing * wage + reserve:
                    consider('hire', {'resource': resource, 'quantity': missing, 'unit_wage': wage}, 73,
                             f'Hire a worker for {missing} {resource} at {wage:g} coins each, below the posted price; '
                             'my goal needs it and I cannot gather it myself.', 1)
                break

        # Voluntary organizations may pay for a road project's missing material
        # from their own voted holdings instead of waiting for volunteers.
        for institution in organizations:
            members = institution.get('members', [])
            if institution.get('purpose') == 'council' or actor['id'] not in members:
                continue
            identifier, shared = institution['id'], institution.get('available_inventory', {})
            decisions = [p for p in institution.get('decisions', []) if p['status'] == 'open' and p['expires'] > tick]
            project = any(p['kind'] == 'repair_route' for p in decisions)
            for proposal in decisions:
                if proposal['kind'] != 'commission':
                    continue
                params = proposal['params']
                budget = params['quantity'] * params['unit_wage']
                support = (project and shared.get('coins', 0) >= budget + ROAD_COSTS['coins']
                           and shared.get(params['resource'], 0) < ROAD_COSTS.get(params['resource'], 0))
                if actor['id'] in proposal.get('electorate', []) and _get(proposal.get('votes', {}), actor['id']) is None:
                    consider('vote', {'institution': identifier, 'proposal': proposal['id'], 'approve': bool(support)},
                             90, 'Judge a paid commission from its cost and the road project still needing material.')
                if support and self._approved(proposal, members, tick):
                    consider('enact', {'institution': identifier, 'proposal': proposal['id']}, 100,
                             'Escrow the voted commission wages from shared holdings.', 2)
            hiring = any(o.get('employer') == {'kind': 'institution', 'id': identifier} for o in orders)
            if not project or hiring or len(members) < 2 or any(p['kind'] == 'commission' for p in decisions):
                continue
            for resource in ('iron', 'wood'):
                deficit = math.ceil(ROAD_COSTS[resource] - shared.get(resource, 0) - 1e-9)
                wage = offered_wage(prices.get(resource, 1.))
                if deficit >= 1 and shared.get('coins', 0) >= deficit * wage + ROAD_COSTS['coins']:
                    consider('propose', {'institution': identifier, 'kind': 'commission',
                                         'params': {'resource': resource, 'quantity': deficit, 'unit_wage': wage}},
                             80, f'Ask members to pay for {deficit} {resource} the road project lacks, from shared coins.', 1)
                    break

        for council in member_councils:
            identifier = council['id']
            authorized = _get(authorities, identifier, False)
            decisions = [p for p in council.get('decisions', [])
                         if p['status'] == 'open' and p['expires'] > tick]
            for proposal in decisions:
                if proposal['kind'] != 'work_order':
                    continue
                params = proposal['params']
                budget = params['quantity'] * params['unit_wage']
                scarce = town.get('deposits', {}).get(params['resource'], 0) >= 1
                affordable = town.get('treasury', 0) >= budget
                # Never pay more per unit than the town's market pays a seller.
                ceiling = bid_price(prices.get(params['resource'], 1.)) if market else 2
                support = scarce and affordable and params['unit_wage'] <= ceiling + 1e-9
                votes = proposal.get('votes', {})
                if actor['id'] in proposal['electorate'] and _get(votes, actor['id']) is None:
                    consider('vote', {'institution': identifier, 'proposal': proposal['id'], 'approve': bool(support)},
                             94, 'Judge a public work budget from its wage, local material and municipal funds.')
                if authorized and support and self._approved(proposal, council['members'], tick):
                    consider('enact', {'institution': identifier, 'proposal': proposal['id']}, 106,
                             'Reserve the voted wage budget before anybody can claim public pay.', 2)
            if authorized and market:
                for kind, params, value, explanation, cost in self._council_trade(observation, market, council, tick):
                    consider(kind, params, value, explanation, cost)
            if (not authorized or any(p['kind'] == 'work_order' for p in decisions)
                    or town.get('treasury', 0) < 8):
                continue
            # Jobs address an observed municipal stock deficit. Policy candidates
            # are public facts, not hidden resource reserves or other wallets.
            candidates = []
            for resource in ('food', 'wood', 'iron'):
                if any(o['resource'] == resource and o.get('employer', {}).get('kind') == 'municipal'
                       for o in orders):
                    continue
                accessible = math.floor(town.get('deposits', {}).get(resource, 0))
                deficit = self._resource_target(town, resource) - town.get(resource, 0)
                if accessible >= 1 and deficit >= 1:
                    candidates.append((deficit / max(1, self._resource_target(town, resource)), resource, accessible))
            if candidates:
                _, resource, accessible = max(candidates)
                wage = offered_wage(prices.get(resource, 1.))
                quantity = min(24, accessible, math.floor(town['treasury'] * .4 / wage))
                if quantity >= 1:
                    consider('propose', {'institution': identifier, 'kind': 'work_order',
                                        'params': {'resource': resource, 'quantity': quantity, 'unit_wage': wage}},
                             84, 'Propose paid extraction for a public shortage, within forty percent of current town coins.', 1)

        # Attach a verifiable purpose to unpaid material gathering for a project.
        if fallback['type'] == 'gather' and 'repair' in reason.lower():
            for institution in organizations:
                if actor['id'] not in institution['members']:
                    continue
                project = next((p for p in institution.get('decisions', [])
                                if p['kind'] == 'repair_route' and p['status'] == 'open'
                                and p['created'] < tick < p['expires']), None)
                if project:
                    fallback['params']['purpose'] = dict(kind='voluntary_project',
                                                       institution=institution['id'], proposal=project['id'])
                    choices[0] = (77 + collective * 20, fallback,
                                  'Choose unpaid project preparation to support a proposed public road repair.')
                    break

        if market:
            for kind, params, value, explanation, cost in (self._market_candidates(observation, market, orders)
                                                          + self._consignment_candidates(observation, market)):
                consider(kind, params, value, explanation, cost)
        _, proposal, self.reason = max(choices, key=lambda item: item[0])
        return deepcopy(proposal)

