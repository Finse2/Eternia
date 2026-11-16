"""v0.7: explicit work compensation and municipal jurisdiction.

The charter covers the represented local electorate, not all aggregate residents.
Only a majority local council may authorize municipal funds. Paid extraction
moves finite material into town storage and existing escrow coins to a worker.
"""
from copy import copy, deepcopy
from contextlib import contextmanager
import math

from .actions import _number, _require
from .community import RESOURCES
from .institutions import approved
from .logistics_engine import LogisticsEngine
from .physical_world import PhysicalWorld
from .regional_engine import RegionalEngine


MUNICIPAL_KINDS = {'work_order', 'trade_terms', 'specialization',
                   'communal_labor', 'migration_policy', 'route_access'}
WORK_SKILLS = {'food': 'foraging', 'wood': 'woodcutting', 'iron': 'mining'}


class SocietyEngine(LogisticsEngine):
    parameters = {**LogisticsEngine.parameters,
                  'gather': {'resource', 'amount', 'purpose'},
                  'contribute': {'institution', 'resource', 'amount', 'purpose'},
                  'work': {'order', 'amount'}}

    def _check_trade(self, actor, settlement, params):
        details = super()._check_trade(actor, settlement, params)
        _require(details['amount'] <= 8, 'retail_limit',
                 'The standing municipal retail charter permits at most eight units per action.')
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
        if kind != 'work_order':
            return super()._proposal_params(kind, params, settlement)
        _require(type(params) is dict and set(params) == {'resource', 'quantity', 'unit_wage'},
                 'invalid_action', 'A work order requires resource, quantity and unit_wage.')
        resource = params.get('resource')
        _require(type(resource) is str and resource in WORK_SKILLS,
                 'invalid_resource', 'Public work extracts food, wood or iron.')
        return {'resource': resource,
                'quantity': _number(params['quantity'], 'quantity', minimum=1, maximum=24, integral=True),
                'unit_wage': _number(params['unit_wage'], 'unit_wage', minimum=.1, maximum=5)}

    def _check_propose(self, actor, settlement, params):
        # Public road access is not private ownership acquired by making a repair.
        if params.get('kind') == 'route_access':
            details = RegionalEngine._check_propose(self, actor, settlement, params)
        else:
            details = super()._check_propose(actor, settlement, params)
        if details['kind'] in MUNICIPAL_KINDS:
            self.world.require_municipal_authority(details['institution'])
        if details['kind'] == 'work_order':
            resource = details['params']['resource']
            _require(not any(o['settlement'] == settlement.id and o['resource'] == resource
                             and o['status'] == 'open' for o in self.world.work_orders),
                     'active_order', 'A live funded order for this resource already exists.')
        return details

    def _check_enact(self, actor, settlement, params):
        institution, frame = self._institution(actor, settlement, params)
        proposal = self._proposal(institution, params)
        kind = proposal['kind']
        if kind in MUNICIPAL_KINDS:
            self.world.require_municipal_authority(institution)
        if kind not in ('work_order', 'route_access'):
            details = super()._check_enact(actor, settlement, params)
            if kind == 'trade_terms':
                self.world.require_municipal_authority(details['reciprocal'][0])
            return details
        _require(approved(self.world, institution, proposal, frame), 'not_approved',
                 'Public spending requires a prior-tick majority and two affirmative voters.')
        normalized = self._proposal_params(kind, proposal['params'], settlement)
        if kind == 'work_order':
            _require(not any(o['settlement'] == settlement.id and o['resource'] == normalized['resource']
                             and o['status'] == 'open' for o in self.world.work_orders),
                     'active_order', 'A funded order for this resource is already open.')
            wage_budget = normalized['quantity'] * normalized['unit_wage']
            _require(self.world._municipal_available(settlement, 'coins') + 1e-9 >= wage_budget,
                     'insufficient_resources', 'The municipality cannot escrow the approved wages.')
            return dict(institution=institution, proposal=proposal, params=normalized,
                        wage_budget=wage_budget, costs={}, energy=2)
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
        _require(order['remaining'] >= amount and settlement.deposits[resource] >= amount,
                 'depleted', 'The order or accessible material cannot support this work.')
        _require(order['escrow'] + 1e-9 >= amount * order['unit_wage'],
                 'insufficient_resources', 'The promised wage is not funded.')
        return dict(order=order, resource=resource, amount=amount, energy=amount * 2)

    def _apply(self, action, actor, settlement, details):
        if action.type == 'work':
            order, amount, resource = details['order'], details['amount'], details['resource']
            paid = min(order['escrow'], amount * order['unit_wage'])
            settlement.deposits[resource] -= amount
            setattr(settlement, resource, getattr(settlement, resource) + amount)
            actor.inventory['coins'] += paid
            order['escrow'] -= paid
            order['remaining'] -= amount
            if order['remaining'] == 0:
                # Refund floating point dust through a transfer, never a money sink.
                settlement.treasury += order['escrow']
                order.update(escrow=0., status='completed')
            return dict(order_id=order['id'], resource=resource, amount=amount, coins=paid,
                        payer=settlement.id, purpose={'kind': 'paid_municipal_work'},
                        message=f'{actor.name} delivered {amount} {resource} under order {order["id"]} and earned {paid:g} escrowed coins.')
        if action.type == 'enact' and details['proposal']['kind'] == 'work_order':
            order = dict(id=self.world.next_work_order_id, settlement=settlement.id,
                         institution=details['institution'].id, proposal=details['proposal']['id'],
                         created=self.world.tick, expires=self.world.tick + 12, status='open',
                         remaining=details['params']['quantity'], escrow=details['wage_budget'],
                         **details['params'])
            self.world.next_work_order_id += 1
            self.world.work_orders.append(order)
            settlement.treasury -= details['wage_budget']
            details['proposal'].update(status='enacted', enacted=self.world.tick, executed_by=actor.id)
            self._metric('institution_enactments')
            return dict(order_id=order['id'], wage_budget=details['wage_budget'], costs={},
                        institution_id=details['institution'].id, project='work_order',
                        message=f'{actor.name} funded public order {order["id"]} with {order["escrow"]:g} existing municipal coins.')
        prior_owner = details.get('link', {}).get('owner')
        result = super()._apply(action, actor, settlement, details)
        if action.type == 'gather':
            result['purpose'] = details['purpose']
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
                                     voluntary_with_paid_option=0, donated_coins=0.)
        self.earnings = {}
        self._economic_choices = {}
        self._transaction_active = False
        self._default_policy = EconomicPolicy(policy_style)
        self.action_engine = SocietyEngine(self)
        self.provenance = run_manifest(self)
        self.snapshots = []
        self._event('charter', 'Municipal funds require a majority local council; work wages are escrowed; public-road maintenance grants no private ownership.')
        self._snapshot()

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
        if kind == 'work':
            paid = effects['coins']
            self.earnings[actor] = self.earnings.get(actor, 0.) + paid
            self.economic_metrics['wages_paid'] += paid
            self.economic_metrics['paid_work_actions'] += 1
            record = dict(mode='paid', purpose='municipal_output', coins=paid,
                          resource=effects['resource'], amount=effects['amount'],
                          payer=effects['payer'], order=effects['order_id'])
        elif kind == 'enact' and effects.get('project') == 'work_order':
            self.economic_metrics['municipal_orders'] += 1
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

    def _maintain_work_orders(self):
        for order in self.work_orders:
            if order['status'] != 'open':
                continue
            institution = self._resolve_institution(order['institution'])
            if self.tick >= order['expires'] or not institution.active:
                self.settlements[order['settlement']].treasury += order['escrow']
                order.update(escrow=0., status='expired')
                self._event('work', f'Order {order["id"]} closed; unused wages returned to its municipality.')

    def plan(self, observations):
        self._economic_choices = {}
        for identity, observation in observations.items():
            person = observation['actor']
            energy = person['energy']
            quotes = []
            for order in observation.get('municipality', {}).get('work_orders', []):
                if WORK_SKILLS[order['resource']] not in person['skills']:
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
                     if key in ('events', 'snapshots', 'action_log', 'decisions', 'work_history')}
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
        observation['municipality'] = dict(
            charter='majority_local_council', retail_limit=8,
            authorities={i.id: self.has_municipal_authority(i) for i in self.institutions},
            work_orders=deepcopy([o for o in self.work_orders
                                  if o['settlement'] == person.home and o['status'] == 'open'
                                  and o['created'] < self.tick < o['expires']]),
            earnings=self.earnings.get(person.id, 0.))
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

    def _assert_invariants(self):
        super()._assert_invariants()
        for order in getattr(self, 'work_orders', ()):
            assert math.isfinite(order['escrow']) and order['escrow'] >= -1e-7
            if order['status'] == 'open':
                assert math.isclose(order['escrow'], order['remaining'] * order['unit_wage'], abs_tol=1e-7)
            else:
                assert abs(order['escrow']) < 1e-7

    def export(self):
        data = super().export()
        data.update(schema='eternia.v0.7', mode='society', provenance=deepcopy(self.provenance),
                    work_orders=deepcopy(self.work_orders), work_history=deepcopy(self.work_history),
                    economic_metrics=dict(self.economic_metrics), earnings=dict(self.earnings),
                    note='Autonomous Society & Persistence. Existing municipal money funds voted, escrowed work; voluntary projects carry purpose. Utility policies propose; the world applies the charter.')
        return data

