"""Physical delivery, travel, finite geology and accounted historical replay."""
import copy
import json
import unittest

from eternia.physical_world import PhysicalWorld
from eternia.regional_engine import RegionalInstitution


class PhysicalWorldTests(unittest.TestCase):
    def setUp(self):
        self.world = PhysicalWorld(seed=42, ticks_per_year=12)
        self.world.tick = 2
        for town in self.world.settlements:
            town.food = 1000.
        for link in self.world.links:
            link.update(condition=1., risk=0., closed=False)
        self.fixture_totals()

    def fixture_totals(self):
        self.world.initial_totals = {
            resource: total - self.world.ledger['produced'][resource]
            + self.world.ledger['consumed'][resource]
            for resource, total in self.world.resource_totals().items()}

    def trading_pair(self, amount=20):
        seller = RegionalInstitution(0, 'Highfen Transport Guild', 1,
                                     members={6, 7}, purpose='guild')
        buyer = RegionalInstitution(1, 'Rivermark Import Guild', 0,
                                    members={0, 1}, purpose='guild')
        self.world.institutions.extend((seller, buyer))
        self.world.next_institution_id = 2
        self.world.routes.append({
            'id': 0, 'exporter': 1, 'importer': 0,
            'exporter_institution': 0, 'importer_institution': 1,
            'resource': 'iron', 'unit_price': 1.5, 'quota': amount,
            'created': 0, 'expires': 100, 'active': True,
            'status': 'active', 'volume': 0., 'shipments': 0,
            'proposals': [0, 1]})
        self.world.next_route_id = 1
        self.world.settlements[1].iron = 50.
        self.world.settlements[0].iron = 0.
        self.fixture_totals()
        return seller, buyer

    def dispatch(self, amount=4, actor=6):
        return self.world.resolve_actions([{
            'actor': actor, 'type': 'dispatch_caravan',
            'params': {'route': 0, 'amount': amount}
        }])[0]['result']

    def progress(self, journey, limit=80):
        for _ in range(limit):
            if journey['status'] != 'in_transit':
                break
            self.world.tick += 1
            self.world.year = self.world.tick // self.world.ticks_per_year
            self.world._advance_journeys()
        self.assertNotEqual(journey['status'], 'in_transit', journey)
        self.world._assert_invariants()

    def test_geography_offers_distinct_physical_routes(self):
        self.assertEqual(len(self.world.settlements), 3)
        self.assertGreaterEqual(len(self.world.links), 3)
        self.assertGreaterEqual(len({link['terrain'] for link in self.world.links}), 2)
        plan = self.world.journey_plan(0, 1)
        self.assertIsNotNone(plan)
        self.assertTrue(plan['path'])
        self.assertGreaterEqual(plan['duration'], 1)
        self.assertGreater(plan['supplies'], 0)
        self.assertGreater(plan['capacity'], 0)

    def test_a_trade_agreement_does_not_automatically_teleport_goods(self):
        self.trading_pair()
        before = self.world.resource_totals()
        self.world._institutional_trade()
        self.assertEqual(self.world.resource_totals(), before)
        self.assertEqual(self.world.settlements[0].iron, 0.)
        self.assertFalse(self.world.trade_shipments)
        self.assertFalse(self.world.journeys)

    def test_dispatch_reserves_cargo_and_payment_until_physical_arrival(self):
        self.trading_pair()
        before = self.world.resource_totals()
        seller, buyer = self.world.settlements[1], self.world.settlements[0]
        seller_coins, buyer_coins = seller.treasury, buyer.treasury
        result = self.dispatch()
        self.assertTrue(result['success'], result)
        journey = self.world.journeys[-1]
        self.assertEqual(journey['kind'], 'caravan')
        self.assertEqual(journey['status'], 'in_transit')
        self.assertEqual(journey['cargo']['iron'], 4.)
        self.assertAlmostEqual(journey['escrow'], 6.)
        self.assertEqual(seller.iron, 46.)
        self.assertEqual(buyer.iron, 0.)
        self.assertEqual(seller.treasury, seller_coins)
        self.assertEqual(buyer.treasury, buyer_coins - 6.)
        for resource, total in before.items():
            self.assertAlmostEqual(self.world.resource_totals()[resource], total)
        self.world._advance_journeys()
        self.assertEqual(journey['status'], 'in_transit')
        self.assertEqual(buyer.iron, 0.)
        self.progress(journey)
        self.assertEqual(journey['status'], 'delivered')
        self.assertEqual(buyer.iron, 4.)
        self.assertEqual(seller.treasury, seller_coins + 6.)
        self.assertEqual(len(self.world.trade_shipments), 1)

    def test_progress_cannot_consume_supplies_twice_in_one_tick(self):
        self.trading_pair()
        result = self.dispatch()
        self.assertTrue(result['success'], result)
        self.world.tick += 1
        self.world._advance_journeys()
        state = copy.deepcopy(self.world.journeys)
        ledger = copy.deepcopy(self.world.ledger)
        self.world._advance_journeys()
        self.assertEqual(self.world.journeys, state)
        self.assertEqual(self.world.ledger, ledger)

    def test_unused_provisions_arrive_with_the_caravan_instead_of_teleporting_home(self):
        self.trading_pair()
        destination = self.world.settlements[0]
        origin = self.world.settlements[1]
        destination_food = destination.food
        result = self.dispatch()
        self.assertTrue(result['success'], result)
        journey = self.world.journeys[-1]
        origin_food = origin.food
        provisions = journey['supplies']
        consumed = self.world.ledger['consumed']['food']
        self.progress(journey)
        self.assertEqual(journey['status'], 'delivered')
        leftovers = provisions - (self.world.ledger['consumed']['food'] - consumed)
        self.assertGreater(leftovers, 0)
        self.assertEqual(origin.food, origin_food)
        self.assertAlmostEqual(destination.food, destination_food + leftovers)

    def test_competing_dispatches_cannot_spend_the_same_importers_coins(self):
        self.trading_pair()
        self.world.settlements[0].treasury = 6.
        for link in self.world.links:
            link['capacity'] = 100.
        self.fixture_totals()
        results = self.world.resolve_actions([
            {'actor': actor, 'type': 'dispatch_caravan',
             'params': {'route': 0, 'amount': 4}}
            for actor in (6, 7)])
        self.assertEqual(sum(r['result']['success'] for r in results), 1, results)
        self.assertEqual(self.world.settlements[0].treasury, 0.)
        self.assertEqual(len(self.world.journeys), 1)
        self.world._assert_invariants()

    def test_transport_capacity_is_shared_by_competing_dispatches(self):
        self.trading_pair()
        for link in self.world.links:
            link['capacity'] = 7.
        results = self.world.resolve_actions([
            {'actor': actor, 'type': 'dispatch_caravan',
             'params': {'route': 0, 'amount': 4}}
            for actor in (6, 7)])
        self.assertEqual(sum(r['result']['success'] for r in results), 1, results)
        self.world._assert_invariants()

    def test_a_caravan_occupies_transport_capacity_across_ticks(self):
        self.trading_pair()
        for link in self.world.links:
            link['capacity'] = 7.
        result = self.dispatch()
        self.assertTrue(result['success'], result)
        self.world.tick += 1
        self.world._advance_journeys()
        self.assertEqual(self.world.journeys[0]['status'], 'in_transit')
        result = self.dispatch(actor=7)
        self.assertFalse(result['success'], result)
        self.assertEqual(len(self.world.journeys), 1)
        self.world._assert_invariants()

    def test_a_delivery_after_planning_cannot_finance_another_dispatch_that_tick(self):
        self.trading_pair()
        self.world.settlements[1].treasury = 0.
        self.world.settlements[1].wood = 0.
        self.world.settlements[2].wood = 100.
        supplier = RegionalInstitution(2, 'Deepwood Transport Guild', 2,
                                        members={12, 13}, purpose='guild')
        self.world.institutions.append(supplier)
        self.world.next_institution_id = 3
        self.world.routes.append({
            'id': 1, 'exporter': 2, 'importer': 1,
            'exporter_institution': 2, 'importer_institution': 0,
            'resource': 'wood', 'unit_price': 1.5, 'quota': 20,
            'created': 0, 'expires': 100, 'active': True,
            'status': 'active', 'volume': 0., 'shipments': 0,
            'proposals': [2, 3]})
        self.world.next_route_id = 2
        for link in self.world.links:
            link.update(capacity=100., speed=100.)
        self.fixture_totals()
        result = self.dispatch()
        self.assertTrue(result['success'], result)
        self.world.tick += 1
        self.world.resolve_actions([{'actor': 11, 'type': 'wait', 'params': {}}])
        self.world._advance_journeys()
        self.assertEqual(self.world.journeys[0]['status'], 'delivered')
        self.assertEqual(self.world.settlements[1].treasury, 6.)
        result = self.world.resolve_actions([{
            'actor': 12, 'type': 'dispatch_caravan', 'params': {'route': 1, 'amount': 4}
        }])[0]['result']
        self.assertFalse(result['success'], result)
        self.assertEqual(len(self.world.journeys), 1)
        self.world._assert_invariants()

    def test_caravan_failure_records_loss_and_refunds_reserved_payment(self):
        self.trading_pair()
        buyer_coins = self.world.settlements[0].treasury
        result = self.dispatch()
        self.assertTrue(result['success'], result)
        journey = self.world.journeys[-1]
        for link in self.world.links:
            link.update(risk=1., condition=.5)
        self.progress(journey)
        self.assertEqual(journey['status'], 'failed')
        self.assertEqual(self.world.settlements[0].iron, 0.)
        self.assertEqual(self.world.settlements[0].treasury, buyer_coins)
        self.assertGreaterEqual(self.world.ledger['consumed']['iron'], 4.)
        self.assertFalse(self.world.trade_shipments)

    def test_a_nonmember_cannot_dispatch_another_guilds_contract(self):
        self.trading_pair()
        result = self.dispatch(actor=8)
        self.assertFalse(result['success'], result)
        self.assertFalse(self.world.journeys)

    def test_blocked_geography_can_prevent_a_valid_commercial_agreement_shipping(self):
        self.trading_pair()
        for link in self.world.links:
            link['condition'] = 0.
        self.assertIsNone(self.world.journey_plan(1, 0, sponsor=0))
        result = self.dispatch()
        self.assertFalse(result['success'], result)
        self.assertFalse(self.world.journeys)

    def test_migration_is_a_journey_and_preserves_population_and_origin_buildings(self):
        actor = self.world.agents[6]
        actor.inventory['food'] = 20.
        actor.structures['house'] = 1
        self.world.settlements[1].buildings['house'] = 1
        institution = RegionalInstitution(0, 'Highfen Guild', 1,
                                          members={6, 7}, purpose='guild')
        self.world.institutions.append(institution)
        self.world.next_institution_id = 1
        before = [s.population for s in self.world.settlements]
        self.fixture_totals()
        result = self.world.resolve_actions([{
            'actor': 6, 'type': 'migrate', 'params': {'destination': 0}
        }])[0]['result']
        self.assertTrue(result['success'], result)
        journey = self.world.journeys[-1]
        self.assertEqual(actor.home, 1)
        self.assertTrue(self.world.is_traveling(actor.id))
        self.assertNotIn(actor.id, institution.members)
        self.assertEqual(self.world.settlements[1].population, before[1] - 1)
        self.assertEqual(self.world.settlements[0].population, before[0])
        result = self.world.resolve_actions([{
            'actor': actor.id, 'type': 'gather',
            'params': {'resource': 'food', 'amount': 1}
        }])[0]['result']
        self.assertFalse(result['success'], result)
        self.progress(journey)
        self.assertEqual(actor.home, 0)
        self.assertFalse(self.world.is_traveling(actor.id))
        self.assertEqual(sum(s.population for s in self.world.settlements), sum(before))
        self.assertEqual(self.world.settlements[1].buildings['house'], 1)
        self.assertEqual(actor.structures['house'], 1)

    def test_a_closed_border_at_arrival_makes_a_migrant_return_physically(self):
        actor = self.world.agents[6]
        actor.inventory['food'] = 30.
        self.fixture_totals()
        population = sum(s.population for s in self.world.settlements)
        result = self.world.resolve_actions([{
            'actor': actor.id, 'type': 'migrate', 'params': {'destination': 0}
        }])[0]['result']
        self.assertTrue(result['success'], result)
        council = RegionalInstitution(0, 'Closed Rivermark Council', 0,
                                      members={0, 1, 2, 3}, purpose='council')
        council.rules['migration_open'] = False
        self.world.institutions.append(council)
        self.world.next_institution_id = 1
        journey = self.world.journeys[-1]
        self.progress(journey)
        self.assertEqual(journey['status'], 'returned')
        self.assertEqual(actor.home, 1)
        self.assertEqual(sum(s.population for s in self.world.settlements), population)

    def test_a_traveling_person_cannot_receive_a_local_lesson(self):
        actor = self.world.agents[6]
        actor.inventory['food'] = 20.
        self.fixture_totals()
        result = self.world.resolve_actions([{
            'actor': actor.id, 'type': 'migrate', 'params': {'destination': 0}
        }])[0]['result']
        self.assertTrue(result['success'], result)
        self.assertNotIn('carpentry', actor.skills)
        result = self.world.resolve_actions([{
            'actor': 9, 'type': 'teach',
            'params': {'target': actor.id, 'topic': 'carpentry'}
        }])[0]['result']
        self.assertFalse(result['success'], result)
        self.assertNotIn('carpentry', actor.skills)

    def test_retirement_during_travel_defers_estate_succession_until_arrival(self):
        actor = self.world.agents[6]
        actor.inventory.update(food=20., wood=7., iron=3., coins=19.)
        actor.structures['house'] = 1
        self.world.settlements[1].buildings['house'] = 1
        self.fixture_totals()
        result = self.world.resolve_actions([{
            'actor': actor.id, 'type': 'migrate', 'params': {'destination': 0}
        }])[0]['result']
        self.assertTrue(result['success'], result)
        pending = self.world.remove_agent(actor.id, 'old age during travel')
        self.assertEqual(pending.id, actor.id)
        self.assertIn(actor, self.world.agents)
        self.assertEqual(len(self.world.agents), 18)
        self.assertFalse(any(a.parent_id == actor.id for a in self.world.agents))
        self.progress(self.world.journeys[-1])
        self.assertNotIn(actor, self.world.agents)
        successor = next(a for a in self.world.agents if a.parent_id == actor.id)
        self.assertEqual(successor.home, 0)
        self.assertEqual(successor.inventory, actor.inventory)
        self.assertEqual(successor.goal, actor.goal)
        self.assertEqual(successor.structures, actor.structures)
        self.assertEqual(successor.preferred_purpose, actor.preferred_purpose)
        self.assertEqual(len(self.world.agents), 18)
        self.assertEqual(self.world.settlements[1].buildings['house'], 1)

    def test_a_traveling_person_cannot_witness_origin_construction(self):
        actor, builder = self.world.agents[6], self.world.agents[9]
        actor.inventory['food'] = 20.
        builder.inventory.update(wood=12., iron=2., coins=8.)
        self.fixture_totals()
        result = self.world.resolve_actions([{
            'actor': actor.id, 'type': 'migrate', 'params': {'destination': 0}
        }])[0]['result']
        self.assertTrue(result['success'], result)
        results = self.world.resolve_actions([{
            'actor': builder.id, 'type': 'build', 'params': {'structure': 'house'}
        }])
        self.assertTrue(results[0]['result']['success'], results)
        self.world.rng.random = lambda: 0.
        self.world.update_relationships(results)
        self.assertNotIn('carpentry', actor.skills)

    def test_departing_migrants_cannot_leave_fulfillable_local_market_offers(self):
        actor = self.world.agents[6]
        actor.inventory['food'] = 20.
        actor.inventory['iron'] = 2.
        self.fixture_totals()
        result = self.world.resolve_actions([{
            'actor': actor.id, 'type': 'offer',
            'params': {'resource': 'iron', 'direction': 'sell', 'amount': 2, 'unit_price': 1}
        }])[0]['result']
        self.assertTrue(result['success'], result)
        self.assertTrue(self.world.offers)
        self.world.tick += 1
        result = self.world.resolve_actions([{
            'actor': actor.id, 'type': 'migrate', 'params': {'destination': 0}
        }])[0]['result']
        self.assertTrue(result['success'], result)
        self.assertFalse(any(offer['actor'] == actor.id for offer in self.world.offers))

    def test_physical_observations_are_detached_and_do_not_disclose_foreign_accounts(self):
        self.trading_pair()
        observation = self.world.observe(6)
        self.assertIn('physical', observation)
        observation['physical']['links'][0]['condition'] = -100
        self.assertGreaterEqual(self.world.links[0]['condition'], 0)
        for institution in observation['institutions']:
            if institution['settlement_id'] != 1:
                self.assertNotIn('treasury', institution)
                self.assertNotIn('inventory', institution)

    def test_depleted_geology_cannot_generate_new_annual_iron(self):
        self.world.mineral_reserves = dict.fromkeys(self.world.mineral_reserves, 0.)
        self.fixture_totals()
        before = self.world.ledger['produced']['iron']
        stocks = [town.iron for town in self.world.settlements]
        self.world._produce_and_consume()
        self.assertEqual(self.world.ledger['produced']['iron'], before)
        self.assertEqual([town.iron for town in self.world.settlements], stocks)
        self.assertTrue(all(amount == 0 for amount in self.world.mineral_reserves.values()))
        self.world._assert_invariants()

    def test_finite_geology_caps_extraction_without_negative_reserves(self):
        for town in self.world.settlements:
            self.world.mineral_reserves[town.id] = .01
        self.fixture_totals()
        before = self.world.ledger['produced']['iron']
        stock = sum(town.iron for town in self.world.settlements)
        total = self.world.resource_totals()['iron']
        self.world._produce_and_consume()
        self.assertEqual(self.world.ledger['produced']['iron'], before)
        self.assertAlmostEqual(sum(town.iron for town in self.world.settlements) - stock, .03)
        self.assertAlmostEqual(self.world.resource_totals()['iron'], total)
        self.assertTrue(all(amount == 0 for amount in self.world.mineral_reserves.values()))
        self.assertTrue(all(amount >= 0 for amount in self.world.mineral_reserves.values()))
        self.world._assert_invariants()

    def test_seeded_physical_history_replays_and_contains_exportable_transit_state(self):
        first = PhysicalWorld(seed=21).run(20)
        second = PhysicalWorld(seed=21).run(20)
        data = first.export()
        self.assertEqual(data, second.export())
        self.assertEqual(data['schema'], 'eternia.v0.6.1')
        self.assertEqual(data['mode'], 'physical_world')
        self.assertEqual(len(data['snapshots']), 21)
        self.assertIn('journeys', data)
        self.assertIn('links', data)
        self.assertIn('physical_metrics', data)
        json.dumps(data, allow_nan=False)
        data['links'][0]['condition'] = -100
        self.assertGreaterEqual(first.links[0]['condition'], 0)
        first._assert_invariants()
        second._assert_invariants()


if __name__ == '__main__':
    unittest.main()
