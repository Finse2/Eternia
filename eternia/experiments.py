"""Matched initial conditions for observing autonomous migration.

These are controlled opportunities, not a new policy or a scheduled migration.
Every case keeps all eighteen original agents, their goals, normal hazard rates,
and the default planner. Only initial resource allocation, accessible local iron,
and (for the blocked control) road condition differ. Later repairs, new mining,
competing projects, and failed journeys remain possible.
"""
from copy import deepcopy

from .physical_world import PhysicalWorld


MIGRATION_SCENARIOS = {
    'opportunity': 'A provisioned, cash-poor miner has no accessible local iron; '
                   'Highfen has accessible iron and an open physical route.',
    'local_work': 'The same miner also has accessible iron at home. Resources '
                  'are moved from municipal storage into the accessible deposit.',
    'blocked_route': 'The same distant mining opportunity exists, but both '
                     'connections out of the home settlement start impassable.',
}


def build_migration_scenario(name, seed=42):
    """Return a fresh normal world and an explicit description of its fixture.

    Resource changes are transfers, so all cases start with identical totals.
    Eight food provides the default four-tick journey's six required provisions
    and a small personal reserve. No action is submitted while building a case.
    """
    if name not in MIGRATION_SCENARIOS:
        raise ValueError(f'Unknown migration scenario: {name!r}')
    world = PhysicalWorld(seed=seed, ticks_per_year=4, shock_year=0)
    origin = world.settlements[0]
    actor = next(a for a in world.agents if a.home == origin.id and a.role == 'miner')
    original_inventory = dict(actor.inventory)
    original_deposit = origin.deposits['iron']

    # Initial allocation, not a fictional contribution or an unrecorded action.
    origin.treasury += actor.inventory['coins']
    actor.inventory['coins'] = 0.
    origin.iron += actor.inventory['iron']
    actor.inventory['iron'] = 0.
    origin.food -= 8. - actor.inventory['food']
    actor.inventory['food'] = 8.
    accessible_iron = 12. if name == 'local_work' else 0.
    origin.iron += origin.deposits['iron'] - accessible_iron
    origin.deposits['iron'] = accessible_iron

    road_changes = []
    if name == 'blocked_route':
        for link in world.links:
            if origin.id in (link['a'], link['b']):
                road_changes.append({'link': link['id'], 'before': link['condition'], 'after': 0.})
                link['condition'] = 0.

    # Replace the constructor's baseline snapshot with the actual experiment.
    world.initial_totals = world.resource_totals()
    world.events = []
    world._event('experiment', MIGRATION_SCENARIOS[name], origin.name, actor.name,
                 scenario=name)
    world.snapshots = []
    world._snapshot()
    world._assert_invariants()
    observation = world.observe(actor.id)
    metadata = {
        'focal_actor': actor.id,
        'actor_name': actor.name,
        'role': actor.role,
        'goal': deepcopy(actor.goal),
        'initial_home': origin.id,
        'initial_home_name': origin.name,
        'initial_inventory': dict(actor.inventory),
        'initial_named_agents': len(world.agents),
        'initial_population': sum(town.population for town in world.settlements),
        'settlements': {town.id: town.name for town in world.settlements},
        'policy': world._default_policy.name,
        'ticks_per_year': world.ticks_per_year,
        'shock_year': world.shock_year,
        'local_accessible_iron': observation['settlement']['deposits']['iron'],
        'neighbor_accessible_iron': {town['id']: town['deposits']['iron']
                                     for town in observation['neighbors']},
        'initial_paths': deepcopy(observation['physical']['paths']),
        'initial_totals': dict(world.initial_totals),
        'controlled_changes': {
            'actor_inventory_before': original_inventory,
            'actor_inventory_after': dict(actor.inventory),
            'municipal_transfers': 'Personal coins and iron enter municipal storage; '
                                   'five food leave municipal storage for the miner.',
            'accessible_iron_before': original_deposit,
            'accessible_iron_after': accessible_iron,
            'accessible_iron_transfer': 'Iron moves between the municipal store and '
                                        'the accessible deposit; buried reserves are unchanged.',
            'road_conditions': road_changes,
        },
        'limitations': [
            'A controlled initial opportunity tests the existing planner, not general migration frequency.',
            'All agents keep their normal goals and policy; no future actions or road repairs are prescribed.',
            'Mining after arrival can serve an institutional project; it does not prove the wealth goal was achieved.',
            'Normal weather, accidents, local replenishment, politics and repairs can change each opportunity.',
        ],
    }
    return world, metadata


