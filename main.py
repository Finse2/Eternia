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


def run_market_experiment(args, parser):
    from eternia.market_experiments import run_market_experiments
    from eternia.report import make_market_experiment_html
    if args.save or args.resume:
        parser.error('--save needs a single world run; the market experiment compares several worlds')
    if args.ticks_per_year not in (None, 4) or args.shock_year not in (None, 0):
        parser.error('Market scenarios use four ticks per year and no scheduled shock')
    try:
        data = run_market_experiments(seed=args.seed if args.seed is not None else 42,
                                      years=args.years if args.years is not None else 2,
                                      policy_style=args.policy_style or 'balanced')
    except ValueError as error:
        parser.error(str(error))
    output = Path(args.output or 'output/market-experiment')
    output.mkdir(parents=True, exist_ok=True)
    for case in data['cases']:
        folder = output / case['name']
        folder.mkdir(parents=True, exist_ok=True)
        (folder / 'history.json').write_text(json.dumps(case['history'], indent=2, allow_nan=False), encoding='utf-8')
        (folder / 'report.html').write_text(make_html(case['history']), encoding='utf-8')
        summary = case['summary']
        print(f'{case["name"]}: Highfen food {summary["start_highfen_food_price"]:g} -> {summary["final_highfen_food_price"]:g} coins; '
              f'{summary["food_shipments_to_highfen"]} food shipments, {summary["food_delivered_to_highfen"]:g} units delivered; '
              f'{summary["negative_expected_departures"]} shipments left expecting a loss.')
    compact = {**data, 'cases': [{k: v for k, v in case.items() if k != 'history'} for case in data['cases']]}
    (output / 'summary.json').write_text(json.dumps(compact, indent=2, allow_nan=False), encoding='utf-8')
    (output / 'report.html').write_text(make_market_experiment_html(compact), encoding='utf-8')
    print('Open:', (output / 'report.html').resolve())


def run_goal_experiment(args, parser):
    from eternia.goal_experiments import run_goal_experiments
    from eternia.report import make_goal_experiment_html
    if args.save or args.resume:
        parser.error('--save needs a single world run; the goal experiment compares several worlds')
    if args.ticks_per_year not in (None, 4) or args.shock_year not in (None, 0):
        parser.error('Goal scenarios use four ticks per year and no scheduled shock')
    try:
        data = run_goal_experiments(seed=args.seed if args.seed is not None else 42,
                                    years=args.years if args.years is not None else 20,
                                    policy_style=args.policy_style or 'balanced')
    except ValueError as error:
        parser.error(str(error))
    output = Path(args.output or 'output/goal-experiment')
    output.mkdir(parents=True, exist_ok=True)
    for case in data['cases']:
        folder = output / case['name']
        folder.mkdir(parents=True, exist_ok=True)
        (folder / 'history.json').write_text(json.dumps(case['history'], indent=2, allow_nan=False), encoding='utf-8')
        (folder / 'report.html').write_text(make_html(case['history']), encoding='utf-8')
        focal = case['summary']['focal']
        print(f'{case["name"]}: Edrin\'s goals {" -> ".join(focal["goal_path"])}; '
              f'{focal["completions"]} reached, {focal["revisions"]} changes.')
    compact = {**data, 'cases': [{k: v for k, v in case.items() if k != 'history'} for case in data['cases']]}
    (output / 'summary.json').write_text(json.dumps(compact, indent=2, allow_nan=False), encoding='utf-8')
    (output / 'report.html').write_text(make_goal_experiment_html(compact), encoding='utf-8')
    print('Open:', (output / 'report.html').resolve())


