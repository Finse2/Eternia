"""Repeatable v0.7 outcome comparisons; outcomes, not pass/fail theater."""
from copy import deepcopy
import math

from .economic_policy import STYLES
from .labor_experiments import labor_migrations, remove_resident_skill
from .market import bid_price
from .market_experiments import HIGHFEN, RIVERMARK, trade_journeys
from .persistence import run_manifest
from .society import SocietyWorld

SCENARIOS = ('baseline', 'local_scarcity', 'blocked_routes', 'labor_shortage', 'food_shortage')


def build_society_scenario(seed, scenario='baseline', policy_style='balanced'):
    if scenario not in SCENARIOS:
        raise ValueError('Unknown society evaluation scenario')
    world = SocietyWorld(seed=seed, policy_style=policy_style)
    before = world.resource_totals()
    if scenario == 'local_scarcity':
        for town in world.settlements:
            town.iron += town.deposits['iron']
            town.deposits['iron'] = 0.
    elif scenario == 'blocked_routes':
        for link in world.links:
            link['condition'] = .05
    elif scenario == 'labor_shortage':
        # Knowledge only: Highfen keeps its iron, but no resident can mine it.
        # Any job, journey or wage that follows is an outcome, not a setup.
        remove_resident_skill(world)
    elif scenario == 'food_shortage':
        # Highfen's stored food starts in Rivermark: a supply condition, not a trade.
        world.settlements[RIVERMARK].food += world.settlements[HIGHFEN].food
        world.settlements[HIGHFEN].food = 0.
    if any(not math.isclose(before[r], world.resource_totals()[r], abs_tol=1e-7) for r in before):
        raise AssertionError('Scenario setup changed resource totals')
    world.reset_market_prices()
    world.scenario = scenario
    world.provenance['scenario'] = scenario
    world.snapshots = []
    world._snapshot()
    return world


def goal_outcome(actor):
    kind, target = actor.goal.get('kind'), actor.goal.get('target', 1)
    value = (actor.inventory['coins'] if kind in ('wealth', 'profit') else
             actor.structures.get('house', 0) if kind == 'houses' else
             actor.knowledge if kind == 'knowledge' else
             actor.inventory['food'] if kind == 'food' else
             actor.influence if kind == 'influence' else 0.)
    return dict(actor=actor.id, lineage=actor.lineage, goal=kind, target=target,
                value=value, completed=value + 1e-9 >= target,
                fraction=min(1., max(0., value / max(target, 1e-9))))


def summarize(world, *, hunger_cycles=0, person_cycles=0):
    outcomes = [goal_outcome(actor) for actor in world.agents]
    residuals = {r: total - (world.initial_totals[r] + world.ledger['produced'][r]
                            - world.ledger['consumed'][r]) for r, total in world.resource_totals().items()}
    moves = labor_migrations(world)
    shipments = trade_journeys(world)
    settled = [j for j in shipments if j['status'] != 'in_transit']
    market = world.market_metrics
    food = {town: prices['food'] for town, prices in world.market_prices.items()}
    return dict(seed=world.seed, scenario=getattr(world, 'scenario', 'baseline'),
                policy_style=world.policy_style, years=world.year, tick=world.tick,
                named_agents=len(world.agents), goals_completed=sum(o['completed'] for o in outcomes),
                mean_goal_fraction=sum(o['fraction'] for o in outcomes) / max(1, len(outcomes)),
                hunger_cycles=hunger_cycles, person_cycles=person_cycles,
                hunger_rate=hunger_cycles / max(1, person_cycles),
                wages_paid=world.economic_metrics['wages_paid'],
                paid_work_actions=world.economic_metrics['paid_work_actions'],
                volunteer_actions=world.economic_metrics['volunteer_actions'],
                voluntary_with_paid_option=world.economic_metrics['voluntary_with_paid_option'],
                donated_coins=world.economic_metrics['donated_coins'],
                municipal_orders=world.economic_metrics['municipal_orders'],
                private_orders=world.economic_metrics['private_orders'],
                commissions=world.economic_metrics['commissions'],
                institutions_active=sum(i.active for i in world.institutions),
                road_repairs=world.physical_metrics['road_repairs'],
                caravans_delivered=world.physical_metrics['caravans_delivered'],
                caravans_failed=world.physical_metrics['caravans_failed'],
                migrations=world.physical_metrics['migrants_arrived'],
                labor_migrations=sum(m['paid_actions'] > 0 for m in moves),
                wages_after_migration=sum(m['wages'] for m in moves),
                retail_purchases=market['purchases'], retail_sales=market['sales'],
                consignments=market['consignments'],
                contract_shipments=sum(not j.get('consignment') for j in shipments),
                shipments_delivered=sum(j['status'] == 'delivered' for j in settled),
                negative_expected_departures=sum(j['expected_gain'] < 0 for j in shipments),
                losing_shipments=sum(j.get('gain', 0) < 0 for j in settled),
                shipment_gain=sum(j.get('gain', 0.) for j in settled),
                food_imported_by_highfen=sum(j.get('delivered_cargo', {}).get('food', 0.) for j in settled
                                             if j['destination'] == HIGHFEN),
                food_prices=food, highfen_food_margin=round(bid_price(food[HIGHFEN]) - food[RIVERMARK], 2),
                ledger_max_residual=max(abs(v) for v in residuals.values()),
                outcomes=outcomes)


