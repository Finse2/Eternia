"""v0.7: explicit work compensation, municipal jurisdiction, a regional labor market
and local markets whose prices respond to supply and demand.

The charter covers the represented local electorate, not all aggregate residents.
Only a majority local council may authorize municipal funds. Voluntary
organizations commission work from their own voted holdings, and individuals
hire from their own coins. Every employer escrows the full wage budget first;
paid extraction moves finite material to the employer and escrowed coins to a
worker. Open jobs are public notices visible in neighboring settlements.

Each town posts prices at the start of every cycle (see ``market.py``). Retail
trade uses them, and a merchant may consign owned goods to a neighboring market:
the goods travel as a physical caravan, the destination escrows payment at its
posted buying price, and the merchant is paid only on delivery.
"""
from copy import copy, deepcopy
from contextlib import contextmanager
import math

from .actions import _number, _require
from .community import RESOURCES
from .institutions import approved
from .logistics_engine import LogisticsEngine
from .market import (BASE_PRICES, BID_SHARE, CONSIGNMENT_LIMIT, GOODS, PRICE_CEILING, PRICE_FLOOR,
                     MAX_STEP, RESERVE_PER_RESIDENT, USE_PER_RESIDENT, WAGE_SHARE, bid_price,
                     bounds, coverage, next_price, target_price)
from .physical_world import PhysicalWorld
from .regional_engine import RegionalEngine


MUNICIPAL_KINDS = {'work_order', 'trade_terms', 'specialization',
                   'communal_labor', 'migration_policy', 'route_access'}
WORK_SKILLS = {'food': 'foraging', 'wood': 'woodcutting', 'iron': 'mining'}
JOB_TERMS = {'resource', 'quantity', 'unit_wage'}
ORDER_TICKS = 12
EMPLOYMENT_PURPOSES = {'municipal': 'municipal_output', 'institution': 'institution_commission',
                       'person': 'private_employment'}