def _migration_case(world, name, metadata):
    actor_id = metadata['focal_actor']
    decisions = [deepcopy(d) for d in world.decisions if d['actor'] == actor_id]
    journeys = [deepcopy(j) for j in world.journeys
                if j['kind'] == 'migrant' and j['actor'] == actor_id]
    arrivals = [j for j in journeys if j['status'] == 'delivered']
    # A recorded successful local action must follow an actual delivery to that
    # settlement, rather than merely following a migration proposal/departure.
    work = [d for d in decisions
            if d['result']['success'] and d['proposal']['type'] == 'gather'
            and d['proposal'].get('params', {}).get('resource') == 'iron'
            and any(j['arrived'] <= d['tick'] and j['destination'] == d['proposal'].get('location')
                    for j in arrivals)]
    living_actor = next((a for a in world.agents if a.id == actor_id), None)
    coins = living_actor.inventory['coins'] if living_actor else None
    first_decision = decisions[0] if decisions else None
    summary = {
        'focal_actor': actor_id,
        'actor_name': metadata['actor_name'],
        'initial_home': metadata['initial_home'],
        'final_home': living_actor.home if living_actor else None,
        'migrations_proposed': sum(d['proposal']['type'] == 'migrate' for d in decisions),
        'departures': len(journeys),
        'arrivals': len(arrivals),
        'returns': sum(j['status'] == 'returned' for j in journeys),
        'in_transit': sum(j['status'] == 'in_transit' for j in journeys),
        'first_action': first_decision['proposal']['type'] if first_decision else None,
        'first_departure_tick': min((j['created'] for j in journeys), default=None),
        'first_arrival_tick': min((j['arrived'] for j in arrivals), default=None),
        'post_arrival_work': len(work),
        'first_post_arrival_work_tick': min((d['tick'] for d in work), default=None),
        'final_goal_progress': coins,
        'goal_target': metadata['goal']['target'],
        'goal_completed': coins is not None and coins >= metadata['goal']['target'],
    }
    journey_ids = {j['id'] for j in journeys}
    evidence = {
        'first_decision': first_decision,
        'decisions': decisions,
        'journeys': journeys,
        'arrival_events': [deepcopy(event) for event in world.events
                           if event.get('journey_id') in journey_ids and event['kind'] == 'arrival'],
        'post_arrival_work': work,
    }
    return dict(name=name, description=MIGRATION_SCENARIOS[name], metadata=metadata,
                summary=summary, evidence=evidence, history=world.export())


def run_migration_experiments(seed=42, years=3):
    """Run paired worlds with normal ``step`` cycles and return JSON-ready evidence.

    Each case includes an independent full history for the existing world report.
    No success criterion is imposed on a seed: a return, a failed proposal or a
    lack of movement remains a valid, visible experimental result.
    """
    if type(years) is not int or not 0 <= years <= 10000:
        raise ValueError('years must be an integer from 0 to 10000')
    cases = []
    for name in MIGRATION_SCENARIOS:
        world, metadata = build_migration_scenario(name, seed)
        world.run(years)
        cases.append(_migration_case(world, name, metadata))
    return {
        'schema': 'eternia.migration_experiment.v1',
        'seed': seed,
        'years': years,
        'ticks_per_year': 4,
        'note': 'Matched initial conditions with eighteen normal autonomous agents per case. '
                'Migration decisions are observed, never injected; outcomes are specific to this scenario and seed.',
        'cases': cases,
    }
