import argparse
import json
from pathlib import Path
from eternia.simulation import World
from eternia.report import make_html


def main():
    parser = argparse.ArgumentParser(description='Eternia headless world simulator')
    parser.add_argument('--years', type=int, default=None,
                        help='Simulated years (default: 100 for experiments, 1000 for society)')
    parser.add_argument('--seed', type=int, default=42, help='Reproducible world seed')
    parser.add_argument('--output', default=None,
                        help='Output folder (default depends on the selected experiment)')
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--npc-demo', action='store_true', help='Run the isolated Edrin action/goal experiment')
    modes.add_argument('--community', action='store_true', help='Run the five-person v0.3 community experiment')
    modes.add_argument('--institutions', action='store_true', help='Run the v0.4 institutional community experiment')
    modes.add_argument('--civilizations', action='store_true', help='Run the v0.5 interconnected-settlement experiment')
    parser.add_argument('--turns', type=int, default=40, help='NPC demo turns, from 1 to 200')
    parser.add_argument('--shock-turn', type=int, default=None,
                        help='NPC demo mine closure turn (default: 8, or disabled for shorter runs); 0 disables it')
    parser.add_argument('--ticks-per-year', type=int, choices=range(1, 13), default=4,
                        help='Community decision cycles per year (default: 4)')
    parser.add_argument('--shock-year', type=int, default=None,
                        help='Resource disruption year (default: 0 for civilizations, 8 for other experiments); 0 disables it')
    args = parser.parse_args()
    years = args.years if args.years is not None else (100 if args.community or args.institutions or args.civilizations else 1000)
    if years < 0 or years > 10000:
        parser.error('--years must be between 0 and 10000')
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
    elif args.community or args.institutions or args.civilizations:
        shock_year = args.shock_year if args.shock_year is not None else (0 if args.civilizations else 8)
        if shock_year < 0:
            parser.error('--shock-year must be nonnegative')
        if args.civilizations:
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
    default_output = ('output/civilizations' if args.civilizations else
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
    elif args.community or args.institutions or args.civilizations:
        metrics = data['snapshots'][-1].get('metrics', {})
        generation = max((a.generation for a in w.agents), default=0)
        print(f'Year {w.year}: {len(w.agents)} living community members; '
              f'{metrics.get("trades", 0)} peer trades; '
              f'{metrics.get("conflicts", 0)} conflicts; '
              f'{metrics.get("knowledge_transfers", 0)} knowledge transfers; '
              f'generation {generation}.')
        if args.institutions or args.civilizations:
            print(f'Institutions: {metrics.get("institutions_formed", 0)} formed; '
                  f'{metrics.get("proposals_passed", 0)} decisions enacted; '
                  f'{metrics.get("institutions_collapsed", 0)} collapsed.')
        if args.civilizations:
            regional = data.get('regional_metrics', {})
            print(f'Region: {len(w.settlements)} settlements; '
                  f'{metrics.get("negotiation_successes", 0)} agreements; '
                  f'{metrics.get("trade_shipments", 0)} inter-settlement shipments; '
                  f'{metrics.get("regional_migrations", 0)} migrations; '
                  f'{len(regional.get("isolated_settlements", []))} currently isolated settlements.')
    else:
        print(f'Year {w.year}: {sum(s.population for s in w.settlements):,} inhabitants across '
              f'{len(w.settlements)} settlements; {len(w.events)} events; '
              f'{sum(s.knowledge == 2 for s in w.settlements)} settlements know an Aether technique.')
    print('Open:', (output / 'report.html').resolve())


if __name__ == '__main__':
    main()
