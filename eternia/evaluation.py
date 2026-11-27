"""Repeatable v0.7 outcome comparisons; outcomes, not pass/fail theater."""
from copy import deepcopy
import math

from .economic_policy import STYLES
from .goal_engine import goal_value
from .inequality import snapshot as inequality_snapshot
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
    """The person's current goal and whether it is met now; lifetime records are in goal_history."""
    kind, target = actor.goal.get('kind'), actor.goal.get('target', 1)
    value = goal_value(actor, actor.goal)
    return dict(actor=actor.id, lineage=actor.lineage, goal=kind, target=target,
                value=value, completed=value + 1e-9 >= target,
                fraction=min(1., max(0., value / max(target, 1e-9))))


def goal_history(world):
    """Lifetime goal records, kept separate from whether current goals are met."""
    log = getattr(world, 'goal_log', [])
    count = lambda *events: sum(entry['event'] in events for entry in log)
    # A human player sets their own aims and has no recorded goal.
    pursuing = [a for a in world.agents if a.id not in getattr(world, 'players', ())]
    return dict(goal_completions=count('completed'),
                goal_revisions=count('revised', 'escalated'),
                goals_escalated=count('escalated'),
                goals_abandoned=sum(e['event'] == 'revised' and e.get('previous_outcome') == 'abandoned' for e in log),
                goals_declined_after_success=count('content'),
                goals_unfinished_at_death=count('ended'),
                goals_active=len(pursuing),
                lineages_that_changed_goal=len({e.get('lineage') for e in log if e['event'] in ('revised', 'escalated')}),
                current_goal_kinds={kind: sum(a.goal.get('kind') == kind for a in pursuing)
                                    for kind in sorted({a.goal.get('kind') for a in pursuing})})


STEP_ACTIONS = {'house': ('build', 'structure', 'house'), 'carpentry': ('research', 'topic', 'carpentry'),
                'research': ('research', 'topic', 'aether')}


def opportunity_record(world):
    """v0.9 Stage 1: every job posted for a step of its employer's own goal, and what became of it.

    A historian's view: who posted it and why, who worked it, whether it was
    completed, expired or is still open, and whether the employer went on to take
    the step it served (build the house, study carpentry, run the experiment).
    """
    names = {}
    for snapshot in getattr(world, 'snapshots', ()):
        names.update({a['id']: (a['name'], a['role']) for a in snapshot.get('agents', [])})
    names.update({a.id: (a.name, a.role) for a in world.agents})
    workers, steps = {}, {}
    for entry in world.action_log:
        action, result = entry['action'], entry['result']
        if not result.get('success'):
            continue
        if action.get('type') == 'work':
            workers.setdefault(result['effects']['order_id'], set()).add(action.get('actor'))
        else:
            params = action.get('params', {})
            for step, (kind, field, value) in STEP_ACTIONS.items():
                if action.get('type') == kind and params.get(field) == value:
                    steps.setdefault((action.get('actor'), step), []).append(entry['tick'])
    jobs = []
    for order in getattr(world, 'work_orders', ()):
        purpose = order.get('purpose')
        if order['employer'].get('kind') != 'person' or not purpose:
            continue
        employer, step = order['employer']['id'], purpose['step']
        taken = next((t for t in steps.get((employer, step), []) if t > order['created']), None)
        jobs.append(dict(order=order['id'], tick=order['created'], employer=names.get(employer, ('?', '?'))[0],
                         role=names.get(employer, ('?', '?'))[1], step=step, resource=order['resource'],
                         quantity=order['quantity'], delivered=order['quantity'] - order['remaining'],
                         unit_wage=order['unit_wage'], status=order['status'],
                         workers=sorted(names.get(w, ('?', '?'))[0] for w in workers.get(order['id'], ())),
                         worker_roles=sorted(names.get(w, ('?', '?'))[1] for w in workers.get(order['id'], ())),
                         step_taken=taken))
    count = lambda test: sum(1 for job in jobs if test(job))
    roles = {}
    for job in jobs:
        for role in job['worker_roles']:
            roles[role] = roles.get(role, 0) + 1
    summary = dict(posted=len(jobs), worked=count(lambda j: j['delivered'] > 0),
                   completed=count(lambda j: j['status'] == 'completed'),
                   expired=count(lambda j: j['status'] == 'expired'), open=count(lambda j: j['status'] == 'open'),
                   step_taken=count(lambda j: j['step_taken'] is not None),
                   employers=len({j['employer'] for j in jobs}), worker_roles=roles,
                   steps={s: count(lambda j, s=s: j['step'] == s) for s in sorted({j['step'] for j in jobs})})
    return dict(jobs=jobs, summary=summary)


