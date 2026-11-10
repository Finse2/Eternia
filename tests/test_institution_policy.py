"""Collective choices depend on public need, personal cost and old votes."""
import copy
import unittest

from eternia.community import CommunityWorld
from eternia.institution_policy import InstitutionalPolicy


class InstitutionalPolicyTests(unittest.TestCase):
    def observation(self):
        world = CommunityWorld(shock_year=0)
        observation = world.observe(0)
        observation['tick'] = 3
        observation['institutions'] = []
        return observation

    def institution(self, observation):
        institution = {'id': 4, 'name': 'Highfen Cooperative', 'settlement_id': 2,
                       'members': [0, 1], 'treasury': 6,
                       'inventory': {'food': 0, 'wood': 10, 'iron': 2},
                       'rules': {'communal_labor': .2, 'tax_rate': .04},
                       'decisions': [], 'active': True}
        observation['institutions'] = [institution]
        return institution

    def test_common_food_pressure_can_motivate_formation(self):
        observation = self.observation()
        proposal = InstitutionalPolicy().propose(observation)
        self.assertEqual(proposal['type'], 'form_institution')

    def test_local_nonmember_joins_without_reading_shared_accounts(self):
        observation = self.observation()
        institution = self.institution(observation)
        institution['members'] = [1, 2]
        del institution['treasury']
        del institution['inventory']
        proposal = InstitutionalPolicy().propose(observation)
        self.assertEqual(proposal['type'], 'join_institution')

    def test_hunger_precedes_an_institutional_opportunity(self):
        observation = self.observation()
        observation['actor']['hunger'] = 90
        proposal = InstitutionalPolicy().propose(observation)
        self.assertEqual(proposal['type'], 'eat')

    def test_pooled_food_can_be_proposed_for_a_settlement_shortage(self):
        observation = self.observation()
        institution = self.institution(observation)
        institution['inventory']['food'] = 50
        observation['settlement']['food'] = observation['settlement']['population'] - 20
        proposal = InstitutionalPolicy().propose(observation)
        self.assertEqual(proposal['type'], 'propose')
        self.assertEqual(proposal['params'], {'institution': institution['id'],
            'kind': 'distribute_food', 'params': {'destination': 'settlement', 'amount': 20}})

    def test_low_personal_reserves_can_motivate_a_bounded_member_request(self):
        observation = self.observation()
        institution = self.institution(observation)
        institution['inventory']['food'] = 20
        observation['actor']['inventory']['food'] = 1
        observation['actor']['available_inventory']['food'] = 1
        proposal = InstitutionalPolicy().propose(observation)
        self.assertEqual(proposal['type'], 'propose')
        self.assertEqual(proposal['params']['params'], {
            'destination': 'member', 'member': observation['actor']['id'], 'amount': 2})

    def food_decision(self, institution, params):
        decision = {'id': 9, 'kind': 'distribute_food', 'params': params,
                    'status': 'open', 'electorate': list(institution['members']),
                    'created': 1, 'expires': 13,
                    'votes': {0: {'approve': True, 'tick': 1},
                              1: {'approve': True, 'tick': 2}}}
        institution['decisions'] = [decision]
        return decision

    def test_funded_food_release_uses_only_a_prior_tick_majority(self):
        observation = self.observation()
        institution = self.institution(observation)
        institution['inventory']['food'] = 5
        decision = self.food_decision(institution, {'destination': 'settlement', 'amount': 4})
        self.assertEqual(InstitutionalPolicy().propose(observation)['type'], 'enact')
        decision['votes'][1]['tick'] = observation['tick']
        self.assertNotEqual(InstitutionalPolicy().propose(observation)['type'], 'enact')

    def test_an_unfunded_food_release_is_not_repeatedly_enacted(self):
        observation = self.observation()
        institution = self.institution(observation)
        institution['inventory']['food'] = 5
        institution['available_inventory'] = {'food': 0, 'wood': 10, 'iron': 2, 'coins': 6}
        self.food_decision(institution, {'destination': 'settlement', 'amount': 4})
        self.assertNotEqual(InstitutionalPolicy().propose(observation)['type'], 'enact')

    def test_a_member_can_approve_a_bounded_public_food_request(self):
        observation = self.observation()
        institution = self.institution(observation)
        institution['inventory']['food'] = 5
        decision = self.food_decision(institution, {'destination': 'member', 'member': 1, 'amount': 2})
        del decision['votes'][0]
        proposal = InstitutionalPolicy().propose(observation)
        self.assertEqual(proposal['type'], 'vote')
        self.assertTrue(proposal['params']['approve'])

    def test_distribution_without_a_visible_need_receives_a_no_vote(self):
        observation = self.observation()
        institution = self.institution(observation)
        institution['inventory']['food'] = 5
        observation['settlement']['food'] = observation['settlement']['population'] * 2
        decision = self.food_decision(institution, {'destination': 'settlement', 'amount': 4})
        del decision['votes'][0]
        proposal = InstitutionalPolicy().propose(observation)
        self.assertEqual(proposal['type'], 'vote')
        self.assertFalse(proposal['params']['approve'])

    def test_surplus_food_can_be_pooled_without_dipping_into_personal_reserves(self):
        observation = self.observation()
        institution = self.institution(observation)
        observation['settlement']['buildings']['granary'] = 1
        observation['actor']['inventory']['food'] = 8
        observation['actor']['available_inventory']['food'] = 8
        proposal = InstitutionalPolicy().propose(observation)
        self.assertEqual(proposal['type'], 'contribute')
        self.assertEqual(proposal['params']['resource'], 'food')
        self.assertLessEqual(proposal['params']['amount'], 5)

    def test_an_acute_food_need_precedes_an_approved_food_release(self):
        observation = self.observation()
        institution = self.institution(observation)
        institution['inventory']['food'] = 5
        self.food_decision(institution, {'destination': 'settlement', 'amount': 4})
        observation['actor']['hunger'] = 90
        self.assertEqual(InstitutionalPolicy().propose(observation)['type'], 'eat')

    def test_urgent_food_migration_precedes_a_ready_collective_project(self):
        observation = self.observation()
        observation['actor']['hunger'] = 90
        observation['actor']['inventory']['food'] = 0
        observation['actor']['available_inventory']['food'] = 0
        observation['settlement']['deposits']['food'] = 0
        institution = self.institution(observation)
        institution['decisions'] = [{'id': 9, 'kind': 'granary', 'params': {},
                                    'status': 'open', 'electorate': [0, 1],
                                    'created': 1, 'expires': 13,
                                    'votes': {0: {'approve': True, 'tick': 1},
                                              1: {'approve': True, 'tick': 2}}}]
        self.assertEqual(InstitutionalPolicy().propose(observation)['type'], 'migrate')

    def test_surplus_is_contributed_without_spending_personal_reserves(self):
        observation = self.observation()
        institution = self.institution(observation)
        institution['inventory']['iron'] = 0
        proposal = InstitutionalPolicy().propose(observation)
        self.assertEqual(proposal['type'], 'contribute')
        self.assertEqual(proposal['params']['resource'], 'iron')
        self.assertLessEqual(proposal['params']['amount'], 2)

    def test_old_majority_is_enacted_but_same_tick_votes_are_not(self):
        observation = self.observation()
        institution = self.institution(observation)
        institution['decisions'] = [{'id': 9, 'kind': 'granary', 'params': {},
                                    'status': 'open', 'electorate': [0, 1],
                                    'created': 1, 'expires': 13,
                                    'votes': {0: {'approve': True, 'tick': 1},
                                              1: {'approve': True, 'tick': 2}}}]
        self.assertEqual(InstitutionalPolicy().propose(observation)['type'], 'enact')
        institution['decisions'][0]['votes'][1]['tick'] = 3
        self.assertNotEqual(InstitutionalPolicy().propose(observation)['type'], 'enact')

    def test_costly_levy_receives_an_independent_no_vote(self):
        observation = self.observation()
        observation['actor']['inventory']['coins'] = 5
        observation['actor']['available_inventory']['coins'] = 5
        institution = self.institution(observation)
        institution['decisions'] = [{'id': 9, 'kind': 'tax_rate', 'params': {'value': .12},
                                    'status': 'open', 'electorate': [0, 1],
                                    'created': 1, 'expires': 13,
                                    'votes': {1: {'approve': True, 'tick': 1}}}]
        proposal = InstitutionalPolicy().propose(observation)
        self.assertEqual(proposal['type'], 'vote')
        self.assertFalse(proposal['params']['approve'])

    def test_funded_project_and_reserve_motivate_ending_a_levy(self):
        observation = self.observation()
        institution = self.institution(observation)
        institution['treasury'] = 20
        observation['settlement']['buildings']['granary'] = 1
        proposal = InstitutionalPolicy().propose(observation)
        self.assertEqual(proposal['type'], 'propose')
        self.assertEqual(proposal['params']['kind'], 'tax_rate')
        self.assertEqual(proposal['params']['params']['value'], 0)

    def test_waiting_for_materials_does_not_justify_an_already_funded_levy(self):
        observation = self.observation()
        institution = self.institution(observation)
        institution['treasury'] = 20
        institution['inventory']['wood'] = 0
        proposal = InstitutionalPolicy().propose(observation)
        self.assertEqual(proposal['type'], 'propose')
        self.assertEqual(proposal['params'], {'institution': institution['id'],
                                             'kind': 'tax_rate', 'params': {'value': 0}})

    def test_poor_member_can_vote_to_remove_a_levy(self):
        observation = self.observation()
        observation['actor']['available_inventory']['coins'] = 1
        institution = self.institution(observation)
        institution['decisions'] = [{'id': 9, 'kind': 'tax_rate', 'params': {'value': 0},
                                    'status': 'open', 'electorate': [0, 1],
                                    'created': 1, 'expires': 13,
                                    'votes': {1: {'approve': True, 'tick': 1}}}]
        proposal = InstitutionalPolicy().propose(observation)
        self.assertEqual(proposal['type'], 'vote')
        self.assertTrue(proposal['params']['approve'])

    def test_member_can_leave_a_burdensome_group_without_quorum(self):
        observation = self.observation()
        observation['tick'] = 20
        observation['actor']['available_inventory']['coins'] = 1
        institution = self.institution(observation)
        institution.update(members=[0], treasury=20, founded=0)
        proposal = InstitutionalPolicy().propose(observation)
        self.assertEqual(proposal['type'], 'leave_institution')

    def test_poor_nonmember_does_not_immediately_rejoin_a_levying_group(self):
        observation = self.observation()
        observation['actor']['available_inventory']['coins'] = 1
        institution = self.institution(observation)
        institution['members'] = [1]
        self.assertNotEqual(InstitutionalPolicy().propose(observation)['type'], 'join_institution')

    def test_public_reciprocal_request_motivates_a_trade_proposal(self):
        observation = self.observation()
        observation['settlement']['buildings']['granary'] = 1
        institution = self.institution(observation)
        institution['rules']['tax_rate'] = 0
        neighbor = observation['neighbors'][0]
        observation['institutions'].append({'id': 7, 'name': 'Neighbor Cooperative',
            'settlement_id': neighbor['id'], 'members': [20, 21], 'active': True,
            'decisions': [{'id': 19, 'kind': 'trade_agreement', 'status': 'open',
                          'params': {'destination': observation['settlement']['id']},
                          'electorate': [20, 21], 'created': 1, 'expires': 13,
                          'votes': {20: {'approve': True, 'tick': 1}}}]})
        proposal = InstitutionalPolicy().propose(observation)
        self.assertEqual(proposal['type'], 'propose')
        self.assertEqual(proposal['params']['kind'], 'trade_agreement')
        self.assertEqual(proposal['params']['params']['destination'], neighbor['id'])

    def test_planning_preserves_the_detached_observation(self):
        observation = self.observation()
        self.institution(observation)
        before = copy.deepcopy(observation)
        InstitutionalPolicy().propose(observation)
        self.assertEqual(observation, before)


if __name__ == '__main__':
    unittest.main()
