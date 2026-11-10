"""Behavioral checks for perception, needs, memory and unscripted replanning."""
import copy
import json
import math
import unittest

from eternia.autonomy import GoalPolicy, run_demo
from eternia.simulation import World


class ObservationTests(unittest.TestCase):
    def test_perception_is_detached_and_hides_aether(self):
        world = World(seed=42)
        actor = world.agents[0]
        observation = world.observe(actor.id)
        self.assertNotIn('aether', observation['settlement'])
        for neighbor in observation['neighbors']:
            self.assertNotIn('aether', neighbor)
        observation['actor']['inventory']['coins'] = 100000
        observation['actor']['skills'].append('invented_skill')
        observation['settlement']['deposits']['iron'] = 100000
        observation['rules']['prices']['iron'] = 100000
        self.assertNotEqual(actor.inventory['coins'], 100000)
        self.assertNotIn('invented_skill', actor.skills)
        self.assertNotEqual(world.settlements[actor.home].deposits['iron'], 100000)
        self.assertEqual(world.observe(actor.id)['rules']['prices']['iron'], 4)

    def test_rejected_proposal_enters_memory_without_spending_turn(self):
        world = World(seed=42)
        actor = world.agents[0]
        before_inventory = dict(actor.inventory)
        result = world.submit_action(dict(actor=actor.id, type='gather', resource='iron', amount=999))
        self.assertFalse(result.success)
        self.assertEqual(actor.inventory, before_inventory)
        self.assertTrue(actor.memory)
        self.assertFalse(actor.memory[-1]['result']['success'])
        following = world.submit_action(dict(actor=actor.id, type='gather', resource='iron', amount=1))
        self.assertTrue(following.success, following.message)


class GoalPolicyTests(unittest.TestCase):
    def setUp(self):
        self.world = World(seed=42)
        self.actor = self.world.agents[0]
        self.actor.name = 'Edrin'
        self.policy = GoalPolicy()

    def test_hunger_changes_choice_to_eating(self):
        self.actor.hunger = 90
        self.actor.inventory['food'] = 2
        proposal = self.policy.propose(self.world.observe(self.actor.id))
        self.assertEqual(proposal['type'], 'eat')
        self.assertTrue(self.world.action_engine.validate(proposal).success)

    def test_exhaustion_changes_choice_to_rest(self):
        self.actor.energy = 0
        self.actor.hunger = 0
        proposal = self.policy.propose(self.world.observe(self.actor.id))
        self.assertEqual(proposal['type'], 'rest')
        self.assertTrue(self.world.action_engine.validate(proposal).success)

    def test_planner_uses_observation_without_mutating_it(self):
        observation = self.world.observe(self.actor.id)
        before = copy.deepcopy(observation)
        proposal = self.policy.propose(observation)
        self.assertEqual(observation, before)
        self.assertTrue(self.world.action_engine.validate(proposal).success)

    def test_empty_mine_is_not_proposed_for_gathering(self):
        self.world.settlements[self.actor.home].deposits['iron'] = 0
        proposal = self.policy.propose(self.world.observe(self.actor.id))
        params = proposal.get('params', proposal)
        self.assertFalse(proposal['type'] == 'gather' and params.get('resource') == 'iron')
        self.assertTrue(self.world.action_engine.validate(proposal).success)

    def test_remembered_rejection_changes_the_next_proposal(self):
        first = self.policy.propose(self.world.observe(self.actor.id))
        home = self.world.settlements[self.actor.home]
        # A temporary prohibition makes the world reject the proposed action.
        # Restore the public conditions so memory is the only changed input.
        home.permissions[first['type']] = False
        rejected = self.world.submit_action(first)
        self.assertFalse(rejected.success)
        home.permissions[first['type']] = True
        following = self.policy.propose(self.world.observe(self.actor.id))
        self.assertNotEqual(first, following)
        self.assertTrue(self.world.action_engine.validate(following).success)

    def test_completed_goals_and_full_energy_produce_a_valid_wait(self):
        self.actor.structures['house'] = 1
        self.actor.inventory.update(coins=self.actor.wealth_goal, food=3)
        self.actor.hunger = 0
        self.actor.energy = 100
        proposal = self.policy.propose(self.world.observe(self.actor.id))
        self.assertEqual(proposal['type'], 'wait')
        before = copy.deepcopy((self.actor.inventory, self.actor.energy, self.actor.hunger))
        result = self.world.submit_action(proposal)
        self.assertTrue(result.success, result.message)
        self.assertEqual(before, (self.actor.inventory, self.actor.energy, self.actor.hunger))

    def test_wealthy_hungry_person_migrates_when_local_food_is_exhausted(self):
        self.actor.structures['house'] = 1
        self.actor.inventory.update(food=0, coins=78)
        self.actor.hunger = 100
        home = self.world.settlements[self.actor.home]
        home.food = 0
        home.deposits['food'] = 0
        proposal = self.policy.propose(self.world.observe(self.actor.id))
        self.assertEqual(proposal['type'], 'migrate')
        result = self.world.action_engine.validate(proposal)
        self.assertTrue(result.success, result.message)
        destination = self.world.settlements[proposal['params']['destination']]
        self.assertGreaterEqual(destination.deposits['food'], 1)


