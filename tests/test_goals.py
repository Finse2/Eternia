"""v0.7 Stage 3: motivations, adaptive goals and the Changing Miner experiment."""
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from eternia.economic_policy import EconomicPolicy
from eternia.evaluation import goal_history, goal_outcome
from eternia.goal_engine import (COOLDOWN, DOUBT_MEMORY, GOAL_KINDS, STALL_GRACE, candidate_goals,
                                 content_threshold, doubt)
from eternia.goal_experiments import GOAL_SCENARIOS, build_goal_scenario, run_goal_case
from eternia.motivations import MAX_SHIFT, MOTIVES, experience_deltas, initial_temperament, update
from eternia.persistence import checkpoint, restore_checkpoint
from eternia.society import SocietyWorld
from v07_helpers import add_council

ROOT = Path(__file__).resolve().parents[1]
EDRIN, RIVERMARK = 1, 0


def even_mind(world, person, value=.5, **motives):
    """Give a person flat motives (and temperament) so a test controls what they care about."""
    mind = world.minds[person]
    mind['motivations'] = {m: motives.get(m, value) for m in MOTIVES}
    mind['temperament'] = dict(mind['motivations'])
    return mind


def give_coins(world, person, amount):
    world.settlements[world.agents[person].home].treasury -= amount  # a transfer, not new money
    world.agents[person].inventory['coins'] += amount


class MotivationTests(unittest.TestCase):
    def setUp(self):
        self.temperament = initial_temperament('miner', curiosity=.5, ambition=.5, openness=.5, seed=1, identity=1)

    def test_one_experience_moves_a_motive_a_little_and_fades(self):
        lived, learned = update(dict(self.temperament), dict(self.temperament), experience_deltas('hunger'))
        rise = lived['security'] - self.temperament['security']
        self.assertGreater(rise, 0)
        self.assertLessEqual(rise, .03 + 1e-9)
        for _ in range(40):
            lived, learned = update(lived, learned, {})
        self.assertLess(abs(lived['security'] - learned['security']), .01)
        self.assertLess(abs(learned['security'] - self.temperament['security']), .005)

    def test_experiences_repeated_for_years_leave_a_lasting_mark(self):
        lived, learned = dict(self.temperament), dict(self.temperament)
        for _ in range(80):
            lived, learned = update(lived, learned, experience_deltas('hunger'))
        self.assertGreater(learned['security'] - self.temperament['security'], .05)

    def test_motives_stay_bounded_and_move_at_most_a_step_per_cycle(self):
        lived, _ = update(dict(self.temperament), dict(self.temperament), {m: 5. for m in MOTIVES})
        for motive in MOTIVES:
            self.assertLessEqual(lived[motive] - self.temperament[motive], MAX_SHIFT + 1e-9)
            self.assertTrue(.05 <= lived[motive] <= .95)

    def test_temperament_is_deterministic_and_leaves_the_world_generator_alone(self):
        first, second = SocietyWorld(seed=42), SocietyWorld(seed=42)
        self.assertEqual(first.minds, second.minds)
        state = first.rng.getstate()
        first.reset_minds()
        self.assertEqual(first.rng.getstate(), state)
        self.assertNotEqual(SocietyWorld(seed=18).minds[EDRIN]['temperament'], first.minds[EDRIN]['temperament'])

    def test_curiosity_shapes_temperament_and_heirs_take_after_predecessors(self):
        dull = initial_temperament('miner', curiosity=0., ambition=.5, openness=.5, seed=1, identity=1)
        keen = initial_temperament('miner', curiosity=1., ambition=.5, openness=.5, seed=1, identity=1)
        self.assertAlmostEqual(keen['curiosity'] - dull['curiosity'], .5, places=6)
        parent = dict.fromkeys(MOTIVES, .9)
        own = initial_temperament('miner', curiosity=.5, ambition=.5, openness=.5, seed=1, identity=2)
        heir = initial_temperament('miner', curiosity=.5, ambition=.5, openness=.5, seed=1, identity=2, parent=parent)
        for motive in MOTIVES:
            self.assertAlmostEqual(heir[motive], (own[motive] + .9) / 2, places=5)


