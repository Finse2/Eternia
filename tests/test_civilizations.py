"""Regional behavior, finite flows, political choices and replay."""
import copy
import json
import unittest

from eternia.civilizations import CivilizationWorld
from eternia.regional_engine import RegionalInstitution


class CivilizationTests(unittest.TestCase):
    def setUp(self):
        self.world = CivilizationWorld(seed=42, shock_year=0)

    def action(self, actor, action_type, **params):
        return {'actor': actor, 'type': action_type, 'params': params}

    def fixture_totals(self):
        self.world.initial_totals = {
            resource: amount - self.world.ledger['produced'][resource]
            + self.world.ledger['consumed'][resource]
            for resource, amount in self.world.resource_totals().items()}

    def organization(self, institution_id, town, members, *, purpose='guild',
                     kind='trade_terms', params=None, expires=20):
        institution = RegionalInstitution(institution_id, f'Organization {institution_id}',
                                           town, members=set(members), purpose=purpose)
        if params is not None:
            institution.decisions.append({
                'id': institution_id, 'kind': kind, 'params': params,
                'proposer': members[0], 'electorate': list(members),
                'votes': {member: {'approve': True, 'tick': 0} for member in members},
                'created': 0, 'expires': expires, 'status': 'open'})
        self.world.institutions.append(institution)
        self.world.next_institution_id = max(self.world.next_institution_id, institution_id + 1)
        self.world.next_proposal_id = max(self.world.next_proposal_id, institution_id + 1)
        self.fixture_totals()
        return institution

    def trading_pair(self):
        self.world.tick = 2
        terms = {'resource': 'food', 'unit_price': .2, 'quota': 20}
        exporter = self.organization(0, 0, (0, 1),
                                     params={**terms, 'destination': 1, 'direction': 'export'})
        importer = self.organization(1, 1, (6, 7),
                                     params={**terms, 'destination': 0, 'direction': 'import'})
        results = self.world.resolve_actions([
            self.action(0, 'enact', institution=exporter.id, proposal=0)])
        self.assertTrue(results[0]['result']['success'], results)
        self.world.advance_time()
        return exporter, importer

    def test_each_founding_settlement_has_independent_people_and_resources(self):
        self.assertEqual(len(self.world.settlements), 3)
        self.assertEqual(len(self.world.agents), 18)
        self.assertEqual([sum(a.home == town.id for a in self.world.agents)
                          for town in self.world.settlements], [6, 6, 6])
        self.assertEqual(len({a.id for a in self.world.agents}), 18)
        self.assertEqual(len({(town.fertility, town.forest, town.ore)
                              for town in self.world.settlements}), 3)
        self.assertFalse(self.world.institutions)
        self.assertFalse(self.world.routes)
        self.assertTrue(all(not town.relations for town in self.world.settlements))

    def test_every_town_plans_from_the_same_detached_tick(self):
        observations = self.world.observe_agents()
        self.assertEqual({o['tick'] for o in observations.values()}, {0})
        self.assertEqual(len({o['actor']['home'] for o in observations.values()}), 3)
        proposals = self.world.plan(observations)
        self.assertEqual({p['actor'] for p in proposals}, {a.id for a in self.world.agents})
        observations[0]['actor']['inventory']['coins'] = 99999
        self.assertNotEqual(self.world.agents[0].inventory['coins'], 99999)

    def test_foreign_shared_balances_and_peer_private_state_are_not_visible(self):
        self.organization(0, 1, (6, 7))
        self.world.institutions[0].treasury = 9876
        self.world.institutions[0].inventory['iron'] = 8765
        observer = self.world.observe(0)
        organization = next(i for i in observer['institutions'] if i['id'] == 0)
        self.assertNotIn('inventory', organization)
        self.assertNotIn('treasury', organization)
        for peer in observer['peers']:
            self.assertNotIn('inventory', peer)
            self.assertNotIn('skills', peer)
            self.assertNotIn('knowledge', peer)

    def test_private_wealth_stays_out_of_policy_profiles_but_is_recorded_for_history(self):
        self.world.agents[6].inventory['coins'] = 9876
        organization = self.organization(0, 1, (6, 7))
        organization.treasury = 8765
        self.fixture_totals()
        observation = self.world.observe(0)
        self.assertTrue(observation['regional']['profiles'])
        for profile in observation['regional']['profiles'].values():
            self.assertNotIn('wealth', profile)
        recorded = self.world.regional_metrics()['per_settlement'][1]
        self.assertGreaterEqual(recorded['wealth'], 9876 + 8765)
        data = self.world.export()
        self.assertEqual(data['regional_metrics']['per_settlement'][1]['wealth'],
                         recorded['wealth'])

    def test_default_has_no_scheduled_shock_and_optional_shock_targets_highfen(self):
        self.world.year = 8
        before = [dict(town.deposits) for town in self.world.settlements]
        self.world._shock()
        self.assertEqual([town.deposits for town in self.world.settlements], before)
        self.assertFalse(any(e['kind'] == 'disruption' for e in self.world.events))
        shocked = CivilizationWorld(seed=42, shock_year=8)
        shocked.year = 8
        before = [dict(town.deposits) for town in shocked.settlements]
        ore = shocked.settlements[1].ore
        shocked._shock()
        self.assertEqual(shocked.settlements[1].name, 'Highfen')
        self.assertEqual(shocked.settlements[1].deposits['iron'], 0)
        self.assertLess(shocked.settlements[1].ore, ore)
        self.assertEqual(shocked.settlements[2].deposits, before[2])
        disruption = next(e for e in shocked.events if e['kind'] == 'disruption')
        self.assertEqual(disruption['settlement'], 'Highfen')
        shocked._assert_invariants()

    def test_negotiated_shipments_transfer_finite_goods_and_coins(self):
        self.trading_pair()
        seller, buyer = self.world.settlements[:2]
        seller.food = seller.population * 2 + 30
        buyer.food = 0
        buyer.treasury = 20
        self.fixture_totals()
        before = self.world.resource_totals()
        seller_food, buyer_food, buyer_coins = seller.food, buyer.food, buyer.treasury
        self.world._institutional_trade()
        self.assertGreater(buyer.food, buyer_food)
        self.assertLess(seller.food, seller_food)
        self.assertLess(buyer.treasury, buyer_coins)
        self.assertEqual(len(self.world.trade_shipments), 1)
        for resource, amount in before.items():
            self.assertAlmostEqual(self.world.resource_totals()[resource], amount)
        self.world._assert_invariants()

    def test_an_embargo_can_suspend_an_approved_route(self):
        exporter, _ = self.trading_pair()
        proposal = {'id': 2, 'kind': 'embargo', 'params': {'destination': 1, 'enabled': True},
                    'proposer': 0, 'electorate': [0, 1],
                    'votes': {0: {'approve': True, 'tick': 0}, 1: {'approve': True, 'tick': 1}},
                    'created': 0, 'expires': 20, 'status': 'open'}
        exporter.decisions.append(proposal)
        self.world.next_proposal_id = 3
        result = self.world.resolve_actions([
            self.action(0, 'enact', institution=0, proposal=2)])[0]
        self.assertTrue(result['result']['success'], result)
        self.world.advance_time()
        seller, buyer = self.world.settlements[:2]
        seller.food = seller.population * 2 + 30
        buyer.food = 0
        self.fixture_totals()
        before = self.world.resource_totals()
        shipments = len(self.world.trade_shipments)
        self.world._institutional_trade()
        self.assertEqual(len(self.world.trade_shipments), shipments)
        self.assertEqual(buyer.food, 0)
        self.assertEqual(self.world.resource_totals(), before)

    def test_migration_moves_a_person_and_resident_count_without_moving_property(self):
        actor = self.world.agents[0]
        institution = self.organization(0, actor.home, (0, 1), purpose='cooperative')
        actor.structures['house'] = 1
        self.world.settlements[actor.home].buildings['house'] = 1
        inventory = dict(actor.inventory)
        population = sum(town.population for town in self.world.settlements)
        origin = actor.home
        result = self.world.resolve_actions([
            self.action(actor.id, 'migrate', destination=1)])[0]
        self.assertTrue(result['result']['success'], result)
        self.assertEqual(actor.home, 1)
        self.assertEqual(actor.inventory, inventory)
        self.assertNotIn(actor.id, institution.members)
        self.assertEqual(self.world.settlements[origin].buildings['house'], 1)
        self.assertEqual(actor.structures['house'], 1)
        self.assertEqual(sum(town.population for town in self.world.settlements), population)
        self.assertGreaterEqual(self.world.metrics['regional_migrations'], 1)

    def test_a_majority_council_can_refuse_incoming_migration(self):
        self.world.tick = 2
        council = self.organization(0, 1, (6, 7, 8, 9), purpose='council',
                                    kind='migration_policy', params={'open': False})
        result = self.world.resolve_actions([
            self.action(6, 'enact', institution=council.id, proposal=0)])[0]
        self.assertTrue(result['result']['success'], result)
        self.world.advance_time()
        before = [town.population for town in self.world.settlements]
        result = self.world.resolve_actions([self.action(0, 'migrate', destination=1)])[0]
        self.assertFalse(result['result']['success'], result)
        self.assertEqual(self.world.agents[0].home, 0)
        self.assertEqual([town.population for town in self.world.settlements], before)

    def test_competing_local_institutions_can_propose_different_economic_goals(self):
        self.organization(0, 0, (0, 1), purpose='cooperative')
        self.organization(1, 0, (2, 3), purpose='guild')
        results = self.world.resolve_actions([
            self.action(0, 'propose', institution=0, kind='specialization', params={'resource': 'food'}),
            self.action(2, 'propose', institution=1, kind='specialization', params={'resource': 'iron'})])
        self.assertTrue(all(r['result']['success'] for r in results), results)
        self.assertEqual({i.decisions[-1]['params']['resource'] for i in self.world.institutions},
                         {'food', 'iron'})

    def test_unmatched_negotiation_can_expire_without_forming_a_route(self):
        self.world.tick = 2
        organization = self.organization(0, 0, (0, 1), expires=4,
                                         params={'destination': 1, 'resource': 'food',
                                                 'direction': 'export', 'unit_price': .3, 'quota': 10})
        self.world.advance_time()
        self.world.advance_time()
        self.assertEqual(organization.decisions[0]['status'], 'expired')
        self.assertFalse(self.world.routes)
        failed = self.world.metrics['negotiations_failed']
        self.assertGreaterEqual(failed, 1)
        self.world._maintain_institutions()
        self.assertEqual(self.world.metrics['negotiations_failed'], failed)

    def test_empty_institution_can_collapse_without_inheriting_common_authority(self):
        institution = self.organization(0, 0, (0, 1), purpose='cooperative')
        institution.inventory['food'] = 10
        institution.treasury = 7
        self.fixture_totals()
        for actor_id in (0, 1):
            successor = self.world.remove_agent(actor_id, 'test succession')
            self.assertNotIn(successor.id, institution.members)
            self.assertTrue(0 <= successor.openness <= 1)
        for _ in range(4):
            self.world.advance_time()
        self.assertFalse(institution.active)
        self.assertEqual(institution.inventory['food'], 0)
        self.assertEqual(institution.treasury, 0)
        self.assertGreaterEqual(self.world.metrics['institutions_collapsed'], 1)
        self.world._assert_invariants()

    def test_regional_replay_and_measurements_are_detached_and_accounted(self):
        first = CivilizationWorld(seed=21).run(20)
        second = CivilizationWorld(seed=21).run(20)
        data = first.export()
        self.assertEqual(data, second.export())
        self.assertEqual(data['schema'], 'eternia.v0.5')
        self.assertEqual(data['mode'], 'civilizations')
        self.assertEqual(data['year'], 20)
        self.assertEqual(len(data['snapshots']), 21)
        self.assertEqual(len(data['regional_metrics']['per_settlement']), 3)
        json.dumps(data, allow_nan=False)
        data['snapshots'][0]['settlements'][0]['food'] = 99999
        self.assertNotEqual(first.snapshots[0]['settlements'][0]['food'], 99999)
        first._assert_invariants()
        second._assert_invariants()


if __name__ == '__main__':
    unittest.main()
