"""Matched starting distributions of wealth and work: does inequality change a society?

Every case keeps all eighteen people, their goals, motives and the default
society policy, and the same total coins in every town. Cases differ only in
who holds the coins at the start:

    equal_start            each town's named residents start with equal coins
    unequal_start          each town's merchant starts with 75% of the residents' coins
    unequal_private_funds  as unequal_start, and 80% of each town treasury also
                           starts with the merchant: fewer coins for public work

Nothing later is injected. Trust, migration, organizations, levies, living
standards and the inequality itself are outcomes, measured every year.
"""
from copy import deepcopy
import math

from .inequality import decade_mobility, trajectory
from .society import SocietyWorld

INEQUALITY_SCENARIOS = {
    'equal_start': "Each town's six named residents start with equal shares of their coins.",
    'unequal_start': "Each town's merchant starts with 75% of the named residents' coins; the other five share the rest.",
    'unequal_private_funds': 'As unequal_start, and 80% of each town treasury also starts with its merchant, '
                             'leaving less public money for paid work.',
}
MERCHANT_SHARE, TREASURY_SHARE = .75, .8


def build_inequality_scenario(name, seed=42, policy_style='balanced'):
    if name not in INEQUALITY_SCENARIOS:
        raise ValueError(f'Unknown inequality scenario: {name!r}')
    world = SocietyWorld(seed=seed, policy_style=policy_style)
    before = world.resource_totals()
    transfers = []
    for town in world.settlements:
        residents = sorted((a for a in world.agents if a.home == town.id), key=lambda a: a.id)
        total = sum(a.inventory['coins'] for a in residents)
        merchant = next(a for a in residents if a.role == 'merchant')
        if name == 'equal_start':
            shares = {a.id: total / len(residents) for a in residents}
        else:
            rest = total * (1 - MERCHANT_SHARE) / (len(residents) - 1)
            shares = {a.id: total * MERCHANT_SHARE if a.id == merchant.id else rest for a in residents}
        for person in residents:
            person.inventory['coins'] = shares[person.id]
        moved = 0.
        if name == 'unequal_private_funds':
            moved = town.treasury * TREASURY_SHARE
            town.treasury -= moved
            merchant.inventory['coins'] += moved
        transfers.append(dict(settlement=town.id, resident_coins=round(total, 6),
                              shares={a.id: round(shares[a.id], 6) for a in residents},
                              treasury_to_merchant=round(moved, 6)))
    after = world.resource_totals()
    if any(not math.isclose(before[r], after[r], abs_tol=1e-7) for r in before):
        raise AssertionError('Inequality scenario setup changed resource totals')
    world.reset_market_prices()
    world.scenario = 'inequality:' + name
    world.provenance['scenario'] = world.scenario
    world._event('experiment', INEQUALITY_SCENARIOS[name], scenario=name)
    world.snapshots = []
    world._snapshot()
    world._assert_invariants()
    metadata = dict(scenario=name, description=INEQUALITY_SCENARIOS[name], seed=seed, policy_style=policy_style,
                    controlled_changes=dict(coin_transfers=transfers), initial_totals=dict(after),
                    limitations=[
                        'Only the starting distribution of coins differs; every later decision follows the same rules.',
                        'Inequality is measured over the named people, not the aggregate population.',
                        'People never see anyone else\'s wealth; they react to their own experiences.',
                        'One seed is one history; compare several before generalizing.'])
    return world, metadata


def _mean_trust(snap):
    """Average trust each named person holds toward their current neighbors."""
    agents = snap.get('agents', [])
    values = []
    for person in agents:
        neighbors = [a['id'] for a in agents if a['home'] == person['home'] and a['id'] != person['id']]
        if neighbors:
            trust = person.get('trust', {})
            values.append(sum(trust.get(n, trust.get(str(n), 0.)) for n in neighbors) / len(neighbors))
    return round(sum(values) / len(values), 4) if values else 0.


