"""v0.7 Stage 3: personal motivations that change slowly with experience.

Six motives weigh how much a person cares about security, wealth, belonging,
curiosity, influence and legacy, each between 0.05 and 0.95.

- A temperament, set at birth from profession, personal traits and a private
  draw, is where motives settle when nothing in particular happens.
- Experiences push motives by small amounts, at most 0.08 per motive per cycle.
- Each cycle motives drift 3% of the way back toward temperament, and
  temperament moves 0.5% toward the motives actually lived. A single event
  fades within a few years; only experiences repeated over years leave a mark.

The world records experiences from authoritative outcomes, never from a
policy's intentions. No draw uses the world's random generator: personal
variation comes from a private stream keyed by the world seed and person ID.
"""
import random

MOTIVES = ('security', 'wealth', 'belonging', 'curiosity', 'influence', 'legacy')
LOW, HIGH = .05, .95
RETURN_RATE = .03      # share of the gap to temperament closed each cycle
LEARNING_RATE = .005   # share of the gap temperament closes toward lived motives each cycle
MAX_SHIFT = .08        # the most one cycle's experiences can move one motive
VARIATION = .12        # personal difference from the profession's typical temperament
HEIR_SHARE = .5        # an heir's temperament blends their own with their predecessor's

ROLE_TEMPERAMENT = {
    'farmer': dict(security=.75, wealth=.35, belonging=.45, curiosity=.2, influence=.2, legacy=.3),
    'miner': dict(security=.55, wealth=.7, belonging=.35, curiosity=.25, influence=.2, legacy=.2),
    'merchant': dict(security=.45, wealth=.75, belonging=.35, curiosity=.3, influence=.35, legacy=.2),
    'builder': dict(security=.5, wealth=.35, belonging=.4, curiosity=.25, influence=.2, legacy=.7),
    'researcher': dict(security=.4, wealth=.25, belonging=.3, curiosity=.8, influence=.2, legacy=.35),
    'councillor': dict(security=.45, wealth=.3, belonging=.55, curiosity=.25, influence=.75, legacy=.35),
}
NEUTRAL = dict.fromkeys(MOTIVES, .4)

# Experience kind: (motive changes, plain description). Income is scaled by ambition.
EXPERIENCES = {
    'hunger': ({'security': .03}, 'went hungry'),
    'starvation': ({'security': .05}, 'came close to starving'),
    'secure': ({'security': -.004}, 'had food and savings'),
    'poverty': ({'security': .01, 'wealth': .008}, 'had almost no coins'),
    'income': ({'wealth': .012}, 'earned coins'),
    'loss': ({'security': .02, 'wealth': -.01}, 'lost goods on the road'),
    'cooperation': ({'belonging': .015}, 'worked with or helped neighbors'),
    'trusted': ({'belonging': .004}, 'lived among trusted neighbors'),
    'estranged': ({'belonging': -.004}, 'distrusted neighbors'),
    'membership': ({'belonging': .002}, 'belonged to an organization'),
    'civic': ({'influence': .006}, 'took part in a collective decision'),
    'enactment': ({'influence': .02}, 'carried out a public decision'),
    'experiment': ({'curiosity': .01}, 'ran an experiment'),
    'discovery': ({'curiosity': .08}, 'reproduced an Aether effect'),
    'witnessed': ({'curiosity': .02}, 'learned by watching a neighbor'),
    'learned': ({'curiosity': .02, 'belonging': .01}, 'was taught by a neighbor'),
    'taught': ({'legacy': .015, 'belonging': .01}, 'taught a neighbor'),
    'built': ({'legacy': .03, 'security': -.01}, 'built a house'),
    'bereavement': ({'legacy': .02, 'belonging': .01}, 'lost a neighbor'),
    'inheritance': ({'legacy': .05}, 'inherited an estate'),
}


def clamp(value):
    return min(HIGH, max(LOW, value))


def initial_temperament(role, *, curiosity, ambition, openness, seed, identity, parent=None):
    """Profession, traits and a private draw; an heir also takes after their predecessor."""
    stream = random.Random(f'eternia-temperament:{seed}:{identity}')
    base = ROLE_TEMPERAMENT.get(role, NEUTRAL)
    temperament = {motive: base[motive] + stream.uniform(-VARIATION, VARIATION) for motive in MOTIVES}
    # The curiosity trait counts as much as the profession's typical outlook.
    temperament['curiosity'] = (temperament['curiosity'] + curiosity) / 2
    temperament['wealth'] += (ambition - .5) * .2
    temperament['influence'] += (ambition - .5) * .2
    temperament['belonging'] += (.5 - openness) * .2
    if parent is not None:
        temperament = {m: HEIR_SHARE * parent[m] + (1 - HEIR_SHARE) * temperament[m] for m in MOTIVES}
    return {motive: round(clamp(value), 6) for motive, value in temperament.items()}


def experience_deltas(kind, *, ambition=.5, count=1):
    """Motive changes for ``count`` occurrences of an experience."""
    changes, _ = EXPERIENCES[kind]
    scale = (.5 + ambition) if kind == 'income' else 1.
    return {motive: change * scale * count for motive, change in changes.items()}


def update(motivations, temperament, deltas):
    """One cycle: apply bounded experience, drift toward temperament, let temperament learn."""
    lived = {}
    for motive in MOTIVES:
        shift = max(-MAX_SHIFT, min(MAX_SHIFT, deltas.get(motive, 0.)))
        value = motivations[motive] + shift
        value += RETURN_RATE * (temperament[motive] - value)
        lived[motive] = round(clamp(value), 6)
    learned = {motive: round(clamp(temperament[motive] + LEARNING_RATE * (lived[motive] - temperament[motive])), 6)
               for motive in MOTIVES}
    return lived, learned


def describe(kind):
    return EXPERIENCES[kind][1] if kind in EXPERIENCES else kind.replace('_', ' ')
