"""The Changing Miner: does experience change what a person wants?

Every case keeps all eighteen agents and the default society policy. The focal
person is Edrin of Rivermark, a miner who starts with the goal of holding 60
coins. Cases differ only in his starting circumstances, and each runs twice:
with adaptive goals and with every goal fixed. Nothing about his later goals is
injected; every change, refusal and completion is an outcome.
"""
from copy import deepcopy
import math

from .evaluation import goal_history, goal_outcome
from .labor_experiments import _resident_council
from .society import SocietyWorld

FOCAL = 1  # Edrin of Rivermark
RIVERMARK = 0
GOAL_SCENARIOS = {
    'successful_miner': 'Edrin starts with 54 coins, six short of his 60-coin goal (moved from the town treasury).',
    'struggling_miner': "Rivermark's accessible iron starts in town storage and Edrin's coins in its treasury: "
                        'no ore to mine at home and 2 coins.',
    'connected_miner': 'Edrin and each of his five Rivermark neighbors start with strong mutual trust, '
                       'in one town council of all six.',
    'curious_miner': 'Edrin starts as curious as a person can be, holding 4 wood and his iron for experiments.',
}
CIVIC = ('vote', 'propose', 'enact', 'join_institution', 'form_institution', 'contribute')


def build_goal_scenario(name, seed=42, policy_style='balanced', adaptive_goals=True):
    if name not in GOAL_SCENARIOS:
        raise ValueError(f'Unknown goal scenario: {name!r}')
    world = SocietyWorld(seed=seed, policy_style=policy_style, adaptive_goals=adaptive_goals)
    before = world.resource_totals()
    edrin, town = world.agents[FOCAL], world.settlements[RIVERMARK]
    changes = {}
    if name == 'successful_miner':
        moved = 54 - edrin.inventory['coins']
        town.treasury -= moved
        edrin.inventory['coins'] += moved
        changes['coins_from_treasury'] = moved
    elif name == 'struggling_miner':
        changes['accessible_iron_to_storage'] = town.deposits['iron']
        town.iron += town.deposits['iron']
        town.deposits['iron'] = 0.
        changes['coins_to_treasury'] = edrin.inventory['coins'] - 2
        town.treasury += edrin.inventory['coins'] - 2
        edrin.inventory['coins'] = 2.
    elif name == 'connected_miner':
        neighbors = [a for a in world.agents if a.home == RIVERMARK and a.id != FOCAL]
        for person in neighbors:
            edrin.trust[person.id] = .7
            person.trust[FOCAL] = .7
        council = _resident_council(world, town)
        changes.update(mutual_trust=.7, neighbors=[p.id for p in neighbors], council=council.id)
    else:
        changes['curiosity'] = (edrin.curiosity, 1.)
        edrin.curiosity = 1.
        town.wood -= 4
        edrin.inventory['wood'] += 4
        changes['wood_from_storage'] = 4
    after = world.resource_totals()
    if any(not math.isclose(before[r], after[r], abs_tol=1e-7) for r in before):
        raise AssertionError('Goal scenario setup changed resource totals')
    world.reset_minds()  # temperament reflects the starting traits
    world.reset_market_prices()
    label = 'adaptive' if adaptive_goals else 'fixed'
    world.scenario = f'goals:{name}:{label}'
    world.provenance['scenario'] = world.scenario
    world._event('experiment', GOAL_SCENARIOS[name], town.name, scenario=name, adaptive_goals=adaptive_goals)
    world.snapshots = []
    world._snapshot()
    world._assert_invariants()
    metadata = dict(scenario=name, description=GOAL_SCENARIOS[name], seed=seed, policy_style=policy_style,
                    adaptive_goals=adaptive_goals, focal=FOCAL, focal_lineage=edrin.lineage,
                    initial_goal=dict(edrin.goal), initial_mind=deepcopy(world.minds[FOCAL]),
                    controlled_changes=changes, initial_totals=dict(after),
                    limitations=[
                        'Starting circumstances are initial conditions; every later goal is chosen by the same rules.',
                        'Goals are limited to kinds the world already measures: coins, food reserve, houses, '
                        'Aether knowledge and public decisions carried out.',
                        'Motives and goal scores are explicit programmed rules, not a psychological model.',
                        'One seed is one history; compare several before generalizing.'])
    return world, metadata


def _lineage_ids(world, lineage):
    return {e['actor'] for e in world.goal_log if e.get('lineage') == lineage}


