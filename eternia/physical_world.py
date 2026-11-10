"""Seasonal journeys, finite mineral seams and institution-maintained routes.

Cargo and payment remain in transit until delivery. Every loss is an explicit
ledger sink; reservation, travel and arrival never manufacture resources.
"""
from copy import deepcopy
import heapq
import math

from .actions import _number, _require, _Rejected
from .civilizations import CivilizationWorld, GOODS
from .community import CommunityWorld, RESOURCES
from .institutional_world import InstitutionalWorld


class PhysicalWorld(CivilizationWorld):
    def __init__(self, seed=42, ticks_per_year=4, shock_year=0, policies=None):
        super().__init__(seed, ticks_per_year, shock_year, policies)
        from .logistics_engine import LogisticsEngine
        from .logistics_policy import LogisticsPolicy
        specs = [(0, 2, 'river', .80, 28., 18., .012),
                 (0, 1, 'upland', .65, 18., 12., .025),
                 (1, 2, 'mountain', .55, 12., 9., .045)]
        self.links = []
        for identity, (a, b, terrain, condition, capacity, speed, risk) in enumerate(specs):
            distance = math.hypot(self.settlements[a].x - self.settlements[b].x,
                                  self.settlements[a].y - self.settlements[b].y)
            self.links.append(dict(id=identity, a=a, b=b, terrain=terrain,
                                   distance=distance, condition=condition,
                                   capacity=capacity, speed=speed, risk=risk,
                                   owner=None, closed=False))
        self.journeys = []
        self.next_journey_id = 0
        self.mineral_reserves = {0: 40., 1: 350., 2: 65.}
        self.initial_mineral_reserves = dict(self.mineral_reserves)
        self.physical_metrics = dict.fromkeys((
            'caravans_dispatched', 'caravans_delivered', 'caravans_failed',
            'migrants_departed', 'migrants_arrived', 'migrants_returned',
            'cargo_delivered', 'cargo_lost', 'supplies_consumed', 'road_repairs',
            'route_disruptions', 'mines_exhausted'), 0)
        self._physical_tick = None
        self._physical_links = {}
        self._physical_contracts = {}
        self._link_remaining = {}
        self._environment_tick = None
        self._default_policy = LogisticsPolicy()
        self.action_engine = LogisticsEngine(self)
        self.events = []
        self.snapshots = []
        self.initial_totals = self.resource_totals()
        self._event('world', 'A river, upland track and mountain pass connect three communities. '
                    'Transport takes seasons; mineral seams are finite.')
        self._snapshot()

    def _begin_institution_tick(self):
        super()._begin_institution_tick()
        if hasattr(self, 'links') and self._physical_tick != self.tick:
            self._physical_tick = self.tick
            self._physical_links = {link['id']: deepcopy(link) for link in self.links}
            self._physical_contracts = {r['id']: deepcopy(r) for r in self.routes if r['active']}
            self._link_remaining = {link['id']: max(0., self._effective_capacity(link) - self._occupied_capacity(link['id']))
                                    for link in self.links}

    def link_frame(self, identity):
        if self._physical_tick == self.tick:
            return deepcopy(self._physical_links.get(identity))
        return deepcopy(next((link for link in self.links if link['id'] == identity), None))

    def is_traveling(self, actor):
        return any(j['kind'] == 'migrant' and j['actor'] == actor and j['status'] == 'in_transit'
                   for j in getattr(self, 'journeys', ()))

    def local_named_count(self, town):
        return sum(a.home == town and not self.is_traveling(a.id) for a in self.agents)

    @staticmethod
    def _effective_capacity(link):
        return link['capacity'] * max(0., link['condition'])

    def _accessible(self, link, sponsor=None):
        return link['condition'] > .12 and (not link['closed'] or link['owner'] == sponsor)

    def _plan_with_links(self, origin, destination, sponsor, links):
        queue = [(0., origin, [])]
        best = {}
        while queue:
            cost, node, path = heapq.heappop(queue)
            if node in best:
                continue
            best[node] = cost
            if node == destination:
                selected = [next(l for l in links if l['id'] == identity) for identity in path]
                duration = sum(max(1, math.ceil(l['distance'] / (l['speed'] * (.4 + .6 * l['condition']))))
                               for l in selected)
                return dict(path=path, duration=duration,
                            capacity=min(self._effective_capacity(l) for l in selected),
                            risk=1 - math.prod(1 - min(1., l['risk']) for l in selected),
                            supplies=round(duration * .5 + 1., 6))
            for link in links:
                if node not in (link['a'], link['b']) or not self._accessible(link, sponsor):
                    continue
                other = link['b'] if node == link['a'] else link['a']
                if other not in best:
                    duration = math.ceil(link['distance'] / (link['speed'] * (.4 + .6 * link['condition'])))
                    heapq.heappush(queue, (cost + duration, other, path + [link['id']]))
        return None

    def journey_plan(self, origin, destination, sponsor=None):
        if origin == destination:
            return None
        return self._plan_with_links(origin, destination, sponsor, self.links)

    def _departure_plan(self, origin, destination, sponsor=None):
        links = deepcopy(self.links)
        if self._physical_tick == self.tick:
            for link in links:
                original = self._physical_links.get(link['id'])
                if original is None:
                    link['condition'] = 0.
                    continue
                link['condition'] = min(link['condition'], original['condition'])
                if not self._accessible(original, sponsor):
                    link['closed'] = True
                    link['owner'] = -1
        return self._plan_with_links(origin, destination, sponsor, links)

    def _original_path_available(self, origin, destination, sponsor, plan):
        if self._physical_tick != self.tick:
            return True
        return all(identity in self._physical_links
                   and self._accessible(self._physical_links[identity], sponsor)
                   for identity in plan['path'])

    def _municipal_available(self, town, resource):
        live = town.treasury if resource == 'coins' else getattr(town, resource)
        if self._budget_tick != self.tick:
            return live
        return max(0., min(live, self._batch_towns.get(town.id, {}).get(resource, 0.)))

    def _available_capacity(self, path):
        live = {i: max(0., self._effective_capacity(self.links[i]) - self._occupied_capacity(i)) for i in path}
        if self._physical_tick != self.tick:
            return min(live.values())
        return min(min(self._link_remaining.get(i, 0.), live[i]) for i in path)

    def _occupied_capacity(self, identity):
        return sum(j.get('transport_load', 1.) for j in self.journeys
                   if j['status'] == 'in_transit' and identity in j['path'][j['leg']:])

    def caravan_quote(self, actor, contract_id, amount):
        _require(type(contract_id) is int and contract_id >= 0, 'unknown_route', 'Use an integer trade contract ID.')
        amount = _number(amount, 'amount', minimum=.1, maximum=40)
        route = next((r for r in self.routes if r['id'] == contract_id), None)
        _require(route is not None and route['active'] and route['expires'] > self.tick,
                 'route_unavailable', 'An active negotiated trade contract is required.')
        _require(self._physical_tick != self.tick or contract_id in self._physical_contracts,
                 'route_unavailable', 'The trade contract must already exist at tick start.')
        _require(actor.home == route['exporter'], 'remote_action', 'Transport is organized at its source.')
        sponsor = self._resolve_institution(route['exporter_institution'])
        _require(sponsor.active and actor.id in sponsor.members, 'not_member', 'The exporting sponsor must authorize its organizer.')
        counterpart = self._resolve_institution(route['importer_institution'])
        _require(counterpart.active and counterpart.members
                 and not self._sponsor_embargo(sponsor, route['importer'])
                 and not self._sponsor_embargo(counterpart, route['exporter']),
                 'route_unavailable', 'A current sponsor closure invalidates a planned departure.')
        plan = self._departure_plan(route['exporter'], route['importer'], sponsor.id)
        _require(plan is not None, 'no_path', 'No open physical route reaches the destination.')
        _require(self._original_path_available(route['exporter'], route['importer'], sponsor.id, plan),
                 'no_path', 'A newly repaired or reopened route becomes usable next tick.')
        load = amount + plan['supplies']
        _require(self._available_capacity(plan['path']) + 1e-9 >= load,
                 'transport_capacity', 'Cargo and provisions exceed the remaining route capacity this tick.')
        used = route.get('quota_used', 0.) if route.get('quota_year') == self.year else 0.
        _require(used + amount <= route['quota'] + 1e-9, 'quota_exceeded', 'The annual contract quota is already reserved.')
        exporter, importer = self.settlements[route['exporter']], self.settlements[route['importer']]
        resource, price = route['resource'], route['unit_price']
        reserve = exporter.population * {'food': 1.1, 'wood': .10, 'iron': .04}[resource]
        required = {resource: amount}
        required['food'] = required.get('food', 0) + plan['supplies']
        for good, quantity in required.items():
            retained = reserve if good == resource else 0.
            _require(self._municipal_available(exporter, good) >= quantity + retained,
                     'insufficient_resources', 'The source lacks tick-start cargo, provisions or its domestic reserve.')
        pending = sum(j['cargo'].get(resource, 0.) for j in self.journeys
                      if j['kind'] == 'caravan' and j['status'] == 'in_transit' and j['destination'] == importer.id)
        target = importer.population * {'food': 1.12, 'wood': .25, 'iron': .12}[resource]
        _require(target - getattr(importer, resource) - pending + 1e-9 >= amount,
                 'not_needed', 'Stocks and already incoming cargo cover this import need.')
        coins = amount * price
        _require(self._municipal_available(importer, 'coins') >= coins,
                 'insufficient_resources', 'The destination cannot escrow the payment from tick-start coins.')
        return dict(route=route, amount=amount, resource=resource, coins=coins,
                    origin=exporter.id, destination=importer.id, sponsor=sponsor.id, **plan)

    def _new_journey(self, kind, quote, **extra):
        journey = dict(id=self.next_journey_id, kind=kind, status='in_transit',
                       origin=quote['origin'], destination=quote['destination'],
                       path=list(quote['path']), duration=quote['duration'],
                       created=self.tick, last_progress_tick=self.tick,
                       leg=0, progress=0., node=quote['origin'], waiting=0,
                       returning=False, cargo={}, escrow=0., supplies=quote['supplies'], **extra)
        self.next_journey_id += 1
        self.journeys.append(journey)
        return journey

    def launch_caravan(self, actor, details):
        route, amount = details['route'], details['amount']
        exporter, importer = self.settlements[details['origin']], self.settlements[details['destination']]
        resource = details['resource']
        setattr(exporter, resource, getattr(exporter, resource) - amount)
        exporter.food -= details['supplies']
        importer.treasury -= details['coins']
        journey = self._new_journey('caravan', details, organizer=actor.id,
                                    sponsor=details['sponsor'], contract=route['id'])
        journey.update(cargo={resource: amount}, escrow=details['coins'])
        journey['transport_load'] = amount + details['supplies']
        if route.get('quota_year') != self.year:
            route.update(quota_year=self.year, quota_used=0.)
        route['quota_used'] += amount
        for identity in details['path']:
            self._link_remaining[identity] -= amount + details['supplies']
        self.physical_metrics['caravans_dispatched'] += 1
        return dict(journey_id=journey['id'], costs={}, message=
                    f'{actor.name} dispatched {amount:g} {resource}; cargo and payment are held in transit for an estimated {details["duration"]} ticks.')

    def migration_quote(self, actor, destination):
        plan = self._departure_plan(actor.home, destination)
        _require(plan is not None, 'no_path', 'No open route is available for migration.')
        _require(self._original_path_available(actor.home, destination, None, plan),
                 'no_path', 'A newly opened path becomes available next tick.')
        _require(self._available_capacity(plan['path']) >= 1., 'transport_capacity', 'There is no remaining passage capacity.')
        supplies = plan['duration'] + 2.  # half a food/tick, including a return contingency
        _require(self.available_inventory(actor)['food'] + 1e-9 >= supplies,
                 'insufficient_resources', 'Migration needs provisions for the journey and a possible return.')
        return dict(origin=actor.home, destination=destination, **{**plan, 'supplies': supplies})

    def launch_migration(self, actor, quote):
        actor.inventory['food'] -= quote['supplies']
        self.settlements[actor.home].population -= 1
        journey = self._new_journey('migrant', quote, actor=actor.id, sponsor=None)
        for institution in self.institutions:
            institution.members.discard(actor.id)
        self.offers[:] = [o for o in self.offers if o['actor'] != actor.id]
        for identity in quote['path']:
            self._link_remaining[identity] -= 1.
        self.physical_metrics['migrants_departed'] += 1
        return dict(journey_id=journey['id'], origin=quote['origin'], destination=quote['destination'],
                    costs={}, message=f'{actor.name} began a {quote["duration"]}-tick migration journey.')

    def resource_totals(self):
        totals = super().resource_totals()
        totals['iron'] += sum(getattr(self, 'mineral_reserves', {}).values())
        for journey in getattr(self, 'journeys', ()):
            if journey['status'] != 'in_transit':
                continue
            totals['food'] += journey['supplies']
            totals['coins'] += journey['escrow']
            for resource, amount in journey['cargo'].items():
                totals[resource] += amount
        return totals

    def resolve_actions(self, proposals):
        # Migration is counted on arrival, rather than by the v0.5 immediate move.
        return InstitutionalWorld.resolve_actions(self, proposals)

    def _institutional_trade(self):
        # An agreement authorizes transport; only a dispatch action launches it.
        self._refresh_treaties()

    def _consume_supplies(self, journey):
        eaten = min(.5, journey['supplies'])
        journey['supplies'] -= eaten
        self.ledger['consumed']['food'] += eaten
        self.physical_metrics['supplies_consumed'] += eaten
        return eaten

    def _fail_caravan(self, journey, reason):
        for resource, amount in journey['cargo'].items():
            self.ledger['consumed'][resource] += amount
            self.physical_metrics['cargo_lost'] += amount
        self.ledger['consumed']['food'] += journey['supplies']
        self.settlements[journey['destination']].treasury += journey['escrow']
        journey.update(status='failed', arrived=self.tick, reason=reason,
                       lost_cargo=dict(journey['cargo']), cargo={}, supplies=0., escrow=0.)
        self.physical_metrics['caravans_failed'] += 1
        self._event('caravan_loss', f'Caravan {journey["id"]} failed: {reason}. Its reserved payment was refunded.',
                    self.settlements[journey['origin']].name, journey_id=journey['id'])

    def _turn_back(self, journey, reason):
        if journey['returning']:
            return
        traveled = journey['path'][:journey['leg']]
        if journey['progress'] > 0 and journey['leg'] < len(journey['path']):
            identity = journey['path'][journey['leg']]
            traveled.append(identity)
            distance = self.links[identity]['distance']
            progress = distance - journey['progress']
            link = self.links[identity]
            journey['node'] = link['b'] if journey['node'] == link['a'] else link['a']
        else:
            progress = 0.
        journey.update(path=list(reversed(traveled)), leg=0, progress=progress,
                       returning=True, waiting=0, reason=reason)
        self._event('migration_return', f'A migrant turned back: {reason}.', journey_id=journey['id'])
        if not traveled:
            self._finish_migrant(journey, returned=True)

    def _finish_migrant(self, journey, returned=False):
        actor = self._resolve_agent(journey['actor'])
        town = journey['origin'] if returned else journey['destination']
        actor.home = town
        self.settlements[town].population += 1
        actor.inventory['food'] += journey['supplies']
        journey.update(status='returned' if returned else 'delivered', arrived=self.tick, supplies=0.)
        self.physical_metrics['migrants_returned' if returned else 'migrants_arrived'] += 1
        if not returned:
            self._migration[journey['origin']]['out'] += 1
            self._migration[town]['in'] += 1
            self.metrics['regional_migrations'] += 1
        self._event('arrival', f'{actor.name} {"returned to" if returned else "arrived in"} '
                    f'{self.settlements[town].name} after a physical journey.', self.settlements[town].name,
                    actor.name, journey_id=journey['id'])
        if journey.get('retirement_pending'):
            super().remove_agent(actor.id, journey['retirement_pending'])

    def _deliver_caravan(self, journey):
        exporter, importer = self.settlements[journey['origin']], self.settlements[journey['destination']]
        route = next(r for r in self.routes if r['id'] == journey['contract'])
        for resource, amount in journey['cargo'].items():
            setattr(importer, resource, getattr(importer, resource) + amount)
            self._flows[exporter.id]['exports'][resource] += amount
            self._flows[importer.id]['imports'][resource] += amount
            route['volume'] += amount
            route['shipments'] += 1
            self.metrics['trade_shipments'] += 1
            self.metrics['trade_volume'] += amount
            self.physical_metrics['cargo_delivered'] += amount
            self.trade_shipments.append(dict(year=self.year, tick=self.tick, route=route['id'],
                                             exporter=exporter.id, importer=importer.id,
                                             resource=resource, amount=amount, coins=journey['escrow'],
                                             journey=journey['id']))
        exporter.treasury += journey['escrow']
        importer.food += journey['supplies']
        self._adjust_diplomacy(exporter.id, importer.id, .025)
        self._adjust_diplomacy(importer.id, exporter.id, .025)
        journey.update(status='delivered', arrived=self.tick, delivered_cargo=dict(journey['cargo']),
                       cargo={}, escrow=0., supplies=0.)
        self.physical_metrics['caravans_delivered'] += 1
        self._event('delivery', f'Caravan {journey["id"]} delivered its cargo to {importer.name}; '
                    'the exporter received the reserved payment.', importer.name, journey_id=journey['id'])

    def _advance_journeys(self):
        for journey in self.journeys:
            if (journey['status'] != 'in_transit' or self.tick <= journey['created']
                    or journey['last_progress_tick'] >= self.tick):
                continue
            journey['last_progress_tick'] = self.tick
            eaten = self._consume_supplies(journey)
            if eaten < .5 and not journey['returning']:
                if journey['kind'] == 'caravan':
                    self._fail_caravan(journey, 'provisions exhausted during the journey')
                    continue
                self._turn_back(journey, 'provisions exhausted')
            if journey['status'] != 'in_transit':
                continue
            if journey['leg'] >= len(journey['path']):
                continue
            link = self.links[journey['path'][journey['leg']]]
            if not journey['returning'] and not self._accessible(link, journey['sponsor']):
                journey['waiting'] += 1
                if journey['waiting'] >= 2 and journey['kind'] == 'migrant':
                    self._turn_back(journey, 'the route became impassable')
                continue
            journey['waiting'] = 0
            if not journey['returning'] and self.rng.random() < min(1., link['risk'] * (1.5 - link['condition'])):
                if journey['kind'] == 'caravan':
                    self._fail_caravan(journey, f'an accident on the {link["terrain"]} route')
                    continue
                self._turn_back(journey, 'unsafe conditions ahead')
                continue
            condition = max(.15, link['condition']) if journey['returning'] else link['condition']
            speed = link['speed'] * (.4 + .6 * condition) * (.75 if journey['returning'] else 1.)
            journey['progress'] = min(link['distance'], journey['progress'] + speed)
            if journey['progress'] + 1e-9 < link['distance']:
                continue
            journey['node'] = link['b'] if journey['node'] == link['a'] else link['a']
            journey['leg'] += 1
            journey['progress'] = 0.
            if journey['leg'] < len(journey['path']):
                continue
            if journey['kind'] == 'caravan':
                self._deliver_caravan(journey)
            elif journey['returning']:
                self._finish_migrant(journey, returned=True)
            elif (not self.regional_migration_open(journey['destination'])
                  or self.settlements[journey['destination']].permissions.get('migrate', True) is False):
                self._turn_back(journey, 'the destination closed its border before arrival')
            else:
                self._finish_migrant(journey)

    def _advance_environment(self):
        if self._environment_tick == self.tick:
            return
        self._environment_tick = self.tick
        for link in self.links:
            wear = self.rng.uniform(.0005, .0025) * (1.4 if link['terrain'] == 'mountain' else 1.)
            condition = max(0., link['condition'] - wear)
            if self.rng.random() < (.009 if link['terrain'] == 'river' else .006):
                condition = max(0., condition - self.rng.uniform(.15, .4))
                self.physical_metrics['route_disruptions'] += 1
                self._event('geography', f'A {"flood" if link["terrain"] == "river" else "landslide"} '
                            f'damaged physical route {link["id"]}.', link_id=link['id'])
            link['condition'] = condition
            if link['owner'] is not None:
                owner = next((i for i in self.institutions if i.id == link['owner']), None)
                if owner is None or not owner.active:
                    link.update(owner=None, closed=False)

    def _produce_and_consume(self):
        if not hasattr(self, 'mineral_reserves'):
            return super()._produce_and_consume()
        policies = self.settlement_policies()
        for town in self.settlements:
            labor = policies[town.id]['communal_labor']
            focus = policies[town.id]['specialization']
            factors = {r: 1.3 if r == focus else .9 if focus else 1. for r in GOODS}
            riverside = any(l['terrain'] == 'river' and town.id in (l['a'], l['b']) for l in self.links)
            weather = self.rng.uniform(.86, 1.16)
            harvest = min(town.population * 1.45, town.farmland * town.fertility * (1 + .16 * town.farming_level))
            food = harvest * weather * (1 + .5 * labor) * factors['food'] * (1.08 if riverside else 1.)
            wood = town.population * .11 * town.forest * (1 - labor) * factors['wood']
            iron = min(self.mineral_reserves[town.id], town.population * .025 * town.ore *
                       (1 + .07 * town.mining_level) * (1 - labor) * factors['iron'])
            prior = self.mineral_reserves[town.id]
            self.mineral_reserves[town.id] -= iron
            if prior > 0 and self.mineral_reserves[town.id] == 0:
                self.physical_metrics['mines_exhausted'] += 1
                self._event('depletion', f'{town.name} exhausted its modeled mineral seam.', town.name)
            for resource, amount in (('food', food), ('wood', wood), ('iron', iron)):
                setattr(town, resource, getattr(town, resource) + amount)
                if resource != 'iron':
                    self.ledger['produced'][resource] += amount
                self._flows[town.id]['production'][resource] += amount
            for resource, cap in (('wood', max(150., town.population * .7)),
                                  ('iron', max(80., town.population * .22))):
                excess = max(0., getattr(town, resource) - cap)
                setattr(town, resource, getattr(town, resource) - excess)
                self.ledger['consumed'][resource] += excess

    def update_needs(self):
        for actor in list(self.agents):
            if self.is_traveling(actor.id):
                actor.hunger = min(100., actor.hunger + (2 if self._migrant_journey(actor.id)['supplies'] >= .5 else 10))
                actor.energy = max(0., actor.energy - 1)
                continue
            actor.hunger = min(100., actor.hunger + 28 / self.ticks_per_year)
            actor.energy = min(100., actor.energy + 24 / self.ticks_per_year)
            actor.starvation_ticks = actor.starvation_ticks + 1 if actor.hunger >= 100 else 0
            if actor.starvation_ticks >= 2 * self.ticks_per_year:
                self.remove_agent(actor.id, 'prolonged food deprivation')

    def _migrant_journey(self, actor):
        return next((j for j in getattr(self, 'journeys', ()) if j['kind'] == 'migrant'
                     and j['actor'] == actor and j['status'] == 'in_transit'), None)

    def remove_agent(self, actor_id, cause='old age'):
        journey = self._migrant_journey(actor_id)
        if journey is not None:
            journey['retirement_pending'] = cause
            return self._resolve_agent(actor_id)
        return super().remove_agent(actor_id, cause)

    def update_relationships(self, results):
        # Travelers cannot witness local demonstrations or count as residents.
        travelers = [a for a in self.agents if self.is_traveling(a.id)]
        self.agents[:] = [a for a in self.agents if not self.is_traveling(a.id)]
        try:
            super().update_relationships(results)
        finally:
            self.agents.extend(travelers)
            self.agents.sort(key=lambda a: a.id)

    def observe(self, actor):
        observation = super().observe(actor)
        person = self._resolve_agent(actor)
        journey = self._migrant_journey(person.id)
        observation['actor']['journey'] = deepcopy(journey)
        observation['peers'] = [p for p in observation['peers'] if not self.is_traveling(p['id'])]
        options = []
        if not journey:
            for route in self.routes:
                if not route['active'] or route['exporter'] != person.home:
                    continue
                sponsor = self._resolve_institution(route['exporter_institution'])
                if person.id not in sponsor.members:
                    continue
                # A policy sees public quotes, never foreign personal accounts.
                for amount in (8., 4., 1.):
                    try:
                        quote = self.caravan_quote(person, route['id'], amount)
                    except _Rejected:
                        continue
                    options.append({k: deepcopy(quote[k]) for k in ('amount', 'path', 'duration', 'risk', 'supplies')}
                                   | {'route': route['id']})
                    break
        observation['physical'] = dict(links=deepcopy(self.links),
                                       paths={town.id: self.journey_plan(person.home, town.id)
                                              for town in self.settlements if town.id != person.home},
                                       dispatch_options=options,
                                       mineral_reserves=dict(self.mineral_reserves))
        return observation

    def advance_time(self):
        self.tick += 1
        self.year = self.tick // self.ticks_per_year
        self._budget_tick = None
        self._batch_knowledge = {}
        self._batch_labor = {}
        self._batch_towns = {}
        self._institution_budget_tick = None
        self._physical_tick = None
        self._expire_offers()
        self._advance_environment()
        self._advance_journeys()
        self._maintain_institutions()
        if self.tick % self.ticks_per_year == 0:
            self._annual_economy()
            self._assert_invariants()
            self._snapshot()

    def _snapshot(self):
        super()._snapshot()
        if not hasattr(self, 'links'):
            return
        snap = self.snapshots[-1]
        snap.update(links=deepcopy(self.links), journeys=deepcopy(self.journeys),
                    mineral_reserves=dict(self.mineral_reserves), physical_metrics=self.logistics_metrics())
        snap['population'] += sum(j['kind'] == 'migrant' and j['status'] == 'in_transit' for j in self.journeys)
        for actor in snap['agents']:
            actor['journey'] = deepcopy(self._migrant_journey(actor['id']))
        for town, profile in snap['regional_metrics']['per_settlement'].items():
            profile['named_agents'] = self.local_named_count(town)

    def _settlement_profiles(self, private=True):
        profiles = super()._settlement_profiles(private)
        for town, profile in profiles.items():
            profile['named_agents'] = self.local_named_count(town)
            if private:
                profile['wealth'] -= sum(a.inventory['coins'] for a in self.agents
                                         if a.home == town and self.is_traveling(a.id))
        return profiles

    def logistics_metrics(self):
        return {**self.physical_metrics,
                'in_transit': sum(j['status'] == 'in_transit' for j in self.journeys),
                'cargo_in_transit': sum(sum(j['cargo'].values()) for j in self.journeys if j['status'] == 'in_transit'),
                'coins_in_escrow': sum(j['escrow'] for j in self.journeys if j['status'] == 'in_transit')}

    def _assert_invariants(self):
        super()._assert_invariants()
        if not hasattr(self, 'links'):
            return
        assert all(0 <= link['condition'] <= 1 for link in self.links)
        assert all(math.isfinite(v) and v >= 0 for v in self.mineral_reserves.values())
        assert len({j['id'] for j in self.journeys}) == len(self.journeys)
        assert len({j['actor'] for j in self.journeys if j['kind'] == 'migrant' and j['status'] == 'in_transit'}) == sum(
            j['kind'] == 'migrant' and j['status'] == 'in_transit' for j in self.journeys)
        for journey in self.journeys:
            assert journey['supplies'] >= -1e-7 and journey['escrow'] >= -1e-7
            assert all(amount >= 0 and math.isfinite(amount) for amount in journey['cargo'].values())

    def export(self):
        data = super().export()
        data.update(schema='eternia.v0.6', mode='physical_world', links=deepcopy(self.links),
                    journeys=deepcopy(self.journeys), mineral_reserves=dict(self.mineral_reserves),
                    initial_mineral_reserves=dict(self.initial_mineral_reserves),
                    physical_metrics=self.logistics_metrics(),
                    note='Seasonal cargo and migrant journeys over river, upland and mountain links. '
                    'Finite modeled seams, explicit provisions, escrow, losses, voted maintenance and access. '
                    'Council representation and exact final trade terms retain v0.5 abstractions. '
                    'Migrant retirement is deferred until arrival or return; returning people use a slow emergency passage.')
        return data
