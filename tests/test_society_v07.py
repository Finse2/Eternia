import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from eternia.evaluation import build_society_scenario, evaluate_society, summarize
from eternia.report import make_html, make_evaluation_html

ROOT = Path(__file__).resolve().parents[1]


class SocietyEvaluationTests(unittest.TestCase):
    def test_matched_scenarios_preserve_initial_resources_and_policy(self):
        worlds = [build_society_scenario(42, scenario) for scenario in
                  ('baseline', 'local_scarcity', 'blocked_routes')]
        self.assertTrue(all(w.resource_totals() == worlds[0].resource_totals() for w in worlds))
        self.assertTrue(all(type(w._default_policy) is type(worlds[0]._default_policy) for w in worlds))
        self.assertTrue(all(not w.action_log for w in worlds))
        self.assertEqual(worlds[1].settlements[0].deposits['iron'], 0)
        self.assertTrue(all(link['condition'] == .05 for link in worlds[2].links))

    def test_seed_matrix_is_repeatable_and_records_failures(self):
        arguments = dict(seeds=(18, 42), years=1, scenarios=('baseline',), styles=('personal', 'collective'))
        first, second = evaluate_society(**arguments), evaluate_society(**arguments)
        self.assertEqual(first, second)
        self.assertEqual(len(first['cases']), 4)
        self.assertTrue(any(c['summary']['goals_completed'] < 18 for c in first['cases']))
        for case in first['cases']:
            self.assertLess(case['summary']['ledger_max_residual'], 1e-6)
            self.assertIn('source_fingerprint', case['provenance'])
            self.assertTrue(all('purpose' in record for record in case['work_evidence']))

    def test_summary_does_not_turn_received_wages_into_automatic_goal_success(self):
        world = build_society_scenario(42).run(3)
        summary = summarize(world)
        self.assertGreater(summary['wages_paid'], 0)
        self.assertEqual(summary['goals_completed'], sum(o['completed'] for o in summary['outcomes']))
        self.assertTrue(any(not outcome['completed'] for outcome in summary['outcomes']))

    def test_invalid_evaluation_requests_fail_without_launching_runs(self):
        for args in (dict(seeds=[]), dict(seeds=[1, 1]), dict(years=0),
                     dict(scenarios=['unknown']), dict(styles=['unknown'])):
            with self.subTest(args=args), self.assertRaises(ValueError):
                evaluate_society(**args)

    def test_reports_expose_escrow_and_metric_definitions(self):
        world = build_society_scenario(42)
        html = make_html(world.export())
        self.assertIn('id="economyPanel"', html)
        self.assertIn('id="workOrders"', html)
        self.assertIn('renderEconomy', html)
        comparison = evaluate_society(seeds=(42,), years=1, scenarios=('baseline',), styles=('balanced',))
        html = make_evaluation_html(comparison)
        self.assertIn('not confidence intervals', html)
        self.assertIn('id="scenario"', html)
        self.assertIn('id="policy"', html)

    def test_generated_society_data_escapes_script_delimiters(self):
        world = build_society_scenario(42)
        data = world.export()
        data['note'] = '</script><script>globalThis.compromised=true</script>'
        html = make_html(data)
        self.assertNotIn(data['note'], html)
        self.assertIn('\\u003c/script>', html)


class SocietyCliTests(unittest.TestCase):
    def run_cli(self, *args):
        return subprocess.run([sys.executable, 'main.py', *map(str, args)], cwd=ROOT,
                              text=True, capture_output=True)

    def test_cli_save_resume_matches_continuous_run(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            first, resumed, continuous = [folder / name for name in ('first', 'resumed', 'continuous')]
            for args in [
                ('--society', '--years', 1, '--seed', 18, '--output', first),
                ('--resume', first / 'world.save.json', '--years', 1, '--output', resumed),
                ('--society', '--years', 2, '--seed', 18, '--output', continuous),
            ]:
                result = self.run_cli(*args)
                self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads((resumed/'history.json').read_text(encoding='utf-8')),
                             json.loads((continuous/'history.json').read_text(encoding='utf-8')))
            self.assertIn('The Living Economy', (resumed/'report.html').read_text(encoding='utf-8'))
            result = self.run_cli('--resume', first/'world.save.json', '--seed', 42)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('do not override', result.stderr)

    def test_cli_evaluation_writes_a_comparison(self):
        with tempfile.TemporaryDirectory() as folder:
            result = self.run_cli('--evaluate-society', '--years', 1, '--evaluation-seeds', '18,42',
                                  '--policy-style', 'balanced', '--output', folder)
            self.assertEqual(result.returncode, 0, result.stderr)
            data = json.loads((Path(folder)/'evaluation.json').read_text(encoding='utf-8'))
            self.assertEqual(len(data['cases']), 10)  # two seeds x five scenarios x one policy style
            self.assertTrue((Path(folder)/'report.html').exists())

