"""An institutional layer connecting personal decisions to aggregate economics.

Organizations start empty, acquire resources through voluntary contributions and
approved member levies, and act only through voted mandates. Production remains
an aggregate model; storage, labor allocation and inter-town trade depend on
institutional decisions. No automatic council investment runs in this mode.
"""
from copy import deepcopy
import math

from .community import CommunityWorld, RESOURCES
from .institutions import InstitutionEngine, vote_counts
from .institution_policy import InstitutionalPolicy


class InstitutionalWorld(CommunityWorld):
    def __init__(self, seed=42, ticks_per_year=4, shock_year=8, policies=None):
        super().__init__(seed, ticks_per_year, shock_year, policies)
        self.institutions = []
        self.next_institution_id = 0
        self.next_proposal_id = 0
        self._institution_budget_tick = None
        self._institution_frames = {}
        self._institution_remaining = {}
        self._default_policy = InstitutionalPolicy()
        self.action_engine = InstitutionEngine(self)
        self.metrics.update(institutions_formed=0, institutions_collapsed=0,
                            proposals_passed=0, institution_contributions=0,
                            institution_votes=0, institution_enactments=0)
        self.events = []
        self.snapshots = []
        self._event('world', 'Five individuals begin with no institutions or collective mandates.')
        self.initial_totals = self.resource_totals()
        self._snapshot()

    def resource_totals(self):
        totals = super().resource_totals()
        for institution in getattr(self, 'institutions', ()):
            for resource in RESOURCES:
                totals[resource] += (institution.treasury if resource == 'coins'
                                     else institution.inventory.get(resource, 0))
        return totals

    def _resolve_institution(self, reference):
        if type(reference) is not int:
            raise ValueError('Institution must be a stable integer ID')
        matches = [i for i in self.institutions if i.id == reference]
        if len(matches) != 1:
            raise ValueError('Institution does not exist')
        return matches[0]

    def _begin_institution_tick(self):
        if self._institution_budget_tick != self.tick:
            self._institution_budget_tick = self.tick
            self._institution_frames = {i.id: i.public_state() for i in self.institutions}
            self._institution_remaining = {
                i.id: {**i.inventory, 'coins': i.treasury} for i in self.institutions}

    def institution_frame(self, institution):
        if self._institution_budget_tick == self.tick:
            return deepcopy(self._institution_frames.get(institution.id))
        return institution.public_state()

    def available_institution_inventory(self, institution):
        current = {**institution.inventory, 'coins': institution.treasury}
        if self._institution_budget_tick != self.tick:
            return current
        remaining = self._institution_remaining.get(institution.id, {})
        return {r: max(0., min(current.get(r, 0), remaining.get(r, 0))) for r in RESOURCES}

    def spend_institution(self, institution, costs):
        available = self.available_institution_inventory(institution)
        if any(available.get(r, 0) < amount for r, amount in costs.items()):
            raise ValueError('Shared resources were not reserved before execution')
        for resource, amount in costs.items():
            if resource == 'coins':
                institution.treasury -= amount
            else:
                institution.inventory[resource] -= amount
            self._institution_remaining[institution.id][resource] -= amount

    def _account_action(self, action, result, before):
        if action.get('type') not in ('form_institution', 'enact'):
            return super()._account_action(action, result, before)
        costs = result.effects.get('costs', {}) if result.success else {}
        for resource, total in self.resource_totals().items():
            cost = costs.get(resource, 0)
            if not math.isclose(total, before[resource] - cost, abs_tol=1e-7):
                raise AssertionError(f'Institutional action violated {resource} conservation')
            self.ledger['consumed'][resource] += cost

    def resolve_actions(self, proposals):
        self._maintain_institutions()
        self._begin_institution_tick()
        results = super().resolve_actions(proposals)
        self._maintain_institutions()
        self.metrics['proposals_passed'] = sum(
            p['status'] == 'enacted' for i in self.institutions for p in i.decisions)
        return results

    def observe(self, actor):
        observation = super().observe(actor)
        person = self._resolve_agent(actor)
        visible_towns = {person.home, *(s['id'] for s in observation['neighbors'])}
        organizations = []
        for institution in self.institutions:
            if institution.settlement_id not in visible_towns:
                continue
            state = institution.public_state()
            if person.id not in institution.members:
                state.pop('inventory')
                state.pop('treasury')
            else:
                state['available_inventory'] = self.available_institution_inventory(institution)
            organizations.append(state)
        observation['institutions'] = organizations
        observation['memberships'] = [i.id for i in self.institutions
                                      if i.active and person.id in i.members]
        observation['actor']['memberships'] = list(observation['memberships'])
        observation['settlement_policies'] = self.settlement_policies()[person.home]
        return observation

    def remove_agent(self, actor_id, cause='old age'):
        successor = super().remove_agent(actor_id, cause)
        for institution in getattr(self, 'institutions', ()):
            if actor_id in institution.members:
                institution.members.remove(actor_id)
                if not institution.members:
                    institution.empty_since = self.tick
                self._event('institution',
                            f'{institution.name} lost a member; its property remains communal.',
                            self.settlements[institution.settlement_id].name,
                            institution_id=institution.id, actor_id=actor_id)
        return successor

    def _maintain_institutions(self):
        local = {a.id: a.home for a in self.agents}
        for institution in self.institutions:
            if not institution.active:
                continue
            departed = {a for a in institution.members if local.get(a) != institution.settlement_id}
            institution.members.difference_update(departed)
            if institution.members:
                institution.empty_since = None
            elif institution.empty_since is None:
                institution.empty_since = self.tick
            for proposal in institution.decisions:
                if proposal['status'] != 'open':
                    continue
                if self.tick >= proposal['expires']:
                    proposal['status'] = 'expired'
                    self._event('institution', f'A {proposal["kind"]} proposal expired in {institution.name}.',
                                institution_id=institution.id, proposal_id=proposal['id'])
                else:
                    # Departed voters cannot leave behind a decisive negative
                    # or positive vote. Authority is recomputed from survivors.
                    _, no, eligible = vote_counts(self, institution, proposal)
                    if no >= 2 and no * 2 > eligible:
                        proposal['status'] = 'rejected'
            if not institution.members and self.tick - institution.empty_since >= 4:
                town = self.settlements[institution.settlement_id]
                town.treasury += institution.treasury
                institution.treasury = 0.
                for resource in ('food', 'wood', 'iron'):
                    setattr(town, resource, getattr(town, resource) + institution.inventory[resource])
                    institution.inventory[resource] = 0.
                institution.active = False
                for proposal in institution.decisions:
                    if proposal['status'] == 'open':
                        proposal['status'] = 'expired'
                self.metrics['institutions_collapsed'] += 1
                self._event('institution', f'{institution.name} collapsed after four ticks without members; its reserves returned to {town.name}.',
                            town.name, institution_id=institution.id)
        self._refresh_treaties()

    def _refresh_treaties(self):
        mandates = set()
        for institution in self.institutions:
            if institution.active and institution.members:
                for proposal in institution.decisions:
                    if proposal['status'] == 'enacted' and proposal['kind'] == 'trade_agreement':
                        mandates.add((institution.settlement_id, proposal['params']['destination']))
        for town in self.settlements:
            for partner, relation in list(town.relations.items()):
                if relation == 'trade' and ((town.id, partner) not in mandates or
                                            (partner, town.id) not in mandates):
                    del town.relations[partner]

    def settlement_policies(self):
        return {s.id: {
            'tax_rate': sum(i.rules.get('tax_rate', 0) for i in self.institutions
                            if i.active and i.members and i.settlement_id == s.id),
            'communal_labor': sum(i.rules.get('communal_labor', 0) for i in self.institutions
                                  if i.active and i.members and i.settlement_id == s.id),
            'trade_partners': sorted(other for other, relation in s.relations.items() if relation == 'trade'),
            'granary_capacity': s.population * (.5 * s.buildings.get('granary', 0)),
        } for s in self.settlements}

    def _produce_and_consume(self):
        policies = self.settlement_policies()
        for town in self.settlements:
            labor = policies[town.id]['communal_labor']
            weather = self.rng.uniform(.86, 1.16)
            productivity = town.fertility * (1 + .16 * town.farming_level)
            harvest = min(town.population * 1.45, town.farmland * productivity) * weather
            food = harvest * (1 + .5 * labor)
            wood = town.population * .11 * town.forest * (1 - labor)
            iron = town.population * .025 * town.ore * (1 + .07 * town.mining_level) * (1 - labor)
            for resource, amount in (('food', food), ('wood', wood), ('iron', iron)):
                setattr(town, resource, getattr(town, resource) + amount)
                self.ledger['produced'][resource] += amount
            # Explicit spoilage/resource capacity sinks, distinct from output.
            for resource, cap in (('wood', max(150., town.population * .7)),
                                  ('iron', max(80., town.population * .22))):
                excess = max(0., getattr(town, resource) - cap)
                setattr(town, resource, getattr(town, resource) - excess)
                self.ledger['consumed'][resource] += excess

    def _institutional_trade(self):
        for buyer in sorted(self.settlements, key=lambda s: (s.food / max(1, s.population), s.id)):
            want = max(0., buyer.population * 1.12 - buyer.food)
            for donor in sorted(self.settlements, key=lambda s: (self.action_engine._distance(s, buyer), s.id)):
                if buyer.relations.get(donor.id) != 'trade' or donor.relations.get(buyer.id) != 'trade':
                    continue
                available = max(0., donor.food - donor.population * 1.45)
                quantity = min(want, available, buyer.treasury / .12)
                if quantity < 1:
                    continue
                donor.food -= quantity
                buyer.food += quantity
                buyer.treasury -= quantity * .12
                donor.treasury += quantity * .12
                want -= quantity
                self._event('trade', f'{donor.name} shipped {quantity:g} food to {buyer.name} under a voted agreement.', buyer.name)

    def _consume_and_demography(self):
        for town in self.settlements:
            original_population = town.population
            shortage = max(0., original_population - town.food)
            eaten = min(town.food, original_population)
            town.food -= eaten
            self.ledger['consumed']['food'] += eaten
            if shortage > 0:
                rate = min(.2, .018 + .42 * shortage / max(1, original_population))
                town.population = max(10, original_population - max(1, round(original_population * rate)))
                if shortage > original_population * .14:
                    self._event('famine', f'{town.name} faced a food deficit; population fell.', town.name)
            else:
                capacity = town.farmland * town.fertility * (1 + .16 * town.farming_level)
                labor = self.settlement_policies()[town.id]['communal_labor']
                capacity *= 1 + .5 * labor
                room = max(0., (capacity * .93 - original_population) / max(1., capacity))
                growth = round(original_population * (.005 + .013 * room))
                if room > .01 and growth == 0 and self.rng.random() < .30:
                    growth = 1
                town.population += max(0, growth)
            cap = town.population * (2 + .5 * town.buildings.get('granary', 0))
            spoiled = max(0., town.food - cap)
            town.food -= spoiled
            self.ledger['consumed']['food'] += spoiled

    def _collect_member_levies(self):
        for institution in sorted(self.institutions, key=lambda i: i.id):
            if not institution.active or not institution.rules.get('tax_rate', 0):
                continue
            for actor in sorted(self.agents, key=lambda a: a.id):
                if actor.id not in institution.members or actor.home != institution.settlement_id:
                    continue
                amount = min(self.available_inventory(actor)['coins'],
                             actor.inventory['coins'] * institution.rules['tax_rate'])
                if amount > 1e-9:
                    actor.inventory['coins'] -= amount
                    institution.treasury += amount
                    self._event('levy', f'{actor.name} paid {amount:g} coins to {institution.name} under its approved member levy.',
                                self.settlements[actor.home].name, actor.name,
                                institution_id=institution.id, amount=amount)

    def _annual_economy(self):
        self._produce_and_consume()
        self._institutional_trade()
        self._consume_and_demography()
        self._collect_member_levies()
        for town in self.settlements:
            for resource, cap, rate in (('food', 24, 6), ('wood', 32, 6), ('iron', 16, 3)):
                quantity = max(0., min(rate, cap - town.deposits[resource], getattr(town, resource)))
                setattr(town, resource, getattr(town, resource) - quantity)
                town.deposits[resource] += quantity
        for actor in list(self.agents):
            actor.age += 1
            if actor.age >= 78 or (actor.age > 60 and self.rng.random() < .035):
                self.remove_agent(actor.id)
        self._maintain_institutions()
        for town in self.settlements:
            town.knowledge = max((a.knowledge for a in self.agents if a.home == town.id), default=0)

    def step(self):
        self._maintain_institutions()
        return super().step()

    def advance_time(self):
        self.tick += 1
        self.year = self.tick // self.ticks_per_year
        self._budget_tick = None
        self._batch_knowledge = {}
        self._batch_labor = {}
        self._batch_towns = {}
        self._institution_budget_tick = None
        self._expire_offers()
        self._maintain_institutions()
        if self.tick % self.ticks_per_year == 0:
            self._annual_economy()
            self._assert_invariants()
            self._snapshot()

    def _snapshot(self):
        super()._snapshot()
        if hasattr(self, 'institutions'):
            self.snapshots[-1]['institutions'] = [i.public_state() for i in self.institutions]
            self.snapshots[-1]['settlement_policies'] = self.settlement_policies()

    def _assert_invariants(self):
        super()._assert_invariants()
        if not hasattr(self, 'institutions'):
            return
        living = {a.id: a.home for a in self.agents}
        assert len({i.id for i in self.institutions}) == len(self.institutions)
        for institution in self.institutions:
            assert all(living.get(member) == institution.settlement_id for member in institution.members)
            assert math.isfinite(institution.treasury) and institution.treasury >= -1e-7
            assert all(math.isfinite(v) and v >= -1e-7 for v in institution.inventory.values())
        for policy in self.settlement_policies().values():
            assert 0 <= policy['tax_rate'] <= .15 + 1e-7
            assert 0 <= policy['communal_labor'] <= .3 + 1e-7

    def export(self):
        data = super().export()
        data.update(schema='eternia.v0.4', mode='institutions',
                    institutions=[i.public_state() for i in self.institutions],
                    settlement_policies=self.settlement_policies(),
                    note='Voluntary institutions authorize shared projects, member levies, labor allocation and reciprocal trade. Aggregate households and adult estate succession remain simplified.')
        return data
