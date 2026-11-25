import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from eternia.economic_policy import EconomicPolicy, job_value
from eternia.evaluation import build_society_scenario, summarize
from eternia.labor_experiments import build_labor_scenario, labor_migrations, run_labor_experiments
from eternia.market import offered_wage
from eternia.persistence import checkpoint, restore_checkpoint
from eternia.society import SocietyWorld
from v07_helpers import add_council, funded_order, proposal

ROOT = Path(__file__).resolve().parents[1]
BUILDER, MINER, FARMER = 3, 1, 0  # Rivermark residents


def hired(world, employer=BUILDER, resource='iron', quantity=2, wage=2.4):
    result = world.submit_action(dict(actor=employer, type='hire', resource=resource,
                                      quantity=quantity, unit_wage=wage))
    assert result.success, result.message
    world.advance_time()
    return world.work_orders[-1]


def funded_guild(world, coins=20.):
    guild = add_council(world, purpose='guild')
    world.settlements[0].treasury -= coins  # a transfer, not new money
    guild.treasury += coins
    return guild


class LaborTestCase(unittest.TestCase):
    def assertConserved(self, before, after):
        for resource, total in before.items():
            self.assertTrue(math.isclose(total, after[resource], abs_tol=1e-9), (resource, total, after[resource]))


class PrivateEmploymentTests(LaborTestCase):
    def test_hire_escrows_personal_coins_without_minting(self):
        world = SocietyWorld()
        before, coins = world.resource_totals(), world.agents[BUILDER].inventory['coins']
        result = world.submit_action(dict(actor=BUILDER, type='hire', resource='iron', quantity=2, unit_wage=2.4))
        self.assertTrue(result.success, result.message)
        order = world.work_orders[-1]
        self.assertEqual(order['employer'], {'kind': 'person', 'id': BUILDER})
        self.assertAlmostEqual(world.agents[BUILDER].inventory['coins'], coins - 4.8)
        self.assertAlmostEqual(order['escrow'], 4.8)
        self.assertEqual(world.economic_metrics['private_orders'], 1)
        self.assertConserved(before, world.resource_totals())

    def test_hire_needs_available_coins_and_one_open_job_per_employer(self):
        world = SocietyWorld()
        result = world.submit_action(dict(actor=BUILDER, type='hire', resource='iron', quantity=24, unit_wage=5))
        self.assertEqual(result.code, 'insufficient_resources')
        self.assertFalse(world.work_orders)
        hired(world)
        result = world.submit_action(dict(actor=BUILDER, type='hire', resource='wood', quantity=1, unit_wage=1))
        self.assertEqual(result.code, 'active_order')

    def test_private_output_reaches_the_employer_and_wages_the_worker(self):
        world = SocietyWorld()
        order = hired(world)
        builder, miner, town = world.agents[BUILDER], world.agents[MINER], world.settlements[0]
        before, iron, coins, stored = world.resource_totals(), builder.inventory['iron'], miner.inventory['coins'], town.iron
        result = world.submit_action(dict(actor=MINER, type='work', order=order['id'], amount=2))
        self.assertTrue(result.success, result.message)
        self.assertEqual(builder.inventory['iron'], iron + 2)
        self.assertAlmostEqual(miner.inventory['coins'], coins + 4.8)
        self.assertEqual(town.iron, stored)  # never routed through municipal storage
        self.assertEqual(order['status'], 'completed')
        record = world.work_history[-1]
        self.assertEqual(record['purpose'], 'private_employment')
        self.assertEqual(record['employer'], {'kind': 'person', 'id': BUILDER})
        self.assertConserved(before, world.resource_totals())

    def test_an_employer_cannot_be_paid_from_their_own_escrow(self):
        world = SocietyWorld()
        world.agents[BUILDER].skills.append('mining')
        order = hired(world)
        result = world.submit_action(dict(actor=BUILDER, type='work', order=order['id'], amount=1))
        self.assertEqual(result.code, 'invalid_action')

    def test_municipal_and_private_jobs_for_one_resource_coexist(self):
        world = SocietyWorld()
        _, municipal = funded_order(world)
        private = hired(world)
        self.assertEqual({municipal['status'], private['status']}, {'open'})
        self.assertEqual(municipal['resource'], private['resource'])

    def test_departed_employer_gets_no_output_and_is_refunded(self):
        world = SocietyWorld()
        order = hired(world)
        employer = world.agents[BUILDER]
        world.settlements[0].food -= 7  # journey provisions transferred from town stores
        employer.inventory['food'] += 7
        coins = employer.inventory['coins']
        self.assertTrue(world.submit_action(dict(actor=BUILDER, type='migrate', destination=1)).success)
        result = world.submit_action(dict(actor=MINER, type='work', order=order['id'], amount=1))
        self.assertEqual(result.code, 'order_unavailable')
        world.advance_time()
        before = world.resource_totals()
        world._maintain_work_orders()
        self.assertEqual(order['status'], 'expired')
        self.assertAlmostEqual(employer.inventory['coins'], coins + 4.8)
        self.assertConserved(before, world.resource_totals())

    def test_deceased_employer_escrow_joins_the_estate(self):
        world = SocietyWorld()
        order = hired(world)
        successor = world.remove_agent(BUILDER, 'a test retirement')
        coins, before = successor.inventory['coins'], world.resource_totals()
        world._maintain_work_orders()
        self.assertEqual(successor.parent_id, BUILDER)
        self.assertEqual(order['status'], 'expired')
        self.assertAlmostEqual(successor.inventory['coins'], coins + 4.8)
        self.assertConserved(before, world.resource_totals())

    def test_failed_hire_accounting_rolls_back(self):
        world = SocietyWorld()
        before, rng = world.export(), world.rng.getstate()
        original = SocietyWorld._account_action

        def fail_after_account(instance, *args):
            original(instance, *args)
            raise RuntimeError('injected after the escrow moved')
        with patch.object(SocietyWorld, '_account_action', fail_after_account):
            with self.assertRaises(RuntimeError):
                world.submit_action(dict(actor=BUILDER, type='hire', resource='iron', quantity=2, unit_wage=2))
        self.assertEqual(world.export(), before)
        self.assertEqual(world.rng.getstate(), rng)

    def test_open_private_jobs_survive_save_and_resume(self):
        world = SocietyWorld(seed=18)
        hired(world)
        restored = restore_checkpoint(json.loads(json.dumps(checkpoint(world), allow_nan=False)))
        for _ in range(8):
            world.step()
            restored.step()
        self.assertEqual(restored.export(), world.export())