def run_inequality_experiment(args, parser):
    from eternia.inequality_experiments import run_inequality_experiments
    from eternia.report import make_inequality_experiment_html
    if args.save or args.resume:
        parser.error('--save needs a single world run; the inequality experiment compares several worlds')
    if args.ticks_per_year not in (None, 4) or args.shock_year not in (None, 0):
        parser.error('Inequality scenarios use four ticks per year and no scheduled shock')
    try:
        data = run_inequality_experiments(seed=args.seed if args.seed is not None else 42,
                                          years=args.years if args.years is not None else 30,
                                          policy_style=args.policy_style or 'balanced')
    except ValueError as error:
        parser.error(str(error))
    output = Path(args.output or 'output/inequality-experiment')
    output.mkdir(parents=True, exist_ok=True)
    for case in data['cases']:
        folder = output / case['name']
        folder.mkdir(parents=True, exist_ok=True)
        (folder / 'history.json').write_text(json.dumps(case['history'], indent=2, allow_nan=False), encoding='utf-8')
        (folder / 'report.html').write_text(make_html(case['history']), encoding='utf-8')
        summary = case['summary']
        print(f'{case["name"]}: wealth Gini {summary["start_gini"]:.2f} -> {summary["end_gini"]:.2f}; '
              f'fairness {summary["late_fairness"]:.2f}; {summary["late_cooperative_share"]:.0%} in cooperatives; '
              f'{summary["migrations"]} migrations.')
    compact = {**data, 'cases': [{k: v for k, v in case.items() if k != 'history'} for case in data['cases']]}
    (output / 'summary.json').write_text(json.dumps(compact, indent=2, allow_nan=False), encoding='utf-8')
    (output / 'report.html').write_text(make_inequality_experiment_html(compact), encoding='utf-8')
    print('Open:', (output / 'report.html').resolve())


PLAY_HELP = ('Type a number to take that choice; add values to change what is in [brackets] '
             '(for example "4 5" takes choice 4 with amount 5, "14 The Free Traders" names an organization). '
             'w waits (w 4 waits a year), t talks to someone (t lists people, t 2 their topics, '
             't 2 5 asks topic 5; talking takes no season), h shows your journal, '
             'm shows the menu again, j {"type": ..., "params": {...}} proposes any action as JSON, '
             's saves and quits, q quits without saving.')


def _say(text=''):
    try:
        print(text)
    except UnicodeEncodeError:  # a console that cannot show a name's accents
        print(text.encode('ascii', 'replace').decode('ascii'))


def _write_play_outputs(session, output):
    session.write_outputs(output)


def _play_session(args, parser, checkpoint):
    """A new or resumed session for --play and --web; ``checkpoint`` is True for a new one."""
    from eternia.playable_session import PlayableSession
    if args.ticks_per_year is not None or args.shock_year is not None or args.fixed_goals:
        parser.error('Play uses the v0.7 society defaults: four cycles a year, no shock, adaptive goals')
    resuming = checkpoint is not True
    if resuming and any(v is not None for v in (args.seed, args.policy_style, args.years)):
        parser.error('A saved world restores its seed, policy and date; do not override them')
    if args.years is not None and not 0 <= args.years <= 200:
        parser.error('--years (autonomous history before the player arrives) must be between 0 and 200')
    try:
        if resuming:
            session = PlayableSession.load(checkpoint)
            if session.player_id is None:
                session.join(args.player_name, args.home)
        else:
            session = PlayableSession.start(args.player_name, args.home,
                                            seed=args.seed if args.seed is not None else 42,
                                            policy_style=args.policy_style or 'balanced',
                                            years=args.years or 0)
    except (ValueError, OSError) as error:
        parser.error(str(error))
    return session


def run_web(args, parser):
    """v0.8 Stage 4: the same session, played in a browser; Python stays the authority."""
    from eternia.web import Game, serve
    if args.save:
        parser.error('--web saves from the browser into the --output folder')
    if not 0 <= args.port <= 65535:
        parser.error('--port must be between 0 and 65535')
    session = _play_session(args, parser, args.web)
    output = Path(args.output or 'output/play')
    slot = None
    if args.web is not True:
        path = Path(args.web)
        if path.name.endswith('.save.json') and path.resolve().parent == output.resolve():
            slot = path.name[:-len('.save.json')]
    serve(Game(session, output, slot=slot), port=args.port, open_browser=not args.no_browser, say=_say)


