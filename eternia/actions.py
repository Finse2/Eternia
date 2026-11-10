"""Authoritative, dependency-free validation and execution of agent proposals.

Policies receive observations and produce data. Only this module applies their
actions. ``validate`` is a dry run: it changes neither state nor random state.
An accepted research action may produce a negative experimental result; that
is a valid experiment, rather than a rejected action.
"""
from copy import deepcopy
from dataclasses import asdict, dataclass, field
import math

from .model import Settlement


PRICES = {'food': 1.0, 'wood': 2.0, 'iron': 4.0}
RECIPES = {
    'house': {'wood': 12.0, 'iron': 2.0, 'coins': 8.0},
    'workshop': {'wood': 18.0, 'iron': 6.0, 'coins': 15.0},
}
GATHER_SKILLS = {'food': 'foraging', 'wood': 'woodcutting', 'iron': 'mining'}
ACTION_PARAMETERS = {
    'gather': {'resource', 'amount'},
    'build': {'structure'},
    'trade': {'resource', 'amount', 'direction'},
    'research': {'topic'},
    'migrate': {'destination'},
    'found_settlement': {'name', 'x', 'y', 'settlers'},
    'negotiate': {'destination', 'treaty'},
    'rest': set(),
    'eat': set(),
    'wait': set(),
}
ENERGY_COSTS = {
    'build': 15.0, 'trade': 1.0, 'research': 10.0,
    'migrate': 12.0, 'found_settlement': 20.0, 'negotiate': 5.0,
    'rest': 0.0, 'eat': 0.0, 'wait': 0.0,
}


@dataclass(frozen=True)
class Action:
    actor: int | str
    type: str
    location: int | str | None = None
    params: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, proposal):
        """Accept either canonical params or a flat, human-readable proposal."""
        if not isinstance(proposal, dict):
            raise ValueError('An action must be an object.')
        if not all(isinstance(key, str) for key in proposal):
            raise ValueError('Action field names must be strings.')
        if 'actor' not in proposal or 'type' not in proposal:
            raise ValueError('An action requires actor and type.')
        params = proposal.get('params', {})
        if not isinstance(params, dict):
            raise ValueError('params must be an object.')
        params = deepcopy(params)
        for key, value in proposal.items():
            if key not in ('actor', 'type', 'location', 'params'):
                if key in params:
                    raise ValueError('A parameter cannot appear twice.')
                params[key] = deepcopy(value)
        return cls(proposal['actor'], proposal['type'], proposal.get('location'), params)

    def to_dict(self):
        return deepcopy(asdict(self))


@dataclass(frozen=True)
class ActionResult:
    success: bool
    code: str
    message: str
    effects: dict = field(default_factory=dict)

    def to_dict(self):
        return deepcopy(asdict(self))


class _Rejected(Exception):
    def __init__(self, code, message):
        self.code, self.message = code, message
        super().__init__(message)


def _require(condition, code, message):
    if not condition:
        raise _Rejected(code, message)


def _number(value, name, *, minimum=0, maximum=None, integral=False):
    valid = (type(value) in (int, float)
             and (type(value) is int or math.isfinite(value))
             and value >= minimum and (maximum is None or value <= maximum)
             and (not integral or value == int(value)))
    _require(valid, 'invalid_amount', f'{name} must be a finite '
             f'{"whole " if integral else ""}number between {minimum} and '
             f'{maximum if maximum is not None else "the supported limit"}.')
    return int(value) if integral else float(value)


def _identifier(value):
    return type(value) is int and value >= 0 or type(value) is str and 0 < len(value) <= 100


def _resolve(items, reference, code, label):
    _require(_identifier(reference), code, f'{label} must be an ID or exact name.')
    matches = [item for item in items
               if (item.id == reference if type(reference) is int else item.name == reference)]
    _require(len(matches) == 1, code, f'{label} was not found or its name is ambiguous.')
    return matches[0]


