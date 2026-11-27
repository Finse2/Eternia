"""v0.9 Stage 4: what becomes of needs, and should a stalled goal raise what people will pay?

The same seeded societies run twice for the same number of years, nobody
playing: once with every person's willingness to pay fixed at a fair price
(1.5 times the base), and once letting it rise while their goal stays blocked,
a tenth of the fair price for each cycle without progress, up to twice it
(``needs.willingness``). Everything else is the same.

Each run reports, from the world's own records:

- what stood between people and the goods their goals lacked, cycle by cycle:
  the market had them but above what they would pay, had none, or a neighbor
  held some to spare (``SocietyWorld._record_needs``);
- what became of every need, from the cycle it arose to the cycle it ended;
- every judgment people made about needs they heard of, and every answer
  (``evaluation.consequence_record``), with the jobs posted for goals
  (``evaluation.opportunity_record``);
- what it cost: goals reached, houses and experiments, hunger, coins, inequality
  and posted prices.
"""
from .evaluation import consequence_record, goal_history, opportunity_record, social_outcomes
from .market import GOODS
from .society import SocietyWorld

POLICY_STYLES = ('balanced', 'personal', 'collective')


def _blockers(world):
    rows = world.opportunity_log
    cycles = sum(r['needs'] for r in rows)
    share = lambda key: round(sum(r[key] for r in rows) / cycles, 4) if cycles else 0.
    judgments = {}
    for row in rows:
        for key, count in row['judgments'].items():
            judgments[key] = judgments.get(key, 0) + count
    ratio = sum(r['price_ratio'] * r['needs'] for r in rows) / cycles if cycles else 0.
    return dict(need_cycles=cycles, priced_out=share('priced_out'), unaffordable=share('unaffordable'),
                empty_market=share('empty_market'), held_nearby=share('held_nearby'),
                mean_price_ratio=round(ratio, 4), judgments=dict(sorted(judgments.items(), key=lambda kv: -kv[1])))


def _episodes(world):
    closed = list(world.need_episodes)
    still = [dict(episode, ended=None, outcome='still open', answered=False)
             for episode in world._open_needs.values()]
    every = closed + still
    outcomes = {}
    for episode in every:
        outcomes[episode['outcome']] = outcomes.get(episode['outcome'], 0) + 1
    lengths = sorted(e['cycles'] for e in closed)
    return dict(needs=len(every), outcomes=dict(sorted(outcomes.items(), key=lambda kv: -kv[1])),
                answered=sum(e['answered'] for e in every),
                mean_cycles=round(sum(lengths) / len(lengths), 2) if lengths else 0.,
                median_cycles=lengths[len(lengths) // 2] if lengths else 0,
                longest=max((e['cycles'] for e in every), default=0),
                by_resource={r: sum(e['resource'] == r for e in every) for r in GOODS},
                max_willing=max((e['max_willing'] for e in every), default=0.))


def run_opportunity_case(seed=42, years=25, rising=False, policy_style='balanced'):
    world = SocietyWorld(seed=seed, policy_style=policy_style, rising_willingness=rising)
    hungry = cycles = 0
    for _ in range(years * world.ticks_per_year):
        world.step()
        cycles += len(world.agents)
        hungry += sum(a.hunger >= 65 for a in world.agents)
    structures = {kind: sum(a.structures.get(kind, 0) for a in world.agents) for kind in ('house', 'workshop')}
    research = sum(1 for r in world.action_log if r['result'].get('success') and r['action'].get('type') == 'research')
    prices = {good: round(sum(world.market_prices[t.id][good] for t in world.settlements) / len(world.settlements), 2)
              for good in GOODS}
    answers = consequence_record(world)['summary']
    jobs = opportunity_record(world)['summary']
    return dict(seed=seed, years=years, policy_style=policy_style, rising_willingness=rising,
                blockers=_blockers(world), needs=_episodes(world),
                answers={k: answers[k] for k in ('answers', 'offers', 'gathered', 'gathered_then_offered', 'fetched', 'supplied',
                                                 'units_supplied', 'lapsed', 'step_taken')},
                jobs={k: jobs[k] for k in ('posted', 'worked', 'completed', 'step_taken')},
                goals=goal_history(world), houses=structures['house'], research_actions=research,
                hunger_rate=round(hungry / max(1, cycles), 4),
                mean_coins=round(sum(a.inventory['coins'] for a in world.agents) / max(1, len(world.agents)), 2),
                social=social_outcomes(world), mean_posted_prices=prices,
                starvation_deaths=sum(1 for e in world.events if e.get('kind') == 'death'
                                      and 'deprivation' in e.get('message', '')))


def run_opportunity_experiments(seeds=(18, 42, 73), years=25, policy_style='balanced'):
    seeds = list(seeds)
    if (not seeds or len(seeds) > 20 or any(type(seed) is not int for seed in seeds)
            or len(set(seeds)) != len(seeds)):
        raise ValueError('Use one to twenty distinct integer seeds')
    if type(years) is not int or not 1 <= years <= 100:
        raise ValueError('Opportunity experiment years must be between 1 and 100')
    if policy_style not in POLICY_STYLES:
        raise ValueError('Unknown policy style')
    cases = [run_opportunity_case(seed, years, rising, policy_style) for seed in seeds for rising in (False, True)]
    return {'schema': 'eternia.opportunity_experiment.v1', 'seeds': seeds, 'years': years,
            'policy_style': policy_style,
            'note': ('Matched societies nobody plays, with willingness to pay fixed at a fair price or rising '
                     'while a goal stays blocked; all else equal.'),
            'cases': cases}
