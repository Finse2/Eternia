"""Capacity-aware routing and the hazard quoted for every travel tick."""
import copy
import unittest
from unittest.mock import Mock

from eternia.actions import _Rejected
from eternia.physical_world import PhysicalWorld
from eternia.regional_engine import RegionalInstitution


class PhysicalRoutingTests(unittest.TestCase):
    def setUp(self):
        self.world = PhysicalWorld(seed=42, ticks_per_year=12)
        self.world.tick = 2
        # One fast direct crossing and a slower, roomier two-leg alternative.
        for link, distance in zip(self.world.links, (10., 20., 20.)):
            link.update(distance=distance, speed=10., condition=1.,
                        capacity=20., risk=0., closed=False)
        for town in self.world.settlements:
            town.food = 1000.

    def trading_pair(self):
        self.world.institutions.extend((
            RegionalInstitution(0, 'Rivermark Export Guild', 0,
                                members={0, 1}, purpose='guild'),
            RegionalInstitution(1, 'Deepwood Import Guild', 2,
                                members={12, 13}, purpose='guild')))
        self.world.next_institution_id = 2
        self.world.routes.append(dict(
            id=0, exporter=0, importer=2, exporter_institution=0,
            importer_institution=1, resource='iron', unit_price=1.5,
            quota=30., created=0, expires=100, active=True, status='active',
            volume=0., shipments=0, proposals=[0, 1]))
        self.world.next_route_id = 1
        self.world.settlements[0].iron = 100.
        self.world.settlements[2].iron = 0.
        self.world.initial_totals = {
            resource: total - self.world.ledger['produced'][resource]
            + self.world.ledger['consumed'][resource]
            for resource, total in self.world.resource_totals().items()}

    @staticmethod
    def dispatch_action(actor=0, amount=4.):
        return dict(actor=actor, type='dispatch_caravan',
                    params=dict(route=0, amount=amount))

    def dispatch(self, actor=0, amount=4.):
        return self.world.resolve_actions([self.dispatch_action(actor, amount)])[0]['result']

    def test_risk_compounds_the_condition_adjusted_hazard_for_every_tick(self):
        self.world.links[0].update(distance=27., condition=.5, risk=.2)
        plan = self.world.journey_plan(0, 2)
        self.assertEqual(plan['path'], [0])
        # Effective speed is 7; the 27-unit crossing needs four hazard checks.
        self.assertEqual(plan['duration'], 4)
        self.assertAlmostEqual(plan['risk'], 1. - .8 ** 4)

    def test_risk_compounds_different_hazards_and_durations_on_each_leg(self):
        self.world.links[0].update(closed=True, owner=99)
        self.world.links[1].update(distance=10., condition=.5, risk=.1)
        self.world.links[2].update(distance=22., condition=.8, risk=.2)
        plan = self.world.journey_plan(0, 2)
        self.assertEqual(plan['path'], [1, 2])
        self.assertEqual(plan['duration'], 5)
        self.assertAlmostEqual(plan['risk'], 1. - .9 ** 2 * .86 ** 3)

    def test_risk_preserves_the_actual_hazard_cap_and_zero_risk(self):
        self.assertEqual(self.world.journey_plan(0, 2)['risk'], 0.)
        self.world.links[0].update(risk=1., condition=.5, distance=7.)
        self.assertEqual(self.world.journey_plan(0, 2)['risk'], 1.)

    def test_busy_fast_crossing_uses_the_slower_passenger_path(self):
        self.world.journeys.append(dict(status='in_transit', path=[0], leg=0,
                                       transport_load=19.5))
        plan = self.world.journey_plan(0, 2)
        self.assertEqual(plan['path'], [1, 2])
        self.assertEqual(plan['duration'], 4)
        self.assertEqual(plan['capacity'], 20.)

    def test_caravan_capacity_includes_provisions_for_the_entire_route(self):
        self.trading_pair()
        self.world.links[0]['capacity'] = 5.
        # Four units of cargo alone fit the crossing; 1.5 provisions do not.
        plan = self.world.caravan_quote(self.world.agents[0], 0, 4.)
        self.assertEqual(plan['path'], [1, 2])
        self.assertEqual(plan['supplies'], 3.)
        self.world.links[1]['capacity'] = 6.
        # Cargo plus each leg's separate supplies would fit, but the complete
        # journey must start with all three food units aboard every leg.
        with self.assertRaises(_Rejected) as rejected:
            self.world.caravan_quote(self.world.agents[0], 0, 4.)
        self.assertEqual(rejected.exception.code, 'no_path')
        self.assertEqual(self.world.journey_plan(0, 2)['path'], [0])

    def test_a_slower_partial_route_is_retained_when_it_has_more_capacity(self):
        def link(identity, a, b, duration, capacity):
            return dict(id=identity, a=a, b=b, distance=duration * 10.,
                        speed=10., condition=1., capacity=capacity,
                        risk=0., closed=False, owner=None)

        self.world.links = [link(0, 0, 2, 1, 6.), link(1, 0, 1, 1, 20.),
                            link(2, 1, 2, 1, 20.), link(3, 2, 3, 4, 20.)]
        # Reaching node 2 fastest would retain a six-unit bottleneck. After
        # the last leg is added, its full provisions would no longer fit.
        plan = self.world.journey_plan(0, 3, cargo_amount=3.)
        self.assertEqual(plan['path'], [1, 2, 3])
        self.assertEqual(plan['duration'], 6)
        self.assertEqual(plan['supplies'], 4.)

    def test_two_same_tick_departures_reserve_different_feasible_paths(self):
        self.trading_pair()
        self.world.links[0]['capacity'] = 5.5
        before = self.world.resource_totals()
        results = self.world.resolve_actions([
            self.dispatch_action(actor=0), self.dispatch_action(actor=1)])
        self.assertTrue(all(receipt['result']['success'] for receipt in results), results)
        self.assertEqual([journey['path'] for journey in self.world.journeys], [[0], [1, 2]])
        self.assertEqual([journey['transport_load'] for journey in self.world.journeys], [5.5, 7.])
        self.assertEqual(self.world._link_remaining, {0: 0., 1: 13., 2: 13.})
        for resource, total in before.items():
            self.assertAlmostEqual(self.world.resource_totals()[resource], total)
        self.world._assert_invariants()

    def test_mid_tick_delivery_does_not_release_tick_start_capacity(self):
        self.trading_pair()
        self.world.links[0]['capacity'] = 5.5
        self.assertTrue(self.dispatch()['success'])
        self.world.tick += 1
        self.world._begin_institution_tick()
        self.world._advance_journeys()
        self.assertEqual(self.world.journeys[0]['status'], 'delivered')
        plan = self.world.caravan_quote(self.world.agents[1], 0, 4.)
        self.assertEqual(plan['path'], [1, 2])
        self.world.tick += 1
        self.assertEqual(self.world.caravan_quote(self.world.agents[1], 0, 4.)['path'], [0])

    def test_repairs_do_not_unlock_an_alternate_paths_capacity_in_the_same_tick(self):
        self.trading_pair()
        self.world.links[0]['capacity'] = 5.
        self.world.links[1].update(condition=.2, capacity=20.)
        self.world._begin_institution_tick()
        self.world.links[1]['condition'] = 1.
        with self.assertRaises(_Rejected) as rejected:
            self.world.caravan_quote(self.world.agents[0], 0, 4.)
        self.assertEqual(rejected.exception.code, 'no_path')
        self.world.tick += 1
        self.assertEqual(self.world.caravan_quote(self.world.agents[0], 0, 4.)['path'], [1, 2])

    def test_departure_respects_old_access_and_current_closures(self):
        self.trading_pair()
        self.world.links[0].update(closed=True, owner=99)
        self.world._begin_institution_tick()
        self.world.links[0]['owner'] = 0
        # A newly acquired closed route cannot use its new sponsor exception.
        self.assertEqual(self.world.caravan_quote(self.world.agents[0], 0, 4.)['path'], [1, 2])
        self.world.links[1].update(closed=True, owner=99)
        with self.assertRaises(_Rejected):
            self.world.caravan_quote(self.world.agents[0], 0, 4.)
        self.world.tick += 1
        self.assertEqual(self.world.caravan_quote(self.world.agents[0], 0, 4.)['path'], [0])

    def test_migration_fallback_requires_provisions_for_its_longer_journey(self):
        actor = self.world.agents[2]
        self.world.links[0]['capacity'] = .5
        actor.inventory['food'] = 5.
        plan = self.world.journey_plan(actor.home, 2)
        self.assertEqual(plan['path'], [1, 2])
        with self.assertRaises(_Rejected) as rejected:
            self.world.migration_quote(actor, 2)
        self.assertEqual(rejected.exception.code, 'insufficient_resources')
        actor.inventory['food'] = 6.
        quote = self.world.migration_quote(actor, 2)
        self.assertEqual(quote['path'], plan['path'])
        self.assertEqual(quote['supplies'], 6.)

    def test_fallback_validation_is_pure_and_deterministic(self):
        self.trading_pair()
        self.world.links[0]['capacity'] = 5.
        self.world._begin_institution_tick()
        state = copy.deepcopy(self.world.export())
        random_state = self.world.rng.getstate()
        reservations = copy.deepcopy(self.world._link_remaining)
        frames = copy.deepcopy(self.world._physical_links)
        first = self.world.action_engine.validate(self.dispatch_action())
        second = self.world.action_engine.validate(self.dispatch_action())
        self.assertTrue(first.success, first)
        self.assertEqual(first, second)
        self.assertEqual(self.world.export(), state)
        self.assertEqual(self.world.rng.getstate(), random_state)
        self.assertEqual(self.world._link_remaining, reservations)
        self.assertEqual(self.world._physical_links, frames)

    def test_arrival_tick_count_matches_the_duration_quote(self):
        self.trading_pair()
        self.world.links[0].update(condition=.5, distance=14.0000000005)
        quote = self.world.caravan_quote(self.world.agents[0], 0, 4.)
        self.assertEqual(quote['duration'], 2)
        result = self.dispatch()
        self.assertTrue(result['success'], result)
        journey = self.world.journeys[0]
        self.world.tick += 1
        self.world._advance_journeys()
        self.assertEqual(journey['status'], 'in_transit')
        self.world.tick += 1
        self.world._advance_journeys()
        self.assertEqual(journey['status'], 'delivered')

    def test_departure_risk_is_historical_but_travel_uses_current_hazards(self):
        self.trading_pair()
        self.world.links[0].update(condition=.5, risk=.2, distance=21.)
        self.assertTrue(self.dispatch()['success'])
        journey = self.world.journeys[0]
        original_estimate = 1. - .8 ** 3
        self.assertAlmostEqual(journey['estimated_risk'], original_estimate)
        # The new weather lowers the per-tick hazard from .2 to .1.
        self.world.links[0]['condition'] = 1.
        self.world.rng = Mock(random=Mock(return_value=.15))
        self.world.tick += 1
        self.world._advance_journeys()
        self.assertEqual(journey['status'], 'in_transit')
        self.assertEqual(journey['progress'], 10.)
        self.assertAlmostEqual(journey['estimated_risk'], original_estimate)
        self.world.rng.random.return_value = .099
        self.world.tick += 1
        self.world._advance_journeys()
        self.assertEqual(journey['status'], 'failed')
        self.assertAlmostEqual(journey['estimated_risk'], original_estimate)
        self.world._assert_invariants()


if __name__ == '__main__':
    unittest.main()