class GoalDecisionTests(unittest.TestCase):
    def review(self, world, tick):
        world.tick = tick
        world._review_minds([])
        return [e for e in world.goal_log if e['actor'] == EDRIN and e['tick'] == tick]

    def test_a_goal_is_held_through_its_cooldown(self):
        world = SocietyWorld(seed=42)
        even_mind(world, EDRIN, security=.95)  # a food reserve now appeals far more than coins
        self.assertEqual(self.review(world, COOLDOWN - 1), [])
        events = self.review(world, COOLDOWN)
        self.assertEqual([e['event'] for e in events], ['revised'])
        self.assertEqual(world.agents[EDRIN].goal['kind'], 'food')

    def test_a_small_advantage_does_not_change_the_goal(self):
        world = SocietyWorld(seed=42)
        even_mind(world, EDRIN)  # food 0.45 against coins 0.40: below the required margin
        self.assertEqual(self.review(world, COOLDOWN), [])
        self.assertEqual(world.agents[EDRIN].goal, {'kind': 'wealth', 'target': 60})

    def test_a_completion_is_recorded_once_and_survives_a_new_goal(self):
        world = SocietyWorld(seed=42)
        even_mind(world, EDRIN)
        world.agents[EDRIN].ambition = 1.
        give_coins(world, EDRIN, 60 - world.agents[EDRIN].inventory['coins'])
        events = [e['event'] for e in self.review(world, COOLDOWN)]
        self.assertEqual(events[0], 'completed')
        self.assertIn(events[1], ('escalated', 'revised'))
        record = world.minds[EDRIN]['history'][-1]
        self.assertEqual((record['outcome'], record['goal']), ('completed', {'kind': 'wealth', 'target': 60}))
        self.assertFalse(goal_outcome(world.agents[EDRIN])['completed'])  # the new goal is not met yet
        edrin = lambda: SimpleNamespace(goal_log=[e for e in world.goal_log if e['actor'] == EDRIN],
                                        agents=world.agents)
        metrics = goal_history(edrin())
        self.assertEqual((metrics['goal_completions'], metrics['goal_revisions'], metrics['goals_abandoned']), (1, 1, 0))
        self.review(world, COOLDOWN + 1)
        self.assertEqual(goal_history(edrin())['goal_completions'], 1)

    def test_people_may_decline_a_new_ambition_after_success(self):
        outcomes = {}
        for ambition in (0., 1.):
            world = SocietyWorld(seed=42)
            even_mind(world, EDRIN)
            world.agents[EDRIN].ambition = ambition
            give_coins(world, EDRIN, 60 - world.agents[EDRIN].inventory['coins'])
            outcomes[ambition] = [e['event'] for e in self.review(world, COOLDOWN)]
        self.assertEqual(outcomes[0.], ['completed', 'content'])
        self.assertIn(outcomes[1.][1], ('escalated', 'revised'))
        self.assertLess(content_threshold(1.), content_threshold(0.))

    def test_a_stalled_goal_is_abandoned_with_its_reasons_and_leaves_doubt(self):
        world = SocietyWorld(seed=42)
        mind = even_mind(world, EDRIN, security=.6)
        tick = STALL_GRACE + 16
        mind['best_tick'] = 0
        event, = self.review(world, tick)
        self.assertEqual((event['event'], event['previous_outcome']), ('revised', 'abandoned'))
        self.assertIn('without progress', event['reason'])
        self.assertTrue(any('no progress' in line for line in event['evidence']))
        self.assertLess(doubt(mind, 'wealth', tick), 1.)
        self.assertEqual(doubt(mind, 'wealth', tick + DOUBT_MEMORY), 1.)

    def test_only_supported_goals_with_unmet_targets_are_candidates(self):
        world = SocietyWorld(seed=42)
        person = world.agents[EDRIN]
        person.knowledge = 2
        options = candidate_goals(person, person.goal, completed=False)
        self.assertTrue(all(o['kind'] in GOAL_KINDS for o in options))
        self.assertNotIn('knowledge', {o['kind'] for o in options})
        self.assertNotIn('wealth', {o['kind'] for o in options})  # the current goal is judged separately
        escalations = candidate_goals(person, {'kind': 'wealth', 'target': 60}, completed=True)
        self.assertIn({'kind': 'wealth', 'target': 120}, escalations)

    def test_fixed_goal_controls_never_change_goals(self):
        world = SocietyWorld(seed=42, adaptive_goals=False).run(4)
        self.assertFalse([e for e in world.goal_log if e['event'] in ('revised', 'escalated', 'content')])
        initial = {a['id']: a['goal'] for a in world.snapshots[0]['agents']}
        for person in world.agents:
            if person.id in initial:
                self.assertEqual(person.goal, initial[person.id])
        self.assertNotEqual(world.minds[EDRIN]['motivations'], world.minds[EDRIN]['temperament'])


