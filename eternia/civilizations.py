"""Interconnected settlements whose institutions negotiate their own interests.

Three aggregate economies host independent local cohorts. No institution, route,
embargo or border closure is assigned at initialization. Annual route execution
transfers finite municipal goods and coins under independently approved terms.
"""
from collections import Counter, defaultdict
from copy import deepcopy
from dataclasses import asdict, dataclass
import math

from .community import Citizen, CommunityWorld, RESOURCES
from .institutional_world import InstitutionalWorld
from .model import Settlement
from .regional_engine import RegionalEngine
from .regional_policy import RegionalPolicy


GOODS = ('food', 'wood', 'iron')
REGIONAL_PRICES = {'food': .2, 'wood': .5, 'iron': 1.5}


@dataclass
class RegionalCitizen(Citizen):
    openness: float = .5
    origin: int = 0
    preferred_purpose: str = 'cooperative'


class CivilizationWorld(InstitutionalWorld):
    def __init__(self, seed=42, ticks_per_year=4, shock_year=0, policies=None):
        super().__init__(seed, ticks_per_year, shock_year, policies)
        # Coordinates keep all three towns within the prototype's travel range.
        sites = [
            ('Rivermark', 25., 50., 180, 210., 1.25, .25, .10, .14),
            ('Highfen', 49., 32., 150, 120., .80, .20, 1.40, .85),
            ('Deepwood', 60., 61., 150, 155., 1.03, 1.10, .12, .48),
        ]
        self.settlements = [Settlement(i, *site, food=site[3] * .75,
                                        wood=40., iron=12., treasury=120.)
                            for i, site in enumerate(sites)]
        for town, deposits in zip(self.settlements, ((32., 8., 4.), (10., 8., 18.), (20., 40., 3.))):
            town.deposits = dict(zip(GOODS, deposits))
        specs = [
            ('Aldric', 'farmer', {'kind': 'food', 'target': 12}, (10, 2, 0, 20), ['woodcutting'], 'cooperative'),
            ('Edrin', 'miner', {'kind': 'wealth', 'target': 60}, (3, 0, 6, 12), ['mining'], 'guild'),
            ('Mara', 'merchant', {'kind': 'profit', 'target': 120}, (6, 4, 2, 50), [], 'guild'),
            ('Toren', 'builder', {'kind': 'houses', 'target': 3}, (3, 8, 0, 28), ['carpentry', 'woodcutting'], 'cooperative'),
            ('Lyra', 'researcher', {'kind': 'knowledge', 'target': 2}, (3, 2, 0, 25), ['woodcutting'], 'cooperative'),
            ('Aldren', 'councillor', {'kind': 'influence', 'target': 12}, (4, 2, 1, 35), ['woodcutting'], 'council'),
        ]
        self.agents = []
        for town in self.settlements:
            for name, role, goal, inventory, skills, purpose in specs:
                identity = len(self.agents)
                if role == 'researcher' and self.rng.random() < .5:
                    purpose = 'council'
                self.agents.append(RegionalCitizen(
                    identity, f'{name} of {town.name}', town.id, role,
                    self.rng.random(), self.rng.random(), self.rng.randint(20, 44),
                    inventory=dict(zip(RESOURCES, inventory)),
                    skills=['foraging', 'trading', *skills], goal=dict(goal),
                    lineage=f'{name} of {town.name}',
                    wealth_goal=goal['target'] if role in ('merchant', 'miner') else 60,
                    openness=self.rng.random(), origin=town.id, preferred_purpose=purpose))
        self.next_agent_id = len(self.agents)
        self.institutions = []
        self.next_institution_id = 0
        self.next_proposal_id = 0
        self.routes = []
        self.next_route_id = 0
        self.trade_shipments = []
        self._regional_trade_year = None
        self._regional_trade_budgets = {}
        self._tick_borders = {}
        self.diplomacy = {f'{a.id}:{b.id}': 0. for a in self.settlements
                          for b in self.settlements if a.id != b.id}
        self._failed_negotiations = set()
        self._flows = {s.id: {kind: dict.fromkeys(GOODS, 0.) for kind in
                              ('production', 'imports', 'exports')} for s in self.settlements}
        self._migration = {s.id: {'in': 0, 'out': 0} for s in self.settlements}
        self.metrics.update(negotiation_attempts=0, negotiation_successes=0,
                            negotiations_failed=0, trade_shipments=0, trade_volume=0.,
                            regional_migrations=0, trade_shortfalls=0,
                            routes_expired=0, routes_cancelled=0,
                            embargo_mandates=0, specialization_mandates=0, border_mandates=0)
        self._default_policy = RegionalPolicy()
        self.action_engine = RegionalEngine(self)
        self.events = []
        self.action_log = []
        self.decisions = []
        self.snapshots = []
        self.last_action_year = {}
        self._budget_tick = None
        self._institution_budget_tick = None
        self.initial_totals = self.resource_totals()
        self._event('world', 'Three settlements begin with eighteen independent people and no political or commercial agreements.')
        self._snapshot()

    def local_named_count(self, town):
        return sum(a.home == town for a in self.agents)

    def _begin_institution_tick(self):
        if self._institution_budget_tick != self.tick:
            self._tick_borders = {s.id: self.regional_migration_open(s.id) for s in self.settlements}
            self._institution_budget_tick = self.tick
            self._institution_frames = {i.id: self._authority_frame(i) for i in self.institutions}
            self._institution_remaining = {i.id: {**i.inventory, 'coins': i.treasury} for i in self.institutions}

    def _authority_frame(self, institution):
        return {'id': institution.id, 'active': institution.active,
                'members': sorted(institution.members), 'rules': deepcopy(institution.rules),
                'decisions': [deepcopy(d) for d in institution.decisions if d['status'] == 'open'],
                'local_named_count': self.local_named_count(institution.settlement_id)}

    def institution_frame(self, institution):
        if self._institution_budget_tick == self.tick:
            return deepcopy(self._institution_frames.get(institution.id))
        return self._authority_frame(institution)

    def regional_migration_open(self, town):
        councils = [i for i in self.institutions if i.active and i.members
                    and i.settlement_id == town and getattr(i, 'purpose', '') == 'council'
                    and len(i.members) * 2 > self.local_named_count(town)
                    and 'migration_open' in i.rules]
        if not councils:
            return True
        council = max(councils, key=lambda i: (len(i.members), self._mandate_time(i, 'migration_policy'), -i.id))
        return council.rules['migration_open']

    def regional_migration_open_at_start(self, town):
        if self._institution_budget_tick == self.tick:
            return self._tick_borders.get(town, False)
        return self.regional_migration_open(town)

    def open_route(self, institution, other, proposal, reciprocal):
        terms = proposal['params']
        exporter, importer = ((institution, other) if terms['direction'] == 'export'
                              else (other, institution))
        route = {'id': self.next_route_id, 'exporter': exporter.settlement_id,
                 'importer': importer.settlement_id, 'exporter_institution': exporter.id,
                 'importer_institution': importer.id, 'resource': terms['resource'],
                 'unit_price': terms['unit_price'], 'quota': terms['quota'],
                 'created': self.tick, 'expires': self.tick + 20, 'active': True,
                 'status': 'active', 'volume': 0., 'shipments': 0,
                 'proposals': [proposal['id'], reciprocal['id']]}
        self.next_route_id += 1
        self.routes.append(route)
        self.metrics['negotiation_successes'] += 1
        self._event('agreement', f'{self.settlements[exporter.settlement_id].name} and '
                    f'{self.settlements[importer.settlement_id].name} authorized '
                    f'{terms["resource"]} trade at {terms["unit_price"]:g} coins per unit '
                    f'for twenty ticks.', route_id=route['id'])
        return route

    def _adjust_diplomacy(self, origin, destination, amount):
        key = f'{origin}:{destination}'
        self.diplomacy[key] = min(1., max(-1., self.diplomacy.get(key, 0) + amount))

    def _refresh_treaties(self):
        # The parent constructor has no regional state yet.
        if not hasattr(self, 'routes'):
            return super()._refresh_treaties()
        organizations = {i.id: i for i in self.institutions}
        for town in self.settlements:
            town.relations = {}
        for route in self.routes:
            if route['status'] in ('expired', 'cancelled'):
                continue
            exporter = organizations.get(route['exporter_institution'])
            importer = organizations.get(route['importer_institution'])
            if not exporter or not importer or not all(i.active and i.members for i in (exporter, importer)):
                route.update(active=False, status='cancelled')
                self.metrics['routes_cancelled'] += 1
                self._event('agreement', f'Route {route["id"]} lost an active sponsoring institution and closed.', route_id=route['id'])
                continue
            if self.tick >= route['expires']:
                route.update(active=False, status='expired')
                self.metrics['routes_expired'] += 1
                self._event('agreement', f'Route {route["id"]} expired; renewal requires new independent mandates.', route_id=route['id'])
                continue
            blocked = self._sponsor_embargo(exporter, importer.settlement_id) or self._sponsor_embargo(importer, exporter.settlement_id)
            route.update(active=not blocked, status='suspended' if blocked else 'active')
            if route['active']:
                self.settlements[route['exporter']].relations[route['importer']] = 'trade'
                self.settlements[route['importer']].relations[route['exporter']] = 'trade'

    @staticmethod
    def _sponsor_embargo(institution, destination):
        embargoes = institution.rules.get('embargoes', {})
        return embargoes.get(destination, embargoes.get(str(destination), False)) is True

    @staticmethod
    def _mandate_time(institution, kind):
        return max((d.get('enacted', -1) for d in institution.decisions
                    if d['kind'] == kind and d['status'] == 'enacted'), default=-1)

    def _maintain_institutions(self):
        super()._maintain_institutions()
        if not hasattr(self, '_failed_negotiations'):
            return
        for institution in self.institutions:
            for proposal in institution.decisions:
                if (proposal['kind'] != 'trade_terms' or proposal['status'] not in ('rejected', 'expired')
                        or proposal['id'] in self._failed_negotiations):
                    continue
                self._failed_negotiations.add(proposal['id'])
                self.metrics['negotiations_failed'] += 1
                destination = proposal['params']['destination']
                self._adjust_diplomacy(institution.settlement_id, destination, -.035)
                self._event('negotiation', f'{institution.name}\'s proposed {proposal["params"]["resource"]} '
                            f'terms with {self.settlements[destination].name} {proposal["status"]}.',
                            self.settlements[institution.settlement_id].name,
                            institution_id=institution.id, proposal_id=proposal['id'])

    def settlement_policies(self):
        policies = super().settlement_policies()
        for town in self.settlements:
            candidates = [i for i in self.institutions if i.active and i.members
                          and i.settlement_id == town.id and i.rules.get('specialization') in GOODS]
            chosen = max(candidates, key=lambda i: (len(i.members), self._mandate_time(i, 'specialization'), -i.id)) if candidates else None
            policies[town.id].update(specialization=chosen.rules['specialization'] if chosen else None,
                                      specialization_institution=chosen.id if chosen else None,
                                      migration_open=self.regional_migration_open(town.id))
        return policies

    def _produce_and_consume(self):
        before = dict(self.ledger['produced'])
        # Reuse the tested base mechanical production, then account a voted
        # specialization's additional output or opportunity-cost reduction.
        prior = {s.id: {r: getattr(s, r) for r in GOODS} for s in self.settlements}
        super()._produce_and_consume()
        for town in self.settlements:
            specialization = self.settlement_policies()[town.id]['specialization']
            labor = self.settlement_policies()[town.id]['communal_labor']
            # Wood/iron base output is known before the base stock-cap sink.
            raw = {'wood': town.population * .11 * town.forest * (1 - labor),
                   'iron': town.population * .025 * town.ore * (1 + .07 * town.mining_level) * (1 - labor)}
            # Food has no production cap or sink in the base production phase.
            raw['food'] = town.food - prior[town.id]['food']
            for resource in GOODS:
                factor = 1.3 if resource == specialization else .9 if specialization else 1.
                adjustment = raw[resource] * (factor - 1)
                # Undo the base capacity clamp before applying specialization.
                cap = (max(150., town.population * .7) if resource == 'wood' else
                       max(80., town.population * .22) if resource == 'iron' else None)
                base_excess = max(0., prior[town.id][resource] + raw[resource] - cap) if cap else 0.
                value = getattr(town, resource) + base_excess + adjustment
                excess = max(0., value - cap) if cap else 0.
                setattr(town, resource, value - excess)
                self.ledger['produced'][resource] += adjustment
                self.ledger['consumed'][resource] += excess - base_excess
                self._flows[town.id]['production'][resource] += raw[resource] * factor
        assert all(self.ledger['produced'][r] >= before[r] for r in GOODS)

    def _institutional_trade(self):
        self._refresh_treaties()
        if self._regional_trade_year != self.year:
            self._regional_trade_year = self.year
            self._regional_trade_budgets = {
                s.id: {**{r: getattr(s, r) for r in GOODS}, 'coins': s.treasury}
                for s in self.settlements}
        budgets = self._regional_trade_budgets
        routes = sorted((r for r in self.routes if r['active']), key=lambda r: r['id'])
        self.rng.shuffle(routes)
        for route in routes:
            exporter, importer = self.settlements[route['exporter']], self.settlements[route['importer']]
            if route.get('quota_year') != self.year:
                route.update(quota_year=self.year, quota_used=0.)
            resource, price = route['resource'], route['unit_price']
            reserve = exporter.population * {'food': 1.1, 'wood': .10, 'iron': .04}[resource]
            target = importer.population * {'food': 1.12, 'wood': .25, 'iron': .12}[resource]
            available = max(0., min(getattr(exporter, resource), budgets[exporter.id][resource]) - reserve)
            want = max(0., target - getattr(importer, resource))
            cash = max(0., min(importer.treasury, budgets[importer.id]['coins']))
            amount = min(max(0., route['quota'] - route['quota_used']), available, want, cash / price)
            if amount < .1:
                if want >= 1:
                    self.metrics['trade_shortfalls'] += 1
                continue
            coins = min(cash, amount * price)
            setattr(exporter, resource, getattr(exporter, resource) - amount)
            setattr(importer, resource, getattr(importer, resource) + amount)
            importer.treasury -= coins
            exporter.treasury += coins
            budgets[exporter.id][resource] -= amount
            budgets[importer.id]['coins'] -= coins
            route['volume'] += amount
            route['quota_used'] += amount
            route['shipments'] += 1
            self.metrics['trade_shipments'] += 1
            self.metrics['trade_volume'] += amount
            self._flows[exporter.id]['exports'][resource] += amount
            self._flows[importer.id]['imports'][resource] += amount
            shipment = {'year': self.year, 'tick': self.tick, 'route': route['id'],
                        'exporter': exporter.id, 'importer': importer.id,
                        'resource': resource, 'amount': amount, 'coins': coins}
            self.trade_shipments.append(shipment)
            self._adjust_diplomacy(exporter.id, importer.id, .025)
            self._adjust_diplomacy(importer.id, exporter.id, .025)
            self._event('shipment', f'{exporter.name} exported {amount:g} {resource} to {importer.name} '
                        f'for {coins:g} coins under negotiated terms.', exporter.name,
                        route_id=route['id'], destination=importer.id, resource=resource, amount=amount)

    def _annual_economy(self):
        super()._annual_economy()
        # Household fuel, tools and repairs make industrial inputs useful. These
        # are explicit aggregate sinks, not transfers into an invisible market.
        for town in self.settlements:
            for resource, rate in (('wood', .05), ('iron', .015)):
                used = min(getattr(town, resource), town.population * rate)
                setattr(town, resource, getattr(town, resource) - used)
                self.ledger['consumed'][resource] += used

    def _shock(self):
        if self.shock_year and self.year >= self.shock_year and not self.shock_applied:
            before = self.resource_totals()
            town = self.settlements[1]
            town.deposits['iron'] = 0.
            town.ore *= .2
            self.shock_applied = True
            self._account(before)
            self._event('disruption', f'A configured rockfall closed {town.name}\'s accessible iron deposit and reduced mining output.', town.name)

    def resolve_actions(self, proposals):
        results = super().resolve_actions(proposals)
        for audit in results:
            action, result = audit['action'], audit['result']
            if result['success'] and action.get('type') == 'migrate':
                origin, destination = result['effects']['origin'], result['effects']['destination']
                self._migration[origin]['out'] += 1
                self._migration[destination]['in'] += 1
                self.metrics['regional_migrations'] += 1
        return results

    def update_relationships(self, results):
        super().update_relationships(results)
        for audit in results:
            if audit['result']['success'] and audit['action'].get('type') == 'enact':
                try:
                    self._resolve_agent(audit['action']['actor']).influence += 1
                except ValueError:
                    pass

    def remove_agent(self, actor_id, cause='old age'):
        parent = self._resolve_agent(actor_id)
        openness, origin, purpose = parent.openness, parent.origin, parent.preferred_purpose
        successor = super().remove_agent(actor_id, cause)
        replacement = RegionalCitizen(**asdict(successor),
                                      openness=min(1., max(0., openness * .6 + self.rng.random() * .4)),
                                      origin=origin, preferred_purpose=purpose)
        self.agents[self.agents.index(successor)] = replacement
        return replacement

    def observe(self, actor):
        # Keep the policy's public bulletin bounded; the historical explorer
        # retains every proposal. Copying decades of closed decisions into each
        # person's quarterly perception adds no actionable information.
        observation = CommunityWorld.observe(self, actor)
        person = self._resolve_agent(actor)
        visible = {person.home, *(s['id'] for s in observation['neighbors'])}
        for neighbor in observation['neighbors']:
            neighbor['migration_open'] = self.regional_migration_open(neighbor['id'])
            neighbor['permissions']['migrate'] = neighbor['permissions'].get('migrate', True) and neighbor['migration_open']
        observation['institutions'] = []
        for institution in self.institutions:
            if institution.settlement_id not in visible:
                continue
            state = {k: deepcopy(getattr(institution, k)) for k in
                     ('id', 'name', 'settlement_id', 'rules', 'active', 'founded', 'empty_since', 'purpose')}
            state['members'] = sorted(institution.members)
            state['decisions'] = [deepcopy(d) for d in institution.decisions if d['status'] == 'open'
                                  or d.get('enacted', d['created']) >= self.tick - 12]
            if person.id in institution.members:
                state.update(inventory=dict(institution.inventory), treasury=institution.treasury,
                             available_inventory=self.available_institution_inventory(institution))
            observation['institutions'].append(state)
        observation['memberships'] = [i.id for i in self.institutions if i.active and person.id in i.members]
        observation['actor']['memberships'] = list(observation['memberships'])
        observation['settlement_policies'] = self.settlement_policies()[person.home]
        observation['regional'] = {
            'prices': dict(REGIONAL_PRICES), 'local_named_count': self.local_named_count(person.home),
            'diplomacy': {s.id: self.diplomacy.get(f'{person.home}:{s.id}', 0.)
                          for s in self.settlements if s.id != person.home and s.id in visible},
            'routes': deepcopy([r for r in self.routes if r['exporter'] in visible and r['importer'] in visible
                                 and (r['status'] in ('active', 'suspended') or r['expires'] >= self.tick - 12)]),
            'profiles': {i: state for i, state in self._settlement_profiles(private=False).items() if i in visible},
            'borders': {s.id: self.regional_migration_open(s.id) for s in self.settlements if s.id in visible},
        }
        return observation

    def _settlement_profiles(self, private=True):
        policies = self.settlement_policies()
        profiles = {}
        for town in self.settlements:
            members = [a for a in self.agents if a.home == town.id]
            organizations = [i for i in self.institutions if i.active and i.settlement_id == town.id]
            profiles[town.id] = {'population': town.population, 'named_agents': len(members),
                                 **deepcopy(self._flows[town.id]),
                                 'migration_in': self._migration[town.id]['in'],
                                 'migration_out': self._migration[town.id]['out'],
                                 'active_institutions': len(organizations),
                                 'purposes': dict(Counter(getattr(i, 'purpose', 'cooperative') for i in organizations)),
                                 'specialization': policies[town.id].get('specialization'),
                                 'migration_open': self.regional_migration_open(town.id)}
            if private:
                profiles[town.id]['wealth'] = (town.treasury + sum(a.inventory.get('coins', 0) for a in members)
                                               + sum(i.treasury for i in organizations))
        return profiles

    def regional_metrics(self):
        profiles = self._settlement_profiles()
        edges = defaultdict(lambda: {'volume': 0., 'coins': 0.})
        for shipment in self.trade_shipments:
            edge = edges[(shipment['exporter'], shipment['importer'], shipment['resource'])]
            edge['volume'] += shipment['amount']
            edge['coins'] += shipment['coins']
        outcomes = Counter(p['status'] for i in self.institutions for p in i.decisions if p['kind'] == 'trade_terms')
        connected = {town for route in self.routes if route['active'] for town in (route['exporter'], route['importer'])}
        hostile = sorted({(i.settlement_id, int(other)) for i in self.institutions if i.active and i.members
                          for other, closed in i.rules.get('embargoes', {}).items() if closed})
        return {'per_settlement': profiles,
                'network_edges': [dict(exporter=a, importer=b, resource=r, **value)
                                  for (a, b, r), value in sorted(edges.items())],
                'isolated_settlements': [s.id for s in self.settlements if s.id not in connected],
                'active_routes': sum(r['active'] for r in self.routes),
                'hostile_pairs': [list(pair) for pair in hostile],
                'negotiation_outcomes': {'proposed': sum(outcomes.values()), 'agreed': outcomes['enacted'],
                                         'rejected': outcomes['rejected'], 'expired': outcomes['expired']},
                'local_competition': sum(max(0, profile['active_institutions'] - 1) for profile in profiles.values())}

    def _snapshot(self):
        super()._snapshot()
        if hasattr(self, 'routes'):
            snap = self.snapshots[-1]
            snap.update(routes=deepcopy(self.routes), diplomacy=dict(self.diplomacy),
                        regional_metrics=self.regional_metrics(), shipment_count=len(self.trade_shipments))
            # The full action/decision archive remains available. Avoid copying
            # sixty-four memories for every person into every annual snapshot.
            for actor in snap['agents']:
                actor['memory'] = actor['memory'][-8:]
            for town in snap['settlements']:
                town['migration_open'] = self.regional_migration_open(town['id'])

    def _assert_invariants(self):
        super()._assert_invariants()
        if not hasattr(self, 'routes'):
            return
        assert all(math.isfinite(s.treasury) and s.treasury >= 0 for s in self.settlements)
        assert all(-1 <= value <= 1 for value in self.diplomacy.values())
        assert len({r['id'] for r in self.routes}) == len(self.routes)
        assert all(r['exporter'] != r['importer'] and r['unit_price'] > 0 and 1 <= r['quota'] <= 40
                   for r in self.routes)

    def export(self):
        data = super().export()
        data.update(schema='eternia.v0.5', mode='civilizations', routes=deepcopy(self.routes),
                    diplomacy=dict(self.diplomacy), trade_shipments=deepcopy(self.trade_shipments),
                    regional_metrics=self.regional_metrics(),
                    note='Three aggregate settlements and eighteen initial independent people. Political and commercial outcomes depend on individual utility, votes, finite resources and negotiated terms. No initial agreements or scripted political outcomes; optional shock is a controlled scenario. Adult estate succession remains simplified.')
        return data
