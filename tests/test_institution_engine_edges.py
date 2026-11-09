"""Boundary checks for institutional authority and shared spending."""
import copy
import json
import math
import unittest

from eternia.institutional_world import InstitutionalWorld
from eternia.institutions import Institution


class InstitutionEngineEdgeTests(unittest.TestCase):
    def setUp(self):
        self.world = InstitutionalWorld(shock_year=0)
        self.world.tick = 2

    def action(self, actor, action_type, **params):
        return {'actor': actor, 'type': action_type, 'params': params}

    def organization(self, institution_id=0, town=2, members=(0, 1), kind='granary', params=None):
        institution = Institution(institution_id, f'Organization {institution_id}', town,
                                  members=set(members), treasury=6,
                                  inventory={'food': 0., 'wood': 10., 'iron': 2.})
        institution.decisions.append({
            'id': institution_id, 'kind': kind, 'params': params or {},
            'proposer': members[0], 'electorate': list(members),
            'votes': {member: {'approve': True, 'tick': 0} for member in members},
            'created': 0, 'expires': 12, 'status': 'open'})
        self.world.institutions.append(institution)
        self.world.next_institution_id = institution_id + 1
        self.world.next_proposal_id = institution_id + 1
        self.world.initial_totals = self.world.resource_totals()
        return institution

    def state(self):
        return copy.deepcopy((self.world.export(), self.world.rng.getstate(),
                              self.world._institution_budget_tick,
                              self.world._institution_frames,
                              self.world._institution_remaining))

    def test_validating_an_approved_project_is_a_pure_dry_run(self):
        self.organization()
        before = self.state()
        result = self.world.action_engine.validate(self.action(0, 'enact', institution=0, proposal=0))
        self.assertTrue(result.success, result.message)
        self.assertEqual(self.state(), before)

    def test_malformed_nested_proposal_parameters_are_safe_and_atomic(self):
        self.organization()
        malformed = [
            self.action(0, 'propose', institution=0, kind='tax_rate', params={'value': math.nan}),
            self.action(0, 'propose', institution=0, kind='tax_rate', params={'value': True}),
            self.action(0, 'propose', institution=0, kind='tax_rate', params={'value': .04, 'override': True}),
            self.action(0, 'propose', institution=0, kind='trade_agreement', params={'destination': True}),
            self.action(0, 'propose', institution=0, kind='communal_labor', params={'value': {'value': .2}}),
            self.action(0, 'vote', institution=0, proposal=0, approve=1),
            self.action(0, 'contribute', institution=True, resource='coins', amount=1),
        ]
        original = self.state()
        for proposal in malformed:
            self.assertFalse(self.world.action_engine.validate(proposal).success, proposal)
            self.assertEqual(self.state(), original)
        results = self.world.resolve_actions(malformed)
        self.assertTrue(all(not r['result']['success'] for r in results))
        self.assertEqual(self.world.resource_totals(), original[0]['final_totals'])
        self.assertEqual(self.world.institutions[0].decisions, original[0]['institutions'][0]['decisions'])
        json.dumps(self.world.export(), allow_nan=False)

    def test_two_executors_cannot_spend_the_same_mandate_twice(self):
        institution = self.organization()
        before = self.world.resource_totals()
        results = self.world.resolve_actions([
            self.action(0, 'enact', institution=0, proposal=0),
            self.action(1, 'enact', institution=0, proposal=0)])
        self.assertEqual(sum(r['result']['success'] for r in results), 1)
        self.assertEqual(self.world.settlements[2].buildings.get('granary'), 1)
        self.assertEqual(institution.treasury, 0)
        for resource, cost in (('wood', 10), ('iron', 2), ('coins', 6)):
            self.assertAlmostEqual(self.world.resource_totals()[resource], before[resource] - cost)
        self.world._assert_invariants()

    def test_a_reciprocal_mandate_can_authorize_only_one_agreement(self):
        self.world.agents[2].home = self.world.agents[3].home = 0
        self.organization(0, kind='trade_agreement', params={'destination': 0})
        self.organization(1, kind='trade_agreement', params={'destination': 0})
        self.organization(2, town=0, members=(2, 3), kind='trade_agreement', params={'destination': 2})
        totals = self.world.resource_totals()
        results = self.world.resolve_actions([
            self.action(0, 'enact', institution=0, proposal=0),
            self.action(1, 'enact', institution=1, proposal=1)])
        self.assertEqual(sum(r['result']['success'] for r in results), 1)
        self.assertEqual(sum(d['status'] == 'enacted' for i in self.world.institutions for d in i.decisions), 2)
        self.assertEqual(self.world.settlements[0].relations[2], 'trade')
        self.assertEqual(self.world.settlements[2].relations[0], 'trade')
        self.assertEqual(self.world.resource_totals(), totals)


if __name__ == '__main__':
    unittest.main()