def yearly(world):
    """One row per recorded year: inequality, beliefs, ties, organizations, movement and needs."""
    rows, levies = [], {}
    for event in world.events:
        if event.get('kind') == 'levy':
            levies[event['year']] = levies.get(event['year'], 0.) + event.get('amount', 0.)
    for snap in world.snapshots:
        data, minds = snap.get('inequality'), snap.get('minds', {})
        if not data:
            continue
        members = {person: set() for person in (a['id'] for a in snap.get('agents', []))}
        for institution in snap.get('institutions', []):
            if institution.get('active'):
                for member in institution.get('members', []):
                    members.setdefault(member, set()).add(institution.get('purpose'))
        count = max(1, len(members))
        rows.append(dict(
            year=snap['year'], wealth_gini=data['region']['wealth_gini'], income_gini=data['region']['income_gini'],
            town_gini={town: group.get('wealth_gini') for town, group in data['towns'].items()},
            poverty_share=data['region']['poverty_share'], food_insecure_share=data['region']['food_insecure_share'],
            poorest_third_wealth=data['region']['poorest_third_mean'], mean_wealth=data['region']['mean_wealth'],
            fairness=round(sum(m.get('fairness', .5) for m in minds.values()) / max(1, len(minds)), 4),
            trust=_mean_trust(snap),
            cooperative_share=round(sum('cooperative' in p for p in members.values()) / count, 4),
            organized_share=round(sum(bool(p) for p in members.values()) / count, 4),
            migrations=snap.get('physical_metrics', {}).get('migrants_arrived', 0),
            levies=round(levies.get(snap['year'], 0.), 4)))
    return rows


def _summary(world, metadata, rows):
    first, last = rows[0], rows[-1]
    span = rows[-max(1, len(rows) // 3):]  # the final third of the run
    mean = lambda key: round(sum(r[key] for r in span) / len(span), 4)
    mobility = [m['mobility'] for m in decade_mobility(world.snapshots) if m['mobility'] is not None]
    starved = sum(e['kind'] == 'death' and 'deprivation' in e['message'] for e in world.events)
    return dict(scenario=metadata['scenario'], seed=metadata['seed'], policy_style=metadata['policy_style'],
                years=world.year, start_gini=first['wealth_gini'], end_gini=last['wealth_gini'],
                late_gini=mean('wealth_gini'), late_fairness=mean('fairness'), late_trust=mean('trust'),
                late_cooperative_share=mean('cooperative_share'), late_organized_share=mean('organized_share'),
                late_poverty_share=mean('poverty_share'), late_food_insecure_share=mean('food_insecure_share'),
                late_poorest_third_wealth=mean('poorest_third_wealth'), late_mean_wealth=mean('mean_wealth'),
                migrations=last['migrations'], levies_paid=round(sum(r['levies'] for r in rows), 2),
                cooperatives_formed=sum(i.purpose == 'cooperative' for i in world.institutions),
                mean_decade_mobility=round(sum(mobility) / len(mobility), 4) if mobility else None,
                starvation_deaths=starved, town_end_gini=dict(last['town_gini']))


def run_inequality_case(name, seed=42, years=30, policy_style='balanced'):
    world, metadata = build_inequality_scenario(name, seed, policy_style)
    world.run(years)
    rows = yearly(world)
    return dict(name=name, description=metadata['description'], metadata=metadata,
                summary=_summary(world, metadata, rows), series=rows,
                evidence=dict(levies=[deepcopy(e) for e in world.events if e.get('kind') == 'levy'][-40:],
                              organizations=[i.public_state() for i in world.institutions],
                              gini_by_town={t.id: trajectory(world.snapshots, town=t.id) for t in world.settlements}),
                history=world.export())


COMPARED = ('late_gini', 'late_fairness', 'late_trust', 'late_cooperative_share', 'late_organized_share',
            'late_poverty_share', 'late_food_insecure_share', 'late_poorest_third_wealth', 'migrations', 'levies_paid')


def run_inequality_experiments(seed=42, years=30, policy_style='balanced'):
    """Matched worlds through ordinary cycles; differences against equal_start are reported, not assumed."""
    if type(years) is not int or not 1 <= years <= 200:
        raise ValueError('years must be an integer from 1 to 200')
    cases = [run_inequality_case(name, seed, years, policy_style) for name in INEQUALITY_SCENARIOS]
    base = cases[0]['summary']
    differences = {case['name']: {key: (round(case['summary'][key] - base[key], 4)
                                        if case['summary'][key] is not None and base[key] is not None else None)
                                  for key in COMPARED} for case in cases[1:]}
    return {'schema': 'eternia.inequality_experiment.v1', 'seed': seed, 'years': years,
            'policy_style': policy_style, 'ticks_per_year': 4, 'compared_with': 'equal_start',
            'note': 'Matched starting distributions of coins with eighteen autonomous agents per case. Trust, '
                    'migration, organizations, levies and inequality are observed, never injected.',
            'differences': differences, 'cases': cases}