class SocietyEngine(LogisticsEngine):
    parameters = {**LogisticsEngine.parameters,
                  'gather': {'resource', 'amount', 'purpose'},
                  'contribute': {'institution', 'resource', 'amount', 'purpose'},
                  'work': {'order', 'amount'},
                  'hire': set(JOB_TERMS),
                  'consign': {'resource', 'amount', 'destination'}}

    def unit_price(self, settlement, resource, direction):
        # People buy at the posted price and sell at the market's buying price.
        return self.world.market_quote(settlement.id, resource, direction)

    @staticmethod
    def _job_terms(params):
        _require(type(params) is dict and set(params) == JOB_TERMS,
                 'invalid_action', 'A paid job requires resource, quantity and unit_wage.')
        resource = params.get('resource')
        _require(type(resource) is str and resource in WORK_SKILLS,
                 'invalid_resource', 'Paid work extracts food, wood or iron.')
        return {'resource': resource,
                'quantity': _number(params['quantity'], 'quantity', minimum=1, maximum=24, integral=True),
                'unit_wage': _number(params['unit_wage'], 'unit_wage', minimum=.1, maximum=5)}

    def _open_job(self, employer, resource, settlement=None):
        return any(o['status'] == 'open' and o['employer'] == employer and o['resource'] == resource
                   and (settlement is None or o['settlement'] == settlement)
                   for o in self.world.work_orders)

    def _check_trade(self, actor, settlement, params):
        details = super()._check_trade(actor, settlement, params)
        _require(details['amount'] <= 8, 'retail_limit',
                 'The standing municipal retail charter permits at most eight units per action.')
        details['unit_price'] = self.unit_price(settlement, details['resource'], details['direction'])
        return details

    def _check_consign(self, actor, settlement, params):
        self._skill(actor, 'trading')
        resource = params.get('resource')
        _require(type(resource) is str and resource in GOODS,
                 'invalid_resource', 'Consign food, wood or iron.')
        amount = _number(params.get('amount'), 'amount', minimum=1, maximum=CONSIGNMENT_LIMIT, integral=True)
        reference = params.get('destination')
        _require(type(reference) is int and reference >= 0, 'unknown_location',
                 'A consignment needs a destination settlement integer ID.')
        target = next((s for s in self.world.settlements if s.id == reference), None)
        _require(target is not None and target.id != settlement.id, 'unknown_location',
                 'Consign goods to a different settlement.')
        _require(self._distance(settlement, target) <= 38, 'out_of_range',
                 'The destination market lies beyond the supported range of 38.')
        _require(target.permissions.get('trade', True) is True, 'permission_denied',
                 'The destination market is closed.')
        details = self.world.consignment_quote(actor, target.id, resource, amount)
        details['energy'] = 4
        return details

    def _purpose(self, actor, settlement, purpose):
        if purpose is None:
            return {'kind': 'personal_inventory'}
        _require(type(purpose) is dict and set(purpose) == {'kind', 'institution', 'proposal'}
                 and purpose.get('kind') == 'voluntary_project',
                 'invalid_purpose', 'Voluntary project work names an institution and proposal.')
        institution, frame = self._institution(actor, settlement, purpose)
        reference = purpose['proposal']
        _require(type(reference) is int, 'unknown_proposal', 'Use an integer project ID.')
        proposal = next((p for p in institution.decisions if p['id'] == reference), None)
        _require(proposal is not None and proposal['kind'] in ('repair_route', 'granary', 'distribute_food')
                 and proposal['status'] == 'open' and proposal['expires'] > self.world.tick
                 and any(p['id'] == reference for p in frame['decisions']),
                 'invalid_purpose', 'The voluntary project must be live and visible at tick start.')
        return deepcopy(purpose)

    def _check_gather(self, actor, settlement, params):
        details = super()._check_gather(actor, settlement, params)
        details['purpose'] = self._purpose(actor, settlement, params.get('purpose'))
        return details

    def _check_contribute(self, actor, settlement, params):
        details = super()._check_contribute(actor, settlement, params)
        if params.get('purpose') is not None:
            details['purpose'] = self._purpose(actor, settlement, params['purpose'])
        else:
            details['purpose'] = {'kind': 'voluntary_shared_reserves',
                                  'institution': details['institution'].id}
        return details

    def _proposal_params(self, kind, params, settlement):
        if kind in ('work_order', 'commission'):
            return self._job_terms(params)
        return super()._proposal_params(kind, params, settlement)

    def _same_subject(self, kind, params, other):
        # Councils negotiate separately with each neighbor for each good.
        if kind == 'trade_terms' and other['kind'] == kind:
            return (other['params'].get('destination') == params['destination']
                    and other['params'].get('resource') == params['resource'])
        return super()._same_subject(kind, params, other)

    @staticmethod
    def _employer(kind, institution, settlement):
        if kind == 'work_order':
            return {'kind': 'municipal', 'id': settlement.id}
        return {'kind': 'institution', 'id': institution.id}

    def _check_propose(self, actor, settlement, params):
        # Public road access is not private ownership acquired by making a repair.
        if params.get('kind') == 'route_access':
            details = RegionalEngine._check_propose(self, actor, settlement, params)
        else:
            details = super()._check_propose(actor, settlement, params)
        if details['kind'] in MUNICIPAL_KINDS:
            self.world.require_municipal_authority(details['institution'])
        if details['kind'] == 'commission':
            # A council spends town money through the municipal charter instead.
            _require(getattr(details['institution'], 'purpose', None) != 'council', 'invalid_action',
                     'Councils fund work through municipal work orders, not commissions.')
        if details['kind'] in ('work_order', 'commission'):
            employer = self._employer(details['kind'], details['institution'], settlement)
            _require(not self._open_job(employer, details['params']['resource'], settlement.id),
                     'active_order', 'This employer already has a live funded order for this resource.')
        return details

    def _check_enact(self, actor, settlement, params):
        institution, frame = self._institution(actor, settlement, params)
        proposal = self._proposal(institution, params)
        kind = proposal['kind']
        if kind in MUNICIPAL_KINDS:
            self.world.require_municipal_authority(institution)
        if kind not in ('work_order', 'commission', 'route_access'):
            details = super()._check_enact(actor, settlement, params)
            if kind == 'trade_terms':
                self.world.require_municipal_authority(details['reciprocal'][0])
            return details
        _require(approved(self.world, institution, proposal, frame), 'not_approved',
                 'Public spending requires a prior-tick majority and two affirmative voters.')
        normalized = self._proposal_params(kind, proposal['params'], settlement)
        if kind in ('work_order', 'commission'):
            if kind == 'commission':
                _require(getattr(institution, 'purpose', None) != 'council', 'invalid_action',
                         'Councils fund work through municipal work orders, not commissions.')
            employer = self._employer(kind, institution, settlement)
            _require(not self._open_job(employer, normalized['resource'], settlement.id),
                     'active_order', 'A funded order for this resource is already open.')
            wage_budget = normalized['quantity'] * normalized['unit_wage']
            available = (self.world._municipal_available(settlement, 'coins') if kind == 'work_order'
                         else self.world.available_institution_inventory(institution)['coins'])
            _require(available + 1e-9 >= wage_budget, 'insufficient_resources',
                     'The municipality cannot escrow the approved wages.' if kind == 'work_order'
                     else 'The organization cannot escrow the approved wages from its own tick-start coins.')
            return dict(institution=institution, proposal=proposal, params=normalized,
                        wage_budget=wage_budget, employer=employer, costs={}, energy=2)
        link = self._link(normalized['link'], settlement)
        counterpart = None
        for other in sorted(self.world.institutions, key=lambda i: i.id):
            if other.settlement_id not in (link['a'], link['b']) or other.settlement_id == settlement.id:
                continue
            if not self.world.has_municipal_authority(other):
                continue
            for decision in other.decisions:
                if (decision['kind'] == 'route_access' and decision['params'] == normalized
                        and approved(self.world, other, decision)):
                    counterpart = (other, decision)
                    break
            if counterpart:
                break
        _require(counterpart is not None, 'no_reciprocal_mandate',
                 'Both endpoint electorates must authorize the same public-road access decision.')
        return dict(institution=institution, proposal=proposal, params=normalized,
                    link=link, costs={}, energy=2, public_counterpart=counterpart)

    def _check_work(self, actor, settlement, params):
        reference = params.get('order')
        _require(type(reference) is int, 'unknown_order', 'Use a public work order integer ID.')
        order = next((o for o in self.world.work_orders if o['id'] == reference), None)
        _require(order is not None and order['status'] == 'open'
                 and order['created'] < self.world.tick < order['expires'],
                 'order_unavailable', 'The funded order must be open from an earlier tick.')
        _require(order['settlement'] == settlement.id, 'remote_action', 'Work requires local presence.')
        resource = order['resource']
        amount = _number(params.get('amount'), 'amount', minimum=1, maximum=8, integral=True)
        self._skill(actor, WORK_SKILLS[resource])
        recipient = self.world.order_recipient(order)
        _require(recipient is not None, 'order_unavailable',
                 'The employer must still exist and be present to receive the output.')
        _require(order['employer'] != {'kind': 'person', 'id': actor.id}, 'invalid_action',
                 'An employer cannot be paid from their own job escrow.')
        _require(order['remaining'] >= amount and settlement.deposits[resource] >= amount,
                 'depleted', 'The order or accessible material cannot support this work.')
        _require(order['escrow'] + 1e-9 >= amount * order['unit_wage'],
                 'insufficient_resources', 'The promised wage is not funded.')
        return dict(order=order, resource=resource, amount=amount, recipient=recipient,
                    energy=amount * 2)

    def _check_hire(self, actor, settlement, params):
        terms = self._job_terms(params)
        employer = {'kind': 'person', 'id': actor.id}
        _require(not any(o['status'] == 'open' and o['employer'] == employer for o in self.world.work_orders),
                 'active_order', 'Complete or close the current private job before posting another.')
        wage_budget = terms['quantity'] * terms['unit_wage']
        _require(self.world.available_inventory(actor)['coins'] + 1e-9 >= wage_budget,
                 'insufficient_resources', 'A private employer must escrow the full wage budget from available coins.')
        return dict(params=terms, wage_budget=wage_budget, employer=employer, energy=1)

    def _apply(self, action, actor, settlement, details):
        if action.type == 'consign':
            return self.world.launch_consignment(actor, details)
        if action.type == 'work':
            order, amount, resource = details['order'], details['amount'], details['resource']
            paid = min(order['escrow'], amount * order['unit_wage'])
            settlement.deposits[resource] -= amount
            recipient = details['recipient']
            if recipient is settlement:
                setattr(settlement, resource, getattr(settlement, resource) + amount)
            else:  # an institution's holdings or a private employer's inventory
                recipient.inventory[resource] += amount
            actor.inventory['coins'] += paid
            order['escrow'] -= paid
            order['remaining'] -= amount
            if order['remaining'] == 0:
                # Refund floating point dust through a transfer, never a money sink.
                self.world.refund_order(order, 'completed')
            kind = order['employer']['kind']
            return dict(order_id=order['id'], resource=resource, amount=amount, coins=paid,
                        payer=settlement.id if kind == 'municipal' else order['employer']['id'],
                        employer=deepcopy(order['employer']),
                        purpose={'kind': EMPLOYMENT_PURPOSES[kind]},
                        message=f'{actor.name} delivered {amount} {resource} under order {order["id"]} and earned {paid:g} escrowed coins.')
        if action.type == 'hire':
            actor.inventory['coins'] -= details['wage_budget']
            order = self.world.open_work_order(settlement, details['employer'], details['params'],
                                               details['wage_budget'])
            return dict(order_id=order['id'], wage_budget=details['wage_budget'], employer=deepcopy(order['employer']),
                        message=f'{actor.name} escrowed {details["wage_budget"]:g} personal coins to hire '
                                f'{order["quantity"]} {order["resource"]} at {order["unit_wage"]:g} each (order {order["id"]}).')
        if action.type == 'enact' and details['proposal']['kind'] in ('work_order', 'commission'):
            institution, kind = details['institution'], details['proposal']['kind']
            if kind == 'work_order':
                settlement.treasury -= details['wage_budget']
            else:
                self.world.spend_institution(institution, {'coins': details['wage_budget']})
            order = self.world.open_work_order(settlement, details['employer'], details['params'],
                                               details['wage_budget'], institution=institution.id,
                                               proposal=details['proposal']['id'])
            details['proposal'].update(status='enacted', enacted=self.world.tick, executed_by=actor.id)
            self._metric('institution_enactments')
            source = 'existing municipal coins' if kind == 'work_order' else f'{institution.name}\'s voted holdings'
            return dict(order_id=order['id'], wage_budget=details['wage_budget'], costs={},
                        institution_id=institution.id, project=kind,
                        message=f'{actor.name} funded {"public order" if kind == "work_order" else "commission"} '
                                f'{order["id"]} with {order["escrow"]:g} coins from {source}.')
        prior_owner = details.get('link', {}).get('owner')
        result = super()._apply(action, actor, settlement, details)
        if action.type == 'gather':
            result['purpose'] = details['purpose']
        elif action.type == 'trade':
            result['unit_price'] = details['unit_price']
        elif action.type == 'contribute':
            result['purpose'] = details['purpose']
        elif action.type == 'enact' and details['proposal']['kind'] == 'repair_route' and prior_owner is None:
            # Voluntary maintenance of a public route conveys no private ownership.
            details['link']['owner'] = None
        elif action.type == 'enact' and details['proposal']['kind'] == 'route_access':
            other, decision = details['public_counterpart']
            decision.update(status='enacted', enacted=self.world.tick, executed_by=actor.id)
            result['counterpart_institution'] = other.id
        return result


