"""Matched initial conditions for observing price-driven regional trade.

Every case keeps all eighteen agents, their goals and the default society
policy. Cases differ only in where the existing stored food sits at the start
and whether the roads into Highfen are passable. Total food is identical in
every case; no purchase, contract or shipment is injected. Whether merchants
or councils move food, and whether it arrives, are outcomes.
"""
from copy import deepcopy
import math

from .market import RESERVE_PER_RESIDENT, USE_PER_RESIDENT, bid_price
from .society import SocietyWorld

RIVERMARK, HIGHFEN, DEEPWOOD = 0, 1, 2
MARKET_SCENARIOS = {
    'price_gap': "Highfen's stored food starts in Rivermark: famine prices in Highfen and a glut in Rivermark.",
    'matched_supply': 'The same stored food is shared so every town starts with equal food coverage: no profitable gap at first.',
    'blocked_route': 'The price gap of price_gap, but both roads into Highfen start impassable.',
}


def _move_food(world, source, target, amount):
    world.settlements[source].food -= amount
    world.settlements[target].food += amount


def match_food_coverage(world):
    """Redistribute stored food so every town's starting food coverage is equal; returns the transfers."""
    towns = world.settlements
    use = {t.id: max(1, t.population) * USE_PER_RESIDENT['food'] for t in towns}
    need = {t.id: use[t.id] + max(1, t.population) * RESERVE_PER_RESIDENT['food'] for t in towns}
    total = sum(t.food for t in towns)
    level = (total + sum(t.deposits['food'] + use[t.id] for t in towns)) / sum(need.values())
    shares = {t.id: max(0., level * need[t.id] - t.deposits['food'] - use[t.id]) for t in towns}
    scale = total / sum(shares.values())
    before = {t.id: t.food for t in towns}
    for town in towns:
        town.food = shares[town.id] * scale
    return [{'settlement': t.id, 'stored_food_before': before[t.id], 'after': t.food} for t in towns]


def build_market_scenario(name, seed=42, policy_style='balanced'):
    if name not in MARKET_SCENARIOS:
        raise ValueError(f'Unknown market scenario: {name!r}')
    world = SocietyWorld(seed=seed, policy_style=policy_style)
    before = world.resource_totals()
    transfers, roads = [], []
    if name in ('price_gap', 'blocked_route'):
        moved = world.settlements[HIGHFEN].food
        _move_food(world, HIGHFEN, RIVERMARK, moved)
        transfers.append({'from': HIGHFEN, 'to': RIVERMARK, 'stored_food': moved})
    else:
        transfers = match_food_coverage(world)
    if name == 'blocked_route':
        for link in world.links:
            if HIGHFEN in (link['a'], link['b']):
                roads.append({'link': link['id'], 'before': link['condition'], 'after': 0.})
                link['condition'] = 0.
    after = world.resource_totals()
    if any(not math.isclose(before[r], after[r], abs_tol=1e-7) for r in before):
        raise AssertionError('Market scenario setup changed resource totals')
    world.reset_market_prices()
    world.scenario = 'market:' + name
    world.provenance['scenario'] = world.scenario
    world._event('experiment', MARKET_SCENARIOS[name], world.settlements[HIGHFEN].name, scenario=name)
    world.snapshots = []
    world._snapshot()
    world._assert_invariants()
    metadata = dict(
        scenario=name, description=MARKET_SCENARIOS[name], seed=seed, policy_style=policy_style,
        destination=HIGHFEN, initial_prices=deepcopy(world.market_prices),
        initial_coverage=deepcopy(world.market_coverage), initial_totals=dict(after),
        controlled_changes=dict(food_transfers=transfers, road_conditions=roads),
        limitations=[
            'The starting food distribution is an initial condition; contracts, purchases and shipments are outcomes.',
            'Prices before the first harvest assume each town produces what it eats; recorded harvests replace that.',
            'Wood and iron prices also differ between towns, so trade in those goods can occur in every case.',
            'One seed is one history. Compare several seeds before generalizing.'])
    return world, metadata


def food_series(world, town):
    return [dict(tick=entry['tick'], price=entry['prices'][town]['food'],
                 coverage=entry['coverage'][town]['food']) for entry in world.price_history]


