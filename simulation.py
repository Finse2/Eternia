"""Proof-of-concept simulation. No LLM; decisions and outcomes are rule based.

This is NOT a full ecology, market or magic physics model. It demonstrates the
architecture: independent state, agents, decisions, validated outcomes, history.
"""
import math
import random
from copy import deepcopy
from dataclasses import asdict
from .model import Agent, Settlement
from .actions import Action, ActionEngine, PRICES, RECIPES

SEEDS = [
    # name, x, y, population, farmland, fertility, forest, ore, Aether
    ('Rivermark', 30, 49, 250, 315, 1.20, .80, .25, .14),
    ('Stoneford', 43, 62, 200, 235, 1.03, .55, .50, .18),
    ('Highfen', 22, 27, 120, 118, .84, .70, .95, .89),
    ('Durnpass', 59, 22, 110, 118, .83, .48, .91, .81),
    ('Tidemere', 76, 76, 100, 121, 1.18, .40, .26, .22),
    ('Deepwood', 12, 74, 110, 127, .95, .98, .26, .56),
    ('Sunfield', 62, 47, 110, 127, 1.21, .67, .36, .10),
]
FIRST_NAMES = ['Edrin','Mara','Tovan','Lysa','Seren','Halen','Iris','Orin','Nessa','Joran',
               'Vela','Darian','Ilya','Renn','Alia','Bren','Tessa','Faren','Mira','Kael']
ROLES = ['farmer','farmer','merchant','miner','artisan','scholar','councillor']


