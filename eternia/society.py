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

from .actions import RECIPES, _number, _require
from .community import RESOURCES
from .goal_engine import STEPS, describe_goal, describe_step, new_mind, next_step, record_experience, review
from .inequality import snapshot as inequality_snapshot
from .institutions import approved
from .logistics_engine import LogisticsEngine
from .motivations import MOTIVES, experience_deltas, initial_temperament, update as update_motives, update_fairness
from .market import (BASE_PRICES, BID_SHARE, CONSIGNMENT_LIMIT, GOODS, PRICE_CEILING, PRICE_FLOOR,
                     MAX_STEP, RESERVE_PER_RESIDENT, USE_PER_RESIDENT, WAGE_SHARE, bid_price,
                     bounds, coverage, next_price, target_price)
from .physical_world import PhysicalWorld
from .regional_engine import RegionalEngine
from .social_memory import firsthand, relay, spread


PLAYER_INVENTORY = {'food': 3., 'wood': 0., 'iron': 0., 'coins': 10.}
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
                  'hire': JOB_TERMS | {'purpose'},
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
        for home, other in ((settlement, target), (target, settlement)):
            for institution in self.world.institutions:
                if (institution.active and institution.settlement_id == home.id
                        and self.world.has_municipal_authority(institution)
                        and self._embargoed(institution, self.world.institution_frame(institution), other.id)):
                    _require(False, 'embargoed', f'{home.name}\'s council has an embargo on trade with {other.name}.')
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

    def _hire_purpose(self, actor, purpose, resource):
        """v0.9: a job may state the step of the employer's own goal it serves; the statement must be true."""
        if purpose is None:
            return None
        _require(type(purpose) is dict and set(purpose) == {'kind', 'step'} and purpose['kind'] == 'goal'
                 and type(purpose['step']) is str and purpose['step'] in STEPS, 'invalid_purpose',
                 'A job\'s stated purpose names a step of the employer\'s own goal.')
        step = next_step(actor.goal, skills=actor.skills, structures=actor.structures, knowledge=actor.knowledge,
                         food=actor.inventory['food'], recipes=RECIPES)
        _require(step is not None and step['step'] == purpose['step'] and step['materials'].get(resource, 0) > 0,
                 'invalid_purpose', 'A job can only state a purpose its employer is actually pursuing.')
        return dict(purpose)

    def _check_hire(self, actor, settlement, params):
        purpose = params.get('purpose')
        terms = self._job_terms({k: v for k, v in params.items() if k != 'purpose'})
        purpose = self._hire_purpose(actor, purpose, terms['resource'])
        employer = {'kind': 'person', 'id': actor.id}
        _require(not any(o['status'] == 'open' and o['employer'] == employer for o in self.world.work_orders),
                 'active_order', 'Complete or close the current private job before posting another.')
        wage_budget = terms['quantity'] * terms['unit_wage']
        _require(self.world.available_inventory(actor)['coins'] + 1e-9 >= wage_budget,
                 'insufficient_resources', 'A private employer must escrow the full wage budget from available coins.')
        return dict(params=terms, wage_budget=wage_budget, employer=employer, energy=1, purpose=purpose)

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
                                               details['wage_budget'], purpose=details['purpose'])
            stated = f' {describe_step(details["purpose"]["step"])}' if details['purpose'] else ''
            result = dict(order_id=order['id'], wage_budget=details['wage_budget'], employer=deepcopy(order['employer']),
                          message=f'{actor.name} escrowed {details["wage_budget"]:g} personal coins to hire '
                                  f'{order["quantity"]} {order["resource"]}{stated} at {order["unit_wage"]:g} each '
                                  f'(order {order["id"]}).')
            if details['purpose']:
                result['purpose'] = dict(details['purpose'])
            return result
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
                        institution_id=institution.id, project=kind, proposal_id=details['proposal']['id'],
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
                 policy_style='balanced', adaptive_goals=True):
        super().__init__(seed, ticks_per_year, shock_year, policies)
        from .economic_policy import EconomicPolicy
        from .persistence import run_manifest
        if type(adaptive_goals) is not bool:
            raise ValueError('adaptive_goals must be True or False')
        self.policy_style = policy_style
        self.adaptive_goals = adaptive_goals
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
        self.minds = {}
        self.goal_log = []
        self._in_cycle = False
        self.players = set()
        self.player_log = []
        self._player_turns = {}
        self.knowledge = {}  # v0.8 Stage 3: each person's claims, with source and age
        self._talks = {}
        self._ensure_minds()
        self.snapshots = []
        self._event('charter', 'Municipal funds require a majority local council; work wages are escrowed; public-road maintenance grants no private ownership.')
        self._event('market', 'Each town posts prices from its own supply and demand; markets buy at 80% of the posted price.')
        self._mind_event_cursor = len(self.events)
        self._news_cursor = len(self.events)
        self._snapshot()

    # ----- Motivations and adaptive goals --------------------------------

    def _log_goal(self, person, entry):
        self.goal_log.append(dict(tick=self.tick, year=self.year, actor=person.id, name=person.name,
                                  lineage=person.lineage, role=person.role, settlement=person.home,
                                  motivations=dict(self.minds[person.id]['motivations']), **entry))

    def _ensure_minds(self):
        """Give newcomers and heirs a mind; close the goals of people who are gone."""
        living = {a.id: a for a in self.agents}
        players = self.active_players() if hasattr(self, 'players') else set()
        for person in sorted(self.agents, key=lambda a: a.id):
            if person.id in self.minds or person.id in players:
                continue
            parent = self.minds.get(person.parent_id) if person.parent_id is not None else None
            temperament = initial_temperament(
                person.role, curiosity=person.curiosity, ambition=person.ambition,
                openness=getattr(person, 'openness', .5), seed=self.seed, identity=person.id,
                parent=parent['temperament'] if parent else None)
            mind = new_mind(temperament, person, self.tick, 'inherited' if parent else 'assigned')
            mind.update(goal=dict(person.goal), name=person.name, lineage=person.lineage, role=person.role,
                        home=person.home)
            self.minds[person.id] = mind
            if parent:
                deltas = experience_deltas('inheritance')
                mind['motivations'], mind['temperament'] = update_motives(mind['motivations'], mind['temperament'], deltas)
                record_experience(mind, 'inheritance', deltas)
                # An heir grows up with part of the household's view of how fair the town is.
                mind['fairness'] = round((parent.get('fairness', .5) + .5) / 2, 6)
                met = mind['best_value'] + 1e-9 >= person.goal.get('target', 1)
                if met:
                    mind['completed_tick'] = self.tick  # the estate already meets it; not their own success
                self._log_goal(person, dict(event='inherited', goal=dict(person.goal), predecessor=person.parent_id,
                                            reason=f'Inherited the goal to {describe_goal(person.goal)} with the estate'
                                                   + (', which already meets it.' if met else '.')))
            else:
                self._log_goal(person, dict(event='assigned', goal=dict(person.goal),
                                            reason=f'Began with the goal to {describe_goal(person.goal)}.'))
        for identity in sorted(set(self.minds) - set(living)):
            mind = self.minds.pop(identity)
            if mind['completed_tick'] is None:
                self.goal_log.append(dict(tick=self.tick, year=self.year, actor=identity, name=mind['name'],
                                          lineage=mind['lineage'], role=mind['role'], settlement=mind['home'],
                                          event='ended',
                                          goal=dict(mind['goal']), motivations=dict(mind['motivations']),
                                          reason=f'Died or retired before managing to {describe_goal(mind["goal"])}.'))

    # ----- Human players --------------------------------------------------

    def add_player(self, name, home=0, inventory=None):
        """A newcomer controlled by a person: no profession, no privileges, a small purse.

        Their belongings arrive with them and are recorded as an explicit inflow,
        so the accounting identity still holds. They join between cycles only.
        """
        def check(condition, message):
            if not condition:
                raise ValueError(message)
        check(not getattr(self, '_resolving', False) and not getattr(self, '_transaction_active', False),
              'A player joins between cycles, not during one.')
        check(type(name) is str and 0 < len(name.strip()) <= 40, 'A player needs a name of 1 to 40 characters.')
        name = name.strip()
        check(not any(a.name == name for a in self.agents) and not any(s.name == name for s in self.settlements),
              f'The name {name!r} is already taken.')
        town = next((s for s in self.settlements if s.id == home or s.name == home), None)
        check(town is not None, f'There is no settlement called {home!r}.')
        belongings = dict(PLAYER_INVENTORY if inventory is None else inventory)
        check(set(belongings) <= set(RESOURCES) and all(
            type(v) in (int, float) and math.isfinite(v) and 0 <= v <= 1000 for v in belongings.values()),
            'Starting goods must be food, wood, iron or coins between 0 and 1000.')
        belongings = {r: float(belongings.get(r, 0.)) for r in RESOURCES}
        from .civilizations import RegionalCitizen
        person = RegionalCitizen(self.next_agent_id, name, town.id, 'newcomer', .5, .5, 25,
                                 inventory=belongings, skills=['foraging', 'trading'], goal={},
                                 lineage=name, wealth_goal=0., openness=.5, origin=town.id,
                                 preferred_purpose='cooperative')
        self.next_agent_id += 1
        self.agents.append(person)
        self.agents.sort(key=lambda a: a.id)
        town.population += 1
        for resource, amount in belongings.items():
            self.ledger['produced'][resource] += amount  # an arrival from outside the region
        self.players.add(person.id)
        self.player_log.append(dict(event='joined', tick=self.tick, actor=person.id, name=name, home=town.id,
                                    inventory=dict(belongings)))
        self._event('arrival', f'{name} arrived in {town.name} to make a living.', town.name, name,
                    actor_id=person.id, player=True)
        self._assert_invariants()
        return person

    def remove_agent(self, actor_id, cause='old age'):
        identity = self._resolve_agent(actor_id).id
        successor = super().remove_agent(actor_id, cause)
        if identity in getattr(self, 'players', ()) and identity not in {a.id for a in self.agents}:
            self._pass_control(identity, successor)  # a traveler's death waits for their arrival
        return successor

    def _pass_control(self, identity, heir):
        """The household goes on: the player continues as the heir, under the ordinary inheritance rules."""
        self.players.discard(identity)
        self._player_turns.pop(identity, None)
        if heir is None or heir not in self.agents:
            return
        self.players.add(heir.id)
        self.minds.pop(heir.id, None)  # no mind of their own to override the player's choices
        self.player_log.append(dict(event='heir', tick=self.tick, actor=heir.id, predecessor=identity, name=heir.name))
        self._event('player', f'{heir.name} inherits the estate; the player continues as them.',
                    self.settlements[heir.home].name, heir.name, actor_id=heir.id, player=True)

    def active_players(self):
        """The people a player controls right now."""
        living = {a.id for a in self.agents}
        for identity in sorted(self.players - living):
            # A death that bypassed remove_agent here, such as one on arriving from a journey.
            self._pass_control(identity, next((a for a in self.agents if a.parent_id == identity), None))
        return set(self.players)

    def queue_player_action(self, player, proposal):
        """Hold a player's proposal for the next cycle, where it is resolved with everyone else's."""
        if player not in self.active_players():
            raise ValueError('Only a living player can queue an action.')
        if not isinstance(proposal, dict):
            raise ValueError('An action must be a JSON object such as {"type": "rest", "params": {}}.')
        proposal = deepcopy(proposal)
        if proposal.setdefault('actor', player) not in (player, self._resolve_agent(player).name):
            raise ValueError('A player can only act as themselves.')
        proposal['actor'] = player
        proposal.setdefault('params', {})
        self._player_turns[player] = proposal
        return deepcopy(proposal)

    def reset_minds(self):
        """Re-derive every mind from current traits, for scenario setup before any decision."""
        self.minds, self.goal_log = {}, []
        self._ensure_minds()

    def _goal_context(self, person):
        town, mind = self.settlements[person.home], self.minds[person.id]
        prices = self.market_prices.get(person.home, BASE_PRICES)
        recipe = RECIPES['house']
        house_cost = (recipe['coins'] + max(0., recipe['wood'] - person.inventory['wood']) * prices['wood']
                      + max(0., recipe['iron'] - person.inventory['iron']) * prices['iron'])
        memberships = [i for i in self.institutions if i.active and person.id in i.members]
        return dict(member=bool(memberships),
                    council_member=any(getattr(i, 'purpose', None) == 'council' and self.has_municipal_authority(i)
                                       for i in memberships),
                    food_access=('foraging' in person.skills and town.deposits.get('food', 0) >= 1)
                    or (town.food >= 1 and person.inventory['coins'] >= prices['food']),
                    house_cost=house_cost, inconclusive=mind['research']['inconclusive'],
                    materials=person.inventory['wood'] >= 1 and person.inventory['iron'] >= 1)

    def _experiences(self, results):
        """What each living person went through this cycle, from authoritative outcomes only."""
        living = {a.id: a for a in self.agents}
        found = {identity: {} for identity in living}

        def note(identity, kind):
            if identity in found:
                found[identity][kind] = found[identity].get(kind, 0) + 1

        for audit in results:
            action, result = audit['action'], audit['result']
            if not result.get('success'):
                continue
            actor, kind, effects = action.get('actor'), action.get('type'), result.get('effects', {})
            if kind == 'work':
                if effects.get('coins', 0) > 0:
                    note(actor, 'income')
                # A worker knows their wage and what the local market pays sellers for the same goods.
                offer = bid_price(self.market_prices[action['location']][effects['resource']])
                wage = effects.get('coins', 0.) / max(1, effects.get('amount', 1))
                trust = .01
                if wage < .5 * offer:
                    note(actor, 'underpaid')
                    trust = -.04
                elif wage >= .75 * offer:
                    note(actor, 'fair_pay')
                    trust = .03
                employer = effects.get('employer', {})
                if employer.get('kind') == 'person':
                    self._adjust_trust(actor, employer['id'], trust)
                    self._adjust_trust(employer['id'], actor, .02)
            elif kind == 'trade' and effects.get('direction') == 'sell':
                note(actor, 'income')
            elif kind == 'accept':
                note(effects.get('seller'), 'income')
            elif kind == 'teach':
                note(actor, 'taught')
                note(effects.get('partner'), 'learned')
            elif kind == 'collaborate':
                note(actor, 'cooperation')
                note(effects.get('partner'), 'cooperation')
            elif kind in ('contribute', 'join_institution', 'form_institution'):
                note(actor, 'cooperation')
                if kind == 'contribute' and actor in living:
                    living[actor].reputation = min(1., living[actor].reputation + .01)  # public generosity
            elif kind in ('vote', 'propose'):
                note(actor, 'civic')
            elif kind == 'enact':
                note(actor, 'enactment')
                institution = next((i for i in self.institutions if i.id == effects.get('institution_id')), None)
                decision = next((d for d in institution.decisions if d['id'] == effects.get('proposal_id')),
                                {}) if institution is not None else {}
                votes = decision.get('votes', {})
                if institution is not None and effects.get('project') in ('distribute_food', 'granary',
                                                                          'work_order', 'commission'):
                    # Working together on something that delivers builds trust in those who made it happen.
                    for member in institution.members:
                        note(member, 'mutual_aid')
                        for voter, vote in votes.items():
                            if vote.get('approve') is True:
                                self._adjust_trust(member, voter, .01)
                elif institution is not None and effects.get('project') == 'tax_rate':
                    # A contested levy strains relations between its supporters and opponents.
                    sides = {voter: vote.get('approve') for voter, vote in votes.items()}
                    for voter, side in sides.items():
                        for other, other_side in sides.items():
                            if side is not None and other_side is not None and side != other_side:
                                self._adjust_trust(voter, other, -.03)
                if institution is not None and effects.get('project') == 'distribute_food' and effects.get('recipient') in living:
                    note(effects['recipient'], 'helped')
                    for voter, vote in votes.items():
                        if vote.get('approve') is True:
                            self._adjust_trust(effects['recipient'], voter, .04)
            elif kind == 'build':
                note(actor, 'built')
            elif kind == 'research' and actor in self.minds:
                research = self.minds[actor]['research']
                research['attempts'] += 1
                note(actor, 'experiment')
                if effects.get('discovered'):
                    note(actor, 'discovery')
                elif effects.get('topic') == 'aether':
                    research['inconclusive'] += 1
        for person in living.values():
            for memory in reversed(person.memory):
                if memory.get('tick') != self.tick:
                    break
                if memory.get('kind') == 'observation':
                    note(person.id, 'witnessed')
                elif memory.get('kind') == 'consignment' and memory.get('gain', 0) < 0:
                    note(person.id, 'loss')
        towns = {town.name: town.id for town in self.settlements}
        names = {person.name: person.id for person in living.values()}
        for event in self.events[self._mind_event_cursor:]:
            if event.get('kind') == 'death' and event.get('settlement') in towns:
                for person in living.values():
                    if person.home == towns[event['settlement']] and person.id != event.get('successor_id'):
                        note(person.id, 'bereavement')
            elif event.get('kind') == 'levy' and event.get('agent') in names:
                note(names[event['agent']], 'taxed')
        self._mind_event_cursor = len(self.events)
        for person in living.values():
            inventory = person.inventory
            if person.starvation_ticks > 0:
                note(person.id, 'starvation')
            elif person.hunger >= 65:
                note(person.id, 'hunger')
            elif inventory['food'] >= 3 and inventory['coins'] >= 20 and person.hunger < 35:
                note(person.id, 'secure')
            if inventory['coins'] < 5:
                note(person.id, 'poverty')
            if self.is_traveling(person.id):
                continue
            town, price = self.settlements[person.home], self.market_prices[person.home]['food']
            if person.hunger >= 35 and inventory['food'] < 1 and town.food >= 1 and inventory['coins'] < price:
                note(person.id, 'priced_out')
            if (inventory['coins'] < 10 and 'income' not in found[person.id]
                    and not any(o['status'] == 'open' and o['settlement'] == person.home and o['remaining'] >= 1
                                and o['created'] < self.tick < o['expires']
                                and WORK_SKILLS[o['resource']] in person.skills
                                and o['employer'] != {'kind': 'person', 'id': person.id}
                                for o in self.work_orders)):
                note(person.id, 'idle_poor')
            peers = [p.id for p in living.values() if p.home == person.home and p.id != person.id]
            trust = sum(person.trust.get(p, 0.) for p in peers) / max(1, len(peers))
            if trust >= .3:
                note(person.id, 'trusted')
            elif trust <= -.3:
                note(person.id, 'estranged')
            if any(i.active and person.id in i.members for i in self.institutions):
                note(person.id, 'membership')
        return found

    def _review_minds(self, results):
        """Once per cycle: experiences move motives, then each person keeps or revises their goal."""
        self._ensure_minds()
        found = self._experiences(results)
        for person in sorted(self.agents, key=lambda a: a.id):
            if person.id not in self.minds:
                continue  # a player decides for themselves
            mind = self.minds[person.id]
            deltas = {}
            for kind, count in sorted(found.get(person.id, {}).items()):
                change = experience_deltas(kind, ambition=person.ambition, count=count)
                record_experience(mind, kind, change, count)
                for motive, value in change.items():
                    deltas[motive] = deltas.get(motive, 0.) + value
            mind['motivations'], mind['temperament'] = update_motives(mind['motivations'], mind['temperament'], deltas)
            mind['fairness'] = update_fairness(mind.get('fairness', .5), found.get(person.id, {}))
            mind['home'] = person.home
            for entry in review(person, mind, self._goal_context(person), tick=self.tick,
                                adaptive=self.adaptive_goals, experienced=found.get(person.id, {})):
                self._log_goal(person, entry)
            mind['goal'] = dict(person.goal)

    def _adjust_trust(self, person, other, change):
        """Authoritative trust change after an economic interaction both sides took part in."""
        holder = next((a for a in self.agents if a.id == person), None)
        if holder is None or other == person or not any(a.id == other for a in self.agents):
            return
        holder.trust[other] = round(min(1., max(-1., holder.trust.get(other, 0.) + change)), 6)

    def _contested(self, action):
        """What an action claims from a shared, limited supply, if anything."""
        params, kind = action.get('params', {}), action.get('type')
        place = action.get('location')
        if place is None:  # a refused action is audited without one; people act where they live
            place = next((a.home for a in self.agents if a.id == action.get('actor')), None)
        if kind == 'trade' and params.get('direction') == 'buy':
            return ('market', place, params.get('resource'))
        if kind == 'gather':
            return ('deposit', place, params.get('resource'))
        if kind == 'work':
            return ('order', params.get('order'))
        return None

    def _social_consequences(self, results):
        """v0.8 Stage 2: how people regard each other after contested goods and gifts, for everyone alike."""
        for audit in results:
            action, result = audit['action'], audit['result']
            actor = action.get('actor')
            if result.get('code') == 'conflict':
                # Losing the last goods, deposits or paid work to someone else in the
                # same cycle sours a person a little on whoever got them.
                subject = self._contested(action)
                if subject is None:
                    continue
                for other in results:
                    rival = other['action'].get('actor')
                    if (other['result'].get('success') and rival != actor
                            and self._contested(other['action']) == subject):
                        self._adjust_trust(actor, rival, -.03)
            elif result.get('success') and action.get('type') == 'contribute':
                # Fellow members notice a gift to what they share.
                institution = next((i for i in self.institutions
                                    if i.id == result.get('effects', {}).get('institution_id')), None)
                for member in sorted(institution.members if institution is not None else ()):
                    self._adjust_trust(member, actor, .02)

    def _learn(self, results):
        """v0.8 Stage 3: what each person experienced this cycle and saw around them since the last."""
        living = {a.id: a for a in self.agents}
        towns = {s.name: s.id for s in self.settlements}

        def residents(town):
            return [a.id for a in sorted(self.agents, key=lambda a: a.id)
                    if a.home == town and not self.is_traveling(a.id)]

        for audit in results:
            action, result = audit['action'], audit['result']
            actor, kind, effects = action.get('actor'), action.get('type'), result.get('effects', {})
            if actor not in living:
                continue
            place = living[actor].home
            if result.get('success'):
                if kind == 'work' and effects.get('employer', {}).get('kind') == 'person':
                    offer = bid_price(self.market_prices[action['location']][effects['resource']])
                    wage = effects.get('coins', 0.) / max(1, effects.get('amount', 1))
                    act = 'underpaid' if wage < .5 * offer else 'paid_fairly' if wage >= .75 * offer else None
                    if act:
                        firsthand(self, actor, 'conduct', place=place, subject=effects['employer']['id'],
                                  facts=dict(act=act, wage=round(wage, 2), market=round(offer, 2),
                                             resource=effects['resource']))
                elif kind in ('teach', 'collaborate') and effects.get('partner') in living:
                    how = f'taught {effects.get("topic")} to' if kind == 'teach' else 'helped build for'
                    firsthand(self, effects['partner'], 'conduct', place=place, subject=actor,
                              facts=dict(act='helped', how=how))
                elif kind == 'enact':
                    institution = next((i for i in self.institutions if i.id == effects.get('institution_id')), None)
                    if institution is not None:
                        what = effects.get('project') or next(
                            (d['kind'] for d in institution.decisions if d['id'] == effects.get('proposal_id')), 'a decision')
                        for person in residents(institution.settlement_id):
                            firsthand(self, person, 'decision', place=institution.settlement_id,
                                      facts=dict(act=effects.get('proposal_id'), institution_name=institution.name,
                                                 what={'tax_rate': 'a levy', 'work_order': 'a public work order',
                                                       'commission': 'a paid commission', 'distribute_food': 'a food release',
                                                       'granary': 'a communal granary', 'trade_terms': 'a trade contract'
                                                       }.get(what, str(what).replace('_', ' '))))
            elif result.get('code') == 'conflict':
                subject = self._contested(action)
                for other in results:
                    rival = other['action'].get('actor')
                    if (subject is not None and other['result'].get('success') and rival != actor and rival in living
                            and self._contested(other['action']) == subject):
                        firsthand(self, actor, 'conduct', place=place, subject=rival,
                                  facts=dict(act='took_last', what=subject[2] if subject[0] != 'order' else 'paid work'))
        for event in self.events[getattr(self, '_news_cursor', len(self.events)):]:
            kind, town = event.get('kind'), towns.get(event.get('settlement'))
            if town is None:
                continue
            if kind == 'famine':
                for person in residents(town):
                    firsthand(self, person, 'famine', place=town, stamp=self.year)
            elif kind == 'death':
                for person in residents(town):
                    firsthand(self, person, 'death', place=town, subject=event.get('actor_id'),
                              facts=dict(cause='lack of food' if 'deprivation' in event['message'] else 'old age'),
                              subject_name=event.get('agent'))
            elif kind == 'arrival':
                arrived = event.get('actor_id', next((a.id for a in self.agents if a.name == event.get('agent')), None))
                for person in residents(town):
                    if person != arrived:
                        firsthand(self, person, 'arrival', place=town, subject=arrived, subject_name=event.get('agent'))
            elif kind == 'caravan_loss':
                journey = next((j for j in self.journeys if j['id'] == event.get('journey_id')), {})
                destination = journey.get('destination')
                cargo = journey.get('lost_cargo') or {}
                for person in residents(town):
                    firsthand(self, person, 'shipment', place=town, subject=journey.get('owner', journey.get('organizer')),
                              facts=dict(outcome='lost', destination=destination,
                                         destination_name=self.settlements[destination].name if destination is not None else None,
                                         resource=next(iter(cargo), 'goods'), reason=journey.get('reason', 'on the road'),
                                         journey=event.get('journey_id')),
                              stamp=event.get('journey_id'))
        for entry in self.trade_history:
            if entry.get('kind') == 'delivery' and entry['tick'] == self.tick - 1 and entry.get('actor') in living:
                # A merchant paid by a distant market hears how that town is faring.
                place, name = entry['settlement'], self.settlements[entry['settlement']].name
                famine = any(e.get('kind') == 'famine' and e.get('settlement') == name and self.tick - e['tick'] <= 4
                             for e in self.events[-200:])
                if famine:
                    firsthand(self, entry['actor'], 'famine', place=place, stamp=self.year, via=f'the {name} market')
        self._news_cursor = len(self.events)
        for person in living.values():
            if person.starvation_ticks > 0 or (person.hunger >= 65 and person.inventory['food'] < 1):
                firsthand(self, person.id, 'hardship', place=person.home, subject=person.id,
                          facts=dict(what='starving' if person.starvation_ticks > 0 else 'hungry'), stamp=self.year)

    # ----- Conversations ---------------------------------------------------

    TALK_LIMIT = 3  # questions a person will answer from the same player in one season

    def talk(self, player, partner, topic, **args):
        """A player asks a neighbor something between cycles; nothing here takes a season.

        The answer comes from the neighbor's own observation and knowledge. News they
        pass on, and news the player tells them, moves by the same rules as any
        conversation between neighbors. Every conversation is recorded for replay.
        """
        from .dialogue import respond
        if getattr(self, '_resolving', False) or getattr(self, '_transaction_active', False):
            raise ValueError('Conversations happen between cycles.')
        if player not in self.active_players():
            raise ValueError('Only a living player can talk to people.')
        me = self._resolve_agent(player)
        other = next((a for a in self.agents if a.id == partner), None)
        if other is None or other.id == player:
            raise ValueError('Talk to someone else who is alive.')
        if other.home != me.home or self.is_traveling(player) or self.is_traveling(other.id):
            raise ValueError(f'{other.name} is not here to talk to.')
        count = self._talks.get(other.id)
        if count and count['tick'] == self.tick and count['count'] >= self.TALK_LIMIT:
            raise ValueError(f'{other.name} has other things to do this season.')
        arguments = deepcopy(args)
        if topic == 'tell':
            claim = next((c for c in self.knowledge.get(player, []) if str(c['key']) == str(args.get('claim'))), None)
            if claim is None:
                raise ValueError('You can only pass on something you know.')
            arguments['claim'] = deepcopy(claim)
        reply = respond(self.observe(other.id), topic, arguments, {'id': me.id, 'name': me.name})
        learned = []
        if topic == 'tell':
            if relay(self, player, other.id, arguments['claim']):
                learned.append(deepcopy(arguments['claim']['key']))
        else:
            for item in reply['tells']:
                if relay(self, other.id, player, item):
                    learned.append(deepcopy(item['key']))
        self._talks[other.id] = dict(tick=self.tick, count=(count['count'] if count and count['tick'] == self.tick else 0) + 1)
        logged = {k: v for k, v in args.items()}
        self.player_log.append(dict(event='talk', tick=self.tick, actor=player, partner=other.id, topic=topic,
                                    args=deepcopy(logged), lines=list(reply['lines']), learned=learned))
        reply['learned'] = learned
        return reply

    def update_relationships(self, results):
        super().update_relationships(results)
        if getattr(self, '_in_cycle', False):
            self._social_consequences(results)
            self._learn(results)
            spread(self, self.active_players())
            self._review_minds(results)

    def _collect_member_levies(self):
        """A levy voted by a council with municipal authority is a municipal tax paid into the
        town treasury, which funds public work and the market. Other organizations keep theirs."""
        for institution in sorted(self.institutions, key=lambda i: i.id):
            rate = institution.rules.get('tax_rate', 0)
            if not institution.active or not rate:
                continue
            town = self.settlements[institution.settlement_id]
            municipal = getattr(institution, 'purpose', None) == 'council' and self.has_municipal_authority(institution)
            for actor in sorted(self.agents, key=lambda a: a.id):
                if actor.id not in institution.members or actor.home != institution.settlement_id:
                    continue
                amount = min(self.available_inventory(actor)['coins'], actor.inventory['coins'] * rate)
                if amount <= 1e-9:
                    continue
                actor.inventory['coins'] -= amount
                if municipal:
                    town.treasury += amount
                else:
                    institution.treasury += amount
                self._event('levy', f'{actor.name} paid {amount:g} coins to '
                            f'{"the " + town.name + " treasury" if municipal else institution.name} under '
                            f'{institution.name}\'s approved levy.', town.name, actor.name,
                            institution_id=institution.id, amount=amount, municipal=municipal)

    def minds_summary(self):
        return {identity: {key: deepcopy(mind[key]) for key in ('motivations', 'temperament', 'goal_since',
                                                                 'goal_origin', 'completed_tick', 'content_since',
                                                                 'fairness')}
                for identity, mind in self.minds.items()}

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

    def open_work_order(self, settlement, employer, terms, wage_budget, *, institution=None, proposal=None,
                        purpose=None):
        """Record a job whose full wage budget the caller has already moved into escrow.

        A private job may carry the stated purpose its employer gave, a public part of the notice.
        """
        order = dict(id=self.next_work_order_id, settlement=settlement.id, employer=dict(employer),
                     institution=institution, proposal=proposal,
                     created=self.tick, expires=self.tick + ORDER_TICKS, status='open',
                     remaining=terms['quantity'], escrow=wage_budget, **terms)
        if purpose:
            order['purpose'] = dict(purpose)
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
        players = self.active_players() if hasattr(self, 'players') else set()
        proposals = super().plan({k: v for k, v in observations.items() if k not in players})
        # A player's proposal joins the same batch as everyone else's: chosen
        # from their own tick-start observation, resolved by the same rules.
        for identity in sorted(players & set(observations)):
            queued = self._player_turns.pop(identity, None)
            proposal = deepcopy(queued) if queued is not None else {'type': 'wait', 'params': {}}
            proposal['actor'] = identity
            proposals.append(proposal)
            self._rationales[identity] = 'Chosen by the player.' if queued is not None else 'The player waited.'
            self.player_log.append(dict(event='action', tick=self.tick, actor=identity,
                                        chosen=queued is not None, proposal=deepcopy(proposal)))
        return proposals

    @contextmanager
    def _transaction(self):
        if getattr(self, '_transaction_active', False):
            yield
            return
        # History is append-only; snapshot active state and list lengths without
        # copying the entire accumulated history every cycle.
        histories = {key: (value, len(value)) for key, value in vars(self).items()
                     if key in ('events', 'snapshots', 'action_log', 'decisions', 'work_history',
                                'price_history', 'trade_history', 'goal_log', 'trade_shipments',
                                'player_log')}
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
            # Motives and goals are reviewed once per full cycle, after needs and
            # relationships update and before time advances.
            self._in_cycle = True
            try:
                return super().step()
            finally:
                self._in_cycle = False

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
                                                    'remaining', 'unit_wage', 'created', 'expires', 'purpose')
                        if k in o}
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
        mind = getattr(self, 'minds', {}).get(person.id)
        if mind:
            # A person knows their own motives and past goals, never anyone else's.
            observation['actor']['mind'] = {key: deepcopy(mind[key]) for key in (
                'motivations', 'goal_since', 'goal_origin', 'completed_tick', 'history', 'fairness', 'best_tick')}
        if hasattr(self, 'knowledge'):
            # What this person has experienced, witnessed or been told, with its source and age.
            observation['actor']['claims'] = deepcopy(self.knowledge.get(person.id, []))
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
        if hasattr(self, 'minds'):
            self.snapshots[-1].update(minds=self.minds_summary(), goal_log_count=len(self.goal_log),
                                     inequality=inequality_snapshot(self))

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
        for identity, mind in getattr(self, 'minds', {}).items():
            for part in ('motivations', 'temperament'):
                assert set(mind[part]) == set(MOTIVES), (identity, part)
                assert all(math.isfinite(v) and .05 - 1e-9 <= v <= .95 + 1e-9 for v in mind[part].values())

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
                    adaptive_goals=self.adaptive_goals, minds=deepcopy(self.minds), goal_log=deepcopy(self.goal_log),
                    players=sorted(getattr(self, 'players', ())), player_log=deepcopy(getattr(self, 'player_log', [])),
                    knowledge=deepcopy(getattr(self, 'knowledge', {})),
                    note='The Living Economy. Towns post prices from local supply and demand; people buy, sell, hire '
                         'and consign goods to neighboring markets at those prices. Councils, voluntary organizations '
                         'and individuals escrow wages from their own money; funded jobs are public across neighboring '
                         'towns. Motives change slowly with experience, and people may revise their goals. '
                         'Utility policies propose; the world applies the charter.')
        return data