def run_play(args, parser):
    """v0.8: play one person in the society, one cycle per turn."""
    from eternia.player import customize, hint
    from eternia.player_history import journal_text
    output = Path(args.output or 'output/play')
    save_path = Path(args.save) if args.save else output / 'world.save.json'
    session = _play_session(args, parser, args.play)
    _say(f'Eternia v0.8: you are {session.person.name}. Everyone else in the region decides for themselves.')
    _say('Each turn is one cycle (a season). Your choice resolves together with everyone else\'s.')
    _say(PLAY_HELP)
    save, show = True, True
    while session.player_id is not None:
        choices, section = session.options(), None
        if show:  # only after time has passed, or when asked with m
            _say()
            for line in session.situation():
                _say(line)
            for number, option in enumerate(choices, 1):
                if option['section'] != section:
                    section = option['section']
                    _say(f'  {section}')
                extra = ' '.join(part for part in (hint(option), '' if option['checked'] else '(the cycle decides)') if part)
                _say(f'  {number:>3}. {option["label"]}' + (f' {extra}' if extra else ''))
        show = False
        try:
            command = input('> ').strip()
        except EOFError:
            command = 's'
        proposals, cycles = [None], 1
        if command in ('s', 'q'):
            save = command == 's'
            break
        if command in ('h', 'journal'):
            for line in journal_text(session.journal()):
                _say(line)
            continue
        if command in ('?', 'help'):
            _say(PLAY_HELP)
            continue
        if command in ('', 'm'):
            show = True
            continue
        if command == 't' or command.startswith('t '):
            _converse(session, command[1:].strip())
            continue
        if command.startswith('w'):
            try:
                cycles = int(command[1:].strip() or 1)
                if not 1 <= cycles <= 400:
                    raise ValueError
            except ValueError:
                _say('Wait 1 to 400 cycles, for example: w 4')
                continue
        elif command.startswith('j'):
            try:
                proposal = json.loads(command[1:])
                if not isinstance(proposal, dict):
                    raise ValueError
                proposals = [proposal]
            except ValueError:
                _say('Write the action as a JSON object, for example: j {"type": "rest", "params": {}}')
                continue
        elif command and command.split()[0].isdigit() and 1 <= int(command.split()[0]) <= len(choices):
            number, _, values = command.partition(' ')
            choice = choices[int(number) - 1]
            try:
                proposal = customize(choice, values)
            except ValueError as error:
                _say(f'{error} {hint(choice)}')
                continue
            check = session.check(proposal) if values.strip() else None
            if check is not None and not check.success:
                _say(f'That would be refused ({check.code}): {check.message} Nothing was spent; choose again.')
                continue
            proposals = [proposal]
        else:
            _say(PLAY_HELP)
            continue
        show = True
        for _ in range(cycles):
            if session.player_id is None:
                break
            try:
                outcome = session.act(proposals[0])
            except ValueError as error:
                _say(f'Not possible: {error}')
                break
            result = outcome['result']
            _say(('Done: ' if result['success'] else f'Refused ({result["code"]}): ') + result['message'])
            if cycles == 1:
                for event in outcome['events'][-12:]:
                    if event['message'] != result['message']:
                        _say(f'  - {event["message"]}')
    if session.player_id is None:
        _say('Your household has ended; no heir remains to continue.')
    try:
        if save:
            _say(f'Saved: {session.save(save_path)}')
        _write_play_outputs(session, output)
    except (ValueError, OSError) as error:
        parser.error(str(error))
    _say(f'Inputs for exact replay: {(output / "inputs.json").resolve()}')
    _say(f'Open: {(output / "report.html").resolve()}')


def _converse(session, text):
    """t: who is here; t N: what you can ask them; t N M [values]: ask, without spending a season."""
    from eternia.player import customize, hint
    people = session.partners()
    parts = text.split(maxsplit=2)
    if not parts:
        if not people:
            _say('Nobody is here to talk to.')
        for number, person in enumerate(people, 1):
            _say(f'  {number:>2}. {person["name"]} ({person["role"]})')
        return
    if not parts[0].isdigit() or not 1 <= int(parts[0]) <= len(people):
        _say('Choose someone by number: t lists the people here.')
        return
    person = people[int(parts[0]) - 1]
    topics = session.conversation(person['id'])
    if len(parts) == 1:
        for number, topic in enumerate(topics, 1):
            _say(f'  {number:>2}. {topic["label"]}' + (f' {hint(topic)}' if topic['fields'] else ''))
        return
    if not parts[1].isdigit() or not 1 <= int(parts[1]) <= len(topics):
        _say(f'Choose a topic by number: t {parts[0]} lists them.')
        return
    choice = topics[int(parts[1]) - 1]
    try:
        asked = customize(choice, parts[2] if len(parts) > 2 else '')
        reply = session.talk(person['id'], asked['type'], **asked['params'])
    except ValueError as error:
        _say(str(error))
        return
    for line in reply['lines']:
        _say(f'{person["name"]}: {line}' if line.startswith('"') else line)
    if reply['learned']:
        _say(f'(You learned {len(reply["learned"])} new thing{"s" if len(reply["learned"]) != 1 else ""}; h shows what you have heard.)')


