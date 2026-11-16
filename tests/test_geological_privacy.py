"""Undiscovered mineral seams stay private; mining memories retain provenance."""
import copy
import unittest

from eternia.physical_world import PhysicalWorld


class GeologicalPrivacyTests(unittest.TestCase):
    def setUp(self):
        self.world = PhysicalWorld(seed=42, ticks_per_year=12)
        self.miner = self.world._resolve_agent(1)

    def gather(self, amount=2, **overrides):
        proposal = {'actor': self.miner.id, 'type': 'gather',
                    'params': {'resource': 'iron', 'amount': amount}}
        proposal.update(overrides)
        return self.world.resolve_actions([proposal])[0]

    def geology(self, actor=None):
        return self.world.observe(self.miner.id if actor is None else actor)['physical']['geology']

    def fixture_totals(self):
        self.world.initial_totals = {
            resource: total - self.world.ledger['produced'][resource]
            + self.world.ledger['consumed'][resource]
            for resource, total in self.world.resource_totals().items()}

    def test_unknown_reserves_cannot_change_observations_or_autonomous_choices(self):
        audit = self.gather()
        self.assertTrue(audit['result']['success'], audit)
        other = copy.deepcopy(self.world)
        other.mineral_reserves = {0: 0., 1: 1_000_000., 2: 1.}
        other.initial_mineral_reserves = {0: 10_000., 1: 2_000_000., 2: 5_000.}

        # Only hidden geology differs: stocks, memories and public history are
        # identical, so every agent must receive the same decision inputs.
        observations = self.world.observe_agents()
        self.assertEqual(observations, other.observe_agents())
        self.assertEqual(self.world.plan(observations), other.plan(other.observe_agents()))

    def test_initial_observations_have_no_reserve_table_at_any_depth(self):
        def assert_private(value):
            if isinstance(value, dict):
                self.assertNotIn('mineral_reserves', value)
                self.assertNotIn('initial_mineral_reserves', value)
                for child in value.values():
                    assert_private(child)
            elif isinstance(value, (tuple, list)):
                for child in value:
                    assert_private(child)

        for observation in self.world.observe_agents().values():
            assert_private(observation)
            self.assertEqual(observation['physical']['geology'], [])
            self.assertIn('iron', observation['settlement']['deposits'])

    def test_success_records_only_actual_personal_collection(self):
        before = self.miner.inventory['iron']
        audit = self.gather(amount=2)
        self.assertTrue(audit['result']['success'], audit)
        self.assertEqual(self.geology(), [{
            'settlement': 0, 'tick': 0, 'source': 'personal_mining',
            'finding': 'iron_collected',
            'amount': self.miner.inventory['iron'] - before,
            'reserve_estimate': None}])

    def test_peers_and_other_settlements_do_not_receive_private_mining_memories(self):
        self.assertTrue(self.gather()['result']['success'])
        self.assertTrue(self.geology())
        self.assertEqual(self.geology(0), [])  # A neighbor in the same settlement.
        self.assertEqual(self.geology(6), [])  # A resident of another settlement.
        for peer in self.world.observe(0)['peers']:
            self.assertNotIn('memory', peer)
            self.assertNotIn('geology', peer)

    def test_empty_accessible_stock_does_not_reveal_buried_exhaustion(self):
        self.world.settlements[0].deposits['iron'] = 0.
        self.assertGreater(self.world.mineral_reserves[0], 0.)
        audit = self.gather(amount=1)
        self.assertEqual(audit['result']['code'], 'depleted', audit)
        evidence = [{
            'settlement': 0, 'tick': 0, 'source': 'personal_mining',
            'finding': 'accessible_stock_unavailable', 'amount': 0.,
            'reserve_estimate': None}]
        self.assertEqual(self.geology(), evidence)
        self.world.mineral_reserves[0] = 0.
        self.assertEqual(self.geology(), evidence)

    def test_failed_mining_keeps_its_historical_location_after_physical_migration(self):
        self.world.settlements[0].deposits['iron'] = 0.
        proposal = {'actor': self.miner.id, 'type': 'gather',
                    'params': {'resource': 'iron', 'amount': 1}}
        original = copy.deepcopy(proposal)
        audit = self.world.resolve_actions([proposal])[0]
        self.assertEqual(audit['result']['code'], 'depleted', audit)
        self.assertEqual(proposal, original, 'Resolution must not rewrite caller input.')
        evidence = copy.deepcopy(self.geology())
        self.assertEqual(evidence[0]['settlement'], 0)

        self.world.tick += 1
        self.miner.inventory['food'] = 30.
        for link in self.world.links:
            link.update(condition=1., risk=0., closed=False)
        self.fixture_totals()
        result = self.world.resolve_actions([{
            'actor': self.miner.id, 'type': 'migrate',
            'params': {'destination': 1}}])[0]['result']
        self.assertTrue(result['success'], result)
        journey = self.world.journeys[-1]
        for _ in range(40):
            if journey['status'] != 'in_transit':
                break
            self.world.tick += 1
            self.world._advance_journeys()
        self.assertEqual(journey['status'], 'delivered', journey)
        self.assertEqual(self.miner.home, 1)
        self.assertEqual(self.geology(), evidence)
        self.world._assert_invariants()

    def test_named_actor_and_location_are_canonicalized_even_when_mining_fails(self):
        self.world.settlements[0].deposits['iron'] = 0.
        audit = self.gather(amount=1, actor=self.miner.name,
                            location=self.world.settlements[0].name)
        self.assertEqual(audit['result']['code'], 'depleted', audit)
        self.assertEqual(audit['action']['actor'], self.miner.id)
        self.assertEqual(audit['action']['location'], self.miner.home)
        self.assertEqual(self.geology()[0]['finding'], 'accessible_stock_unavailable')

    def test_competing_miners_remember_their_own_resolved_outcomes(self):
        competitor = self.world._resolve_agent(0)
        competitor.skills.append('mining')
        self.world.settlements[0].deposits['iron'] = 2.
        audits = self.world.resolve_actions([
            {'actor': actor.id, 'type': 'gather',
             'params': {'resource': 'iron', 'amount': 2}}
            for actor in (self.miner, competitor)])
        self.assertEqual(sum(audit['result']['success'] for audit in audits), 1)
        for audit in audits:
            evidence = self.geology(audit['action']['actor'])
            if audit['result']['success']:
                self.assertEqual(evidence[0]['finding'], 'iron_collected')
                self.assertEqual(evidence[0]['amount'], 2.)
            else:
                self.assertEqual(audit['result']['code'], 'conflict')
                self.assertEqual(audit['result']['effects']['cause'], 'depleted')
                self.assertEqual(evidence[0]['finding'], 'accessible_stock_unavailable')
                self.assertEqual(evidence[0]['amount'], 0.)
            self.assertIsNone(evidence[0]['reserve_estimate'])

    def test_permission_rejection_provides_no_geological_evidence(self):
        self.world.settlements[0].permissions['gather'] = False
        audit = self.gather()
        self.assertFalse(audit['result']['success'], audit)
        self.assertNotEqual(audit['result']['code'], 'depleted')
        self.assertEqual(self.geology(), [])

    def test_successor_gets_inherited_accounts_with_original_time_and_place(self):
        self.assertTrue(self.gather()['result']['success'])
        evidence = self.geology()
        self.world.tick = 8
        successor = self.world.remove_agent(self.miner.id, 'fixture succession')
        inherited = self.geology(successor.id)
        self.assertEqual(inherited, [{**evidence[0], 'source': 'inherited_mining_account'}])
        self.assertEqual(self.geology(0), [])

    def test_another_persons_record_is_not_personal_evidence_without_inheritance(self):
        audit = self.gather()
        self.assertTrue(audit['result']['success'], audit)
        observer = self.world._resolve_agent(0)
        observer.memory.append(copy.deepcopy(audit))
        self.assertEqual(self.geology(observer.id), [])

    def test_latest_local_attempt_replaces_older_evidence_without_live_truth_refresh(self):
        self.assertTrue(self.gather()['result']['success'])
        self.world.tick = 1
        self.world.settlements[0].deposits['iron'] = 0.
        self.assertEqual(self.gather(amount=1)['result']['code'], 'depleted')
        evidence = self.geology()
        self.assertEqual(len(evidence), 1)
        self.assertEqual(evidence[0]['tick'], 1)
        self.assertEqual(evidence[0]['finding'], 'accessible_stock_unavailable')
        self.world.tick = 20
        self.world.mineral_reserves[0] = 1_000.
        self.world.settlements[0].deposits['iron'] = 10.
        self.assertEqual(self.geology(), evidence)

    def test_observation_evidence_is_detached_from_memory_and_does_not_use_randomness(self):
        self.assertTrue(self.gather()['result']['success'])
        memory = copy.deepcopy(self.miner.memory)
        random_state = self.world.rng.getstate()
        evidence = self.geology()
        evidence[0]['amount'] = 9_999.
        self.assertEqual(self.geology()[0]['amount'], 2.)
        self.assertEqual(self.miner.memory, memory)
        self.assertEqual(self.world.rng.getstate(), random_state)

    def test_authoritative_exports_keep_reserve_truth_for_history(self):
        data = self.world.export()
        self.assertEqual(data['schema'], 'eternia.v0.6.1')
        self.assertEqual(data['mineral_reserves'], self.world.mineral_reserves)
        self.assertEqual(data['initial_mineral_reserves'], self.world.initial_mineral_reserves)
        self.assertEqual(data['snapshots'][0]['mineral_reserves'], self.world.mineral_reserves)
        data['mineral_reserves'][0] = -1.
        data['snapshots'][0]['mineral_reserves'][0] = -2.
        self.assertEqual(self.world.mineral_reserves[0], 40.)
        self.assertEqual(self.world.snapshots[0]['mineral_reserves'][0], 40.)


if __name__ == '__main__':
    unittest.main()
