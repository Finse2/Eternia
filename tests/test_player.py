"""v0.8 Stage 1: a human player is one more person in the same cycle, under the same rules."""
from copy import deepcopy
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from eternia import player as player_view
from eternia.evaluation import goal_history, summarize
from eternia.persistence import load_world, save_world
from eternia.playable_session import PlayableSession
from eternia.society import SocietyWorld

ROOT = Path(__file__).resolve().parents[1]
MERCHANT = 2  # Rivermark's trader


def exported(world):
    data = world.export()
    data.pop('provenance', None)
    return json.dumps(data, sort_keys=True)


def option(session, kind, **params):
    """The first menu choice of a kind (and matching parameters), as a player would pick it."""
    for choice in session.options():
        proposal = choice['proposal']
        if proposal['type'] == kind and all(proposal['params'].get(k) == v for k, v in params.items()):
            return proposal
    raise AssertionError(f'No {kind} option with {params}: {[c["label"] for c in session.options()]}')


def play_turns(session):
    """A short, varied stretch of play: gather, sell, buy, eat, wait and a refused attempt."""
    outcomes = [session.act(option(session, 'gather', resource='food'))]
    outcomes.append(session.act(option(session, 'trade', resource='food', direction='sell')))
    outcomes.append(session.act(option(session, 'trade', resource='food', direction='buy')))
    outcomes.append(session.act(option(session, 'eat')))
    outcomes.append(session.act())
    outcomes.append(session.act({'type': 'gather', 'params': {'resource': 'iron', 'amount': 2}}))
    return outcomes


class PlayerJoinsTests(unittest.TestCase):
    def test_a_player_arrives_as_an_ordinary_accounted_newcomer(self):
        world = SocietyWorld(seed=42)
        town = world.settlements[0]
        population, people = town.population, len(world.agents)
        person = world.add_player('Ilsa', home='Rivermark')
        self.assertEqual((town.population, len(world.agents)), (population + 1, people + 1))
        self.assertEqual(world.active_players(), {person.id})
        self.assertEqual((person.home, person.role, person.goal), (0, 'newcomer', {}))
        self.assertEqual(sorted(person.skills), ['foraging', 'trading'])
        self.assertEqual(person.inventory, {'food': 3., 'wood': 0., 'iron': 0., 'coins': 10.})
        self.assertNotIn(person.id, world.minds)  # nobody decides for the player
        world._assert_invariants()  # belongings are an explicit, accounted inflow
        self.assertEqual(world.player_log[-1]['event'], 'joined')
        self.assertTrue(world.events[-1]['player'])

    def test_joining_is_validated(self):
        world = SocietyWorld(seed=42)
        for name, home, inventory in (('', 0, None), ('x' * 41, 0, None), ('Edrin of Rivermark', 0, None),
                                      ('Rivermark', 0, None), ('Ilsa', 'Atlantis', None), ('Ilsa', 0, {'gold': 5}),
                                      ('Ilsa', 0, {'coins': -1}), ('Ilsa', 0, {'coins': math.inf})):
            with self.subTest(name=name, home=home, inventory=inventory), self.assertRaises(ValueError):
                world.add_player(name, home, inventory)
        self.assertEqual(world.players, set())
        world._resolving = True
        with self.assertRaises(ValueError):
            world.add_player('Ilsa')
        world._resolving = False
        self.assertEqual(world.add_player('Ilsa', 'Highfen', {'coins': 3}).inventory['coins'], 3.)