def evaluate_society(seeds=(18, 42, 73), years=5, scenarios=SCENARIOS, styles=STYLES):
    seeds, scenarios, styles = list(seeds), list(scenarios), list(styles)
    if (not seeds or len(seeds) > 20 or any(type(seed) is not int for seed in seeds)
            or len(set(seeds)) != len(seeds)):
        raise ValueError('Use one to twenty distinct integer seeds')
    if type(years) is not int or not 1 <= years <= 100:
        raise ValueError('Evaluation years must be between 1 and 100')
    if (not scenarios or len(set(scenarios)) != len(scenarios)
            or any(s not in SCENARIOS for s in scenarios)):
        raise ValueError('Invalid or duplicate evaluation scenarios')
    if not styles or len(set(styles)) != len(styles) or any(s not in STYLES for s in styles):
        raise ValueError('Invalid or duplicate policy styles')
    cases = []
    for seed in seeds:
        for scenario in scenarios:
            for style in styles:
                world = build_society_scenario(seed, scenario, style)
                hungry = cycles = 0
                for _ in range(years * world.ticks_per_year):
                    world.step()
                    cycles += len(world.agents)
                    hungry += sum(a.hunger >= 65 for a in world.agents)
                cases.append(dict(summary=summarize(world, hunger_cycles=hungry, person_cycles=cycles),
                                  provenance=deepcopy(world.provenance),
                                  work_evidence=deepcopy(world.work_history[-12:])))
    groups = []
    for scenario in scenarios:
        for style in styles:
            selected = [case['summary'] for case in cases
                        if case['summary']['scenario'] == scenario and case['summary']['policy_style'] == style]
            fields = ('goals_completed', 'mean_goal_fraction', 'hunger_rate', 'wages_paid',
                      'volunteer_actions', 'voluntary_with_paid_option', 'road_repairs', 'caravans_failed',
                      'private_orders', 'labor_migrations', 'wages_after_migration', 'retail_purchases',
                      'consignments', 'contract_shipments', 'negative_expected_departures', 'losing_shipments',
                      'food_imported_by_highfen')
            groups.append(dict(scenario=scenario, policy_style=style, runs=len(selected),
                               means={key: sum(s[key] for s in selected) / len(selected) for key in fields},
                               ranges={key: [min(s[key] for s in selected), max(s[key] for s in selected)]
                                       for key in fields}))
    return dict(schema='eternia.evaluation.v0.7.2', years=years, seeds=seeds,
                scenarios=scenarios, policy_styles=styles, cases=cases, groups=groups,
                definitions=dict(
                    goals_completed='Final living agents meeting the current goal; not lifetime or population-wide success.',
                    wealth='Coins held; profit goals retain the earlier holdings-target semantics, not net accounting profit.',
                    hunger_rate='Share of end-of-cycle person observations with hunger >= 65.',
                    voluntary_with_paid_option='Completed voluntary actions with a public paid quote at planning time; competition may make that quote unavailable.',
                    labor_migrations='Completed journeys followed by paid work in the destination before the person moved again; motive is not inferred.',
                    labor_shortage='Highfen residents start without mining knowledge; no job, journey or wage is injected.',
                    food_shortage="Highfen's stored food starts in Rivermark; no purchase, contract or shipment is injected.",
                    negative_expected_departures='Shipments that left although the payment, discounted by the quoted journey risk, '
                                                 'was below the cargo and provisions\' value at home. The policy aims for zero.',
                    losing_shipments='Settled shipments paid less than the cargo and provisions were worth at home, or lost on the road.',
                    food_imported_by_highfen='Food units delivered to Highfen by merchant consignments or contract caravans.',
                    means='Arithmetic means over the selected seeds; ranges are observed minima/maxima, not confidence intervals.'),
                limitations=[
                    'Small seeded prototype; no calibration or claim of general intelligence.',
                    'Only initial scenario conditions change. Annual replenishment and road repairs can remove a control condition.',
                    'Different policy styles change programmed priorities, not authoritative rules.',
                    'Goal, wage, survival and public-project outcomes can conflict; failures are reported rather than suppressed.'])

