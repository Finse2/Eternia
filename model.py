from dataclasses import dataclass, asdict, field


@dataclass
class Settlement:
    id: int
    name: str
    x: float
    y: float
    population: int
    farmland: float
    fertility: float
    forest: float
    ore: float
    aether: float  # WORLD TRUTH: agents cannot inspect this directly
    food: float = 0.0
    wood: float = 0.0
    iron: float = 0.0
    treasury: float = 90.0
    farming_level: int = 0
    mining_level: int = 0
    knowledge: int = 0  # 0 unknown; 1 observations; 2 reproduced effect
    founded: int = 0
    buildings: dict[str, int] = field(default_factory=dict)
    permissions: dict[str, bool] = field(default_factory=lambda: {
        action: True for action in ('gather', 'build', 'trade', 'research',
                                     'migrate', 'found_settlement', 'negotiate')
    })
    # Finite, accessible deposits for individual actions, separate from the
    # aggregate annual economy. Gathering transfers rather than creates stock.
    deposits: dict[str, float] = field(default_factory=lambda: {
        'food': 120.0, 'wood': 160.0, 'iron': 100.0
    })
    relations: dict[int, str] = field(default_factory=dict)

    def public_state(self):
        """Intentionally excludes hidden Aether and other undiscovered details."""
        d = asdict(self)
        d.pop('aether')
        return d


@dataclass
class Agent:
    id: int
    name: str
    home: int
    role: str
    curiosity: float
    ambition: float
    age: int
    influence: float = 0.0
    knowledge: int = 0
    experiments: int = 0
    inventory: dict[str, float] = field(default_factory=lambda: {
        'food': 3.0, 'wood': 0.0, 'iron': 0.0, 'coins': 5.0
    })
    skills: list[str] = field(default_factory=lambda: [
        'foraging', 'woodcutting', 'mining', 'trading'
    ])
    hunger: float = 0.0
    energy: float = 100.0
    wealth_goal: float = 60.0
    memory: list[dict] = field(default_factory=list)
    structures: dict[str, int] = field(default_factory=dict)