def consequence_record(world):
    """v0.9 Stage 3: needs people heard of and answered, and what came of each answer.

    Every offer, gathering or purchase in another town a person made for someone
    else's need, from the recorded actions: who answered whose need, by which
    route, and whether the person it was for took the goods up, someone else
    bought them, or the offer lapsed untaken; for goods fetched from another town,
    whether they arrived and whether the same person then supplied the need. For
    needs supplied: whether the buyer went on to take the step the goods were for.
    And how far word of the needs and of the supplies spread.
    """
    names = {}
    for snapshot in getattr(world, 'snapshots', ()):
        names.update({a['id']: a['name'] for a in snapshot.get('agents', [])})
    names.update({a.id: a.name for a in world.agents})
    lapsed = {e['lapsed'] for e in world.events if e.get('lapsed') is not None}
    accepts, steps, answers = {}, {}, []
    for entry in world.action_log:
        action, result = entry['action'], entry['result']
        if not result.get('success'):
            continue
        params, effects, kind = action.get('params', {}), result.get('effects', {}), action.get('type')
        purpose = params.get('purpose') or {}
        if kind in ('offer', 'gather', 'procure') and purpose.get('kind') == 'need':
            answers.append(dict(tick=entry['tick'], route=kind, by=names.get(action.get('actor'), '?'),
                                actor=action.get('actor'), to=names.get(purpose['subject'], '?'),
                                subject=purpose['subject'], step=purpose['step'],
                                resource=params.get('resource'), units=params.get('amount'),
                                unit_price=params.get('unit_price', effects.get('unit_price')),
                                offer=effects.get('offer_id'), journey=effects.get('journey_id'),
                                source=params.get('source')))
        elif kind == 'accept':
            accepts.setdefault(params.get('offer_id'), []).append((entry['tick'], effects))
        for step, (act, field, value) in STEP_ACTIONS.items():
            if kind == act and params.get(field) == value:
                steps.setdefault((action.get('actor'), step), []).append(entry['tick'])
    for answer in answers:
        if answer['route'] != 'offer':
            continue
        taken = accepts.get(answer['offer'], [])
        mine = [(tick, e) for tick, e in taken if e.get('buyer') == answer['subject']]
        answer.update(supplied=sum(e['amount'] for _, e in mine), sold_to_others=sum(
            e['amount'] for _, e in taken if e.get('buyer') != answer['subject']))
        answer['outcome'] = ('supplied' if mine else 'sold to others' if taken else
                             'lapsed' if answer['offer'] in lapsed else 'open')
        supplied = min((tick for tick, _ in mine), default=None)
        answer['step_taken'] = next((t for t in steps.get((answer['subject'], answer['step']), [])
                                     if supplied is not None and t > supplied), None)
    journeys = {j['id']: j for j in getattr(world, 'journeys', ())}
    for answer in answers:
        if answer['route'] != 'procure':
            continue
        journey = journeys.get(answer['journey'], {})
        answer['arrival'] = {'delivered': 'arrived', 'failed': 'lost'}.get(journey.get('status'), 'on the road')
        answer['cost'] = journey.get('cost')
        # Whether the same person then met the need with goods offered for it.
        later = [a for a in answers if a['route'] == 'offer' and a['actor'] == answer['actor']
                 and a['subject'] == answer['subject'] and a['resource'] == answer['resource'] and a['tick'] > answer['tick']]
        answer['supplied'] = sum(a.get('supplied', 0) for a in later)
        answer['outcome'] = ('lost' if answer['arrival'] == 'lost' else 'supplied' if answer['supplied']
                             else answer['arrival'])
    offers = [a for a in answers if a['route'] == 'offer']
    fetched = [a for a in answers if a['route'] == 'procure']
    knowledge = getattr(world, 'knowledge', {})
    told = [(holder, c) for holder, store in knowledge.items() for c in store]
    count = lambda test: sum(1 for a in offers if test(a))
    summary = dict(
        answers=len(answers), offers=len(offers), gathered=sum(a['route'] == 'gather' for a in answers),
        fetched=len(fetched), fetched_arrived=sum(a['arrival'] == 'arrived' for a in fetched),
        fetched_lost=sum(a['arrival'] == 'lost' for a in fetched),
        fetched_supplied=sum(a['outcome'] == 'supplied' for a in fetched),
        answerers=len({a['by'] for a in answers}), answered=len({(a['subject'], a['step']) for a in answers}),
        supplied=count(lambda a: a['outcome'] == 'supplied'), units_supplied=sum(a.get('supplied', 0) for a in offers),
        sold_to_others=count(lambda a: a['outcome'] == 'sold to others'),
        lapsed=count(lambda a: a['outcome'] == 'lapsed'), open=count(lambda a: a['outcome'] == 'open'),
        step_taken=count(lambda a: a.get('step_taken') is not None),
        needs_heard=sum(1 for holder, c in told if c['kind'] == 'need' and c['subject'] != holder
                        and not c['facts'].get('gone')),
        corrections_heard=sum(1 for _, c in told if c['kind'] == 'need' and c['facts'].get('gone')),
        supplies_heard=sum(1 for holder, c in told if c['kind'] == 'conduct' and c['facts'].get('act') == 'supplied'
                           and holder not in (c['subject'], c['facts'].get('buyer'))))
    return dict(answers=answers, summary=summary)