def _measure(world, metadata, needs):
    lineage, log = metadata['focal_lineage'], world.goal_log
    ids = _lineage_ids(world, lineage)
    focal = next((a for a in world.agents if a.lineage == lineage), None)
    decisions = [d for d in world.decisions if d['actor'] in ids]
    timeline = [{k: deepcopy(e.get(k)) for k in ('tick', 'year', 'name', 'event', 'goal', 'previous',
                                                 'previous_outcome', 'reason', 'evidence', 'motivations')}
                for e in log if e.get('lineage') == lineage]
    changes = [e for e in timeline if e['event'] in ('revised', 'escalated')]
    motives = [dict(year=snap['year'], **{k: round(v, 3) for k, v in snap['minds'][identity]['motivations'].items()})
               for snap in world.snapshots for identity in snap.get('minds', {})
               if identity in ids]
    person_cycles = max(1, needs['person_cycles'])
    all_decisions = max(1, len(world.decisions))
    focal_summary = dict(
        name=focal.name if focal else None, final_goal=dict(focal.goal) if focal else None,
        final_goal_met=goal_outcome(focal)['completed'] if focal else None,
        completions=sum(e['event'] == 'completed' for e in timeline),
        revisions=len(changes), abandoned=sum(e['previous_outcome'] == 'abandoned' for e in changes),
        declined_after_success=sum(e['event'] == 'content' for e in timeline),
        goal_path=[describe(e['goal']) for e in timeline if e['event'] in ('assigned', 'inherited', 'revised', 'escalated')],
        coins=round(focal.inventory['coins'], 2) if focal else None,
        food=round(focal.inventory['food'], 2) if focal else None,
        houses=focal.structures.get('house', 0) if focal else None,
        knowledge=focal.knowledge if focal else None, influence=focal.influence if focal else None,
        memberships=sum(i.active and focal.id in i.members for i in world.institutions) if focal else 0,
        civic_actions=sum(d['proposal'].get('type') in CIVIC and d['result']['success'] for d in decisions),
        hunger_cycles=needs['focal_hungry'], exhausted_cycles=needs['focal_exhausted'],
        wasted_share=round(sum(not d['result']['success'] or d['proposal'].get('type') == 'wait'
                               for d in decisions) / max(1, len(decisions)), 4))
    population = dict(
        **goal_history(world),
        current_goals_met=sum(goal_outcome(a)['completed'] for a in world.agents),
        hunger_rate=round(needs['hungry'] / person_cycles, 4),
        exhaustion_rate=round(needs['exhausted'] / person_cycles, 4),
        wasted_share=round(sum(not d['result']['success'] or d['proposal'].get('type') == 'wait'
                               for d in world.decisions) / all_decisions, 4),
        civic_share=round(sum(d['proposal'].get('type') in CIVIC and d['result']['success']
                              for d in world.decisions) / all_decisions, 4),
        mean_coins=round(sum(a.inventory['coins'] for a in world.agents) / max(1, len(world.agents)), 2),
        mean_food=round(sum(a.inventory['food'] for a in world.agents) / max(1, len(world.agents)), 2))
    return dict(focal=focal_summary, population=population), dict(timeline=timeline, motivations=motives)


def describe(goal):
    from .goal_engine import describe_goal
    return describe_goal(goal) if goal else None


def run_goal_case(name, seed=42, years=20, policy_style='balanced', adaptive_goals=True):
    world, metadata = build_goal_scenario(name, seed, policy_style, adaptive_goals)
    needs = dict(focal_hungry=0, focal_exhausted=0, hungry=0, exhausted=0, person_cycles=0)
    lineage = metadata['focal_lineage']
    for _ in range(years * world.ticks_per_year):
        world.step()
        needs['person_cycles'] += len(world.agents)
        needs['hungry'] += sum(a.hunger >= 65 for a in world.agents)
        needs['exhausted'] += sum(a.energy < 15 for a in world.agents)
        focal = next((a for a in world.agents if a.lineage == lineage), None)
        if focal is not None:
            needs['focal_hungry'] += focal.hunger >= 65
            needs['focal_exhausted'] += focal.energy < 15
    summary, evidence = _measure(world, metadata, needs)
    label = 'adaptive' if adaptive_goals else 'fixed'
    return dict(name=f'{name}-{label}', scenario=name, adaptive_goals=adaptive_goals,
                description=metadata['description'], metadata=metadata, summary=summary,
                evidence=evidence, history=world.export())


def run_goal_experiments(seed=42, years=20, policy_style='balanced'):
    """Each scenario with adaptive goals and with fixed goals; every outcome is reported."""
    if type(years) is not int or not 0 <= years <= 100:
        raise ValueError('years must be an integer from 0 to 100')
    cases = [run_goal_case(name, seed, years, policy_style, adaptive)
             for name in GOAL_SCENARIOS for adaptive in (True, False)]
    return {'schema': 'eternia.goal_experiment.v1', 'seed': seed, 'years': years,
            'policy_style': policy_style, 'ticks_per_year': 4, 'focal': FOCAL,
            'note': 'Matched starting circumstances for one miner, each run with adaptive and with fixed goals. '
                    'Goal changes, refusals and completions are observed, never injected.',
            'cases': cases}
