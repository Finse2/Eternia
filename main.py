import argparse
import json
from pathlib import Path
from eternia.simulation import World
from eternia.report import make_html


def run_labor_experiment(args, parser):
    from eternia.labor_experiments import run_labor_experiments
    from eternia.report import make_labor_experiment_html
    if args.save or args.resume:
        parser.error('--save needs a single world run; the labor experiment compares several worlds')
    if args.ticks_per_year not in (None, 4) or args.shock_year not in (None, 0):
        parser.error('Labor scenarios use four ticks per year and no scheduled shock')
    try:
        data = run_labor_experiments(seed=args.seed if args.seed is not None else 42,
                                     years=args.years if args.years is not None else 3,
                                     policy_style=args.policy_style or 'balanced')
    except ValueError as error:
        parser.error(str(error))
    output = Path(args.output or 'output/labor-experiment')
    output.mkdir(parents=True, exist_ok=True)
    for case in data['cases']:
        folder = output / case['name']
        folder.mkdir(parents=True, exist_ok=True)
        (folder / 'history.json').write_text(json.dumps(case['history'], indent=2, allow_nan=False), encoding='utf-8')
        (folder / 'report.html').write_text(make_html(case['history']), encoding='utf-8')
        summary = case['summary']
        print(f'{case["name"]}: {summary["labor_migrations"]} moves followed by paid work; '
              f'{summary["wages_after_migration"]:g} coins earned after moving; Highfen job {summary["highfen_job_status"]}.')
    compact = {**data, 'cases': [{k: v for k, v in case.items() if k != 'history'} for case in data['cases']]}
    (output / 'summary.json').write_text(json.dumps(compact, indent=2, allow_nan=False), encoding='utf-8')
    (output / 'report.html').write_text(make_labor_experiment_html(compact), encoding='utf-8')
    print('Open:', (output / 'report.html').resolve())


def run_v07(args, parser):
    from eternia.persistence import load_world, save_world
    if args.labor_experiment:
        return run_labor_experiment(args, parser)
    if args.evaluate_society:
        from eternia.evaluation import evaluate_society
        from eternia.report import make_evaluation_html
        if args.save:
            parser.error('--save requires a world run, not an evaluation matrix')
        try:
            seeds = [int(seed.strip()) for seed in args.evaluation_seeds.split(',')]
            data = evaluate_society(seeds=seeds, years=args.years if args.years is not None else 5,
                                    **({'styles': [args.policy_style]} if args.policy_style else {}))
        except ValueError as error:
            parser.error(str(error))
        output = Path(args.output or 'output/society-evaluation')
        output.mkdir(parents=True, exist_ok=True)
        (output / 'evaluation.json').write_text(json.dumps(data, indent=2, allow_nan=False), encoding='utf-8')
        (output / 'report.html').write_text(make_evaluation_html(data), encoding='utf-8')
        print(f'Evaluation: {len(data["cases"])} runs across {len(data["seeds"])} seeds; outcomes include unmet goals.')
    else:
        years = args.years if args.years is not None else (0 if args.resume else 10)
        if not 0 <= years <= 10000:
            parser.error('--years must be between 0 and 10000')
        try:
            if args.resume:
                if any(value is not None for value in (args.seed, args.ticks_per_year, args.shock_year, args.policy_style)):
                    parser.error('Resume restores seed, clock, shock and policy; do not override them')
                world = load_world(args.resume)
            else:
                from eternia.society import SocietyWorld
                world = SocietyWorld(seed=args.seed if args.seed is not None else 42,
                                     ticks_per_year=args.ticks_per_year or 4,
                                     shock_year=args.shock_year or 0,
                                     policy_style=args.policy_style or 'balanced')
            world.run(years)
        except (ValueError, OSError) as error:
            parser.error(str(error))
        output = Path(args.output or ('output/society-resumed' if args.resume else 'output/society'))
        output.mkdir(parents=True, exist_ok=True)
        data = world.export()
        (output / 'history.json').write_text(json.dumps(data, indent=2, allow_nan=False), encoding='utf-8')
        (output / 'report.html').write_text(make_html(data), encoding='utf-8')
        try:
            saved = save_world(world, args.save or output / 'world.save.json')
        except (ValueError, OSError) as error:
            parser.error(str(error))
        economy = data.get('economic_metrics', {})
        print(f'Year {world.year}: {economy.get("wages_paid", 0):g} coins paid in wages; '
              f'{economy.get("volunteer_actions", 0)} voluntary actions. Checkpoint: {saved}')
    print('Open:', (output / 'report.html').resolve())