def run_replay(args, parser):
    """Rebuild a played session from its settings and recorded inputs alone."""
    from eternia.playable_session import PlayableSession
    try:
        history = json.loads(Path(args.replay).read_text(encoding='utf-8'))
        session = PlayableSession.replay(history)
    except (ValueError, OSError, KeyError, TypeError) as error:
        parser.error(f'Cannot replay {args.replay}: {error}')
    output = Path(args.output or 'output/play-replay')
    _write_play_outputs(session, output)
    person = session.person
    _say(f'Replayed {len(history["inputs"])} inputs to cycle {session.world.tick}'
         + (f'; {person.name} lives in {session.world.settlements[person.home].name}.' if person else '.'))
    _say(f'Open: {(output / "report.html").resolve()}')


def run_v07(args, parser):
    from eternia.persistence import load_world, save_world
    if args.labor_experiment:
        return run_labor_experiment(args, parser)
    if args.inequality_experiment:
        return run_inequality_experiment(args, parser)
    if args.market_experiment:
        return run_market_experiment(args, parser)
    if args.goal_experiment:
        return run_goal_experiment(args, parser)
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
                                     policy_style=args.policy_style or 'balanced',
                                     adaptive_goals=not args.fixed_goals)
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
        market = data.get('market_metrics', {})
        goals = data.get('goal_log', [])
        print(f'Year {world.year}: {economy.get("wages_paid", 0):g} coins paid in wages; '
              f'{economy.get("volunteer_actions", 0)} voluntary actions; {market.get("purchases", 0)} market purchases; '
              f'{market.get("consignments", 0)} merchant consignments; '
              f'{sum(e["event"] == "completed" for e in goals)} goals reached and '
              f'{sum(e["event"] in ("revised", "escalated") for e in goals)} changed. Checkpoint: {saved}')
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
    modes.add_argument('--market-experiment', action='store_true',
                       help='Compare matched v0.7 food distributions: does food follow the price? (default: 2 years)')
    modes.add_argument('--goal-experiment', action='store_true',
                       help='The Changing Miner: matched circumstances with adaptive and fixed goals (default: 20 years)')
    modes.add_argument('--inequality-experiment', action='store_true',
                       help='Compare matched starting distributions of wealth and public funds (default: 30 years)')
    parser.add_argument('--fixed-goals', action='store_true',
                        help='Keep every v0.7 society goal fixed (a control for adaptive goals)')
    modes.add_argument('--play', nargs='?', const=True, default=None, metavar='CHECKPOINT',
                       help='v0.8: play one person in the society, a cycle per turn; give a checkpoint to continue')
    modes.add_argument('--replay', metavar='INPUTS',
                       help='v0.8: rebuild a played session exactly from its recorded inputs.json')
    modes.add_argument('--web', nargs='?', const=True, default=None, metavar='CHECKPOINT',
                       help='v0.8: play in your browser, served from this computer; give a checkpoint to continue')
    parser.add_argument('--port', type=int, default=8765, help='Local port for --web (default: 8765; 0 picks one)')
    parser.add_argument('--no-browser', action='store_true', help='With --web, do not open a browser window')
    parser.add_argument('--player-name', default='Wanderer', help='Name of the person you play (default: Wanderer)')
    parser.add_argument('--home', default='Rivermark', help='Settlement where the player arrives (default: Rivermark)')
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
    if args.play is not None:
        return run_play(args, parser)
    if args.web is not None:
        return run_web(args, parser)
    if args.replay:
        if any(v is not None for v in (args.seed, args.policy_style, args.years, args.ticks_per_year, args.shock_year)):
            parser.error('A replay restores its settings from the recorded inputs')
        return run_replay(args, parser)
    if (args.society or args.evaluate_society or args.resume or args.labor_experiment
            or args.market_experiment or args.goal_experiment or args.inequality_experiment):
        if args.fixed_goals and not args.society:
            parser.error('--fixed-goals applies to a --society run')
        run_v07(args, parser)
        return
    if args.policy_style is not None or args.fixed_goals:
        parser.error('--policy-style and --fixed-goals require a v0.7 society mode')
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