class World:
    def __init__(self, seed=42):
        self.seed = seed
        self.rng = random.Random(seed)
        self.year = 0
        self.settlements = [
            Settlement(i, name, x, y, pop, land, fertility, forest, ore, aether,
                       food=pop * .75, wood=50.0, iron=10.0)
            for i, (name, x, y, pop, land, fertility, forest, ore, aether) in enumerate(SEEDS)
        ]
        self.agents = []
        for i in range(50):
            self.agents.append(self._new_agent(i, i % len(self.settlements)))
        self.next_agent_id = 50
        self.events = []
        self.snapshots = []
        self.action_log = []
        self.last_action_year = {}
        self.action_engine = ActionEngine(self)
        self._event('world', 'Year Zero: seven independent settlements begin their history.')
        self._snapshot()

    def _new_agent(self, id, home):
        return Agent(id, f'{self.rng.choice(FIRST_NAMES)}-{id}', home,
                     self.rng.choice(ROLES), self.rng.random(), self.rng.random(),
                     self.rng.randint(16, 45))

    def _event(self, kind, message, settlement=None, agent=None):
        self.events.append({'year': self.year, 'kind': kind,
                            'settlement': settlement, 'agent': agent, 'message': message})

    def _snapshot(self):
        snapshot = {
            'year': self.year,
            'population': sum(s.population for s in self.settlements),
            'settlements': [s.public_state() for s in self.settlements],
            'named_agents': len(self.agents),
            'magic_discoveries': sum(s.knowledge == 2 for s in self.settlements),
        }
        if hasattr(self, 'demo') and self.agents:
            snapshot['focal_agent'] = asdict(self.agents[0])
        self.snapshots.append(snapshot)

    def _resolve_agent(self, actor):
        matches = [a for a in self.agents if
                   (type(actor) is int and a.id == actor) or
                   (isinstance(actor, str) and a.name == actor)]
        if len(matches) != 1:
            raise ValueError('Actor must identify one living agent')
        return matches[0]

    def observe(self, actor):
        """Detached public perception: no world reference or hidden Aether field."""
        a = self._resolve_agent(actor)
        s = next(s for s in self.settlements if s.id == a.home)
        neighbors = []
        for other in self.settlements:
            distance = math.hypot(s.x - other.x, s.y - other.y)
            if other.id != s.id and distance <= 38:
                neighbor = other.public_state()
                neighbor['distance'] = distance
                neighbors.append(neighbor)
        return deepcopy({
            'year': self.year, 'actor': asdict(a), 'settlement': s.public_state(),
            'neighbors': neighbors,
            'rules': {'prices': PRICES, 'recipes': RECIPES,
                      'gather_limit': 8, 'gather_energy_per_unit': 2},
            'recent_events': [e for e in self.events if
                              e['settlement'] in (None, s.name)][-12:],
        })

    def submit_action(self, proposal):
        """Only the engine applies proposals. Remember outcomes, including rejection."""
        result = self.action_engine.execute(proposal)
        actor = proposal.actor if isinstance(proposal, Action) else (
            proposal.get('actor') if isinstance(proposal, dict) else None)
        try:
            a = self._resolve_agent(actor)
        except ValueError:
            return result
        a.memory.append(deepcopy(self.action_log[-1]))
        del a.memory[:-64]
        return result

    def step(self):
        self.year += 1
        self._produce_and_consume()
        self._trade()
        self._govern()
        self._agents_act()
        self._expand()
        if self.year % 10 == 0:
            self._snapshot()
        self._assert_invariants()

    def run(self, years=1000):
        for _ in range(years):
            self.step()
        if self.snapshots[-1]['year'] != self.year:
            self._snapshot()
        return self

    def _produce_and_consume(self):
        for s in self.settlements:
            weather = self.rng.uniform(.86, 1.16)
            yield_per_area = s.fertility * (1.0 + .16 * s.farming_level)
            harvest = min(s.population * 1.45, s.farmland * yield_per_area) * weather
            s.food += harvest
            s.wood += s.population * .11 * s.forest
            s.iron += s.population * .025 * s.ore * (1 + .07 * s.mining_level)
            # Ecological and resource limits: stocks do not grow without bounds.
            s.wood = min(s.wood, max(150.0, s.population * .7))
            s.iron = min(s.iron, max(80.0, s.population * .22))
            s.treasury = min(600.0, s.treasury + s.population * .06)
            # Consumption occurs after food trade, in _trade().

    def _trade(self):
        # Sellers transport surplus, buyers pay; no free food is created.
        for buyer in sorted(self.settlements, key=lambda s: s.food / max(1, s.population)):
            want = max(0., buyer.population * 1.12 - buyer.food)
            if want < 1:
                continue
            donors = sorted((s for s in self.settlements if s.id != buyer.id),
                            key=lambda s: math.hypot(s.x-buyer.x, s.y-buyer.y))
            for donor in donors:
                dist = math.hypot(donor.x-buyer.x, donor.y-buyer.y)
                if dist > 38:
                    continue
                available = max(0., donor.food - donor.population * 1.45)
                amount = min(want, available, buyer.treasury / 0.12)
                if amount < 5:
                    continue
                buyer.food += amount
                donor.food -= amount
                buyer.treasury -= amount * .12
                donor.treasury += amount * .12
                want -= amount
                if self.rng.random() < .012:
                    self._event('trade', f'{donor.name} sent {int(amount)} food to {buyer.name}.', buyer.name)
                if want <= 0:
                    break
        for s in self.settlements:
            shortage = max(0., s.population - s.food)
            s.food = max(0., s.food - s.population)
            # Resource support and demographic caps. Food shortages cause losses.
            if shortage > 0:
                rate = min(.20, .018 + .42 * shortage / max(1, s.population))
                loss = max(1, round(s.population * rate))
                s.population = max(10, s.population - loss)
                if shortage > s.population * .14 and self.rng.random() < .12:
                    self._event('famine', f'Food shortage in {s.name}; population fell.', s.name)
            else:
                capacity = s.farmland * s.fertility * (1 + .16*s.farming_level)
                room = max(0., (capacity * .93 - s.population) / max(1., capacity))
                growth = round(s.population * (.005 + .013 * room))
                if room > .01 and growth == 0 and self.rng.random() < .30:
                    growth = 1
                s.population += max(0, growth)
            s.food = min(s.food, s.population * 2.0)

    def _govern(self):
        for s in self.settlements:
            # Councils decide independently using their local resources.
            if s.population > 20 and (s.food < s.population * .5 or
                                      s.population > s.farmland * .9):
                if s.wood >= 18 and s.treasury >= 30 and s.farming_level < 25:
                    s.wood -= 18
                    s.treasury -= 30
                    s.farming_level += 1
                    if s.farming_level in (1, 5, 10, 20):
                        self._event('construction',
                                    f'{s.name} expanded farmland techniques to level {s.farming_level}.', s.name)
            if s.iron >= 20 and s.treasury >= 40 and s.mining_level < 10:
                if self.rng.random() < .015:
                    s.iron -= 20
                    s.treasury -= 40
                    s.mining_level += 1

    def _agents_act(self):
        for a in list(self.agents):
            a.age += 1
            s = self.settlements[a.home]
            # Agents are finite-lived; replacement has different preferences.
            if a.age > 77 or (a.age > 55 and self.rng.random() < .024):
                self.agents.remove(a)
                successor = self._new_agent(self.next_agent_id, a.home)
                self.next_agent_id += 1
                # Inherit property rather than minting a fresh starting inventory.
                successor.inventory = dict(a.inventory)
                successor.structures = dict(a.structures)
                # Imperfect cultural transmission: formal knowledge can persist.
                successor.knowledge = min(a.knowledge, s.knowledge)
                self.agents.append(successor)
                continue
            # Background NPCs also propose; only the action engine changes their
            # resources or evaluates hidden experimental conditions.
            if (a.role in ('miner', 'scholar', 'artisan') and a.knowledge < 2
                    and self.rng.random() < .09 * a.curiosity):
                proposal = {'actor': a.id, 'location': s.id}
                if a.energy < 10:
                    proposal.update(type='rest')
                elif a.inventory['wood'] < 1:
                    proposal.update(type='gather', resource='wood', amount=1)
                elif a.inventory['iron'] < 1:
                    proposal.update(type='gather', resource='iron', amount=1)
                else:
                    proposal.update(type='research', topic='aether')
                self.submit_action(proposal)
            # People occasionally share an observed or tested technique across
            # neighboring settlements. Knowledge can travel without matter teleporting.
            if a.knowledge > 0 and self.rng.random() < .005:
                destinations = [v for v in self.settlements if v.id != s.id and
                                math.hypot(v.x-s.x, v.y-s.y) <= 35]
                if destinations:
                    v = self.rng.choice(destinations)
                    if a.knowledge > v.knowledge:
                        v.knowledge = a.knowledge
                        self._event('knowledge',
                                    f'Knowledge of mineral resonance spread from {s.name} to {v.name}.',
                                    v.name, a.name)
            # Sometimes a curious individual adopts documented knowledge.
            if a.knowledge < s.knowledge and self.rng.random() < .07:
                a.knowledge = s.knowledge

    def _expand(self):
        if len(self.settlements) >= 25:
            return
        candidates = [s for s in self.settlements if s.population >= 380 and
                      s.wood >= 45 and s.treasury >= 70]
        for parent in candidates:
            if self.rng.random() >= .022:
                continue
            x = min(96., max(4., parent.x + self.rng.randint(-17, 17)))
            y = min(96., max(4., parent.y + self.rng.randint(-17, 17)))
            if any(math.hypot(s.x-x, s.y-y) < 8 for s in self.settlements):
                continue
            councillors = [a for a in self.agents if a.home == parent.id
                           and a.role == 'councillor'
                           and self.last_action_year.get(a.id) != self.year]
            if not councillors:
                continue
            n = len(self.settlements)
            self.submit_action({'actor': councillors[0].id, 'type': 'found_settlement',
                                'location': parent.id, 'name': f'{parent.name} Haven {n}',
                                'x': x, 'y': y, 'settlers': 65})
            if len(self.settlements) >= 25:
                break

    def _assert_invariants(self):
        ids = [s.id for s in self.settlements]
        assert len(ids) == len(set(ids))
        assert all(s.population >= 10 for s in self.settlements)
        assert all(min(s.food, s.wood, s.iron, s.treasury) >= -1e-7 for s in self.settlements)
        assert all(0 <= s.knowledge <= 2 for s in self.settlements)
        assert len({a.id for a in self.agents}) == len(self.agents)
        assert all(0 <= a.home < len(self.settlements) for a in self.agents)
        assert all(all(math.isfinite(v) and v >= 0 for v in a.inventory.values())
                   for a in self.agents)
        assert all(0 <= a.hunger <= 100 and 0 <= a.energy <= 100 for a in self.agents)
        assert all(all(math.isfinite(v) and v >= 0 for v in s.deposits.values())
                   for s in self.settlements)

    def export(self):
        data = {'schema': 'eternia.v0.2', 'seed': self.seed, 'year': self.year,
                'note': 'Toy model: population and research approximations; no LLM, warfare or real magic physics.',
                'snapshots': self.snapshots, 'events': self.events,
                'final_agents': [asdict(a) for a in self.agents],
                'actions': self.action_log}
        if hasattr(self, 'demo'):
            data['demo'] = self.demo
            data['decisions'] = self.decisions
        return data