class AutonomyDemoTests(unittest.TestCase):
    def test_demo_is_repeatable_and_records_each_decision(self):
        first = run_demo(seed=42, turns=40, shock_turn=8)
        second = run_demo(seed=42, turns=40, shock_turn=8)
        self.assertEqual(first.export(), second.export())
        self.assertEqual(len(first.agents), 1)
        self.assertEqual(first.agents[0].name, 'Edrin')
        self.assertEqual(len(first.decisions), 40)
        self.assertEqual(len(first.action_log), 40)
        self.assertEqual(first.year, 40)
        self.assertTrue(all('result' in d and 'proposal' in d for d in first.decisions))

    def test_goal_progress_survives_an_unexpected_mine_closure(self):
        world = run_demo(seed=42, turns=40, shock_turn=8)
        actor = world.agents[0]
        self.assertGreaterEqual(actor.structures.get('house', 0), 1)
        self.assertGreaterEqual(actor.inventory['coins'], actor.wealth_goal)
        self.assertLess(actor.hunger, 70)
        self.assertTrue(actor.memory)
        self.assertLessEqual(len(actor.memory), 64)
        self.assertTrue(any(e['kind'] == 'disruption' for e in world.events))
        self.assertTrue(any(s.buildings.get('house', 0) for s in world.settlements))

    def test_disruption_changes_decisions_without_changing_the_policy(self):
        baseline = run_demo(seed=42, turns=24, shock_turn=0)
        disrupted = run_demo(seed=42, turns=24, shock_turn=8)
        baseline_proposals = [d['proposal'] for d in baseline.decisions]
        disrupted_proposals = [d['proposal'] for d in disrupted.decisions]
        self.assertEqual(baseline_proposals[:7], disrupted_proposals[:7])
        self.assertNotEqual(baseline_proposals[7:], disrupted_proposals[7:])

    def test_malformed_provider_proposals_still_export_as_strict_json(self):
        nan_proposal = dict(actor=0, type='gather', resource='iron', amount=math.nan)
        cyclic_proposal = dict(actor=0, type='gather', resource='iron', amount=1)
        cyclic_proposal['params'] = cyclic_proposal
        for proposal in (nan_proposal, cyclic_proposal):
            with self.subTest(kind='nan' if proposal is nan_proposal else 'cyclic'):
                class MalformedPolicy:
                    name = 'malformed provider fixture'

                    def propose(self, observation):
                        return proposal

                world = run_demo(seed=42, turns=2, shock_turn=0, policy=MalformedPolicy())
                self.assertTrue(all(not d['result']['success'] for d in world.decisions))
                json.dumps(world.export(), allow_nan=False)


if __name__ == '__main__':
    unittest.main()
