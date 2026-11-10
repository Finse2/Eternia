"""Institutional authority and tick isolation for physical infrastructure."""
import copy
import unittest

from eternia.physical_world import PhysicalWorld
from eternia.regional_engine import RegionalInstitution
from eternia.logistics_engine import ROAD_COSTS


class LogisticsEngineTests(unittest.TestCase):
    def setUp(self):
        self.world = PhysicalWorld(seed=42, ticks_per_year=12)
        self.world.tick = 2
        self.institution = RegionalInstitution(0, 'Road Council', 0,
                                               members={0, 1}, purpose='council')
        self.institution.inventory.update(wood=12., iron=2.)
        self.institution.treasury = 6.
        self.world.institutions.append(self.institution)
        self.world.next_institution_id = 1
        self.link = next(link for link in self.world.links if 0 in (link['a'], link['b']))
        self.link['condition'] = .3
        self.fixture_totals()

    def fixture_totals(self):
        self.world.initial_totals = {
            resource: total - self.world.ledger['produced'][resource]
            + self.world.ledger['consumed'][resource]
            for resource, total in self.world.resource_totals().items()}

    def proposal(self, kind='repair_route', params=None, same_tick_vote=False):
        proposal = {'id': self.world.next_proposal_id, 'kind': kind,
                    'params': params or {'link': self.link['id']},
                    'electorate': [0, 1], 'created': 0, 'expires': 20,
                    'votes': {0: {'approve': True, 'tick': 0},
                              1: {'approve': True,
                                  'tick': self.world.tick if same_tick_vote else 0}},
                    'status': 'open'}
        self.world.next_proposal_id += 1
        self.institution.decisions.append(proposal)
        return proposal

    def enact(self, proposal, actor=0):
        return self.world.resolve_actions([{
            'actor': actor, 'type': 'enact',
            'params': {'institution': self.institution.id, 'proposal': proposal['id']}
        }])[0]['result']

    def test_prior_majority_can_fund_a_repair_and_claim_an_unowned_link(self):
        proposal = self.proposal()
        before = self.world.resource_totals()
        result = self.enact(proposal)
        self.assertTrue(result['success'], result)
        self.assertAlmostEqual(self.link['condition'], .75)
        self.assertEqual(self.link['owner'], self.institution.id)
        self.assertEqual(proposal['status'], 'enacted')
        for resource, total in before.items():
            self.assertAlmostEqual(self.world.resource_totals()[resource],
                                   total - ROAD_COSTS.get(resource, 0))
        self.world._assert_invariants()

    def test_same_tick_votes_do_not_authorize_public_works(self):
        proposal = self.proposal(same_tick_vote=True)
        before = self.world.resource_totals()
        result = self.enact(proposal)
        self.assertFalse(result['success'], result)
        self.assertEqual(self.link['condition'], .3)
        self.assertEqual(self.world.resource_totals(), before)

    def test_a_nonmember_cannot_execute_a_road_mandate(self):
        result = self.enact(self.proposal(), actor=2)
        self.assertFalse(result['success'], result)
        self.assertIsNone(self.link['owner'])

    def test_an_institution_cannot_claim_a_link_without_a_local_endpoint(self):
        remote = next(link for link in self.world.links if 0 not in (link['a'], link['b']))
        remote['condition'] = .3
        result = self.enact(self.proposal(params={'link': remote['id']}))
        self.assertFalse(result['success'], result)
        self.assertIsNone(remote['owner'])

    def test_repair_cannot_seize_another_institutions_link(self):
        self.link['owner'] = 99
        result = self.enact(self.proposal())
        self.assertFalse(result['success'], result)
        self.assertEqual(self.link['owner'], 99)
        self.assertEqual(self.link['condition'], .3)

    def test_only_the_owner_can_change_access(self):
        self.link['owner'] = 99
        result = self.enact(self.proposal('route_access',
                                          {'link': self.link['id'], 'closed': True}))
        self.assertFalse(result['success'], result)
        self.assertFalse(self.link['closed'])

    def test_an_owners_prior_majority_can_close_its_link(self):
        self.link['owner'] = self.institution.id
        result = self.enact(self.proposal('route_access',
                                          {'link': self.link['id'], 'closed': True}))
        self.assertTrue(result['success'], result)
        self.assertTrue(self.link['closed'])

    def test_new_contributions_cannot_finance_repairs_in_the_same_tick(self):
        self.institution.inventory.update(wood=0., iron=1.)
        self.institution.treasury = 3.
        self.world.agents[0].inventory['wood'] = 6.
        proposal = self.proposal()
        self.fixture_totals()
        contribution = self.world.resolve_actions([{
            'actor': 0, 'type': 'contribute',
            'params': {'institution': 0, 'resource': 'wood', 'amount': 6}
        }])[0]['result']
        self.assertTrue(contribution['success'], contribution)
        result = self.enact(proposal, actor=1)
        self.assertFalse(result['success'], result)
        self.assertEqual(self.link['condition'], .3)
        self.assertEqual(self.institution.inventory['wood'], 6.)
        self.world._assert_invariants()

    def test_validation_of_a_road_mandate_is_a_pure_dry_run(self):
        proposal = self.proposal()
        action = {'actor': 0, 'type': 'enact',
                  'params': {'institution': 0, 'proposal': proposal['id']}}
        before = copy.deepcopy(self.world.export())
        random_state = self.world.rng.getstate()
        result = self.world.action_engine.validate(action)
        self.assertTrue(result.success, result)
        self.assertEqual(self.world.export(), before)
        self.assertEqual(self.world.rng.getstate(), random_state)

    def test_a_new_repair_does_not_enable_migration_until_the_next_tick(self):
        for link in self.world.links:
            link['condition'] = 0.
        actor = self.world.agents[2]
        actor.inventory['food'] = 30.
        self.fixture_totals()
        proposal = self.proposal()
        result = self.enact(proposal)
        self.assertTrue(result['success'], result)
        destination = self.link['b'] if self.link['a'] == 0 else self.link['a']
        movement = {'actor': actor.id, 'type': 'migrate',
                    'params': {'destination': destination}}
        result = self.world.resolve_actions([movement])[0]['result']
        self.assertFalse(result['success'], result)
        self.assertFalse(self.world.is_traveling(actor.id))
        self.world.tick += 1
        result = self.world.resolve_actions([movement])[0]['result']
        self.assertTrue(result['success'], result)
        self.assertTrue(self.world.is_traveling(actor.id))

    def test_a_newly_claimed_link_does_not_grant_immediate_access_authority(self):
        repair = self.proposal()
        result = self.enact(repair)
        self.assertTrue(result['success'], result)
        result = self.world.resolve_actions([{
            'actor': 1, 'type': 'propose',
            'params': {'institution': 0, 'kind': 'route_access',
                       'params': {'link': self.link['id'], 'closed': True}}
        }])[0]['result']
        self.assertFalse(result['success'], result)
        self.assertFalse(self.link['closed'])


if __name__ == '__main__':
    unittest.main()
