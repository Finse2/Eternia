"""Five independent households, finite markets and a synchronous planning cycle.

All planners see the same tick-start world. Resolution uses seeded priority and
original spending budgets: receipts and lessons cannot fund another action in
the same tick. Standing offers reserve inventory until filled or expired.
"""
from collections import Counter
from copy import deepcopy
from dataclasses import asdict, dataclass, field
import math

from .actions import (Action, ActionEngine, ActionResult, ACTION_PARAMETERS,
                      RECIPES, _require, _number, _resolve)
from .model import Agent
from .simulation import World
from .society_policy import CommunityPolicy


RESOURCES = ('food', 'wood', 'iron', 'coins')


@dataclass
class Citizen(Agent):
    goal: dict = field(default_factory=dict)
    trust: dict[int, float] = field(default_factory=dict)
    reputation: float = .5
    lineage: str = ''
    generation: int = 0
    parent_id: int | None = None
    labor_credit: float = 0
    lifetime_trades: int = 0
    starvation_ticks: int = 0


class CommunityEngine(ActionEngine):
    parameters = {**{k: v for k, v in ACTION_PARAMETERS.items()
                     if k not in ('found_settlement', 'negotiate')},
                  'offer': {'resource', 'amount', 'unit_price', 'direction'},
                  'accept': {'offer_id', 'amount'},
                  'teach': {'target', 'topic'}, 'collaborate': {'target'}}

    def execute(self, proposal):
        if self.world._batch_remaining is None:
            raise RuntimeError('Use CommunityWorld.submit_action or resolve_actions for accounted execution.')
        return super().execute(proposal)

    def _skill(self, actor, skill):
        skills = self.world._tick_skills.get(actor.id, ()) if self.world._budget_tick == self.world.tick else actor.skills
        _require(skill in skills, 'missing_knowledge', f'{skill} knowledge at tick start is required.')

    def _inventory(self, actor, costs):
        stock = self.world.available_inventory(actor)
        _require(all(stock.get(r, 0) + 1e-9 >= n for r, n in costs.items()),
                 'insufficient_resources', 'Unreserved tick-start resources are insufficient.')

    def _check_build(self, actor, settlement, params):
        structure = params.get('structure')
        _require(type(structure) is str and structure in RECIPES,
                 'unknown_structure', 'The known structures are house and workshop.')
        self._skill(actor, 'carpentry')
        limit = actor.goal.get('target', 1) if actor.goal.get('kind') == 'houses' else 1
        _require(actor.structures.get(structure, 0) < limit,
                 'already_built', 'The construction ownership goal is already met.')
        self._inventory(actor, RECIPES[structure])
        credit = min(actor.labor_credit, getattr(self.world, '_batch_labor', {}).get(actor.id, actor.labor_credit))
        return {'structure': structure, 'costs': dict(RECIPES[structure]),
                'labor_used': min(15, credit), 'energy': max(1, 15 - credit)}

    def _check_trade(self, actor, settlement, params):
        details = super()._check_trade(actor, settlement, params)
        budget = getattr(self.world, '_batch_towns', {}).get(settlement.id)
        if budget is not None:
            resource = details['resource'] if details['direction'] == 'buy' else 'coins'
            amount = details['amount'] if details['direction'] == 'buy' else details['price']
            _require(budget[resource] + 1e-9 >= amount, 'insufficient_resources',
                     'The market has no remaining tick-start stock for this trade.')
        return details

    def _check_offer(self, actor, settlement, params):
        self._skill(actor, 'trading')
        resource, direction = params.get('resource'), params.get('direction')
        _require(type(resource) is str and resource in RESOURCES[:3],
                 'invalid_resource', 'Offer food, wood or iron.')
        _require(direction in ('buy', 'sell'), 'invalid_action', 'Offer direction must be buy or sell.')
        amount = _number(params.get('amount'), 'amount', minimum=1, maximum=1000, integral=True)
        price = _number(params.get('unit_price'), 'unit_price', minimum=.1, maximum=100)
        _require(not any(o['actor'] == actor.id and o['direction'] == direction
                         for o in self.world.offers), 'active_offer',
                 'An actor may post only one offer of each direction at a time.')
        self._inventory(actor, {resource: amount} if direction == 'sell' else {'coins': amount * price})
        return {'resource': resource, 'direction': direction, 'amount': amount,
                'unit_price': price, 'energy': 0}

    def _check_accept(self, actor, settlement, params):
        self._skill(actor, 'trading')
        offer_id = params.get('offer_id')
        _require(type(offer_id) is int, 'invalid_action', 'An offer requires an integer ID.')
        offer = next((o for o in self.world.offers if o['id'] == offer_id), None)
        _require(offer is not None, 'offer_unavailable', 'The offer is no longer available.')
        maker = _resolve(self.world.agents, offer['actor'], 'unknown_actor', 'Offer maker')
        _require(maker.id != actor.id, 'invalid_action', 'An actor cannot accept their own offer.')
        _require(offer['created'] < self.world.tick < offer['expires'],
                 'offer_unavailable', 'Only a live offer from an earlier tick can be accepted.')
        _require(maker.home == settlement.id == offer['home'],
                 'remote_action', 'Both parties must still be in the offer settlement.')
        _require(settlement.permissions.get('trade', True) is True,
                 'permission_denied', 'The local market is closed.')
        amount = _number(params.get('amount', offer['amount']), 'amount', minimum=1,
                         maximum=offer['amount'], integral=True)
        seller, buyer = (maker, actor) if offer['direction'] == 'sell' else (actor, maker)
        cost = amount * offer['unit_price']
        for person, resource, quantity in ((seller, offer['resource'], amount), (buyer, 'coins', cost)):
            available = self.world.available_inventory(person, exclude_offer=offer_id)
            _require(available.get(resource, 0) + 1e-9 >= quantity,
                     'insufficient_resources', 'A party can no longer fulfill the reserved trade.')
        return {'offer': offer, 'seller': seller, 'buyer': buyer, 'amount': amount,
                'price': cost, 'energy': 1}

    def _peer(self, actor, settlement, params):
        target = _resolve(self.world.agents, params.get('target'), 'unknown_actor', 'Partner')
        _require(target.id != actor.id and target.home == settlement.id,
                 'remote_action', 'A different living local partner is required.')
        return target

    def _check_teach(self, actor, settlement, params):
        target = self._peer(actor, settlement, params)
        topic = params.get('topic')
        _require(type(topic) is str and topic in ('aether', 'carpentry'),
                 'unknown_topic', 'Teach aether or carpentry.')
        _require(target.trust.get(actor.id, 0) > -.6,
                 'permission_denied', 'The partner does not trust this teacher.')
        level = min(actor.knowledge, getattr(self.world, '_batch_knowledge', {}).get(actor.id, actor.knowledge))
        known = level > target.knowledge if topic == 'aether' else (
            'carpentry' in actor.skills and 'carpentry' not in target.skills)
        _require(known, 'already_known', 'The teacher has no new knowledge for this partner.')
        return {'target': target, 'topic': topic, 'level': level, 'energy': 5}

    def _check_collaborate(self, actor, settlement, params):
        target = self._peer(actor, settlement, params)
        _require(target.role == 'builder' and target.labor_credit < 15,
                 'not_needed', 'The partner does not need more construction labor.')
        _require(target.structures.get('house', 0) < target.goal.get('target', 3),
                 'not_needed', 'The partner has completed their construction goal.')
        _require(target.trust.get(actor.id, 0) > -.6,
                 'permission_denied', 'The partner declines cooperation.')
        return {'target': target, 'energy': 5}

    def _apply(self, action, actor, settlement, details):
        if action.type == 'offer':
            offer = {k: details[k] for k in ('resource', 'amount', 'unit_price', 'direction')}
            offer.update(id=self.world.next_offer_id, actor=actor.id, home=actor.home,
                         created=self.world.tick, expires=self.world.tick + 4)
            self.world.next_offer_id += 1
            self.world.offers.append(offer)
            return {'offer_id': offer['id'], 'message':
                    f'{actor.name} offered to {offer["direction"]} {offer["amount"]} '
                    f'{offer["resource"]} at {offer["unit_price"]:g} coins each.'}
        if action.type == 'accept':
            offer, seller, buyer = details['offer'], details['seller'], details['buyer']
            resource, amount, price = offer['resource'], details['amount'], details['price']
            seller.inventory[resource] -= amount
            buyer.inventory[resource] += amount
            buyer.inventory['coins'] -= price
            seller.inventory['coins'] += price
            offer['amount'] -= amount
            if not offer['amount']:
                self.world.offers.remove(offer)
            seller.lifetime_trades += 1
            buyer.lifetime_trades += 1
            return {'seller': seller.id, 'buyer': buyer.id, 'partner':
                    seller.id if buyer.id == actor.id else buyer.id,
                    'resource': resource, 'amount': amount, 'coins': price,
                    'message': f'{buyer.name} bought {amount} {resource} from {seller.name} for {price:g} coins.'}
        if action.type == 'teach':
            target, topic = details['target'], details['topic']
            if topic == 'aether':
                target.knowledge = details['level']
            else:
                target.skills.append('carpentry')
            return {'partner': target.id, 'topic': topic, 'message':
                    f'{actor.name} taught {topic} to {target.name}.'}
        if action.type == 'collaborate':
            target = details['target']
            target.labor_credit = min(15, target.labor_credit + 5)
            return {'partner': target.id, 'labor': 5, 'message':
                    f'{actor.name} contributed construction labor to {target.name}.'}
        result = super()._apply(action, actor, settlement, details)
        if action.type == 'build':
            actor.labor_credit -= details['labor_used']
        return result