class ActionEngine:
    parameters = ACTION_PARAMETERS

    def __init__(self, world):
        self.world = world

    def validate(self, proposal):
        """Check current rules and inventories without consuming a turn."""
        try:
            self._prepare(proposal)
            return ActionResult(True, 'ok', 'Action is valid.')
        except _Rejected as error:
            return ActionResult(False, error.code, error.message)

    def execute(self, proposal):
        """Validate again, apply once, and audit both accepted/rejected attempts."""
        prepared = None
        try:
            prepared = self._prepare(proposal)
            action, actor, settlement, details = prepared
            effects = self._apply(action, actor, settlement, details)
            actor.energy = max(0.0, actor.energy - details['energy'])
            if not hasattr(self.world, 'last_action_year'):
                self.world.last_action_year = {}
            self.world.last_action_year[actor.id] = self._clock()
            result = ActionResult(True, 'ok', effects.pop('message'), effects)
        except _Rejected as error:
            result = ActionResult(False, error.code, error.message)
        if not hasattr(self.world, 'action_log'):
            self.world.action_log = []
        if prepared:
            action, actor, settlement, _ = prepared
            audit_action = action.to_dict()
            audit_action.update(actor=actor.id, location=settlement.id)
        else:
            audit_action = self._safe_proposal(proposal)
        self.world.action_log.append({
            'year': self.world.year, 'action': audit_action, 'result': result.to_dict()
        })
        if result.success:
            self.world._event('action', result.message, settlement.name, actor.name)
        return result

    @staticmethod
    def _safe_proposal(proposal):
        # Invalid data is still audited, without retaining caller-owned objects
        # or unserializable/nonfinite values in the history.
        def safe(value, depth=0):
            if depth > 3:
                return '[nested value omitted]'
            if value is None or type(value) is bool:
                return value
            if type(value) is int:
                return value if abs(value) <= 10**12 else '[out-of-range integer]'
            if type(value) is float:
                return value if math.isfinite(value) else str(value)
            if type(value) is str:
                return value[:200]
            if isinstance(value, dict):
                return {str(k)[:100]: safe(v, depth + 1)
                        for k, v in list(value.items())[:20]}
            if isinstance(value, (list, tuple)):
                return [safe(v, depth + 1) for v in value[:20]]
            return '[unsupported value]'
        if isinstance(proposal, Action):
            return safe({'actor': proposal.actor, 'type': proposal.type,
                         'location': proposal.location, 'params': proposal.params})
        if isinstance(proposal, dict):
            params = proposal.get('params', {})
            params = dict(params) if isinstance(params, dict) else {'invalid_params': params}
            params.update({key: value for key, value in proposal.items()
                           if key not in ('actor', 'type', 'location', 'params')})
            return safe({'actor': proposal.get('actor'), 'type': proposal.get('type'),
                         'location': proposal.get('location'), 'params': params})
        return {'actor': None, 'type': 'invalid', 'location': None,
                'params': {'proposal': safe(proposal)}}

    def _prepare(self, proposal):
        try:
            if isinstance(proposal, Action):
                action = Action.from_dict(proposal.to_dict())
            else:
                action = Action.from_dict(proposal)
        except (ValueError, TypeError, RecursionError):
            raise _Rejected('invalid_action', 'An action must contain actor, type and valid parameters.')
        _require(type(action.type) is str and action.type in self.parameters,
                 'unknown_action', 'Unknown action type.')
        _require(all(type(key) is str for key in action.params)
                  and set(action.params) <= self.parameters[action.type],
                 'invalid_action', 'Unknown parameters for this action type.')
        actor = _resolve(self.world.agents, action.actor, 'unknown_actor', 'Actor')
        settlement = _resolve(self.world.settlements,
                              actor.home if action.location is None else action.location,
                              'unknown_location', 'Location')
        _require(actor.home == settlement.id, 'remote_action', 'Actor must be at the action location.')
        _require(getattr(self.world, 'last_action_year', {}).get(actor.id) != self._clock(),
                 'turn_spent', 'Actor has already completed an action this tick.')
        _require(settlement.permissions.get(action.type, True) is True,
                 'permission_denied', f'{action.type} is not permitted in {settlement.name}.')
        details = getattr(self, '_check_' + action.type)(actor, settlement, action.params)
        details['energy'] = details.get('energy', ENERGY_COSTS.get(action.type, 0.0))
        _require(actor.energy >= details['energy'], 'insufficient_energy',
                 'Actor needs to rest before attempting this action.')
        return action, actor, settlement, details

    def _clock(self):
        return getattr(self.world, 'tick', self.world.year)

    @staticmethod
    def _skill(actor, skill):
        _require(skill in actor.skills, 'missing_knowledge', f'{skill} knowledge is required.')

    @staticmethod
    def _inventory(actor, costs):
        _require(all(actor.inventory.get(resource, 0.0) >= amount
                     for resource, amount in costs.items()),
                 'insufficient_resources', 'Actor lacks the necessary materials or coins.')

    @staticmethod
    def _distance(a, b):
        return math.hypot(a.x - b.x, a.y - b.y)

    def _check_gather(self, actor, settlement, params):
        resource = params.get('resource')
        _require(type(resource) is str and resource in GATHER_SKILLS,
                 'invalid_resource', 'Gather food, wood or iron.')
        amount = _number(params.get('amount'), 'amount', minimum=1, maximum=8, integral=True)
        self._skill(actor, GATHER_SKILLS[resource])
        _require(settlement.deposits.get(resource, 0.0) >= amount,
                 'depleted', f'There is not enough accessible {resource} here.')
        return {'resource': resource, 'amount': amount, 'energy': amount * 2.0}

    def _check_build(self, actor, settlement, params):
        structure = params.get('structure')
        _require(type(structure) is str and structure in RECIPES,
                 'unknown_structure', 'The known structures are house and workshop.')
        self._skill(actor, 'carpentry')
        _require(actor.structures.get(structure, 0) == 0, 'already_built',
                 f'Actor already owns a {structure} here.')
        self._inventory(actor, RECIPES[structure])
        return {'structure': structure, 'costs': dict(RECIPES[structure])}

    def _check_trade(self, actor, settlement, params):
        self._skill(actor, 'trading')
        resource = params.get('resource')
        _require(type(resource) is str and resource in PRICES,
                 'invalid_resource', 'Trade food, wood or iron.')
        amount = _number(params.get('amount'), 'amount', minimum=1, maximum=1000, integral=True)
        direction = params.get('direction')
        _require(type(direction) is str and direction in ('buy', 'sell'),
                 'invalid_action', 'Trade direction must be buy or sell.')
        price = amount * PRICES[resource]
        if direction == 'buy':
            self._inventory(actor, {'coins': price})
            _require(getattr(settlement, resource) >= amount, 'insufficient_resources',
                     'The local market lacks the requested stock.')
        else:
            self._inventory(actor, {resource: amount})
            _require(settlement.treasury >= price, 'insufficient_resources',
                     'The local market cannot afford this purchase.')
        return {'resource': resource, 'amount': amount, 'direction': direction, 'price': price}

    def _check_research(self, actor, settlement, params):
        topic = params.get('topic')
        _require(type(topic) is str and topic in ('carpentry', 'aether'),
                 'unknown_topic', 'The research topics are carpentry and aether.')
        _require(topic != 'carpentry' or 'carpentry' not in actor.skills,
                 'already_known', 'Actor already knows carpentry.')
        _require(topic != 'aether' or actor.knowledge < 2,
                 'already_known', 'Actor already knows the reproduced Aether effect.')
        self._inventory(actor, {'wood': 1.0, 'iron': 1.0})
        return {'topic': topic}

    def _check_migrate(self, actor, settlement, params):
        target = _resolve(self.world.settlements, params.get('destination'),
                          'unknown_location', 'Destination')
        _require(target.id != settlement.id, 'invalid_action', 'Actor is already at that settlement.')
        _require(target.permissions.get('migrate', True) is True,
                 'permission_denied', 'The destination is closed to migration.')
        _require(self._distance(settlement, target) <= 38, 'out_of_range',
                 'The destination is beyond the travel range of 38.')
        _require(settlement.population > 10, 'population_floor',
                 'Migration would leave fewer than ten residents.')
        return {'destination': target}

    def _check_found_settlement(self, actor, settlement, params):
        _require(actor.role == 'councillor', 'permission_denied',
                 'Only an authorized councillor can found a settlement.')
        _require(len(self.world.settlements) < 25, 'settlement_limit',
                 'This prototype supports at most 25 settlements.')
        name = params.get('name')
        _require(type(name) is str and 0 < len(name.strip()) <= 64,
                 'invalid_action', 'A new settlement requires a name of at most 64 characters.')
        name = name.strip()
        _require(not any(s.name == name for s in self.world.settlements),
                 'invalid_action', 'Settlement names must be unique.')
        x = _number(params.get('x'), 'x', minimum=4, maximum=96)
        y = _number(params.get('y'), 'y', minimum=4, maximum=96)
        settlers = _number(params.get('settlers', 65), 'settlers', minimum=10,
                           maximum=1000, integral=True)
        _require(settlement.population - settlers >= 10, 'population_floor',
                 'The parent settlement must retain at least ten residents.')
        _require(math.hypot(x - settlement.x, y - settlement.y) <= 24,
                 'out_of_range', 'A new settlement must be within 24 map units.')
        _require(all(math.hypot(s.x - x, s.y - y) >= 8 for s in self.world.settlements),
                 'location_occupied', 'The proposed location is too close to an existing settlement.')
        _require(settlement.food >= 70 and settlement.wood >= 40
                 and settlement.iron >= 5 and settlement.treasury >= 60,
                 'insufficient_resources', 'The parent lacks supplies for founding a settlement.')
        return {'name': name, 'x': x, 'y': y, 'settlers': settlers}

    def _check_negotiate(self, actor, settlement, params):
        _require(actor.role == 'councillor', 'permission_denied',
                 'Only an authorized councillor can sign treaties.')
        target = _resolve(self.world.settlements, params.get('destination'),
                          'unknown_location', 'Destination')
        _require(target.id != settlement.id, 'invalid_action', 'A treaty needs two settlements.')
        _require(params.get('treaty') == 'trade', 'invalid_action',
                 'Only a trade treaty is supported.')
        _require(target.permissions.get('negotiate', True) is True,
                 'permission_denied', 'The other settlement declines negotiation.')
        _require(self._distance(settlement, target) <= 38, 'out_of_range',
                 'The other settlement is beyond diplomatic range.')
        _require(settlement.relations.get(target.id) != 'trade', 'already_known',
                 'These settlements already have a trade treaty.')
        return {'destination': target, 'treaty': 'trade'}

    @staticmethod
    def _check_rest(actor, settlement, params):
        _require(actor.energy < 100, 'not_needed', 'Actor is already fully rested.')
        return {}

    @staticmethod
    def _check_wait(actor, settlement, params):
        return {}

    def _check_eat(self, actor, settlement, params):
        _require(actor.hunger > 0, 'not_needed', 'Actor is not hungry.')
        self._inventory(actor, {'food': 1.0})
        return {}

    def _apply(self, action, actor, settlement, details):
        kind = action.type
        if kind == 'gather':
            resource, amount = details['resource'], details['amount']
            settlement.deposits[resource] -= amount
            actor.inventory[resource] = actor.inventory.get(resource, 0.0) + amount
            return {'resource': resource, 'amount': amount,
                    'message': f'{actor.name} gathered {amount} {resource} in {settlement.name}.'}
        if kind == 'build':
            structure = details['structure']
            for resource, amount in details['costs'].items():
                actor.inventory[resource] -= amount
            actor.structures[structure] = actor.structures.get(structure, 0) + 1
            settlement.buildings[structure] = settlement.buildings.get(structure, 0) + 1
            return {'structure': structure, 'costs': details['costs'],
                    'message': f'{actor.name} built a {structure} in {settlement.name}.'}
        if kind == 'trade':
            resource, amount, price = details['resource'], details['amount'], details['price']
            sign = 1 if details['direction'] == 'buy' else -1
            actor.inventory[resource] = actor.inventory.get(resource, 0.0) + sign * amount
            setattr(settlement, resource, getattr(settlement, resource) - sign * amount)
            actor.inventory['coins'] -= sign * price
            settlement.treasury += sign * price
            return {'resource': resource, 'amount': amount, 'direction': details['direction'],
                    'price': price, 'message': f'{actor.name} {"bought" if sign == 1 else "sold"} '
                    f'{amount} {resource} for {price:g} coins in {settlement.name}.'}
        if kind == 'research':
            topic = details['topic']
            # Draw before any state mutation. Validation never inspects this
            # hidden condition or advances the random generator.
            discovered = topic == 'aether' and settlement.aether * settlement.ore > .52 \
                and self.world.rng.random() < .21
            actor.inventory['wood'] -= 1.0
            actor.inventory['iron'] -= 1.0
            actor.experiments += 1
            if topic == 'carpentry':
                actor.skills.append('carpentry')
                return {'topic': topic, 'learned': True,
                        'message': f'{actor.name} learned carpentry through practical study.'}
            actor.knowledge = max(actor.knowledge, 2 if discovered else 1)
            settlement.knowledge = max(settlement.knowledge, actor.knowledge)
            return {'topic': topic, 'discovered': discovered,
                    'message': f'{actor.name} '
                    f'{"reproduced an Aether effect" if discovered else "recorded an inconclusive Aether experiment"} '
                    f'in {settlement.name}.'}
        if kind == 'migrate':
            target = details['destination']
            settlement.population -= 1
            target.population += 1
            actor.home = target.id
            return {'origin': settlement.id, 'destination': target.id,
                    'message': f'{actor.name} migrated from {settlement.name} to {target.name}.'}
        if kind == 'found_settlement':
            n = max(s.id for s in self.world.settlements) + 1
            colony = Settlement(n, details['name'], details['x'], details['y'],
                                details['settlers'], self.world.rng.uniform(90, 160),
                                self.world.rng.uniform(.85, 1.25),
                                self.world.rng.uniform(.35, .9),
                                self.world.rng.uniform(.2, .9),
                                self.world.rng.uniform(.08, .95),
                                food=70.0, wood=40.0, iron=5.0, treasury=35.0,
                                founded=self.world.year, knowledge=settlement.knowledge)
            settlement.population -= details['settlers']
            settlement.food -= 70.0
            settlement.wood -= 40.0
            settlement.iron -= 5.0
            settlement.treasury -= 60.0
            self.world.settlements.append(colony)
            actor.home = colony.id
            return {'settlement_id': colony.id, 'settlers': details['settlers'],
                    'founding_cost': 25.0,
                    'message': f'{actor.name} founded {colony.name} from {settlement.name}.'}
        if kind == 'negotiate':
            target = details['destination']
            settlement.relations[target.id] = 'trade'
            target.relations[settlement.id] = 'trade'
            return {'destination': target.id, 'treaty': 'trade',
                    'message': f'{actor.name} signed a trade treaty between '
                    f'{settlement.name} and {target.name}.'}
        if kind == 'rest':
            restored = min(30.0, 100.0 - actor.energy)
            actor.energy += restored
            return {'energy_restored': restored, 'message': f'{actor.name} rested and regained energy.'}
        if kind == 'wait':
            return {'message': f'{actor.name} waited and observed {settlement.name}.'}
        actor.inventory['food'] -= 1.0
        hunger_reduced = min(35.0, actor.hunger)
        actor.hunger -= hunger_reduced
        return {'hunger_reduced': hunger_reduced, 'message': f'{actor.name} ate a meal.'}