class SameCycleTests(unittest.TestCase):
    def setUp(self):
        self.session = PlayableSession.start('Ilsa', 'Rivermark', seed=42)
        self.world, self.me = self.session.world, self.session.player_id

    def test_acceptance_choices_resolve_with_everyone_and_their_consequences_persist(self):
        """Start a society, play a person in Rivermark, let every NPC act in the same cycle, repeat."""
        world, me = self.world, self.me
        batches = []
        resolve = world.resolve_actions
        world.resolve_actions = lambda proposals: batches.append(list(proposals)) or resolve(proposals)

        living = len(world.agents)
        deposits, energy = world.settlements[0].deposits['food'], self.session.person.energy
        gather = option(self.session, 'gather', resource='food')
        outcome = self.session.act(gather)
        # One batch, one proposal from each living person, the player's among them.
        self.assertEqual(len(batches), 1)
        self.assertEqual(sorted(p['actor'] for p in batches[0]), sorted(a.id for a in world.agents))
        self.assertEqual(outcome['actions_resolved'], living)
        self.assertTrue(outcome['result']['success'], outcome['result'])
        amount = gather['params']['amount']
        person = self.session.person
        self.assertEqual(person.inventory['food'], 3. + amount)
        self.assertEqual(person.energy, min(100., energy - 2 * amount + 6))  # same costs and recovery
        self.assertLessEqual(world.settlements[0].deposits['food'], deposits - amount)
        npc_actions = [r for r in world.action_log if r['tick'] == outcome['tick'] and r['action']['actor'] != me]
        self.assertEqual(len(npc_actions), living - 1)

        # Later turns build on what the earlier ones left behind.
        coins = person.inventory['coins']
        sell = option(self.session, 'trade', resource='food', direction='sell')
        sold = self.session.act(sell)
        self.assertTrue(sold['result']['success'], sold['result'])
        self.assertAlmostEqual(person.inventory['coins'], coins + sold['result']['effects']['price'])
        self.assertEqual(person.inventory['food'], 3. + amount - sell['params']['amount'])
        hunger = person.hunger
        ate = self.session.act(option(self.session, 'eat'))
        self.assertTrue(ate['result']['success'])
        self.assertLess(person.hunger, hunger + 7)
        self.assertEqual(person.inventory['food'], 3. + amount - sell['params']['amount'] - 1)
        self.assertEqual(len(batches), 3)
        self.assertEqual(world.tick, 3)
        self.assertEqual([e['tick'] for e in world.player_log if e['event'] == 'action'], [0, 1, 2])
        world._assert_invariants()

    def test_the_player_is_not_resolved_first(self):
        positions = []
        for _ in range(12):
            tick = self.world.tick
            self.session.act()
            batch = [r['action']['actor'] for r in self.world.action_log if r['tick'] == tick]
            positions.append(batch.index(self.me))
        self.assertGreater(len(set(positions)), 3)  # the seeded order of the whole batch decides
        self.assertNotEqual(set(positions), {0})

    def test_contested_last_units_are_settled_like_anyone_elses(self):
        world, me = self.world, self.me
        town = world.settlements[0]
        merchant = world.agents[MERCHANT]
        self.assertIn('trading', merchant.skills)
        moved = town.food - 6
        town.food -= moved
        world.ledger['consumed']['food'] += moved
        buy = lambda actor: {'actor': actor, 'type': 'trade', 'params': {'resource': 'food', 'amount': 6, 'direction': 'buy'}}
        for actor in (me, merchant.id):
            self.assertTrue(world.action_engine.validate(buy(actor)).success)
        results = world.resolve_actions([buy(me), buy(merchant.id)])
        outcome = {r['action']['actor']: r['result'] for r in results}
        self.assertEqual(sorted(r['success'] for r in outcome.values()), [False, True])
        loser = next(r for r in outcome.values() if not r['success'])
        self.assertEqual(loser['code'], 'conflict')
        self.assertEqual(town.food, 0)

    def test_the_same_rules_bind_the_player(self):
        with self.assertRaises(ValueError):
            self.session.act({'actor': 0, 'type': 'rest', 'params': {}})  # nobody acts for someone else
        refused = self.session.act({'type': 'gather', 'params': {'resource': 'iron', 'amount': 2}})
        self.assertFalse(refused['result']['success'])
        self.assertEqual(refused['result']['code'], 'missing_knowledge')
        rested = self.session.act({'type': 'rest', 'params': {}})
        self.assertEqual(rested['result']['code'], 'not_needed')
        broke = self.session.act({'type': 'trade', 'params': {'resource': 'iron', 'amount': 9, 'direction': 'buy'}})
        self.assertEqual(broke['result']['code'], 'insufficient_resources')
        self.assertEqual(self.session.person.inventory['coins'], 10.)
        # Refusals still cost the turn: time passed and hunger rose.
        self.assertEqual(self.world.tick, 3)
        self.assertGreater(self.session.person.hunger, 0)

    def test_a_player_who_chooses_nothing_waits(self):
        outcome = self.session.act()
        self.assertEqual(outcome['action']['type'], 'wait')
        self.assertTrue(outcome['result']['success'])
        self.assertEqual(self.world.player_log[-1]['chosen'], False)
        self.assertEqual(self.world._rationales[self.me], 'The player waited.')

    def test_the_player_sees_what_anyone_sees(self):
        mine, npc = self.session.observation(), self.world.observe(0)
        self.assertEqual(set(mine), set(npc))
        self.assertEqual(set(mine['actor']), set(npc['actor']) - {'mind'})
        self.assertEqual(mine['settlement'], npc['settlement'])
        self.assertEqual(mine['prices'], npc['prices'])
        self.assertNotIn('rng', json.dumps(mine))
        text = '\n'.join(self.session.situation())
        self.assertIn('You are Ilsa, living in Rivermark.', text)
        text.encode('ascii')

    def test_every_menu_option_comes_from_the_observation_and_passes_the_rules(self):
        for _ in range(9):
            before = exported(self.world)
            choices = self.session.options()
            self.assertEqual(exported(self.world), before)  # a dry run changes nothing
            candidates = [label for label, _ in player_view.candidate_actions(deepcopy(self.session.observation()))]
            self.assertTrue({c['label'] for c in choices} <= set(candidates))
            for choice in choices:
                self.assertTrue(self.world.action_engine.validate(choice['proposal']).success, choice['label'])
            self.assertEqual(choices[0]['proposal']['type'], 'wait')
            self.session.act(choices[min(len(choices) - 1, 1 + self.world.tick % 4)]['proposal'])

    def test_goal_statistics_cover_autonomous_people_only(self):
        self.session.act()
        history = goal_history(self.world)
        self.assertEqual(history['goals_active'], len(self.world.agents) - 1)
        self.assertNotIn(None, history['current_goal_kinds'])
        summary = summarize(self.world)
        self.assertEqual(summary['named_agents'], len(self.world.agents))