class CommunityWorld(World):
    """Quarterly decisions and an annual aggregate population/economy model."""

    def __init__(self, seed=42, ticks_per_year=4, shock_year=8, policies=None):
        if type(ticks_per_year) is not int or not 1 <= ticks_per_year <= 12:
            raise ValueError('ticks_per_year must be an integer from 1 to 12')
        if type(shock_year) is not int or shock_year < 0:
            raise ValueError('shock_year must be a nonnegative integer')
        super().__init__(seed)
        self.tick = 0
        self.ticks_per_year = ticks_per_year
        self.shock_year = shock_year
        self.shock_applied = False
        self.offers = []
        self.next_offer_id = 0
        self.decisions = []
        self.policies = policies or {}
        self._default_policy = CommunityPolicy()
        self._batch_remaining = None
        self._budget_tick = None
        self._tick_remaining = {}
        self._tick_skills = {}
        self._resolving = False
        self._pending_events = []
        self.metrics = dict.fromkeys(('trades', 'conflicts', 'cooperations',
                                     'knowledge_transfers', 'births', 'deaths'), 0)
        self.ledger = {kind: dict.fromkeys(RESOURCES, 0.) for kind in ('produced', 'consumed')}
        specs = [
            ('Edrin', 'miner', 24, {'kind': 'wealth', 'target': 60}, (2, 0, 8, 8), ['mining']),
            ('Mara', 'merchant', 30, {'kind': 'profit', 'target': 120}, (8, 6, 2, 60), []),
            ('Toren', 'builder', 27, {'kind': 'houses', 'target': 3}, (3, 8, 0, 28), ['carpentry', 'woodcutting']),
            ('Lyra', 'researcher', 22, {'kind': 'knowledge', 'target': 2}, (3, 2, 0, 30), ['woodcutting']),
            ('Aldric', 'farmer', 39, {'kind': 'food', 'target': 12}, (12, 2, 0, 16), ['woodcutting']),
        ]
        self.agents = [Citizen(i, name, 2, role, .7 + .04 * i, .85 - .06 * i, age,
                               inventory=dict(zip(RESOURCES, inventory)),
                               skills=['foraging', 'trading', *skills], goal=goal,
                               lineage=name, wealth_goal=goal['target'] if role in ('miner', 'merchant') else 60)
                       for i, (name, role, age, goal, inventory, skills) in enumerate(specs)]
        self.next_agent_id = 5
        self.action_engine = CommunityEngine(self)
        for town in self.settlements:
            town.deposits = {'food': 16., 'wood': 24., 'iron': 12.}
        self.events = []
        self.snapshots = []
        self._event('world', 'Five independent people begin a community in Highfen.')
        self.initial_totals = self.resource_totals()
        self._snapshot()

    def _event(self, kind, message, settlement=None, agent=None, **details):
        event = {'year': self.year, 'tick': getattr(self, 'tick', 0), 'kind': kind,
                 'message': message, 'settlement': settlement, 'agent': agent, **details}
        if getattr(self, '_resolving', False):
            self._pending_events.append(event)
        else:
            self.events.append(event)

    def resource_totals(self):
        return {r: sum(a.inventory.get(r, 0) for a in self.agents) + sum(
            (s.treasury if r == 'coins' else getattr(s, r) + s.deposits.get(r, 0))
            for s in self.settlements) for r in RESOURCES}

    def _account(self, before):
        for resource, total in self.resource_totals().items():
            delta = total - before[resource]
            self.ledger['produced' if delta >= 0 else 'consumed'][resource] += abs(delta)

    def _account_action(self, action, result, before):
        """Only declared action costs are sinks; exchanges cannot mint stock."""
        costs = {}
        if result.success:
            if action.get('type') == 'build':
                costs = result.effects['costs']
            elif action.get('type') == 'research':
                costs = {'wood': 1, 'iron': 1}
            elif action.get('type') == 'eat':
                costs = {'food': 1}
        for resource, total in self.resource_totals().items():
            cost = costs.get(resource, 0)
            if not math.isclose(total, before[resource] - cost, abs_tol=1e-7):
                raise AssertionError(f'{action.get("type")} violated {resource} conservation')
            self.ledger['consumed'][resource] += cost

    def offer_reservations(self, exclude_offer=None):
        reservations = {a.id: dict.fromkeys(RESOURCES, 0.) for a in self.agents}
        for offer in self.offers:
            if offer['id'] == exclude_offer or offer['actor'] not in reservations:
                continue
            resource = offer['resource'] if offer['direction'] == 'sell' else 'coins'
            amount = offer['amount'] if offer['direction'] == 'sell' else offer['amount'] * offer['unit_price']
            reservations[offer['actor']][resource] += amount
        return reservations

    def available_inventory(self, actor, exclude_offer=None):
        if type(actor) is int:
            actor = self._resolve_agent(actor)
        reserved = self.offer_reservations(exclude_offer).get(actor.id, {})
        budget = self._tick_remaining.get(actor.id, {}) if self._budget_tick == self.tick else actor.inventory
        return {r: max(0., min(actor.inventory.get(r, 0), budget.get(r, 0)) - reserved.get(r, 0))
                for r in RESOURCES}

    def _expire_offers(self):
        living = {a.id: a for a in self.agents}
        for offer in list(self.offers):
            maker = living.get(offer['actor'])
            if maker is None or maker.home != offer['home'] or self.tick >= offer['expires']:
                self.offers.remove(offer)
                self._event('market', f'Offer {offer["id"]} expired or its maker left the market.')

    def observe(self, actor):
        observation = super().observe(actor)
        person = self._resolve_agent(actor)
        observation.update(tick=self.tick, ticks_per_year=self.ticks_per_year)
        observation['actor']['available_inventory'] = self.available_inventory(person)
        # Private memories, trust and personal goals are not readable on peers.
        observation['peers'] = [{k: deepcopy(getattr(a, k)) for k in (
            'id', 'name', 'home', 'role', 'inventory', 'skills', 'knowledge',
            'structures', 'reputation', 'labor_credit')}
            for a in self.agents if a.id != person.id and a.home == person.home]
        observation['market'] = deepcopy([o for o in self.offers if o['home'] == person.home])
        return observation

    def observe_agents(self):
        return {a.id: self.observe(a.id) for a in sorted(self.agents, key=lambda a: a.id)}

    def plan(self, observations):
        proposals = []
        self._rationales = {}
        for actor_id, observation in sorted(observations.items()):
            policy = self.policies.get(actor_id, self._default_policy)
            try:
                proposal = policy.propose(deepcopy(observation))
                nominated = proposal.actor if isinstance(proposal, Action) else (
                    proposal.get('actor') if isinstance(proposal, dict) else None)
                if nominated != actor_id or type(nominated) is not int:
                    proposal = {'actor': actor_id, 'type': 'invalid_actor', 'params': {}}
            except Exception as error:
                proposal = {'actor': actor_id, 'type': 'policy_error', 'params': {}}
                self._rationales[actor_id] = f'Policy raised {type(error).__name__}.'
            reason = getattr(policy, 'reason', 'External policy proposal.')
            self._rationales.setdefault(actor_id, reason if isinstance(reason, str) else 'External policy proposal.')
            proposals.append(proposal)
        return proposals

    def _actor_id(self, proposal):
        value = proposal.actor if isinstance(proposal, Action) else (
            proposal.get('actor') if isinstance(proposal, dict) else None)
        if type(value) is int:
            return value
        if type(value) is str:
            try:
                return self._resolve_agent(value).id
            except ValueError:
                pass
        return None

    def submit_action(self, proposal):
        """A convenience entry point with the same accounting and tick limits."""
        results = self.resolve_actions([proposal])
        self.update_relationships(results)
        self.record_events(results)
        return ActionResult(**results[0]['result'])

    def resolve_actions(self, proposals):
        """Reserve against a common start state, then commit in seeded priority.

        Baseline-invalid plans stay rejected, even when an earlier action would
        make them feasible. Actual execution rechecks geography and stocks.
        """
        self._expire_offers()
        proposals = list(proposals)
        if self._budget_tick != self.tick:
            self._budget_tick = self.tick
            self._tick_remaining = {a.id: dict(a.inventory) for a in self.agents}
            self._tick_skills = {a.id: list(a.skills) for a in self.agents}
            self._batch_knowledge = {a.id: a.knowledge for a in self.agents}
            self._batch_labor = {a.id: a.labor_credit for a in self.agents}
            self._batch_towns = {s.id: {r: s.treasury if r == 'coins' else getattr(s, r)
                                       for r in RESOURCES} for s in self.settlements}
        counts = Counter(self._actor_id(p) for p in proposals if self._actor_id(p) is not None)
        baseline = [self.action_engine.validate(p) for p in proposals]
        priority = sorted(range(len(proposals)), key=lambda i: (
            self._actor_id(proposals[i]) is None, self._actor_id(proposals[i]) or 0))
        self.rng.shuffle(priority)
        self._batch_remaining = self._tick_remaining
        output = []
        try:
            for i in priority:
                proposal, initial = proposals[i], baseline[i]
                actor_id = self._actor_id(proposal)
                before = self.resource_totals()
                inventory_before = {a.id: dict(a.inventory) for a in self.agents}
                towns_before = {s.id: {r: s.treasury if r == 'coins' else getattr(s, r)
                                      for r in RESOURCES} for s in self.settlements}
                if counts.get(actor_id, 0) > 1:
                    result = ActionResult(False, 'duplicate_action', 'Only one proposal per actor is permitted in a batch.')
                elif not initial.success:
                    result = initial
                else:
                    result = self.action_engine.execute(proposal)
                    record = self.action_log.pop()
                    if not result.success:
                        result = ActionResult(False, 'conflict', result.message, {'cause': result.code})
                action = (record['action'] if initial.success and counts.get(actor_id, 0) <= 1
                          else self.action_engine._safe_proposal(proposal))
                audit = {'year': self.year, 'tick': self.tick, 'action': action,
                         'result': result.to_dict()}
                self.action_log.append(audit)
                output.append(deepcopy(audit))
                for person in self.agents:
                    for resource in RESOURCES:
                        spent = max(0., inventory_before[person.id][resource] - person.inventory[resource])
                        self._batch_remaining.setdefault(person.id, dict.fromkeys(RESOURCES, 0.))[resource] -= spent
                for town in self.settlements:
                    if town.id not in towns_before:
                        continue
                    for resource in RESOURCES:
                        current = town.treasury if resource == 'coins' else getattr(town, resource)
                        spent = max(0., towns_before[town.id][resource] - current)
                        self._batch_towns[town.id][resource] -= spent
                self._account_action(action, result, before)
                if actor_id is not None:
                    try:
                        actor = self._resolve_agent(actor_id)
                    except ValueError:
                        pass
                    else:
                        actor.memory.append(deepcopy(audit))
                        del actor.memory[:-64]
                self.decisions.append({'year': self.year, 'tick': self.tick, 'actor': actor_id,
                                       'proposal': deepcopy(action), 'result': result.to_dict(),
                                       'rationale': getattr(self, '_rationales', {}).get(actor_id, 'Submitted proposal.')})
        finally:
            self._batch_remaining = None
        self._expire_offers()
        return output

    def update_needs(self):
        before = self.resource_totals()
        for actor in list(self.agents):
            actor.hunger = min(100., actor.hunger + 28 / self.ticks_per_year)
            actor.energy = min(100., actor.energy + 24 / self.ticks_per_year)
            actor.starvation_ticks = actor.starvation_ticks + 1 if actor.hunger >= 100 else 0
            if actor.starvation_ticks >= 2 * self.ticks_per_year:
                self.remove_agent(actor.id, 'prolonged food deprivation')
        self._account(before)

    def update_relationships(self, results):
        living = {a.id: a for a in self.agents}
        for audit in results:
            actor = living.get(audit['action'].get('actor'))
            result = audit['result']
            kind = audit['action'].get('type')
            effects = result.get('effects', {})
            if result['success']:
                if kind == 'accept':
                    self.metrics['trades'] += 1
                if kind in ('teach', 'collaborate'):
                    self.metrics['cooperations'] += 1
                if kind == 'teach':
                    self.metrics['knowledge_transfers'] += 1
                partner = living.get(effects.get('partner'))
                if actor and partner:
                    for person, other in ((actor, partner), (partner, actor)):
                        person.trust[other.id] = min(1., person.trust.get(other.id, 0) + .12)
                        person.reputation = min(1., person.reputation + .015)
                    partner.memory.append({'year': self.year, 'tick': self.tick,
                                           'kind': 'interaction', 'partner': actor.id,
                                           'message': result['message']})
                    del partner.memory[:-64]
                    self._event('relationship', f'{actor.name} and {partner.name} grew more trusting.',
                                self.settlements[actor.home].name, actor.name,
                                actor_id=actor.id, partner_id=partner.id)
                # Learning by seeing a successful practical demonstration, not
                # reading hidden world conditions or another agent's memory.
                if actor and kind in ('build', 'research'):
                    for witness in self.agents:
                        if witness.id == actor.id or witness.home != actor.home:
                            continue
                        if self.rng.random() >= .12:
                            continue
                        learned = False
                        practical = kind == 'build' or effects.get('topic') == 'carpentry'
                        if practical and 'carpentry' not in witness.skills:
                            witness.skills.append('carpentry')
                            learned = True
                        elif kind == 'research' and effects.get('topic') == 'aether':
                            demonstrated = 2 if effects.get('discovered') else 1
                            if demonstrated > witness.knowledge:
                                witness.knowledge = min(demonstrated, witness.knowledge + 1)
                                learned = True
                        if learned:
                            self.metrics['knowledge_transfers'] += 1
                            witness.memory.append({'year': self.year, 'tick': self.tick,
                                                   'kind': 'observation', 'message': result['message']})
                            del witness.memory[:-64]
                            self._event('knowledge', f'{witness.name} learned by observing {actor.name}.')
            elif result['code'] == 'conflict':
                self.metrics['conflicts'] += 1
                offer_id = audit['action'].get('params', {}).get('offer_id')
                rival = next((r['action'].get('actor') for r in results if r['result']['success']
                              and r['action'].get('params', {}).get('offer_id') == offer_id), None)
                if actor and rival in living and rival != actor.id and offer_id is not None:
                    actor.trust[rival] = max(-1., actor.trust.get(rival, 0) - .06)
                self._event('conflict', result['message'], agent=actor.name if actor else None)
        for town in self.settlements:
            town.knowledge = max((a.knowledge for a in self.agents if a.home == town.id), default=0)

    def record_events(self, results):
        self.events.extend(self._pending_events)
        self._pending_events.clear()

    def remove_agent(self, actor_id, cause='old age'):
        """Retire a person and transfer an estate to a new generation, without minting assets."""
        actor = self._resolve_agent(actor_id)
        self.agents.remove(actor)
        self.offers[:] = [o for o in self.offers if o['actor'] != actor.id]
        successor = Citizen(self.next_agent_id, f'{actor.lineage}-{actor.generation + 2}',
                            actor.home, actor.role, self.rng.random(), self.rng.random(), 18,
                            inventory=dict(actor.inventory), structures=dict(actor.structures),
                            skills=['foraging', 'trading'], goal=dict(actor.goal),
                            wealth_goal=actor.wealth_goal, lineage=actor.lineage,
                            generation=actor.generation + 1, parent_id=actor.id)
        self.next_agent_id += 1
        for skill in actor.skills:
            if skill not in successor.skills and self.rng.random() < .7:
                successor.skills.append(skill)
        successor.knowledge = actor.knowledge if self.rng.random() < .65 else 0
        successor.memory = [{'year': self.year, 'tick': self.tick, 'kind': 'inheritance',
                             'message': f'Inherited the estate and recollections of {actor.name}.'}]
        successor.memory.extend({**deepcopy(m), 'inherited': True} for m in actor.memory[-4:])
        self.agents.append(successor)
        self.settlements[actor.home].knowledge = max(
            a.knowledge for a in self.agents if a.home == actor.home)
        for person in self.agents:
            person.trust.pop(actor.id, None)
        self.policies.pop(actor.id, None)
        self.metrics['deaths'] += 1
        self.metrics['births'] += 1
        self._event('death', f'{actor.name} died of {cause}; {successor.name} inherited the estate.',
                    self.settlements[actor.home].name, actor.name,
                    actor_id=actor.id, successor_id=successor.id,
                    knowledge_before=actor.knowledge, knowledge_after=successor.knowledge)
        return successor

    def _annual_economy(self):
        # Each explicit production/consumption phase is accounted separately;
        # exchanges and replenishment transfers conserve the combined stocks.
        for phase in (self._produce_and_consume, self._trade, self._govern):
            before = self.resource_totals()
            phase()
            self._account(before)
        for town in self.settlements:
            for resource, cap, rate in (('food', 24, 6), ('wood', 32, 6), ('iron', 16, 3)):
                quantity = max(0., min(rate, cap - town.deposits[resource], getattr(town, resource)))
                setattr(town, resource, getattr(town, resource) - quantity)
                town.deposits[resource] += quantity
        for actor in list(self.agents):
            actor.age += 1
            if actor.age >= 78 or (actor.age > 60 and self.rng.random() < .035):
                self.remove_agent(actor.id)
        for town in self.settlements:
            town.knowledge = max((a.knowledge for a in self.agents if a.home == town.id), default=0)

    def advance_time(self):
        self.tick += 1
        self.year = self.tick // self.ticks_per_year
        self._budget_tick = None
        self._batch_knowledge = {}
        self._batch_labor = {}
        self._batch_towns = {}
        self._expire_offers()
        if self.tick % self.ticks_per_year == 0:
            self._annual_economy()
            self._assert_invariants()
            self._snapshot()

    def _shock(self):
        if self.shock_year and self.year >= self.shock_year and not self.shock_applied:
            before = self.resource_totals()
            town = self.settlements[2]
            town.deposits['iron'] = 0
            town.ore *= .2
            self.shock_applied = True
            self._account(before)
            self._event('disruption', f'A rockfall closed Highfen\'s accessible iron deposit and reduced mining output.', town.name)

    def step(self):
        self._expire_offers()
        self._shock()
        observations = self.observe_agents()
        proposals = self.plan(observations)
        self._resolving = True
        try:
            results = self.resolve_actions(proposals)
            self.update_needs()
            self.update_relationships(results)
        finally:
            self._resolving = False
        self.record_events(results)
        self.advance_time()
        self._assert_invariants()
        return results

    def run(self, years=100):
        if type(years) is not int or not 0 <= years <= 10000:
            raise ValueError('years must be an integer from 0 to 10000')
        for _ in range(years * self.ticks_per_year):
            self.step()
        return self

    def _snapshot(self):
        # World.__init__ calls this before community-specific fields exist.
        if not hasattr(self, 'tick'):
            return super()._snapshot()
        self.snapshots.append({'year': self.year, 'tick': self.tick,
                               'population': sum(s.population for s in self.settlements),
                               'settlements': [s.public_state() for s in self.settlements],
                               'named_agents': len(self.agents),
                               'magic_discoveries': sum(s.knowledge == 2 for s in self.settlements),
                               'agents': [asdict(a) for a in self.agents],
                               'offers': deepcopy(self.offers), 'metrics': dict(self.metrics),
                               'event_count': len(self.events), 'action_count': len(self.action_log),
                               'decision_count': len(self.decisions),
                               'ledger': deepcopy(self.ledger)})

    def _assert_invariants(self):
        super()._assert_invariants()
        for resource, total in self.resource_totals().items():
            expected = self.initial_totals[resource] + self.ledger['produced'][resource] - self.ledger['consumed'][resource]
            assert math.isclose(total, expected, abs_tol=1e-6), (resource, total, expected)
        reserved = self.offer_reservations()
        assert all(reserved[a.id][r] <= a.inventory[r] + 1e-7 for a in self.agents for r in RESOURCES)
        assert all(-1 <= value <= 1 for a in self.agents for value in a.trust.values())

    def export(self):
        return deepcopy({'schema': 'eternia.v0.3', 'mode': 'community',
                         'seed': self.seed, 'year': self.year, 'tick': self.tick,
                         'ticks_per_year': self.ticks_per_year,
                         'note': 'Classical utility policies; no LLM. Five represented households in an aggregate population. Cooperation is possible, never guaranteed.',
                         'snapshots': self.snapshots, 'events': self.events,
                         'actions': self.action_log, 'decisions': self.decisions,
                         'final_agents': [asdict(a) for a in self.agents],
                         'metrics': self.metrics, 'initial_totals': self.initial_totals,
                         'final_totals': self.resource_totals(), 'ledger': self.ledger})


def run_community(seed=42, years=100, ticks_per_year=4, shock_year=8):
    return CommunityWorld(seed, ticks_per_year, shock_year).run(years)