def trade_journeys(world):
    """Every caravan judged by the market: merchant consignments and contract shipments."""
    return [j for j in world.journeys if j['kind'] == 'caravan' and 'expected_gain' in j]


def _market_case(world, metadata):
    journeys = trade_journeys(world)
    food_in = [j for j in journeys if j['destination'] == HIGHFEN
               and 'food' in (j.get('delivered_cargo') or j.get('lost_cargo') or j['cargo'])]
    delivered = sum(j.get('delivered_cargo', {}).get('food', 0.) for j in food_in)
    start = world.price_history[0]['prices']
    deaths = [e for e in world.events if e['kind'] == 'death' and 'deprivation' in e['message']]
    summary = dict(
        scenario=metadata['scenario'], seed=metadata['seed'], policy_style=metadata['policy_style'],
        start_highfen_food_price=start[HIGHFEN]['food'], start_rivermark_food_price=start[RIVERMARK]['food'],
        start_food_margin=round(bid_price(start[HIGHFEN]['food']) - start[RIVERMARK]['food'], 2),
        final_highfen_food_price=world.market_prices[HIGHFEN]['food'],
        food_shipments_to_highfen=len(food_in),
        merchant_food_shipments=sum(bool(j.get('consignment')) for j in food_in),
        contract_food_shipments=sum(not j.get('consignment') for j in food_in),
        first_food_departure_tick=min((j['created'] for j in food_in), default=None),
        food_delivered_to_highfen=delivered,
        shipments=len(journeys), shipments_delivered=sum(j['status'] == 'delivered' for j in journeys),
        shipments_lost=sum(j['status'] == 'failed' for j in journeys),
        negative_expected_departures=sum(j['expected_gain'] < 0 for j in journeys),
        losing_shipments=sum(j.get('gain', 0) < 0 for j in journeys if j['status'] != 'in_transit'),
        realized_gain=round(sum(j.get('gain', 0.) for j in journeys if j['status'] != 'in_transit'), 2),
        food_contracts_into_highfen=sum(r['resource'] == 'food' and r['importer'] == HIGHFEN for r in world.routes),
        retail_food_purchases_in_highfen=sum(t['kind'] == 'purchase' and t['resource'] == 'food'
                                             and t['settlement'] == HIGHFEN for t in world.trade_history),
        highfen_population=[world.snapshots[0]['settlements'][HIGHFEN]['population'],
                            world.settlements[HIGHFEN].population],
        starvation_deaths=len(deaths))
    evidence = dict(
        highfen_food_prices=food_series(world, HIGHFEN), rivermark_food_prices=food_series(world, RIVERMARK),
        shipments=[{k: deepcopy(j.get(k)) for k in ('id', 'consignment', 'owner', 'organizer', 'contract', 'origin',
                                                    'destination', 'created', 'arrived', 'status', 'unit_price',
                                                    'expected_gain', 'gain', 'delivered_cargo', 'lost_cargo')}
                   for j in journeys],
        contracts=[deepcopy(r) for r in world.routes],
        trade_decisions=[deepcopy(d) for d in world.decisions
                         if d['proposal'].get('type') in ('consign', 'dispatch_caravan')
                         or 'consign' in d['rationale'] or 'trade terms' in d['rationale'].lower()])
    return dict(name=metadata['scenario'], description=metadata['description'], metadata=metadata,
                summary=summary, evidence=evidence, history=world.export())


def run_market_experiments(seed=42, years=2, policy_style='balanced'):
    """Run matched worlds through ordinary ``step`` cycles; every outcome is reported."""
    if type(years) is not int or not 0 <= years <= 100:
        raise ValueError('years must be an integer from 0 to 100')
    cases = []
    for name in MARKET_SCENARIOS:
        world, metadata = build_market_scenario(name, seed, policy_style)
        world.run(years)
        cases.append(_market_case(world, metadata))
    return {'schema': 'eternia.market_experiment.v1', 'seed': seed, 'years': years,
            'policy_style': policy_style, 'ticks_per_year': 4,
            'note': 'Matched initial food distributions with eighteen autonomous agents per case. Prices, purchases, '
                    'contracts and shipments are observed, never injected; outcomes are specific to this seed.',
            'cases': cases}
