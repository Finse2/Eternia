"""Transport work responds to public geography and preserves personal needs."""
import copy
import unittest

from eternia.civilizations import CivilizationWorld
from eternia.logistics_policy import LogisticsPolicy


class LogisticsPolicyTests(unittest.TestCase):
    def observation(self):
        world = CivilizationWorld(seed=42)
        world.tick = 10
        observation = world.observe(2)
        observation['actor'].update(hunger=0, energy=100, knowledge=2)
        observation['actor']['inventory'].update(food=5, wood=0, iron=0, coins=30)
        observation['actor']['available_inventory'] = dict(observation['actor']['inventory'])
        observation['settlement']['food'] = observation['settlement']['population'] * 1.5
        observation['physical'] = {
            'links': [{'id': 0, 'a': 0, 'b': 1, 'condition': .4, 'owner': None,
                       'closed': False, 'capacity': 20, 'speed': 10, 'risk': .02}],
            'paths': {}, 'dispatch_options': []}
        institution = {'id': 0, 'name': 'Trading Guild', 'purpose': 'guild',
                       'settlement_id': 0, 'members': [1, 2], 'active': True,
                       'rules': {'tax_rate': 0, 'communal_labor': 0}, 'decisions': [],
                       'inventory': {'food': 0, 'wood': 0, 'iron': 0}, 'treasury': 0}
        observation['institutions'] = [institution]
        observation['memberships'] = [0]
        observation['actor']['memberships'] = [0]
        return observation, institution

    def decision(self, institution, *, kind='repair_route', params=None, votes=None):
        decision = {'id': 0, 'kind': kind, 'params': params or {'link': 0},
                    'created': 5, 'expires': 17, 'status': 'open', 'electorate': [1, 2],
                    'votes': votes if votes is not None else {
                        1: {'approve': True, 'tick': 6}, 2: {'approve': True, 'tick': 7}}}
        institution['decisions'].append(decision)
        return decision

    def dispatch(self, observation):
        observation['regional']['routes'] = [
            {'id': 0, 'exporter': 0, 'importer': 1, 'exporter_institution': 0,
             'importer_institution': 1, 'resource': 'iron', 'unit_price': 1.5,
             'quota': 10, 'expires': 25, 'status': 'active', 'active': True}]
        observation['physical']['dispatch_options'] = [
            {'route': 0, 'amount': 4, 'path': [0], 'duration': 3, 'risk': .05, 'supplies': 1.5}]

    def test_a_traveler_waits_instead_of_exercising_home_authority(self):
        observation, institution = self.observation()
        self.decision(institution)
        observation['actor']['journey'] = {'status': 'in_transit', 'destination': 1}
        proposal = LogisticsPolicy().propose(observation)
        self.assertEqual(proposal['type'], 'wait')

    def test_merchant_can_organize_an_authorized_feasible_delivery(self):
        observation, _ = self.observation()
        self.dispatch(observation)
        proposal = LogisticsPolicy().propose(observation)
        self.assertEqual(proposal['type'], 'dispatch_caravan')
        self.assertEqual(proposal['params'], {'route': 0, 'amount': 4})

    def test_foreign_sponsor_does_not_grant_transport_authority(self):
        observation, _ = self.observation()
        self.dispatch(observation)
        observation['regional']['routes'][0]['exporter_institution'] = 99
        self.assertNotEqual(LogisticsPolicy().propose(observation)['type'], 'dispatch_caravan')

    def test_pathless_or_excessively_risky_delivery_can_be_declined(self):
        for change in ({'path': []}, {'risk': .8}):
            with self.subTest(change=change):
                observation, _ = self.observation()
                self.dispatch(observation)
                observation['physical']['dispatch_options'][0].update(change)
                self.assertNotEqual(LogisticsPolicy().propose(observation)['type'], 'dispatch_caravan')

    def test_hunger_precedes_organizing_a_caravan(self):
        observation, _ = self.observation()
        self.dispatch(observation)
        observation['actor']['hunger'] = 90
        proposal = LogisticsPolicy().propose(observation)
        self.assertEqual(proposal['type'], 'eat')

    def test_members_seek_a_vote_before_repairing_a_damaged_connection(self):
        observation, _ = self.observation()
        proposal = LogisticsPolicy().propose(observation)
        self.assertEqual(proposal['type'], 'propose')
        self.assertEqual(proposal['params']['kind'], 'repair_route')

    def test_foreign_owned_connections_are_not_claimed_by_a_repair_proposal(self):
        observation, _ = self.observation()
        observation['physical']['links'][0]['owner'] = 9
        proposal = LogisticsPolicy().propose(observation)
        self.assertNotEqual(proposal.get('params', {}).get('kind'), 'repair_route')

    def test_a_member_votes_on_an_unfunded_project_without_spending_its_resources(self):
        observation, institution = self.observation()
        self.decision(institution, votes={1: {'approve': True, 'tick': 6}})
        proposal = LogisticsPolicy().propose(observation)
        self.assertEqual(proposal['type'], 'vote')
        self.assertTrue(proposal['params']['approve'])

    def test_prior_majority_and_funds_motivate_execution(self):
        observation, institution = self.observation()
        self.decision(institution)
        institution['inventory'].update(wood=6, iron=1)
        institution['treasury'] = 3
        proposal = LogisticsPolicy().propose(observation)
        self.assertEqual(proposal['type'], 'enact')
        self.assertEqual(proposal['params']['proposal'], 0)

    def test_new_votes_do_not_look_like_a_prior_tick_mandate(self):
        observation, institution = self.observation()
        self.decision(institution, votes={1: {'approve': True, 'tick': 10},
                                          2: {'approve': True, 'tick': 10}})
        institution['inventory'].update(wood=6, iron=1)
        institution['treasury'] = 3
        self.assertNotEqual(LogisticsPolicy().propose(observation)['type'], 'enact')

    def test_member_can_contribute_affordable_personal_reserves_to_a_road(self):
        observation, institution = self.observation()
        self.decision(institution)
        observation['actor']['inventory']['wood'] = 6
        observation['actor']['available_inventory']['wood'] = 6
        proposal = LogisticsPolicy().propose(observation)
        self.assertEqual(proposal['type'], 'contribute')
        self.assertEqual(proposal['params'], {'institution': 0, 'resource': 'wood', 'amount': 6})

    def test_reopening_an_owned_route_can_be_an_independent_collective_goal(self):
        observation, institution = self.observation()
        link = observation['physical']['links'][0]
        link.update(owner=0, condition=.9, closed=True)
        proposal = LogisticsPolicy().propose(observation)
        self.assertEqual(proposal['type'], 'propose')
        self.assertEqual(proposal['params'], {'institution': 0, 'kind': 'route_access',
                                             'params': {'link': 0, 'closed': False}})

    def test_planning_does_not_change_observations_or_read_peer_private_accounts(self):
        observation, _ = self.observation()
        before = copy.deepcopy(observation)
        original = LogisticsPolicy().propose(observation)
        self.assertEqual(observation, before)
        for peer in observation['peers']:
            peer.update(inventory={'food': 999999}, skills=['trading', 'carpentry'])
        self.assertEqual(LogisticsPolicy().propose(observation), original)

    def test_food_emergency_does_not_plan_an_unprovisioned_journey(self):
        observation, _ = self.observation()
        observation['actor']['inventory']['food'] = 0
        observation['actor']['available_inventory']['food'] = 0
        observation['actor']['hunger'] = 90
        observation['settlement']['deposits']['food'] = 0
        observation['physical']['paths'] = {neighbor['id']: {'path': [0], 'duration': 3, 'capacity': 10}
                                             for neighbor in observation['neighbors']}
        self.assertNotEqual(LogisticsPolicy().propose(observation)['type'], 'migrate')

    def test_professional_migration_requires_supplies_and_passage_capacity(self):
        for food, capacity, permitted in ((4, 10, False), (5, .5, False), (5, 10, True)):
            with self.subTest(food=food, capacity=capacity):
                observation, _ = self.observation()
                observation['institutions'] = []
                actor = observation['actor']
                actor.update(role='miner', preferred_purpose='guild', goal={'kind': 'wealth', 'target': 60})
                actor['inventory'].update(food=food, coins=0)
                actor['available_inventory'] = dict(actor['inventory'])
                observation['settlement']['deposits']['iron'] = 0
                for neighbor in observation['neighbors']:
                    neighbor['deposits']['iron'] = 12
                observation['physical']['paths'] = {
                    neighbor['id']: {'path': [0], 'duration': 3, 'capacity': capacity}
                    for neighbor in observation['neighbors']}
                proposal = LogisticsPolicy().propose(observation)
                self.assertEqual(proposal['type'] == 'migrate', permitted, proposal)


if __name__ == '__main__':
    unittest.main()