def social_outcomes(world):
    """Stage 4: inequality, fairness and organization among the named people now."""
    region = inequality_snapshot(world)['region']
    minds = getattr(world, 'minds', {})
    cooperative = {m for i in world.institutions if i.active and getattr(i, 'purpose', '') == 'cooperative'
                   for m in i.members}
    return dict(wealth_gini=region['wealth_gini'], income_gini=region['income_gini'],
                poverty_share=region['poverty_share'], food_insecure_share=region['food_insecure_share'],
                mean_fairness=round(sum(m.get('fairness', .5) for m in minds.values()) / max(1, len(minds)), 4),
                cooperative_share=round(len(cooperative) / max(1, len(world.agents)), 4),
                levies_paid=round(sum(e.get('amount', 0.) for e in world.events if e.get('kind') == 'levy'), 4))


def summarize(world, *, hunger_cycles=0, person_cycles=0):
    # A human player sets their own aims, so goal statistics cover autonomous people.
    outcomes = [goal_outcome(actor) for actor in world.agents if actor.id not in getattr(world, 'players', ())]
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
                adaptive_goals=getattr(world, 'adaptive_goals', False), **goal_history(world),
                **social_outcomes(world),
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
                      'food_imported_by_highfen', 'goal_completions', 'goal_revisions', 'goals_abandoned',
                      'wealth_gini', 'mean_fairness', 'cooperative_share', 'levies_paid')
            groups.append(dict(scenario=scenario, policy_style=style, runs=len(selected),
                               means={key: sum(s[key] for s in selected) / len(selected) for key in fields},
                               ranges={key: [min(s[key] for s in selected), max(s[key] for s in selected)]
                                       for key in fields}))
    return dict(schema='eternia.evaluation.v0.7.4', years=years, seeds=seeds,
                scenarios=scenarios, policy_styles=styles, cases=cases, groups=groups,
                definitions=dict(
                    goals_completed='Final living agents meeting their current goal now; not lifetime or population-wide success.',
                    goal_completions='Goals reached during the run, counted when first reached, including goals later replaced. '
                                     'A goal an heir inherits already met is not counted.',
                    goal_revisions='Goal changes: escalations to a larger goal of the same kind plus switches to another kind.',
                    goals_abandoned='Goals replaced before they were reached.',
                    wealth_gini='Gini coefficient of named people\'s wealth (coins, goods at home buying prices and '
                                'structures at material cost) at the end; 0 is equal, 0.94 is one person holding all.',
                    mean_fairness='Average of each person\'s belief that the local economy treats them fairly '
                                  '(0.5 neutral), built only from their own experiences.',
                    cooperative_share='Share of named people belonging to a cooperative at the end.',
                    levies_paid='Coins paid in organization levies over the run; council levies go to the town treasury.',
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