class ReplayAndSaveTests(unittest.TestCase):
    def test_recorded_inputs_replay_the_session_exactly(self):
        session = PlayableSession.start('Ilsa', 'Rivermark', seed=18, policy_style='collective', years=1)
        play_turns(session)
        history = json.loads(json.dumps(session.input_history()))
        self.assertEqual([e['event'] for e in history['inputs']].count('joined'), 1)
        self.assertEqual(history['inputs'][0]['tick'], 4)  # arrived after a year of autonomous history
        replayed = PlayableSession.replay(history)
        self.assertEqual(exported(replayed.world), exported(session.world))
        self.assertEqual(replayed.world.player_log, session.world.player_log)
        broken = deepcopy(history)
        broken['inputs'][0]['actor'] += 1
        with self.assertRaises(ValueError):
            PlayableSession.replay(broken)

    def test_save_and_load_between_turns_matches_uninterrupted_play(self):
        straight = PlayableSession.start('Ilsa', 'Rivermark', seed=42)
        resumed = PlayableSession.start('Ilsa', 'Rivermark', seed=42)
        play_turns(straight)
        play_turns(resumed)
        with tempfile.TemporaryDirectory() as folder:
            path = resumed.save(Path(folder) / 'world.save.json')
            resumed = PlayableSession.load(path)
        self.assertEqual(resumed.player_id, straight.player_id)
        for session in (straight, resumed):
            play_turns(session)
        self.assertEqual(exported(resumed.world), exported(straight.world))
        self.assertEqual(resumed.world.player_log, straight.world.player_log)
        # And the full record still replays from inputs alone, across the save.
        self.assertEqual(exported(PlayableSession.replay(resumed.input_history()).world), exported(straight.world))

    def test_a_queued_choice_survives_a_save(self):
        session = PlayableSession.start('Ilsa', 'Rivermark', seed=42)
        session.world.queue_player_action(session.player_id, option(session, 'gather', resource='food'))
        with tempfile.TemporaryDirectory() as folder:
            world = load_world(save_world(session.world, Path(folder) / 'w.json'))
        outcome = PlayableSession(world).act()
        self.assertEqual(outcome['action']['type'], 'gather')

    def test_a_saved_society_can_be_joined(self):
        world = SocietyWorld(seed=42)
        world.run(1)
        with tempfile.TemporaryDirectory() as folder:
            session = PlayableSession.load(save_world(world, Path(folder) / 'w.json'))
        self.assertIsNone(session.player_id)
        session.join('Ilsa', 'Highfen')
        with self.assertRaises(ValueError):
            session.join('Toma', 'Highfen')
        self.assertEqual(session.world.settlements[session.person.home].name, 'Highfen')
        session.act()
        replayed = PlayableSession.replay(session.input_history())
        self.assertEqual(exported(replayed.world), exported(session.world))

    def test_an_heir_continues_after_the_player_starves(self):
        session = PlayableSession.start('Ilsa', 'Rivermark', seed=42)
        first = session.player_id
        while session.player_id == first:
            self.assertLess(session.world.tick, 40)
            session.act()  # never eating has the same end as for anyone
        heir = session.person
        self.assertEqual(heir.parent_id, first)
        self.assertNotIn(heir.id, session.world.minds)
        self.assertEqual(session.world.active_players(), {heir.id})
        self.assertIn('prolonged food deprivation',
                      next(e['message'] for e in session.world.events if e['kind'] == 'death' and e['actor_id'] == first))
        entry = next(e for e in session.world.player_log if e['event'] == 'heir')
        self.assertEqual((entry['predecessor'], entry['actor']), (first, heir.id))
        session.act()
        outcome = session.act(option(session, 'eat'))
        self.assertEqual(outcome['actor'], heir.id)
        self.assertTrue(outcome['result']['success'])
        session.world._assert_invariants()
        replayed = PlayableSession.replay(session.input_history())
        self.assertEqual(replayed.world.player_log, session.world.player_log)

    def test_a_death_on_the_road_passes_control_on_arrival(self):
        session = PlayableSession.start('Ilsa', 'Rivermark', seed=42)
        world, first = session.world, session.player_id
        session.act(option(session, 'gather', resource='food'))  # provisions for the road
        self.assertTrue(session.act(option(session, 'migrate'))['result']['success'])
        self.assertTrue(world.is_traveling(first))
        self.assertEqual(world.remove_agent(first, 'old age').id, first)  # deferred until arrival
        self.assertEqual(world.active_players(), {first})
        self.assertFalse(any(e['event'] == 'heir' for e in world.player_log))
        while session.player_id == first:
            self.assertLess(world.tick, 20)
            session.act()
        heir = session.person
        self.assertEqual((heir.parent_id, world.settlements[heir.home].name), (first, 'Highfen'))
        self.assertNotIn(heir.id, world.minds)
        self.assertEqual([e['actor'] for e in world.player_log if e['event'] == 'heir'], [heir.id])
        world._assert_invariants()


