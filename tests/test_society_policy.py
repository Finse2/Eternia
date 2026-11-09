"""Policy choices must follow visible needs, budgets and personal goals."""
import copy
import unittest

from eternia.simulation import World
from eternia.society_policy import CommunityPolicy


class CommunityPolicyTests(unittest.TestCase):
    def observation(self, role='miner', **inventory):
        world = World(42)
        observation = world.observe(world.agents[0].id)
        actor = observation['actor']
        actor.update(role=role, energy=100, hunger=0, knowledge=0,
                     structures={}, trust={}, reputation=.5,
                     goal={'kind': role, 'target': 3 if role == 'builder' else 12 if role == 'farmer' else 60})
        actor['inventory'] = {'food': 3, 'wood': 0, 'iron': 0, 'coins': 20, **inventory}
        actor['skills'] = ['foraging', 'trading']
        if role == 'builder':
            actor['skills'] += ['carpentry', 'woodcutting']
        if role == 'miner':
            actor['skills'].append('mining')
        actor['available_inventory'] = dict(actor['inventory'])
        observation['tick'] = 1
        observation['market'] = []
        observation['peers'] = [
            {'id': 99, 'name': 'Neighbor', 'home': actor['home'], 'role': 'builder',
             'inventory': {'food': 3, 'wood': 0, 'iron': 0, 'coins': 30},
             'goal': {'kind': 'houses', 'target': 3}, 'structures': {},
             'skills': ['foraging'], 'knowledge': 0, 'reputation': .5}]
        return observation

    def test_observation_is_unchanged(self):
        observation = self.observation('miner', iron=8)
        before = copy.deepcopy(observation)
        CommunityPolicy().propose(observation)
        self.assertEqual(observation, before)

    def test_professions_choose_from_their_own_needs_and_goals(self):
        cases = [
            ('builder', {'wood': 12, 'iron': 2}, 'build'),
            ('researcher', {'wood': 2, 'iron': 2}, 'research'),
            ('miner', {'iron': 8}, 'offer'),
            ('farmer', {'food': 0}, 'gather'),
        ]
        for role, inventory, expected in cases:
            with self.subTest(role=role):
                proposal = CommunityPolicy().propose(self.observation(role, **inventory))
                self.assertEqual(proposal['type'], expected)

    def test_building_cannot_spend_reserved_materials(self):
        observation = self.observation('builder', wood=12, iron=2)
        observation['actor']['available_inventory']['wood'] = 0
        self.assertNotEqual(CommunityPolicy().propose(observation)['type'], 'build')

    def test_hungry_wealthy_person_moves_to_food_after_local_exhaustion(self):
        observation = self.observation('miner', food=0, coins=78)
        observation['actor']['hunger'] = 100
        observation['settlement']['deposits']['food'] = 0
        proposal = CommunityPolicy().propose(observation)
        self.assertEqual(proposal['type'], 'migrate')

    def test_food_purchase_is_partial_and_affordable(self):
        observation = self.observation('miner', food=0, coins=2)
        observation['actor']['hunger'] = 70
        observation['settlement']['deposits']['food'] = 0
        observation['market'] = [{'id': 5, 'actor': 99, 'resource': 'food',
                                  'direction': 'sell', 'amount': 4, 'unit_price': 1}]
        proposal = CommunityPolicy().propose(observation)
        self.assertEqual(proposal['type'], 'accept')
        self.assertEqual(proposal['params'], {'offer_id': 5, 'amount': 2})

    def test_merchant_buys_a_visible_bargain_with_a_potential_customer(self):
        observation = self.observation('merchant', coins=60)
        observation['peers'].append({'id': 98, 'name': 'Seller', 'role': 'miner',
                                    'inventory': {'food': 3, 'wood': 0, 'iron': 8},
                                    'skills': [], 'knowledge': 0, 'reputation': .5})
        observation['market'] = [{'id': 7, 'actor': 98, 'resource': 'iron',
                                  'direction': 'sell', 'amount': 4, 'unit_price': 3.5}]
        proposal = CommunityPolicy().propose(observation)
        self.assertEqual(proposal['type'], 'accept')
        self.assertEqual(proposal['params']['offer_id'], 7)

    def test_a_recent_failed_plan_changes_the_next_choice(self):
        observation = self.observation('miner', iron=8)
        policy = CommunityPolicy()
        first = policy.propose(observation)
        observation['actor']['memory'] = [
            {'tick': 1, 'action': first, 'result': {'success': False}}]
        self.assertNotEqual(policy.propose(observation), first)


if __name__ == '__main__':
    unittest.main()
