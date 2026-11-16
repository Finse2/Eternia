"""Matched initial conditions for observing a regional labor market.

Every case keeps all eighteen agents, their goals and the default society
policy. In every case Highfen's resident miner lacks mining knowledge, as when
a successor does not inherit the skill, and every town starts with a council of
its residents. Cases differ only in which funded jobs exist at the start and
whether the roads into Highfen are passable. No later action is injected:
whether anyone travels, who arrives first and who gets paid are outcomes.
"""
from copy import deepcopy
import math

from .society import ORDER_TICKS, SocietyWorld, WORK_SKILLS

HIGHFEN = 1
LABOR_SCENARIOS = {
    'paid_opportunity': 'Highfen posts a funded 16-unit iron job at 2 coins per unit that no resident can work.',
    'low_wage': 'The same Highfen job pays 0.5 coins per unit: too little to cover travel and leaving home.',
    'local_work': 'The same Highfen job, but both other towns also post funded 15- to 16-unit iron jobs at home.',
    'blocked_route': 'The same Highfen job, but both roads into Highfen start impassable.',
}


def remove_resident_skill(world, town=HIGHFEN, skill='mining'):
    """Knowledge, not resources: resident holders of ``skill`` lose it. Returns their IDs."""
    affected = [a.id for a in world.agents if a.home == town and skill in a.skills]
    for actor in world.agents:
        if actor.id in affected:
            actor.skills.remove(skill)
    return affected


def _resident_council(world, town):
    from .regional_engine import RegionalInstitution
    members = {a.id for a in world.agents if a.home == town.id}
    council = RegionalInstitution(world.next_institution_id, town.name + ' Municipal Council', town.id,
                                  members=members, purpose='council')
    world.next_institution_id += 1
    world.institutions.append(council)
    return council


def _posted_job(world, town, council, resource, quantity, wage):
    """A municipal order posted two cycles before observation; escrow leaves the treasury."""
    budget = quantity * wage
    town.treasury -= budget
    order = world.open_work_order(town, {'kind': 'municipal', 'id': town.id},
                                  {'resource': resource, 'quantity': quantity, 'unit_wage': wage},
                                  budget, institution=council.id)
    order.update(created=-2, expires=-2 + ORDER_TICKS)
    return order


def build_labor_scenario(name, seed=42, policy_style='balanced'):
    if name not in LABOR_SCENARIOS:
        raise ValueError(f'Unknown labor scenario: {name!r}')
    world = SocietyWorld(seed=seed, policy_style=policy_style)
    before = world.resource_totals()
    unskilled = remove_resident_skill(world)
    councils = {town.id: _resident_council(world, town) for town in world.settlements}
    highfen = world.settlements[HIGHFEN]
    jobs = [_posted_job(world, highfen, councils[HIGHFEN], 'iron', 16, .5 if name == 'low_wage' else 2.)]
    transfers = []
    if name == 'local_work':
        for town in world.settlements:
            if town.id == HIGHFEN:
                continue
            # Stored iron becomes accessible: a transfer, not new material.
            moved = town.iron
            town.deposits['iron'] += moved
            town.iron = 0.
            transfers.append({'settlement': town.id, 'stored_to_accessible_iron': moved})
            quantity = min(16, math.floor(town.deposits['iron']))
            jobs.append(_posted_job(world, town, councils[town.id], 'iron', quantity, 2.))
    roads = []
    if name == 'blocked_route':
        for link in world.links:
            if HIGHFEN in (link['a'], link['b']):
                roads.append({'link': link['id'], 'before': link['condition'], 'after': 0.})
                link['condition'] = 0.
    after = world.resource_totals()
    if any(not math.isclose(before[r], after[r], abs_tol=1e-7) for r in before):
        raise AssertionError('Labor scenario setup changed resource totals')
    world.scenario = 'labor:' + name
    world.provenance['scenario'] = world.scenario
    world._event('experiment', LABOR_SCENARIOS[name], highfen.name, scenario=name)
    world.snapshots = []
    world._snapshot()
    world._assert_invariants()
    miners = [a.id for a in world.agents if 'mining' in a.skills]
    metadata = dict(
        scenario=name, description=LABOR_SCENARIOS[name], seed=seed, policy_style=policy_style,
        destination=HIGHFEN, skilled_workers=miners, residents_without_skill=unskilled,
        initial_jobs=deepcopy(jobs), councils={t: c.id for t, c in councils.items()},
        initial_totals=dict(after),
        controlled_changes=dict(
            knowledge=f'Highfen resident(s) {unskilled} start without mining knowledge.',
            institutions='Each town starts with one council of all its named residents.',
            jobs='Funded municipal jobs were posted two cycles earlier; their escrow left the town treasury.',
            iron_transfers=transfers, road_conditions=roads),
        limitations=[
            'The starting job is an initial condition; the experiment tests decisions and consequences, not job creation.',
            'All agents keep their goals and the default policy; journeys, competition and repairs remain uncontrolled.',
            'Expected-value estimates use public notices and routes; they are programmed heuristics, not foresight.',
            'One seed is one history. Compare several seeds before generalizing.'])
    return world, metadata