class SocietyWorld(PhysicalWorld):
    def __init__(self, seed=42, ticks_per_year=4, shock_year=0, policies=None,
                 policy_style='balanced'):
        super().__init__(seed, ticks_per_year, shock_year, policies)
        from .economic_policy import EconomicPolicy
        from .persistence import run_manifest
        self.policy_style = policy_style
        self.work_orders = []
        self.next_work_order_id = 0
        self.work_history = []
        self.economic_metrics = dict(wages_paid=0., paid_work_actions=0,
                                     volunteer_actions=0, municipal_orders=0,
                                     commissions=0, private_orders=0,
                                     voluntary_with_paid_option=0, donated_coins=0.)
        self.earnings = {}
        self._economic_choices = {}
        self._transaction_active = False
        self._default_policy = EconomicPolicy(policy_style)
        self.action_engine = SocietyEngine(self)
        self.provenance = run_manifest(self)
        self.market_prices = {}
        self.market_coverage = {}
        self.market_production = {town.id: None for town in self.settlements}
        self.price_history = []
        self.trade_history = []
        self.market_metrics = dict(purchases=0, sales=0, units_bought=0, units_sold=0,
                                   retail_spent=0., retail_received=0., consignments=0,
                                   consignments_delivered=0, consignments_lost=0, consigned_units=0,
                                   consignment_revenue=0., consignment_gain=0., losing_consignments=0)
        self._update_prices()
        self.snapshots = []
        self._event('charter', 'Municipal funds require a majority local council; work wages are escrowed; public-road maintenance grants no private ownership.')
        self._event('market', 'Each town posts prices from its own supply and demand; markets buy at 80% of the posted price.')
        self._snapshot()

    # ----- Local markets -------------------------------------------------

    def _incoming(self, town, resource):
        return sum(j['cargo'].get(resource, 0.) for j in self.journeys
                   if j['kind'] == 'caravan' and j['status'] == 'in_transit' and j['destination'] == town)

    def market_basis(self, town, resource):
        """The public quantities behind a town's price for one good."""
        settlement = self.settlements[town]
        production = (self.market_production.get(town) or {}).get(resource)
        return dict(population=settlement.population, stock=getattr(settlement, resource),
                    accessible=settlement.deposits.get(resource, 0.),
                    incoming=self._incoming(town, resource), production=production)

    def _update_prices(self):
        """Post the next cycle's prices. Called once per cycle, never during resolution."""
        for town in self.settlements:
            posted, basis = {}, {}
            for resource in GOODS:
                cover = coverage(resource, **self.market_basis(town.id, resource))
                previous = self.market_prices.get(town.id, {}).get(resource)
                posted[resource] = next_price(resource, previous, target_price(resource, cover))
                basis[resource] = round(cover, 4)
            self.market_prices[town.id] = posted
            self.market_coverage[town.id] = basis
        self.price_history.append(dict(tick=self.tick, year=self.year,
                                       prices=deepcopy(self.market_prices),
                                       coverage=deepcopy(self.market_coverage)))

    def reset_market_prices(self):
        """Re-post prices from current conditions, for scenario setup before any decision."""
        self.market_prices, self.market_coverage, self.price_history = {}, {}, []
        self._update_prices()

    def market_quote(self, town, resource, direction):
        ask = self.market_prices[town][resource]
        return ask if direction == 'buy' else bid_price(ask)

    def consignment_quote(self, actor, destination, resource, amount):
        target = self.settlements[destination]
        plan = self._departure_plan(actor.home, destination, cargo_amount=amount)
        _require(plan is not None, 'no_path', 'No open route has room for the cargo and its journey provisions.')
        _require(self._original_path_available(actor.home, destination, None, plan),
                 'no_path', 'A newly repaired or reopened route becomes usable next tick.')
        load = amount + plan['supplies']
        _require(self._available_capacity(plan['path']) + 1e-9 >= load, 'transport_capacity',
                 'Cargo and provisions exceed the remaining route capacity this tick.')
        needed = {resource: float(amount)}
        needed['food'] = needed.get('food', 0.) + plan['supplies']
        stock = self.available_inventory(actor)
        _require(all(stock.get(r, 0.) + 1e-9 >= q for r, q in needed.items()), 'insufficient_resources',
                 'The merchant lacks unreserved tick-start cargo or journey provisions.')
        unit = self.market_quote(destination, resource, 'sell')
        coins = amount * unit
        _require(self._municipal_available(target, 'coins') + 1e-9 >= coins, 'insufficient_resources',
                 'The destination market cannot escrow the payment from its tick-start coins.')
        origin = actor.home
        origin_value = self._shipment_value(origin, resource, amount, plan['supplies'])
        return dict(origin=origin, destination=destination, resource=resource, amount=amount,
                    unit_price=unit, coins=coins, origin_value=origin_value, **plan)

    def launch_consignment(self, actor, details):
        resource, amount, supplies = details['resource'], details['amount'], details['supplies']
        target = self.settlements[details['destination']]
        actor.inventory[resource] -= amount
        actor.inventory['food'] -= supplies
        target.treasury -= details['coins']
        journey = self._new_journey('caravan', details, organizer=actor.id, owner=actor.id,
                                    sponsor=None, contract=None, consignment=True)
        journey.update(cargo={resource: float(amount)}, escrow=details['coins'], unit_price=details['unit_price'],
                       origin_value=details['origin_value'],
                       expected_gain=(1 - details['risk']) * details['coins'] - details['origin_value'],
                       transport_load=amount + supplies)
        for identity in details['path']:
            self._link_remaining[identity] = self._link_remaining.get(identity, 0.) - (amount + supplies)
        self.physical_metrics['caravans_dispatched'] += 1
        return dict(journey_id=journey['id'], resource=resource, amount=amount, destination=target.id,
                    unit_price=details['unit_price'], coins=details['coins'], costs={},
                    expected_gain=journey['expected_gain'],
                    message=f'{actor.name} consigned {amount} {resource} to {target.name}; the market there escrowed '
                            f'{details["coins"]:g} coins at {details["unit_price"]:g} each, payable on delivery in about '
                            f'{details["duration"]} ticks.')

    def _consignment_recipient(self, journey):
        owner = journey['owner']
        person = next((a for a in self.agents if a.id == owner), None)
        # A deceased merchant's payment joins the estate held by the successor.
        return person or next((a for a in self.agents if a.parent_id == owner), None)

    def _remember_consignment(self, journey, outcome, gain):
        person = self._consignment_recipient(journey)
        if person is not None:
            person.memory.append(dict(year=self.year, tick=self.tick, kind='consignment', outcome=outcome,
                                      journey=journey['id'], destination=journey['destination'],
                                      gain=round(gain, 6),
                                      message=f'Consignment {journey["id"]} {outcome}; gain {gain:.2f} coins.'))
            del person.memory[:-64]

    def _shipment_value(self, origin, resource, amount, supplies):
        """What cargo and provisions were worth at home: cargo at the market's buying price, food at its price."""
        return amount * self.market_quote(origin, resource, 'sell') + supplies * self.market_quote(origin, 'food', 'buy')

    def launch_caravan(self, actor, details):
        result = super().launch_caravan(actor, details)
        if hasattr(self, 'market_prices'):
            # Contract caravans are judged by the same public measure as merchant consignments.
            journey = self.journeys[-1]
            value = self._shipment_value(details['origin'], details['resource'], details['amount'], details['supplies'])
            journey.update(origin_value=value, expected_gain=(1 - details['risk']) * details['coins'] - value)
            result['expected_gain'] = journey['expected_gain']
        return result

    def _deliver_caravan(self, journey):
        if not journey.get('consignment'):
            paid = journey['escrow']
            super()._deliver_caravan(journey)
            if 'origin_value' in journey:
                journey.update(paid=paid, gain=paid - journey['origin_value'])
            return
        origin, target = self.settlements[journey['origin']], self.settlements[journey['destination']]
        for resource, amount in journey['cargo'].items():
            setattr(target, resource, getattr(target, resource) + amount)
            self._flows[origin.id]['exports'][resource] += amount
            self._flows[target.id]['imports'][resource] += amount
            self.metrics['trade_shipments'] += 1
            self.metrics['trade_volume'] += amount
            self.physical_metrics['cargo_delivered'] += amount
            self.trade_shipments.append(dict(year=self.year, tick=self.tick, route=None, exporter=origin.id,
                                             importer=target.id, resource=resource, amount=amount,
                                             coins=journey['escrow'], journey=journey['id'], consignment=True))
        recipient, paid = self._consignment_recipient(journey), journey['escrow']
        if recipient is None:
            target.treasury += paid  # no living heir: the escrow returns to the market
            paid = 0.
        else:
            # A payment commitment between markets; physical coin carriage is not modeled.
            recipient.inventory['coins'] += paid
        target.food += journey['supplies']  # unused provisions stay with the delivered goods
        gain = paid - journey['origin_value']
        journey.update(status='delivered', arrived=self.tick, delivered_cargo=dict(journey['cargo']),
                       cargo={}, escrow=0., supplies=0., paid=paid, gain=gain)
        self.physical_metrics['caravans_delivered'] += 1
        metrics = self.market_metrics
        metrics['consignments_delivered'] += 1
        metrics['consignment_revenue'] += paid
        metrics['consignment_gain'] += gain
        metrics['losing_consignments'] += gain < 0
        self.trade_history.append(dict(tick=self.tick, year=self.year, kind='delivery', actor=journey['owner'],
                                       settlement=target.id, origin=origin.id, journey=journey['id'],
                                       resource=next(iter(journey['delivered_cargo']), None),
                                       amount=sum(journey['delivered_cargo'].values()),
                                       unit_price=journey['unit_price'], coins=paid, gain=gain))
        self._remember_consignment(journey, 'delivered', gain)
        self._event('delivery', f'Consignment {journey["id"]} reached {target.name}; its merchant was paid '
                    f'{paid:g} coins from escrow.', target.name, journey_id=journey['id'])

    def _fail_caravan(self, journey, reason):
        cargo = dict(journey['cargo'])
        super()._fail_caravan(journey, reason)
        if 'origin_value' in journey:
            journey['gain'] = -journey['origin_value']
        if not journey.get('consignment'):
            return
        gain = -journey['origin_value']
        journey['gain'] = gain
        metrics = self.market_metrics
        metrics['consignments_lost'] += 1
        metrics['consignment_gain'] += gain
        metrics['losing_consignments'] += 1
        self.trade_history.append(dict(tick=self.tick, year=self.year, kind='loss', actor=journey['owner'],
                                       settlement=journey['destination'], origin=journey['origin'],
                                       journey=journey['id'], resource=next(iter(cargo), None),
                                       amount=sum(cargo.values()), unit_price=journey['unit_price'],
                                       coins=0., gain=gain, reason=reason))
        self._remember_consignment(journey, 'lost', gain)

    def _annual_economy(self):
        before = {town: dict(flows['production']) for town, flows in self._flows.items()}
        super()._annual_economy()
        if hasattr(self, 'market_production'):
            # Last year's recorded output becomes the expected production behind prices.
            self.market_production = {town: {r: self._flows[town]['production'][r] - before[town][r]
                                              for r in GOODS} for town in before}

    def advance_time(self):
        super().advance_time()
        if hasattr(self, 'market_prices'):
            self._update_prices()
            if self.snapshots and self.snapshots[-1].get('tick') == self.tick:
                # Annual snapshots show the prices posted for the cycle that begins.
                self.snapshots[-1]['market'] = self._market_snapshot()

    def _market_snapshot(self):
        return dict(prices=deepcopy(self.market_prices), coverage=deepcopy(self.market_coverage),
                    metrics=dict(self.market_metrics))

    def has_municipal_authority(self, institution):
        if not institution.active or getattr(institution, 'purpose', None) != 'council':
            return False
        frame = self.institution_frame(institution)
        if not frame or not frame['active']:
            return False
        current = {a.id for a in self.agents if a.home == institution.settlement_id
                   and not self.is_traveling(a.id)}
        supporters = institution.members & set(frame['members']) & current
        return (len(supporters) >= 2 and len(supporters) * 2 > len(current)
                and len(supporters) * 2 > frame.get('local_named_count', len(current)))

    def require_municipal_authority(self, institution):
        _require(self.has_municipal_authority(institution), 'insufficient_authority',
                 'Municipal authority requires a council representing a strict majority of local named residents at tick start and now.')

    def open_work_order(self, settlement, employer, terms, wage_budget, *, institution=None, proposal=None):
        """Record a job whose full wage budget the caller has already moved into escrow."""
        order = dict(id=self.next_work_order_id, settlement=settlement.id, employer=dict(employer),
                     institution=institution, proposal=proposal,
                     created=self.tick, expires=self.tick + ORDER_TICKS, status='open',
                     remaining=terms['quantity'], escrow=wage_budget, **terms)
        self.next_work_order_id += 1
        self.work_orders.append(order)
        return order

    def order_recipient(self, order):
        """Who receives delivered output now: a town store, live organization or present employer."""
        employer, town = order['employer'], self.settlements[order['settlement']]
        if employer['kind'] == 'municipal':
            return town
        if employer['kind'] == 'institution':
            institution = next((i for i in self.institutions if i.id == employer['id']), None)
            return institution if institution is not None and institution.active else None
        person = next((a for a in self.agents if a.id == employer['id']), None)
        if person is None or person.home != town.id or self.is_traveling(person.id):
            return None  # goods are never teleported to an absent employer
        return person

    def _refund_target(self, order):
        employer, town = order['employer'], self.settlements[order['settlement']]
        if employer['kind'] == 'institution':
            institution = next((i for i in self.institutions if i.id == employer['id']), None)
            # A collapsed organization's reserves already returned to its town.
            return institution if institution is not None and institution.active else town
        if employer['kind'] == 'person':
            person = next((a for a in self.agents if a.id == employer['id']), None)
            # A deceased employer's escrow joins the estate held by the successor.
            heir = person or next((a for a in self.agents if a.parent_id == employer['id']), None)
            return heir or town
        return town

    def refund_order(self, order, status):
        """Close an order and return all unused escrow to whoever funded it."""
        target, amount = self._refund_target(order), order['escrow']
        if hasattr(target, 'treasury'):  # a settlement or an institution
            target.treasury += amount
        else:
            target.inventory['coins'] += amount
        order.update(escrow=0., status=status)
        return target

    def caravan_quote(self, actor, contract_id, amount):
        details = super().caravan_quote(actor, contract_id, amount)
        route = details['route']
        for field in ('exporter_institution', 'importer_institution'):
            self.require_municipal_authority(self._resolve_institution(route[field]))
        return details

    def resource_totals(self):
        totals = super().resource_totals()
        totals['coins'] += sum(order['escrow'] for order in getattr(self, 'work_orders', ()))
        return totals

    def _account_action(self, action, result, before):
        super()._account_action(action, result, before)
        if not result.success or not hasattr(self, 'work_history'):
            return
        kind, effects = action['type'], result.effects
        actor = action['actor']
        record = None
        if kind in ('trade', 'consign') and hasattr(self, 'market_metrics'):
            self._record_market_action(action, effects)
        if kind == 'work':
            paid = effects['coins']
            self.earnings[actor] = self.earnings.get(actor, 0.) + paid
            self.economic_metrics['wages_paid'] += paid
            self.economic_metrics['paid_work_actions'] += 1
            record = dict(mode='paid', purpose=effects['purpose']['kind'], coins=paid,
                          resource=effects['resource'], amount=effects['amount'],
                          payer=effects['payer'], employer=effects['employer'], order=effects['order_id'])
        elif kind == 'enact' and effects.get('project') == 'work_order':
            self.economic_metrics['municipal_orders'] += 1
        elif kind == 'enact' and effects.get('project') == 'commission':
            self.economic_metrics['commissions'] += 1
        elif kind == 'hire':
            self.economic_metrics['private_orders'] += 1
        elif kind in ('gather', 'contribute', 'collaborate', 'teach', 'build', 'research', 'dispatch_caravan'):
            purpose = effects.get('purpose', {'kind': {
                'collaborate': 'voluntary_construction_aid', 'teach': 'voluntary_knowledge_sharing',
                'build': 'personal_property', 'research': 'personal_knowledge',
                'dispatch_caravan': 'voluntary_public_transport',
            }.get(kind, 'personal_inventory')})
            voluntary = purpose['kind'].startswith('voluntar')
            record = dict(mode='voluntary' if voluntary else 'personal', purpose=purpose,
                          coins=0., resource=effects.get('resource'), amount=effects.get('amount', 0),
                          institution=effects.get('institution_id'))
            if voluntary:
                self.economic_metrics['volunteer_actions'] += 1
                planned = self._economic_choices.get(actor, {})
                quote = planned.get('paid_alternative_quote', 0.) if planned.get('tick') == self.tick else 0.
                record['paid_alternative_quote'] = quote
                if quote > 0:
                    self.economic_metrics['voluntary_with_paid_option'] += 1
                if kind == 'contribute':
                    record['donated_resource'] = effects['resource']
                    record['donated_amount'] = effects['amount']
                    if effects['resource'] == 'coins':
                        self.economic_metrics['donated_coins'] += effects['amount']
        elif kind == 'trade' and effects.get('direction') == 'sell':
            record = dict(mode='paid_sale', purpose='personal_goods_sale',
                          coins=effects['price'], payer=action['location'],
                          resource=effects['resource'], amount=effects['amount'])
        elif kind == 'accept':
            actor = effects['seller']
            record = dict(mode='paid_sale', purpose='peer_goods_sale',
                          coins=effects['coins'], payer=effects['buyer'],
                          resource=effects['resource'], amount=effects['amount'])
        if record:
            self.work_history.append(dict(tick=self.tick, actor=actor, action=kind,
                                          settlement=action['location'], **record))

    def _record_market_action(self, action, effects):
        metrics, actor = self.market_metrics, action['actor']
        entry = dict(tick=self.tick, year=self.year, actor=actor, resource=effects['resource'],
                     amount=effects['amount'], unit_price=effects['unit_price'])
        if action['type'] == 'trade':
            buy = effects['direction'] == 'buy'
            metrics['purchases' if buy else 'sales'] += 1
            metrics['units_bought' if buy else 'units_sold'] += effects['amount']
            metrics['retail_spent' if buy else 'retail_received'] += effects['price']
            entry.update(kind='purchase' if buy else 'sale', settlement=action['location'], coins=effects['price'])
        else:
            metrics['consignments'] += 1
            metrics['consigned_units'] += effects['amount']
            entry.update(kind='consignment', settlement=effects['destination'], origin=action['location'],
                         journey=effects['journey_id'], coins=effects['coins'],
                         expected_gain=effects['expected_gain'])
        self.trade_history.append(entry)

    def _maintain_work_orders(self):
        for order in self.work_orders:
            if order['status'] != 'open':
                continue
            employer = order['employer']
            if employer['kind'] == 'municipal':
                sponsor = self._resolve_institution(order['institution'])
                closed = self.tick >= order['expires'] or not sponsor.active
            else:
                # An absent private employer or a collapsed organization cannot
                # receive output, so its job closes rather than idling in escrow.
                closed = self.tick >= order['expires'] or self.order_recipient(order) is None
            if closed:
                target = self.refund_order(order, 'expired')
                owner = getattr(target, 'name', 'its funder')
                self._event('work', f'Order {order["id"]} closed; {order["remaining"]} unworked units '
                            f'and their unused wages returned to {owner}.', order_id=order['id'])

    def plan(self, observations):
        self._economic_choices = {}
        for identity, observation in observations.items():
            person = observation['actor']
            energy = person['energy']
            quotes = []
            for order in observation.get('municipality', {}).get('work_orders', []):
                if (WORK_SKILLS[order['resource']] not in person['skills']
                        or order['employer'] == {'kind': 'person', 'id': identity}):
                    continue
                quantity = min(8, order['remaining'], math.floor(energy / 2),
                               math.floor(observation['settlement']['deposits'][order['resource']]))
                quotes.append(quantity * order['unit_wage'])
            self._economic_choices[identity] = {'tick': self.tick,
                                               'paid_alternative_quote': max(quotes, default=0.)}
        return super().plan(observations)

    @contextmanager
    def _transaction(self):
        if getattr(self, '_transaction_active', False):
            yield
            return
        # History is append-only; snapshot active state and list lengths without
        # copying the entire accumulated history every cycle.
        histories = {key: (value, len(value)) for key, value in vars(self).items()
                     if key in ('events', 'snapshots', 'action_log', 'decisions', 'work_history',
                                'price_history', 'trade_history')}
        state = deepcopy({key: value for key, value in vars(self).items()
                          if key not in histories and key != 'action_engine'})
        self._transaction_active = True
        try:
            yield
        except Exception:
            for value, length in histories.values():
                del value[length:]
            engine = self.action_engine
            self.__dict__.clear()
            self.__dict__.update(state)
            self.__dict__.update({key: pair[0] for key, pair in histories.items()})
            self.action_engine = engine
            raise
        finally:
            self._transaction_active = False

    def step(self):
        with self._transaction():
            self._maintain_work_orders()
            return super().step()

    def resolve_actions(self, proposals):
        with self._transaction():
            self._maintain_work_orders()
            return super().resolve_actions(proposals)

    def observe(self, actor):
        observation = super().observe(actor)
        if not hasattr(self, 'work_orders'):
            return observation
        person = self._resolve_agent(actor)
        workable = lambda o: o['status'] == 'open' and o['created'] < self.tick < o['expires']
        # A funded job is a public notice. Neighbors learn its terms and how much
        # has been claimed, never the employer's other accounts or hidden reserves.
        nearby = {neighbor['id'] for neighbor in observation.get('neighbors', [])}
        observation['municipality'] = dict(
            charter='majority_local_council', retail_limit=8,
            authorities={i.id: self.has_municipal_authority(i) for i in self.institutions},
            work_orders=deepcopy([o for o in self.work_orders
                                  if o['settlement'] == person.home and workable(o)]),
            job_board=[{k: deepcopy(o[k]) for k in ('id', 'settlement', 'employer', 'resource', 'quantity',
                                                    'remaining', 'unit_wage', 'created', 'expires')}
                       for o in self.work_orders if o['settlement'] in nearby and workable(o)],
            earnings=self.earnings.get(person.id, 0.))
        if hasattr(self, 'market_prices'):
            # Posted prices are public notices at home and in neighboring towns.
            home = person.home
            visible = sorted({home, *nearby})
            local = dict(self.market_prices[home])
            observation['rules'] = {**observation.get('rules', {}), 'prices': local, 'bid_share': BID_SHARE}
            if 'regional' in observation:
                observation['regional']['prices'] = dict(local)
            observation['prices'] = dict(home=home, base=dict(BASE_PRICES), bid_share=BID_SHARE,
                                         wage_share=WAGE_SHARE,
                                         posted={town: dict(self.market_prices[town]) for town in visible},
                                         coverage={home: dict(self.market_coverage[home])})
        return observation

    def geological_observations(self, person):
        # Paid extraction is personal evidence of actual collection too. Keep
        # its original location and amount; never consult buried reserves.
        observer = copy(person)
        observer.memory = []
        for memory in person.memory:
            action, result = memory.get('action', {}), memory.get('result', {})
            if (action.get('type') == 'work' and result.get('success')
                    and result.get('effects', {}).get('resource') == 'iron'):
                memory = {**memory, 'action': {**action, 'type': 'gather', 'params': {'resource': 'iron'}}}
            observer.memory.append(memory)
        return super().geological_observations(observer)

    def _snapshot(self):
        super()._snapshot()
        if hasattr(self, 'work_orders'):
            self.snapshots[-1].update(work_orders=deepcopy(self.work_orders),
                                     economic_metrics=dict(self.economic_metrics),
                                     earnings=dict(self.earnings),
                                     work_history_count=len(self.work_history))
        if hasattr(self, 'market_prices'):
            self.snapshots[-1].update(market=self._market_snapshot(),
                                     trade_history_count=len(self.trade_history))

    def _assert_invariants(self):
        super()._assert_invariants()
        for order in getattr(self, 'work_orders', ()):
            assert math.isfinite(order['escrow']) and order['escrow'] >= -1e-7
            if order['status'] == 'open':
                assert math.isclose(order['escrow'], order['remaining'] * order['unit_wage'], abs_tol=1e-7)
            else:
                assert abs(order['escrow']) < 1e-7
        for town, prices in getattr(self, 'market_prices', {}).items():
            for resource, price in prices.items():
                low, high = bounds(resource)
                assert math.isfinite(price) and low <= price <= high, (town, resource, price)

    def export(self):
        data = super().export()
        data.update(schema='eternia.v0.7', mode='society', provenance=deepcopy(self.provenance),
                    work_orders=deepcopy(self.work_orders), work_history=deepcopy(self.work_history),
                    economic_metrics=dict(self.economic_metrics), earnings=dict(self.earnings),
                    market=dict(rule=dict(reserve_per_resident=dict(RESERVE_PER_RESIDENT),
                                          use_per_resident=dict(USE_PER_RESIDENT),
                                          base_prices=dict(BASE_PRICES), bid_share=BID_SHARE,
                                          wage_share=WAGE_SHARE, floor=PRICE_FLOOR, ceiling=PRICE_CEILING,
                                          max_step=MAX_STEP, consignment_limit=CONSIGNMENT_LIMIT),
                                prices=deepcopy(self.market_prices), coverage=deepcopy(self.market_coverage),
                                production=deepcopy(self.market_production), history=deepcopy(self.price_history)),
                    trade_history=deepcopy(self.trade_history), market_metrics=dict(self.market_metrics),
                    note='The Living Economy. Towns post prices from local supply and demand; people buy, sell, hire '
                         'and consign goods to neighboring markets at those prices. Councils, voluntary organizations '
                         'and individuals escrow wages from their own money; funded jobs are public across neighboring '
                         'towns. Utility policies propose; the world applies the charter.')
        return data

