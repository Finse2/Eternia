"""Shared reserves can relieve food shortages only through authorized transfers."""
import copy
import json
import math
import unittest

from eternia.institutional_world import InstitutionalWorld
from eternia.institutions import Institution


class FoodDistributionTests(unittest.TestCase):
    def setUp(self):
        self.world = InstitutionalWorld(seed=42, shock_year=0)
        self.world.tick = 2

    def action(self, actor, action_type='enact', **params):
        return {'actor': actor, 'type': action_type, 'params': params}

    def fixture_totals(self):
        self.world.initial_totals = {
            resource: total - self.world.ledger['produced'][resource]
            + self.world.ledger['consumed'][resource]
            for resource, total in self.world.resource_totals().items()
        }

    def organization(self, *, food=10., amount=6., destination='settlement', member=2):
        institution = Institution(0, 'Food Cooperative', 2, members={0, 1, 2},
                                  inventory={'food': food, 'wood': 0., 'iron': 0.})
        params = {'destination': destination, 'amount': amount}
        if destination == 'member':
            params['member'] = member
        proposal = {
            'id': 0, 'kind': 'distribute_food', 'params': params,
            'proposer': 0, 'electorate': [0, 1, 2],
            'votes': {0: {'approve': True, 'tick': 0},
                      1: {'approve': True, 'tick': 1}},
            'created': 0, 'expires': 12, 'status': 'open',
        }
        institution.decisions.append(proposal)
        self.world.institutions.append(institution)
        self.world.next_institution_id = 1
        self.world.next_proposal_id = 1
        self.fixture_totals()
        return institution, proposal

    def enact(self, actor=0, proposal=0):
        return self.world.resolve_actions([
            self.action(actor, institution=0, proposal=proposal)
        ])[0]

    def assert_conserved(self, before):
        for resource, total in before.items():
            self.assertAlmostEqual(self.world.resource_totals()[resource], total,
                                   msg=resource)
        self.world._assert_invariants()

    def test_approved_release_moves_shared_food_to_settlement_without_a_sink(self):
        institution, proposal = self.organization(food=10, amount=6.25)
        town = self.world.settlements[institution.settlement_id]
        before = self.world.resource_totals()
        before_town = town.food
        consumed = dict(self.world.ledger['consumed'])
        result = self.enact()
        self.assertTrue(result['result']['success'], result)
        self.assertEqual(institution.inventory['food'], 3.75)
        self.assertEqual(town.food, before_town + 6.25)
        self.assertEqual(proposal['status'], 'enacted')
        self.assertEqual(result['result']['effects'].get('costs', {}), {})
        self.assertEqual(self.world.ledger['consumed'], consumed)
        self.assert_conserved(before)

    def test_food_released_to_a_member_requires_a_later_eating_action(self):
        institution, _ = self.organization(amount=2, destination='member')
        recipient = self.world.agents[2]
        recipient.inventory['food'] = 0
        recipient.hunger = 50
        self.fixture_totals()
        before = self.world.resource_totals()
        results = self.world.resolve_actions([
            self.action(0, institution=0, proposal=0),
            self.action(recipient.id, 'eat'),
        ])
        by_actor = {result['action']['actor']: result for result in results}
        self.assertTrue(by_actor[0]['result']['success'], results)
        self.assertFalse(by_actor[recipient.id]['result']['success'], results)
        self.assertEqual(recipient.inventory['food'], 2)
        self.assertEqual(institution.inventory['food'], 8)
        self.assertEqual(recipient.hunger, 50)
        self.assert_conserved(before)
        self.world.advance_time()
        result = self.world.resolve_actions([self.action(recipient.id, 'eat')])[0]
        self.assertTrue(result['result']['success'], result)
        self.assertEqual(recipient.inventory['food'], 1)
        self.assertEqual(recipient.hunger, 15)
        self.assertEqual(self.world.resource_totals()['food'], before['food'] - 1)
        self.world._assert_invariants()

    def test_shared_food_can_prevent_an_aggregate_population_shortage(self):
        institution, _ = self.organization(food=120, amount=120)
        town = self.world.settlements[institution.settlement_id]
        town.food = 0
        self.fixture_totals()
        unreleased = copy.deepcopy(self.world)
        original_population = town.population
        result = self.enact()
        self.assertTrue(result['result']['success'], result)
        self.world._consume_and_demography()
        unreleased._consume_and_demography()
        self.assertGreaterEqual(town.population, original_population)
        self.assertLess(unreleased.settlements[town.id].population, original_population)
        self.assertEqual(unreleased.institutions[0].inventory['food'], 120)
        self.assertEqual(institution.inventory['food'], 0)
        self.world._assert_invariants()
        unreleased._assert_invariants()

    def test_unsupported_or_malformed_distribution_parameters_are_atomic(self):
        institution, _ = self.organization()
        institution.decisions.clear()
        malformed = [
            {'destination': 'settlement', 'amount': amount}
            for amount in (True, False, math.nan, math.inf, -math.inf, 0, -1,
                           1001, '2', None)
        ]
        malformed.extend((
            {}, {'destination': 'settlement'}, {'amount': 2},
            {'destination': 'remote', 'amount': 2},
            {'destination': 0, 'amount': 2},
            {'destination': 'member', 'amount': 2},
            {'destination': 'member', 'member': True, 'amount': 2},
            {'destination': 'member', 'member': 'Toren', 'amount': 2},
            {'destination': 'member', 'member': 999, 'amount': 2},
            {'destination': 'member', 'member': 3, 'amount': 2},
            {'destination': 'settlement', 'member': 2, 'amount': 2},
            {'destination': 'settlement', 'amount': 2, 'override': True},
        ))
        authoritative = copy.deepcopy((self.world.resource_totals(),
                                        institution.public_state(),
                                        self.world.rng.getstate()))
        for params in malformed:
            with self.subTest(params=params):
                result = self.world.submit_action(self.action(
                    0, 'propose', institution=0, kind='distribute_food', params=params))
                self.assertFalse(result.success, params)
                self.assertEqual((self.world.resource_totals(), institution.public_state(),
                                  self.world.rng.getstate()), authoritative)
        json.dumps(self.world.export(), allow_nan=False)

    def test_proposing_and_voting_on_member_aid_does_not_release_food_early(self):
        institution, _ = self.organization()
        institution.decisions.clear()
        recipient = self.world.agents[2]
        recipient.inventory['food'] = 0
        self.fixture_totals()
        result = self.world.resolve_actions([self.action(
            0, 'propose', institution=0, kind='distribute_food',
            params={'destination': 'member', 'member': recipient.id, 'amount': 3})])[0]
        self.assertTrue(result['result']['success'], result)
        proposal = institution.decisions[-1]
        self.assertEqual(institution.inventory['food'], 10)
        self.assertEqual(recipient.inventory['food'], 0)
        self.world.advance_time()
        result = self.world.resolve_actions([self.action(
            1, 'vote', institution=0, proposal=proposal['id'], approve=True)])[0]
        self.assertTrue(result['result']['success'], result)
        self.assertEqual(institution.inventory['food'], 10)
        self.assertEqual(recipient.inventory['food'], 0)
        self.world.advance_time()
        before = self.world.resource_totals()
        result = self.enact(proposal=proposal['id'])
        self.assertTrue(result['result']['success'], result)
        self.assertEqual(institution.inventory['food'], 7)
        self.assertEqual(recipient.inventory['food'], 3)
        self.assert_conserved(before)

    def test_an_outsider_cannot_release_reserves(self):
        institution, proposal = self.organization()
        before = self.world.resource_totals()
        result = self.enact(actor=3)
        self.assertFalse(result['result']['success'], result)
        self.assertEqual(institution.inventory['food'], 10)
        self.assertEqual(proposal['status'], 'open')
        self.assert_conserved(before)

    def test_a_current_tick_vote_cannot_authorize_a_release(self):
        institution, proposal = self.organization()
        proposal['votes'][1]['tick'] = self.world.tick
        before = self.world.resource_totals()
        result = self.enact()
        self.assertFalse(result['result']['success'], result)
        self.assertEqual(institution.inventory['food'], 10)
        self.assert_conserved(before)
        self.world.advance_time()
        self.assertTrue(self.enact()['result']['success'])

    def test_an_approved_release_cannot_exceed_current_shared_reserves(self):
        institution, proposal = self.organization(food=3, amount=6)
        before = self.world.resource_totals()
        before_town = self.world.settlements[2].food
        result = self.enact()
        self.assertFalse(result['result']['success'], result)
        self.assertEqual(institution.inventory['food'], 3)
        self.assertEqual(self.world.settlements[2].food, before_town)
        self.assertEqual(proposal['status'], 'open')
        self.assert_conserved(before)

    def test_a_distribution_plan_is_rechecked_when_reserves_change(self):
        institution, proposal = self.organization(food=6, amount=6)
        checked = self.world.action_engine.validate(self.action(0, institution=0, proposal=0))
        self.assertTrue(checked.success, checked.message)
        institution.inventory['food'] -= 3
        self.world.settlements[2].food += 3
        before = self.world.resource_totals()
        result = self.enact()
        self.assertFalse(result['result']['success'], result)
        self.assertEqual(institution.inventory['food'], 3)
        self.assertEqual(proposal['status'], 'open')
        self.assert_conserved(before)

    def test_a_collapsed_institution_cannot_execute_its_old_food_mandate(self):
        institution, proposal = self.organization(food=10, amount=6)
        institution.members.clear()
        institution.empty_since = self.world.tick - 4
        before = self.world.resource_totals()
        before_town = self.world.settlements[2].food
        result = self.enact()
        self.assertFalse(result['result']['success'], result)
        self.assertFalse(institution.active)
        self.assertEqual(proposal['status'], 'expired')
        # Dissolution returns the estate once; the old mandate cannot also pay.
        self.assertEqual(self.world.settlements[2].food, before_town + 10)
        self.assertEqual(institution.inventory['food'], 0)
        self.assert_conserved(before)

    def test_a_same_tick_contribution_cannot_fund_an_approved_release(self):
        institution, _ = self.organization(food=0, amount=6)
        donor = self.world.agents[1]
        donor.inventory['food'] = 6
        self.fixture_totals()
        before = self.world.resource_totals()
        contribution = self.world.resolve_actions([
            self.action(donor.id, 'contribute', institution=0, resource='food', amount=6)
        ])[0]
        self.assertTrue(contribution['result']['success'], contribution)
        result = self.enact()
        self.assertFalse(result['result']['success'], result)
        self.assertEqual(institution.inventory['food'], 6)
        self.assert_conserved(before)
        self.world.advance_time()
        self.assertTrue(self.enact()['result']['success'])

    def test_two_executors_cannot_distribute_the_same_reserves_twice(self):
        institution, proposal = self.organization(food=6, amount=6)
        before = self.world.resource_totals()
        before_town = self.world.settlements[2].food
        results = self.world.resolve_actions([
            self.action(0, institution=0, proposal=0),
            self.action(1, institution=0, proposal=0),
        ])
        self.assertEqual(sum(result['result']['success'] for result in results), 1)
        self.assertEqual(self.world.settlements[2].food, before_town + 6)
        self.assertEqual(institution.inventory['food'], 0)
        self.assertEqual(proposal['status'], 'enacted')
        self.assert_conserved(before)

    def test_competing_approved_releases_cannot_overdraw_the_food_pool(self):
        institution, proposal = self.organization(food=6, amount=6)
        second = copy.deepcopy(proposal)
        second.update(id=1, params={'destination': 'member', 'member': 2, 'amount': 6})
        institution.decisions.append(second)
        before = self.world.resource_totals()
        results = self.world.resolve_actions([
            self.action(0, institution=0, proposal=0),
            self.action(1, institution=0, proposal=1),
        ])
        self.assertEqual(sum(result['result']['success'] for result in results), 1)
        self.assertEqual(institution.inventory['food'], 0)
        self.assertEqual(sum(p['status'] == 'enacted' for p in institution.decisions), 1)
        self.assert_conserved(before)

    def test_approval_does_not_override_a_missing_recipient(self):
        for invalidation in ('death', 'migration', 'leave'):
            with self.subTest(invalidation=invalidation):
                self.setUp()
                institution, proposal = self.organization(destination='member')
                if invalidation == 'death':
                    self.world.remove_agent(2, cause='test death')
                elif invalidation == 'migration':
                    recipient = self.world.agents[2]
                    self.world.settlements[recipient.home].population -= 1
                    recipient.home = 0
                    self.world.settlements[0].population += 1
                else:
                    institution.members.remove(2)
                before = self.world.resource_totals()
                result = self.enact()
                self.assertFalse(result['result']['success'], result)
                self.assertEqual(institution.inventory['food'], 10)
                self.assertEqual(proposal['status'], 'open')
                self.assert_conserved(before)

    def test_a_new_member_cannot_become_an_existing_proposals_beneficiary(self):
        institution, proposal = self.organization(destination='member', member=3)
        institution.members.add(3)
        before = self.world.resource_totals()
        result = self.enact()
        self.assertFalse(result['result']['success'], result)
        self.assertEqual(institution.inventory['food'], 10)
        self.assertEqual(proposal['status'], 'open')
        self.assert_conserved(before)

    def test_validating_a_distribution_does_not_mutate_authority_or_resources(self):
        self.organization(destination='member')
        before = copy.deepcopy((self.world.export(), self.world.rng.getstate(),
                                self.world._institution_budget_tick,
                                self.world._institution_frames,
                                self.world._institution_remaining))
        result = self.world.action_engine.validate(self.action(0, institution=0, proposal=0))
        self.assertTrue(result.success, result.message)
        self.assertEqual((self.world.export(), self.world.rng.getstate(),
                          self.world._institution_budget_tick,
                          self.world._institution_frames,
                          self.world._institution_remaining), before)


if __name__ == '__main__':
    unittest.main()