class GoalBehaviorTests(unittest.TestCase):
    def setUp(self):
        self.world = SocietyWorld(seed=42)
        # A council Edrin does not belong to: no founding to do, and no council business of his own.
        add_council(self.world, members=[0, 2])
        self.person = self.world.agents[EDRIN]

    def plan(self, **motives):
        even_mind(self.world, EDRIN, **motives)
        return EconomicPolicy('balanced').propose(self.world.observe(EDRIN))

    def give_wood(self):
        self.world.settlements[RIVERMARK].wood -= 1  # a transfer standing in for a purchase
        self.person.inventory['wood'] += 1

    def test_a_knowledge_goal_leads_to_experiments(self):
        self.person.goal = {'kind': 'knowledge', 'target': 1}
        self.give_wood()
        plan = self.plan(curiosity=.9)
        self.assertEqual((plan['type'], plan['params']), ('research', {'topic': 'aether'}), plan)

    def test_a_houses_goal_without_carpentry_starts_with_study(self):
        self.person.goal = {'kind': 'houses', 'target': 1}
        self.give_wood()
        plan = self.plan(legacy=.9)
        self.assertEqual((plan['type'], plan['params']), ('research', {'topic': 'carpentry'}), plan)

    def test_a_food_goal_leads_to_gathering(self):
        self.person.goal = {'kind': 'food', 'target': 12}
        plan = self.plan(security=.9)
        self.assertEqual((plan['type'], plan['params']['resource']), ('gather', 'food'), plan)

    def test_the_same_person_acts_differently_under_a_coins_goal(self):
        self.give_wood()
        plan = self.plan(curiosity=.9)
        self.assertNotEqual(plan['type'], 'research', plan)

    def test_survival_comes_before_any_ambition(self):
        self.person.goal = {'kind': 'knowledge', 'target': 1}
        self.give_wood()
        self.person.hunger = 70.
        self.assertEqual(self.plan(curiosity=.95)['type'], 'eat')


class GoalPersistenceTests(unittest.TestCase):
    def test_minds_and_goal_history_resume_exactly(self):
        world = SocietyWorld(seed=18).run(3)
        restored = restore_checkpoint(json.loads(json.dumps(checkpoint(world), allow_nan=False)))
        self.assertEqual(restored.minds, world.minds)
        for _ in range(10):
            world.step()
            restored.step()
        self.assertEqual(restored.export(), world.export())
        self.assertEqual(restored.goal_log, world.goal_log)

    def test_a_failed_cycle_rolls_back_motives_and_goal_records(self):
        world = SocietyWorld(seed=42).run(2)
        before, rng = world.export(), world.rng.getstate()
        advance = SocietyWorld.advance_time

        def fail(instance):
            advance(instance)
            raise RuntimeError('injected after the goal review')
        with patch.object(SocietyWorld, 'advance_time', fail):
            with self.assertRaises(RuntimeError):
                world.step()
        self.assertEqual(world.export(), before)
        self.assertEqual(world.rng.getstate(), rng)


class GoalExperimentTests(unittest.TestCase):
    def test_setups_change_circumstances_not_totals(self):
        totals = SocietyWorld(seed=42).resource_totals()
        minds = {}
        for name in GOAL_SCENARIOS:
            world, metadata = build_goal_scenario(name, 42)
            for resource, amount in totals.items():
                self.assertAlmostEqual(world.resource_totals()[resource], amount)
            self.assertEqual(world.agents[EDRIN].goal, {'kind': 'wealth', 'target': 60})
            minds[name] = world.minds[EDRIN]
        self.assertGreater(minds['curious_miner']['temperament']['curiosity'],
                           minds['successful_miner']['temperament']['curiosity'])

    def test_adaptive_and_fixed_cases_differ_only_in_goal_adaptation(self):
        adaptive = run_goal_case('successful_miner', 42, years=3)
        fixed = run_goal_case('successful_miner', 42, years=3, adaptive_goals=False)
        events = [e['event'] for e in adaptive['evidence']['timeline']]
        self.assertIn('completed', events)
        self.assertTrue({'escalated', 'revised', 'content'} & set(events))
        self.assertEqual(fixed['summary']['focal']['revisions'], 0)
        self.assertEqual(fixed['summary']['population']['goal_revisions'], 0)
        for event in adaptive['evidence']['timeline']:
            if event['event'] in ('revised', 'escalated'):
                self.assertTrue(event['reason'] and event['evidence'])

    def test_cli_runs_the_goal_experiment_and_a_fixed_goal_society(self):
        run = lambda *args: subprocess.run([sys.executable, 'main.py', *map(str, args)], cwd=ROOT,
                                           text=True, capture_output=True)
        with tempfile.TemporaryDirectory() as folder:
            result = run('--goal-experiment', '--years', 1, '--output', folder)
            self.assertEqual(result.returncode, 0, result.stderr)
            data = json.loads((Path(folder) / 'summary.json').read_text(encoding='utf-8'))
            self.assertEqual(len(data['cases']), 8)
            self.assertIn('The Changing Miner', (Path(folder) / 'report.html').read_text(encoding='utf-8'))
            self.assertIn('id="ambitionPanel"',
                          (Path(folder) / 'curious_miner-adaptive' / 'report.html').read_text(encoding='utf-8'))
            self.assertNotEqual(run('--goal-experiment', '--save', Path(folder) / 'x.json').returncode, 0)
            result = run('--society', '--years', 1, '--fixed-goals', '--output', Path(folder) / 'fixed')
            self.assertEqual(result.returncode, 0, result.stderr)
            history = json.loads((Path(folder) / 'fixed' / 'history.json').read_text(encoding='utf-8'))
            self.assertFalse(history['adaptive_goals'])
            self.assertNotEqual(run('--labor-experiment', '--fixed-goals').returncode, 0)


if __name__ == '__main__':
    unittest.main()
