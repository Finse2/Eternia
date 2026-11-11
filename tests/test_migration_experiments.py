"""Controlled opportunities connect ordinary choices to physical migration."""
import json
import unittest

from eternia.experiments import build_migration_scenario, run_migration_experiments
from eternia.logistics_policy import LogisticsPolicy
from eternia.physical_world import PhysicalWorld


class MigrationExperimentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.experiment = run_migration_experiments(seed=42, years=3)
        cls.cases = {case['name']: case for case in cls.experiment['cases']}

    def test_fixtures_preserve_resources_goals_and_normal_policies(self):
        baseline = PhysicalWorld(seed=42, shock_year=0)
        for name in self.cases:
            with self.subTest(case=name):
                world, metadata = build_migration_scenario(name, seed=42)
                self.assertIsInstance(world._default_policy, LogisticsPolicy)
                self.assertFalse(world.policies)
                self.assertEqual(len(world.agents), 18)
                self.assertEqual([a.goal for a in world.agents], [a.goal for a in baseline.agents])
                self.assertEqual(world.resource_totals(), baseline.resource_totals())
                self.assertEqual(world.mineral_reserves, baseline.mineral_reserves)
                self.assertFalse(world.decisions)
                self.assertFalse(world.journeys)
                self.assertEqual(world.snapshots[0]['agents'][metadata['focal_actor']]['inventory'],
                                 metadata['initial_inventory'])
                world._assert_invariants()

    def test_opportunity_produces_a_chosen_journey_arrival_and_local_work(self):
        case = self.cases['opportunity']
        first = case['evidence']['first_decision']
        journey = case['evidence']['journeys'][0]
        self.assertEqual(first['proposal']['type'], 'migrate')
        self.assertTrue(first['result']['success'])
        self.assertIn('accessible iron', first['rationale'])
        self.assertEqual(first['result']['effects']['journey_id'], journey['id'])
        self.assertGreater(journey['arrived'], journey['created'])
        self.assertEqual(journey['status'], 'delivered')
        self.assertEqual(case['summary']['final_home'], journey['destination'])
        self.assertTrue(case['evidence']['arrival_events'])
        self.assertTrue(case['evidence']['post_arrival_work'])
        for action in case['evidence']['post_arrival_work']:
            self.assertGreaterEqual(action['tick'], journey['arrived'])
            self.assertEqual(action['proposal']['location'], journey['destination'])
            self.assertGreater(action['result']['effects']['amount'], 0)
        # Finding work is not evidence of earning the miner's target wealth.
        self.assertFalse(case['summary']['goal_completed'])

    def test_matched_local_work_and_impassable_route_controls_do_not_depart(self):
        opportunity = self.cases['opportunity']
        for name in ('local_work', 'blocked_route'):
            with self.subTest(case=name):
                case = self.cases[name]
                self.assertEqual(case['metadata']['initial_inventory'],
                                 opportunity['metadata']['initial_inventory'])
                self.assertEqual(case['metadata']['goal'], opportunity['metadata']['goal'])
                self.assertEqual(case['metadata']['initial_totals'],
                                 opportunity['metadata']['initial_totals'])
                self.assertNotEqual(case['summary']['first_action'], 'migrate')
                self.assertEqual(case['summary']['departures'], 0)
                self.assertEqual(case['summary']['post_arrival_work'], 0)
        self.assertGreater(self.cases['local_work']['metadata']['local_accessible_iron'], 0)
        self.assertEqual(self.cases['blocked_route']['metadata']['local_accessible_iron'], 0)
        self.assertTrue(all(path is None for path in
                            self.cases['blocked_route']['metadata']['initial_paths'].values()))

    def test_exported_evidence_and_resource_ledger_match_real_history(self):
        for name, case in self.cases.items():
            with self.subTest(case=name):
                history = case['history']
                actual = [d for d in history['decisions'] if d['actor'] == case['summary']['focal_actor']]
                self.assertEqual(actual, case['evidence']['decisions'])
                for resource, total in history['final_totals'].items():
                    expected = (history['initial_totals'][resource]
                                + history['ledger']['produced'][resource]
                                - history['ledger']['consumed'][resource])
                    self.assertAlmostEqual(total, expected, places=6)
        self.assertTrue(json.dumps(self.experiment, allow_nan=False))

    def test_seed_replays_the_same_autonomous_departure_and_arrival(self):
        first, _ = build_migration_scenario('opportunity', seed=42)
        replay, _ = build_migration_scenario('opportunity', seed=42)
        first.run(1)
        replay.run(1)
        self.assertEqual(first.export(), replay.export())
        self.assertEqual(first.journeys[0]['status'], 'delivered')

    def test_zero_years_records_no_decisions_or_invented_success(self):
        result = run_migration_experiments(years=0)
        for case in result['cases']:
            self.assertIsNone(case['summary']['first_action'])
            self.assertIsNone(case['evidence']['first_decision'])
            self.assertEqual(case['summary']['departures'], 0)
            self.assertFalse(case['summary']['goal_completed'])

    def test_invalid_scenarios_and_durations_are_rejected(self):
        with self.assertRaises(ValueError):
            build_migration_scenario('unknown')
        for years in (-1, 1.5, True):
            with self.subTest(years=years), self.assertRaises(ValueError):
                run_migration_experiments(years=years)


if __name__ == '__main__':
    unittest.main()