class PlayCommandLineTests(unittest.TestCase):
    def run_main(self, *args, stdin=''):
        return subprocess.run([sys.executable, 'main.py', *map(str, args)], cwd=ROOT, input=stdin,
                              text=True, capture_output=True)

    def test_play_continue_and_replay(self):
        with tempfile.TemporaryDirectory() as folder:
            first, second, again = (Path(folder) / name for name in ('first', 'second', 'replay'))
            result = self.run_main('--play', '--player-name', 'Ilsa', '--output', first,
                                   stdin='2\nw 2\nj {"type": "rest", "params": {}}\nnonsense\ns\n')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('You are Ilsa, living in Rivermark.', result.stdout)
            self.assertIn('Refused (not_needed)', result.stdout)
            for name in ('world.save.json', 'history.json', 'report.html', 'inputs.json'):
                self.assertTrue((first / name).exists(), name)
            # Continue from the checkpoint; end of input saves and quits.
            result = self.run_main('--play', first / 'world.save.json', '--output', second, stdin='1\n')
            self.assertEqual(result.returncode, 0, result.stderr)
            history = json.loads((second / 'history.json').read_text(encoding='utf-8'))
            self.assertEqual(sum(e['event'] == 'action' for e in history['player_log']), 5)
            result = self.run_main('--replay', second / 'inputs.json', '--output', again)
            self.assertEqual(result.returncode, 0, result.stderr)
            replayed = json.loads((again / 'history.json').read_text(encoding='utf-8'))
            for data in (history, replayed):
                data.pop('provenance', None)
            self.assertEqual(replayed, history)
            self.assertNotEqual(self.run_main('--play', first / 'world.save.json', '--seed', 3, stdin='q\n').returncode, 0)
            self.assertNotEqual(self.run_main('--play', '--ticks-per-year', 2, stdin='q\n').returncode, 0)
            self.assertNotEqual(self.run_main('--play', '--home', 'Atlantis', stdin='q\n').returncode, 0)


if __name__ == '__main__':
    unittest.main()