class CommissionTests(LaborTestCase):
    def test_commission_spends_the_organizations_own_voted_holdings(self):
        world = SocietyWorld()
        guild = funded_guild(world)
        world.advance_time()
        world.advance_time()
        decision = proposal(world, guild, 'commission', dict(resource='iron', quantity=3, unit_wage=2))
        before, town_coins = world.resource_totals(), world.settlements[0].treasury
        result = world.submit_action(dict(actor=FARMER, type='enact', institution=guild.id, proposal=decision['id']))
        self.assertTrue(result.success, result.message)
        order = world.work_orders[-1]
        self.assertEqual(order['employer'], {'kind': 'institution', 'id': guild.id})
        self.assertEqual(guild.treasury, 14)
        self.assertEqual(world.settlements[0].treasury, town_coins)
        self.assertConserved(before, world.resource_totals())
        world.advance_time()
        result = world.submit_action(dict(actor=MINER, type='work', order=order['id'], amount=3))
        self.assertTrue(result.success, result.message)
        self.assertEqual(guild.inventory['iron'], 3)
        self.assertEqual(world.work_history[-1]['purpose'], 'institution_commission')
        self.assertEqual(world.economic_metrics['commissions'], 1)

    def test_councils_spend_town_money_through_work_orders_not_commissions(self):
        world = SocietyWorld()
        council, guild = add_council(world), add_council(world, purpose='guild')
        terms = dict(resource='iron', quantity=2, unit_wage=2)
        result = world.submit_action(dict(actor=FARMER, type='propose', params=dict(
            institution=council.id, kind='commission', params=terms)))
        self.assertEqual(result.code, 'invalid_action')
        world.advance_time()
        result = world.submit_action(dict(actor=FARMER, type='propose', params=dict(
            institution=guild.id, kind='commission', params=terms)))
        self.assertTrue(result.success, result.message)

    def test_commission_requires_the_organizations_coins(self):
        world = SocietyWorld()
        guild = funded_guild(world, coins=2.)
        world.tick = 2
        decision = proposal(world, guild, 'commission', dict(resource='iron', quantity=3, unit_wage=2))
        town_coins = world.settlements[0].treasury
        result = world.submit_action(dict(actor=FARMER, type='enact', institution=guild.id, proposal=decision['id']))
        self.assertEqual(result.code, 'insufficient_resources')
        self.assertEqual(world.settlements[0].treasury, town_coins)

    def test_collapsed_organizations_escrow_returns_to_its_town(self):
        world = SocietyWorld()
        guild = funded_guild(world)
        world.tick = 2
        decision = proposal(world, guild, 'commission', dict(resource='iron', quantity=3, unit_wage=2))
        self.assertTrue(world.submit_action(dict(actor=FARMER, type='enact', institution=guild.id,
                                                 proposal=decision['id'])).success)
        order, town = world.work_orders[-1], world.settlements[0]
        guild.members.clear()
        guild.empty_since = world.tick - 4
        before, coins = world.resource_totals(), town.treasury
        world._maintain_institutions()  # collapse returns the remaining 14 coins
        world._maintain_work_orders()   # the escrowed 6 follow
        self.assertFalse(guild.active)
        self.assertEqual(order['status'], 'expired')
        self.assertAlmostEqual(town.treasury, coins + 20)
        self.assertConserved(before, world.resource_totals())