def main():
    parser = argparse.ArgumentParser(description='Eternia headless world simulator')
    parser.add_argument('--years', type=int, default=None,
                        help='Simulated years (default: 3 for migration scenarios, 100 for other experiments, 1000 for society)')
    parser.add_argument('--seed', type=int, default=None, help='Reproducible world seed (default: 42)')
    parser.add_argument('--output', default=None,
                        help='Output folder (default depends on the selected experiment)')
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--npc-demo', action='store_true', help='Run the isolated Edrin action/goal experiment')
    modes.add_argument('--community', action='store_true', help='Run the five-person v0.3 community experiment')
    modes.add_argument('--institutions', action='store_true', help='Run the v0.4 institutional community experiment')
    modes.add_argument('--civilizations', action='store_true', help='Run the v0.5 interconnected-settlement experiment')
    modes.add_argument('--physical-world', action='store_true', help='Run the v0.6 geography and logistics experiment')
    modes.add_argument('--society', '--autonomous-society', action='store_true',
                       help='Run v0.7 The Living Economy society (default: 10 years)')
    modes.add_argument('--evaluate-society', action='store_true',
                       help='Compare v0.7 seeds, scenarios and policy priorities (default: 5 years)')
    modes.add_argument('--labor-experiment', action='store_true',
                       help='Compare matched v0.7 labor-market scenarios: will someone travel for paid work? (default: 3 years)')
    modes.add_argument('--resume', metavar='CHECKPOINT', help='Resume an exact-version checkpoint; --years adds years')
    parser.add_argument('--save', metavar='CHECKPOINT', help='Write a resumable checkpoint (v0.7 saves by default)')
    parser.add_argument('--policy-style', choices=('balanced', 'personal', 'collective'), default=None,
                        help='v0.7 programmed priorities; an evaluation defaults to all three')
    parser.add_argument('--evaluation-seeds', default='18,42,73', help='Comma-separated evaluation seeds')
    modes.add_argument('--migration-experiment', action='store_true',
                       help='Compare controlled v0.6.1 migration scenarios using the autonomous planner')
    parser.add_argument('--turns', type=int, default=40, help='NPC demo turns, from 1 to 200')
    parser.add_argument('--shock-turn', type=int, default=None,
                        help='NPC demo mine closure turn (default: 8, or disabled for shorter runs); 0 disables it')
    parser.add_argument('--ticks-per-year', type=int, choices=range(1, 13), default=None,
                        help='Community decision cycles per year (default: 4)')
    parser.add_argument('--shock-year', type=int, default=None,
                        help='Resource disruption year (default: 0 for civilizations/physical world, 8 for other experiments); 0 disables it')
    args = parser.parse_args()
    if args.society or args.evaluate_society or args.resume or args.labor_experiment:
        run_v07(args, parser)
        return
    if args.policy_style is not None:
        parser.error('--policy-style requires --society, --evaluate-society or --labor-experiment')
    args.seed = args.seed if args.seed is not None else 42
    args.ticks_per_year = args.ticks_per_year or 4
    years = args.years if args.years is not None else (3 if args.migration_experiment else
            100 if args.community or args.institutions or args.civilizations or args.physical_world else 1000)
    if years < 0 or years > 10000:
        parser.error('--years must be between 0 and 10000')
    if args.migration_experiment:
        if args.save:
            parser.error('--save needs a single world mode; migration-experiment compares several worlds')
        if args.ticks_per_year != 4 or args.shock_year not in (None, 0):
            parser.error('Migration scenarios use four ticks per year and no scheduled shock')
        from eternia.experiments import run_migration_experiments
        from eternia.report import make_migration_experiment_html
        data = run_migration_experiments(seed=args.seed, years=years)
        output = Path(args.output or 'output/migration-experiment')
        output.mkdir(parents=True, exist_ok=True)
        for case in data['cases']:
            folder = output / case['name']
            folder.mkdir(parents=True, exist_ok=True)
            (folder / 'history.json').write_text(json.dumps(case['history'], indent=2, allow_nan=False), encoding='utf-8')
            (folder / 'report.html').write_text(make_html(case['history']), encoding='utf-8')
            summary = case['summary']
            print(f'{case["name"]}: first choice {summary["first_action"]}; '
                  f'{summary["departures"]} departures, {summary["arrivals"]} arrivals; '
                  f'{summary["post_arrival_work"]} mining actions after arrival.')
        compact = {**data, 'cases': [{k: v for k, v in case.items() if k != 'history'} for case in data['cases']]}
        (output / 'summary.json').write_text(json.dumps(compact, indent=2, allow_nan=False), encoding='utf-8')
        (output / 'report.html').write_text(make_migration_experiment_html(compact), encoding='utf-8')
        print('Open:', (output / 'report.html').resolve())
        return
    if args.npc_demo:
        if not 1 <= args.turns <= 200:
            parser.error('--turns must be between 1 and 200')
        shock_turn = args.shock_turn
        if shock_turn is None:
            shock_turn = 8 if args.turns >= 8 else 0
        if not 0 <= shock_turn <= args.turns:
            parser.error('--shock-turn must be between 0 and --turns')
        from eternia.autonomy import run_demo
        w = run_demo(seed=args.seed, turns=args.turns, shock_turn=shock_turn)
    elif args.community or args.institutions or args.civilizations or args.physical_world:
        shock_year = args.shock_year if args.shock_year is not None else (0 if args.civilizations or args.physical_world else 8)
        if shock_year < 0:
            parser.error('--shock-year must be nonnegative')
        if args.physical_world:
            from eternia.physical_world import PhysicalWorld
            world_type = PhysicalWorld
        elif args.civilizations:
            from eternia.civilizations import CivilizationWorld
            world_type = CivilizationWorld
        elif args.institutions:
            from eternia.institutional_world import InstitutionalWorld
            world_type = InstitutionalWorld
        else:
            from eternia.community import CommunityWorld
            world_type = CommunityWorld
        w = world_type(seed=args.seed, ticks_per_year=args.ticks_per_year,
                       shock_year=shock_year).run(years)
    else:
        w = World(seed=args.seed).run(years)
    data = w.export()
    if args.save:
        from eternia.persistence import save_world
        try:
            save_world(w, args.save)
        except (ValueError, OSError) as error:
            parser.error(str(error))
    default_output = ('output/physical-world' if args.physical_world else
                      'output/civilizations' if args.civilizations else
                      'output/institutions' if args.institutions else
                      'output/community' if args.community else
                      'output/autonomy' if args.npc_demo else 'output')
    output = Path(args.output or default_output)
    output.mkdir(parents=True, exist_ok=True)
    (output / 'history.json').write_text(json.dumps(data, indent=2, allow_nan=False), encoding='utf-8')
    (output / 'report.html').write_text(make_html(data), encoding='utf-8')
    if args.npc_demo:
        a = w.agents[0]
        print(f'Turn {w.year}: {a.name} owns {a.structures.get("house", 0)} house(s), '
              f'{a.inventory["coins"]:g}/{a.wealth_goal:g} coins; '
              f'{sum(entry["result"]["success"] for entry in w.action_log)} accepted actions.')
    elif args.community or args.institutions or args.civilizations or args.physical_world:
        metrics = data['snapshots'][-1].get('metrics', {})
        generation = max((a.generation for a in w.agents), default=0)
        print(f'Year {w.year}: {len(w.agents)} living community members; '
              f'{metrics.get("trades", 0)} peer trades; '
              f'{metrics.get("conflicts", 0)} conflicts; '
              f'{metrics.get("knowledge_transfers", 0)} knowledge transfers; '
              f'generation {generation}.')
        if args.institutions or args.civilizations or args.physical_world:
            print(f'Institutions: {metrics.get("institutions_formed", 0)} formed; '
                  f'{metrics.get("proposals_passed", 0)} decisions enacted; '
                  f'{metrics.get("institutions_collapsed", 0)} collapsed.')
        if args.civilizations or args.physical_world:
            regional = data.get('regional_metrics', {})
            print(f'Region: {len(w.settlements)} settlements; '
                  f'{metrics.get("negotiation_successes", 0)} agreements; '
                  f'{metrics.get("trade_shipments", 0)} inter-settlement shipments; '
                  f'{metrics.get("regional_migrations", 0)} migrations; '
                  f'{len(regional.get("isolated_settlements", []))} currently isolated settlements.')
        if args.physical_world:
            logistics = data.get('physical_metrics', {})
            print(f'Logistics: {logistics.get("caravans_dispatched", 0)} caravans dispatched; '
                  f'{logistics.get("caravans_delivered", 0)} delivered; '
                  f'{logistics.get("caravans_failed", 0)} failed; '
                  f'{logistics.get("road_repairs", 0)} road repairs; '
                  f'{logistics.get("mines_exhausted", 0)} mines exhausted.')
    else:
        print(f'Year {w.year}: {sum(s.population for s in w.settlements):,} inhabitants across '
              f'{len(w.settlements)} settlements; {len(w.events)} events; '
              f'{sum(s.knowledge == 2 for s in w.settlements)} settlements know an Aether technique.')
    print('Open:', (output / 'report.html').resolve())


if __name__ == '__main__':
    main()