def labor_migrations(world):
    """Arrivals followed by paid work in the destination before the person left again."""
    found = []
    journeys = sorted((j for j in world.journeys if j['kind'] == 'migrant'), key=lambda j: j['created'])
    for journey in journeys:
        if journey['status'] != 'delivered':
            continue
        later = [j['created'] for j in journeys if j['actor'] == journey['actor'] and j['created'] > journey['arrived']]
        until = min(later, default=math.inf)
        paid = [r for r in world.work_history if r['actor'] == journey['actor'] and r['mode'] == 'paid'
                and r['settlement'] == journey['destination'] and journey['arrived'] <= r['tick'] < until]
        found.append(dict(actor=journey['actor'], origin=journey['origin'], destination=journey['destination'],
                          departed=journey['created'], arrived=journey['arrived'], paid_actions=len(paid),
                          wages=sum(r['coins'] for r in paid),
                          first_paid_tick=min((r['tick'] for r in paid), default=None)))
    return found


def _labor_case(world, metadata):
    miners = metadata['skilled_workers']
    living = {a.id: a for a in world.agents}
    jobs = {job['id'] for job in metadata['initial_jobs'] if job['settlement'] == HIGHFEN}
    delivered = [r for r in world.work_history if r['mode'] == 'paid' and r.get('order') in jobs]
    decisions = [deepcopy(d) for d in world.decisions if d['actor'] in miners]
    moves = labor_migrations(world)
    workers = []
    for identity in miners:
        person = living.get(identity)
        own = [d for d in decisions if d['actor'] == identity]
        workers.append(dict(
            actor=identity, name=person.name if person else None,
            initial_home=next(a['home'] for a in world.snapshots[0]['agents'] if a['id'] == identity),
            final_home=person.home if person else None,
            provisioning_actions=sum('journey provisions' in d['rationale'] for d in own),
            job_migrations_proposed=sum(d['proposal']['type'] == 'migrate' and 'paid work' in d['rationale'] for d in own),
            departures=sum(j['kind'] == 'migrant' and j['actor'] == identity for j in world.journeys),
            wages_earned=world.earnings.get(identity, 0.),
            final_coins=person.inventory['coins'] if person else None))
    order = next(o for o in world.work_orders if o['id'] in jobs)
    summary = dict(
        scenario=metadata['scenario'], seed=metadata['seed'], policy_style=metadata['policy_style'],
        departures=sum(j['kind'] == 'migrant' for j in world.journeys),
        arrivals=sum(j['kind'] == 'migrant' and j['status'] == 'delivered' for j in world.journeys),
        labor_migrations=sum(m['paid_actions'] > 0 for m in moves),
        wages_after_migration=sum(m['wages'] for m in moves),
        highfen_job_units_delivered=sum(r['amount'] for r in delivered),
        highfen_job_workers=sorted({r['actor'] for r in delivered}),
        highfen_job_status=order['status'], workers=workers)
    evidence = dict(migrations=moves, highfen_job_work=deepcopy(delivered),
                    journeys=[deepcopy(j) for j in world.journeys if j['kind'] == 'migrant'],
                    decisions=decisions)
    return dict(name=metadata['scenario'], description=metadata['description'], metadata=metadata,
                summary=summary, evidence=evidence, history=world.export())


def run_labor_experiments(seed=42, years=3, policy_style='balanced'):
    """Run matched worlds through ordinary ``step`` cycles; every outcome is reported."""
    if type(years) is not int or not 0 <= years <= 100:
        raise ValueError('years must be an integer from 0 to 100')
    cases = []
    for name in LABOR_SCENARIOS:
        world, metadata = build_labor_scenario(name, seed, policy_style)
        world.run(years)
        cases.append(_labor_case(world, metadata))
    return {'schema': 'eternia.labor_experiment.v1', 'seed': seed, 'years': years,
            'policy_style': policy_style, 'ticks_per_year': 4,
            'note': 'Matched initial conditions with eighteen autonomous agents per case. Travel for work '
                    'is observed, never injected; outcomes are specific to these conditions and this seed.',
            'skills': dict(WORK_SKILLS), 'cases': cases}