class JobBoardTests(unittest.TestCase):
    def test_neighbors_see_public_terms_of_remote_jobs_only(self):
        world = SocietyWorld()
        _, order = funded_order(world, town=0)
        local = world.observe(MINER)['municipality']
        self.assertEqual([o['id'] for o in local['work_orders']], [order['id']])
        self.assertEqual(local['job_board'], [])
        remote = world.observe(7)['municipality']  # Highfen's miner
        self.assertEqual(remote['work_orders'], [])
        notice, = remote['job_board']
        self.assertEqual(notice['id'], order['id'])
        self.assertEqual(set(notice), {'id', 'settlement', 'employer', 'resource', 'quantity',
                                       'remaining', 'unit_wage', 'created', 'expires'})

    def test_a_job_is_not_advertised_before_it_can_be_worked(self):
        world = SocietyWorld()
        world.submit_action(dict(actor=BUILDER, type='hire', resource='iron', quantity=2, unit_wage=2))
        self.assertEqual(world.observe(7)['municipality']['job_board'], [])


class JobValuationTests(unittest.TestCase):
    order = dict(quantity=16, remaining=16, unit_wage=2., created=4, expires=16)

    def test_remote_value_needs_evidence_and_shrinks_with_competition(self):
        value = lambda order, tick: job_value(order, tick=tick, energy=80, regen=6, deposit=18, delay=4)
        self.assertEqual(value(self.order, 5), (0., 0.))  # nobody could have worked it yet
        idle, units = value(self.order, 6)
        self.assertGreater(idle, 0)
        self.assertEqual(units, 16)
        self.assertEqual(value({**self.order, 'remaining': 8}, 6)[0], 0)  # 8 claimed per tick locally
        self.assertEqual(value(self.order, 13), (0., 0.))  # it would expire before arrival
        risky = job_value(self.order, tick=6, energy=80, regen=6, deposit=18, delay=4, risk=.5)[0]
        self.assertAlmostEqual(risky, idle / 2)

    @staticmethod
    def builder_missing_iron():
        world = SocietyWorld()
        # A minority council: membership exists, but no authority over town money,
        # so the builder must obtain the missing iron personally.
        add_council(world, members=[FARMER, BUILDER])
        builder, town = world.agents[BUILDER], world.settlements[0]
        town.wood -= 4  # a transfer: only iron is still missing for the house
        builder.inventory['wood'] += 4
        return world, town

    def test_builder_buys_iron_the_market_stocks_at_a_reasonable_price(self):
        world, town = self.builder_missing_iron()
        self.assertLessEqual(world.market_prices[0]['iron'], 1.5 * 4)
        plan = EconomicPolicy('balanced').propose(world.observe(BUILDER))
        self.assertEqual(plan['type'], 'trade', plan)
        self.assertEqual(plan['params'], {'resource': 'iron', 'amount': 2, 'direction': 'buy'})

    def test_builder_hires_for_iron_the_market_cannot_supply(self):
        world, town = self.builder_missing_iron()
        town.deposits['iron'] += town.iron  # stored iron becomes accessible: nothing to buy
        town.iron = 0.
        world.reset_market_prices()
        plan = EconomicPolicy('balanced').propose(world.observe(BUILDER))
        self.assertEqual(plan['type'], 'hire', plan)
        # Since v0.9 the job says which step of his own goal it serves.
        self.assertEqual(plan['params'], {'resource': 'iron', 'quantity': 2,
                                          'unit_wage': offered_wage(world.market_prices[0]['iron']),
                                          'purpose': {'kind': 'goal', 'step': 'house'}})

    def test_members_propose_a_commission_for_missing_road_material(self):
        world = SocietyWorld()
        guild = funded_guild(world)
        world.tick = 2
        world.links[1]['condition'] = .4
        proposal(world, guild, 'repair_route', {'link': 1}, approved=False)
        farmer = world.agents[FARMER]
        world.settlements[0].food -= 12 - farmer.inventory['food']  # his own food reserve is already met
        farmer.inventory['food'] = 12.
        plan = EconomicPolicy('personal').propose(world.observe(FARMER))
        self.assertEqual(plan['type'], 'propose', plan)
        self.assertEqual(plan['params']['kind'], 'commission')
        self.assertEqual(plan['params']['params'], {'resource': 'iron', 'quantity': 1,
                                                    'unit_wage': offered_wage(world.market_prices[0]['iron'])})


class LaborExperimentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = run_labor_experiments(seed=42, years=2)
        cls.cases = {case['name']: case for case in cls.data['cases']}

    def test_setups_change_conditions_not_resource_totals(self):
        totals = [build_labor_scenario(name, 42)[0].resource_totals() for name in self.cases]
        for other in totals[1:]:
            for resource, amount in totals[0].items():
                self.assertAlmostEqual(other[resource], amount)
        world, metadata = build_labor_scenario('paid_opportunity', 42)
        self.assertFalse(world.action_log)
        self.assertNotIn('mining', world.agents[7].skills)
        self.assertEqual(metadata['skilled_workers'], [1, 13])

    def test_valuable_remote_work_leads_to_travel_work_and_pay(self):
        summary = self.cases['paid_opportunity']['summary']
        self.assertGreaterEqual(summary['labor_migrations'], 1)
        self.assertGreater(summary['wages_after_migration'], 0)
        self.assertGreater(summary['highfen_job_units_delivered'], 0)
        workers = set(summary['highfen_job_workers'])
        self.assertTrue(workers and workers <= {1, 13})
        for move in self.cases['paid_opportunity']['evidence']['migrations']:
            self.assertGreaterEqual(move['first_paid_tick'], move['arrived'])

    def test_low_pay_local_work_and_blocked_roads_keep_miners_home(self):
        for name in ('low_wage', 'local_work', 'blocked_route'):
            with self.subTest(case=name):
                summary = self.cases[name]['summary']
                self.assertEqual(summary['highfen_job_units_delivered'], 0)
                for worker in summary['workers']:
                    self.assertEqual(worker['job_migrations_proposed'], 0)
                    self.assertEqual(worker['final_home'], worker['initial_home'])

    def test_experiment_is_repeatable_and_accounting_reconciles(self):
        first, second = (run_labor_experiments(seed=42, years=1) for _ in range(2))
        self.assertEqual([c['summary'] for c in first['cases']], [c['summary'] for c in second['cases']])
        world, _ = build_labor_scenario('paid_opportunity', 42)
        world.run(2)
        self.assertLess(summarize(world)['ledger_max_residual'], 1e-6)


class LaborEvaluationTests(unittest.TestCase):
    def test_labor_shortage_changes_knowledge_not_resources(self):
        baseline, shortage = (build_society_scenario(42, s) for s in ('baseline', 'labor_shortage'))
        self.assertEqual(baseline.resource_totals(), shortage.resource_totals())
        self.assertIn('mining', baseline.agents[7].skills)
        self.assertNotIn('mining', shortage.agents[7].skills)
        self.assertFalse(shortage.work_orders)

    def test_labor_migrations_need_paid_work_in_the_destination_after_arrival(self):
        world = SocietyWorld()
        world.journeys.append(dict(kind='migrant', status='delivered', actor=MINER, origin=0,
                                   destination=1, created=2, arrived=5))
        paid = lambda tick, town: dict(tick=tick, actor=MINER, mode='paid', settlement=town, coins=4.)
        world.work_history = [paid(4, 1), paid(6, 0), paid(6, 1), paid(7, 1)]
        move, = labor_migrations(world)
        self.assertEqual((move['paid_actions'], move['wages'], move['first_paid_tick']), (2, 8., 6))
        summary = summarize(world)
        self.assertEqual((summary['labor_migrations'], summary['wages_after_migration']), (1, 8.))


class LaborCliTests(unittest.TestCase):
    def run_cli(self, *args):
        return subprocess.run([sys.executable, 'main.py', *map(str, args)], cwd=ROOT,
                              text=True, capture_output=True)

    def test_cli_writes_matched_cases_and_rejects_single_world_options(self):
        with tempfile.TemporaryDirectory() as folder:
            result = self.run_cli('--labor-experiment', '--years', 1, '--output', folder)
            self.assertEqual(result.returncode, 0, result.stderr)
            data = json.loads((Path(folder) / 'summary.json').read_text(encoding='utf-8'))
            self.assertEqual([c['name'] for c in data['cases']],
                             ['paid_opportunity', 'low_wage', 'local_work', 'blocked_route'])
            self.assertIn('Will someone travel for paid work?', (Path(folder) / 'report.html').read_text(encoding='utf-8'))
            self.assertTrue((Path(folder) / 'paid_opportunity' / 'report.html').exists())
            result = self.run_cli('--labor-experiment', '--save', Path(folder) / 'x.json')
            self.assertNotEqual(result.returncode, 0)


if __name__ == '__main__':
    unittest.main()
