"""v0.7 Stage 2: local prices, purchasing, merchant consignments and price-aware wages."""
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from eternia.economic_policy import EconomicPolicy, market_view, shipment_gain
from eternia.evaluation import build_society_scenario, summarize
from eternia.market import bid_price, bounds, coverage, next_price, offered_wage, target_price
from eternia.market_experiments import HIGHFEN, RIVERMARK, build_market_scenario, run_market_experiments
from eternia.persistence import checkpoint, restore_checkpoint
from eternia.society import SocietyWorld
from v07_helpers import add_council, funded_order, proposal

ROOT = Path(__file__).resolve().parents[1]
FARMER, MINER, MERCHANT, RESEARCHER = 0, 1, 2, 4  # Rivermark residents


def totals_equal(test, before, after):
    for resource, total in before.items():
        test.assertTrue(math.isclose(total, after[resource], abs_tol=1e-9), (resource, total, after[resource]))


def safe_roads(world):
    for link in world.links:
        link['risk'] = 0.


class PriceRuleTests(unittest.TestCase):
    def test_a_town_producing_its_use_and_holding_its_reserve_pays_the_base_price(self):
        cover = coverage('food', population=100, stock=112, production=100)
        self.assertAlmostEqual(cover, 1.)
        self.assertAlmostEqual(target_price('food', cover), 1.)

    def test_scarcity_raises_the_target_within_bounds(self):
        self.assertAlmostEqual(target_price('food', .5), 2.)
        self.assertAlmostEqual(target_price('iron', 2.), 2.)
        self.assertEqual(target_price('food', 0.), bounds('food')[1])
        self.assertEqual(target_price('food', 100.), bounds('food')[0])

    def test_posted_prices_move_at_most_a_quarter_per_cycle(self):
        self.assertEqual(next_price('food', 1., 4.), 1.25)
        self.assertEqual(next_price('food', 1., .1), .8)
        self.assertEqual(next_price('food', 1., 1.1), 1.1)
        self.assertEqual(next_price('food', None, 2.346), 2.35)

    def test_wages_and_bids_follow_the_posted_price(self):
        self.assertEqual(bid_price(2.5), 2.)
        self.assertEqual(offered_wage(5.), 3.)
        self.assertEqual(offered_wage(16.), 5.)  # job wages stay within 0.1 to 5 coins
        self.assertEqual(offered_wage(.1), .1)


class LocalPriceTests(unittest.TestCase):
    def test_a_food_shortage_raises_the_local_price_against_matched_conditions(self):
        control, shortage = SocietyWorld(seed=42), build_society_scenario(42, 'food_shortage')
        self.assertEqual(control.resource_totals(), shortage.resource_totals())
        self.assertGreater(shortage.market_prices[HIGHFEN]['food'], control.market_prices[HIGHFEN]['food'])
        self.assertLess(shortage.market_prices[RIVERMARK]['food'], control.market_prices[RIVERMARK]['food'])
        self.assertEqual(shortage.market_prices[HIGHFEN]['iron'], control.market_prices[HIGHFEN]['iron'])

    def test_increased_supply_reduces_scarcity_pressure(self):
        world = build_society_scenario(42, 'food_shortage')
        price, cover = world.market_prices[HIGHFEN]['food'], world.market_coverage[HIGHFEN]['food']
        world.settlements[RIVERMARK].food -= 120  # a transfer, as a delivery would make
        world.settlements[HIGHFEN].food += 120
        world._update_prices()
        self.assertGreater(world.market_coverage[HIGHFEN]['food'], cover)
        self.assertLess(world.market_prices[HIGHFEN]['food'], price)
        self.assertGreaterEqual(world.market_prices[HIGHFEN]['food'], round(price / 1.25, 2) - .01)

    def test_cargo_on_the_road_counts_as_supply(self):
        world = build_society_scenario(42, 'food_shortage')
        before = coverage('food', **world.market_basis(HIGHFEN, 'food'))
        world.journeys.append(dict(id=99, kind='caravan', status='in_transit', destination=HIGHFEN,
                                   cargo={'food': 30.}))
        self.assertEqual(world.market_basis(HIGHFEN, 'food')['incoming'], 30.)
        self.assertGreater(coverage('food', **world.market_basis(HIGHFEN, 'food')), before)

    def test_a_recorded_harvest_replaces_the_neutral_production_estimate(self):
        world = SocietyWorld(seed=42)
        self.assertIsNone(world.market_basis(HIGHFEN, 'food')['production'])
        world.run(1)
        produced = world.market_basis(HIGHFEN, 'food')['production']
        self.assertGreater(produced, 0)
        self.assertLess(produced, world.settlements[HIGHFEN].population * 1.2)  # Highfen cannot feed itself
        self.assertEqual(len(world.price_history), world.tick + 1)

    def test_prices_are_public_notices_at_home_and_in_neighbor_towns(self):
        world = SocietyWorld(seed=42)
        observation = world.observe(MERCHANT)
        self.assertEqual(observation['rules']['prices'], world.market_prices[RIVERMARK])
        self.assertEqual(observation['regional']['prices'], world.market_prices[RIVERMARK])
        self.assertEqual(set(observation['prices']['posted']), {0, 1, 2})
        self.assertEqual(set(observation['prices']['coverage']), {RIVERMARK})


class RetailTests(unittest.TestCase):
    def test_people_buy_at_the_posted_price_and_sell_at_the_markets_bid(self):
        world = SocietyWorld(seed=42)
        prices, before = dict(world.market_prices[RIVERMARK]), world.resource_totals()
        coins = {i: world.agents[i].inventory['coins'] for i in (FARMER, RESEARCHER)}
        records = world.resolve_actions([
            dict(actor=FARMER, type='trade', resource='food', amount=2, direction='buy'),
            dict(actor=RESEARCHER, type='trade', resource='wood', amount=1, direction='sell')])
        self.assertTrue(all(r['result']['success'] for r in records), records)
        self.assertAlmostEqual(world.agents[FARMER].inventory['coins'], coins[FARMER] - 2 * prices['food'])
        self.assertAlmostEqual(world.agents[RESEARCHER].inventory['coins'], coins[RESEARCHER] + bid_price(prices['wood']))
        totals_equal(self, before, world.resource_totals())
        kinds = [(t['kind'], t['unit_price']) for t in world.trade_history]
        self.assertCountEqual(kinds, [('purchase', prices['food']), ('sale', bid_price(prices['wood']))])
        self.assertEqual(world.market_metrics['purchases'], 1)

    def test_one_posted_price_applies_to_every_trade_in_a_cycle(self):
        world = SocietyWorld(seed=42)
        price = world.market_prices[RIVERMARK]['food']
        records = world.resolve_actions([dict(actor=i, type='trade', resource='food', amount=8, direction='buy')
                                         for i in (FARMER, RESEARCHER)])
        self.assertEqual({r['result']['effects']['unit_price'] for r in records}, {price})
        self.assertEqual(world.market_prices[RIVERMARK]['food'], price)  # updates only between cycles
        world.advance_time()
        self.assertEqual(len(world.price_history), 2)


class ConsignmentTests(unittest.TestCase):
    def merchant_with_cargo(self, scenario='price_gap', food=8):
        world, _ = build_market_scenario(scenario, 42)
        safe_roads(world)
        world.settlements[RIVERMARK].food -= food  # a transfer standing in for a purchase
        world.agents[MERCHANT].inventory['food'] += food
        return world

    def consign(self, world, amount=8):
        return world.submit_action(dict(actor=MERCHANT, type='consign', resource='food',
                                        amount=amount, destination=HIGHFEN))

    def test_consignment_escrows_payment_and_puts_goods_on_the_road(self):
        world = self.merchant_with_cargo()
        merchant, highfen = world.agents[MERCHANT], world.settlements[HIGHFEN]
        before, food, treasury = world.resource_totals(), merchant.inventory['food'], highfen.treasury
        offer = bid_price(world.market_prices[HIGHFEN]['food'])
        result = self.consign(world)
        self.assertTrue(result.success, result.message)
        journey = world.journeys[-1]
        self.assertTrue(journey['consignment'])
        self.assertEqual(journey['cargo'], {'food': 8.})
        self.assertAlmostEqual(journey['escrow'], 8 * offer)
        self.assertAlmostEqual(highfen.treasury, treasury - 8 * offer)
        self.assertAlmostEqual(merchant.inventory['food'], food - 8 - journey['supplies'])
        self.assertGreater(journey['expected_gain'], 0)
        totals_equal(self, before, world.resource_totals())
        self.assertEqual(world.trade_history[-1]['kind'], 'consignment')

    def test_delivery_pays_the_merchant_and_stocks_the_destination(self):
        world = self.merchant_with_cargo()
        self.assertTrue(self.consign(world).success)
        journey, merchant = world.journeys[-1], world.agents[MERCHANT]
        coins, escrow = merchant.inventory['coins'], journey['escrow']
        for _ in range(12):
            if journey['status'] != 'in_transit':
                break
            world.advance_time()
        self.assertEqual(journey['status'], 'delivered')
        self.assertAlmostEqual(merchant.inventory['coins'], coins + escrow)
        # Delivered into Highfen's stores (its population may eat them at the year's end).
        self.assertEqual(world._flows[HIGHFEN]['imports']['food'], 8)
        self.assertEqual(world.trade_shipments[-1]['importer'], HIGHFEN)
        self.assertAlmostEqual(journey['gain'], escrow - journey['origin_value'])
        self.assertEqual(world.market_metrics['consignments_delivered'], 1)
        self.assertEqual(merchant.memory[-1]['kind'], 'consignment')
        world._assert_invariants()

    def test_a_lost_consignment_refunds_the_market_and_counts_as_a_loss(self):
        world = self.merchant_with_cargo()
        treasury = world.settlements[HIGHFEN].treasury
        self.assertTrue(self.consign(world).success)
        journey, coins = world.journeys[-1], world.agents[MERCHANT].inventory['coins']
        world._fail_caravan(journey, 'a test accident')
        self.assertAlmostEqual(world.settlements[HIGHFEN].treasury, treasury)
        self.assertEqual(world.agents[MERCHANT].inventory['coins'], coins)
        self.assertAlmostEqual(journey['gain'], -journey['origin_value'])
        self.assertEqual(world.market_metrics['consignments_lost'], 1)
        self.assertEqual(world.agents[MERCHANT].memory[-1]['gain'], round(journey['gain'], 6))
        world._assert_invariants()

    def test_consignment_needs_cargo_provisions_a_road_and_a_solvent_market(self):
        world = self.merchant_with_cargo()
        world.agents[MERCHANT].inventory['food'] = 8.  # cargo but no journey food
        world.settlements[RIVERMARK].food += 14.        # keep totals: the rest returns to town
        before = world.resource_totals()
        self.assertEqual(self.consign(world).code, 'insufficient_resources')
        totals_equal(self, before, world.resource_totals())
        world = self.merchant_with_cargo('blocked_route')
        self.assertEqual(self.consign(world).code, 'no_path')
        world = self.merchant_with_cargo()
        world.settlements[RIVERMARK].treasury += world.settlements[HIGHFEN].treasury
        world.settlements[HIGHFEN].treasury = 0.
        self.assertEqual(self.consign(world).code, 'insufficient_resources')
        world = self.merchant_with_cargo()
        world.agents[MERCHANT].skills.remove('trading')
        self.assertEqual(self.consign(world).code, 'missing_knowledge')
        self.assertFalse(any(j.get('consignment') for j in world.journeys))


class MerchantPolicyTests(unittest.TestCase):
    def candidates(self, world):
        observation = world.observe(MERCHANT)
        return EconomicPolicy('balanced')._consignment_candidates(observation, market_view(observation))

    def test_shipment_gain_counts_risk_and_provisions(self):
        self.assertAlmostEqual(shipment_gain(amount=8, destination_bid=2, unit_cost=1, supplies=3,
                                             food_price=1, risk=.25), 12 - 8 - 3)

    def test_a_merchant_buys_cheap_food_for_a_dearer_market(self):
        world, _ = build_market_scenario('price_gap', 42)
        plan = EconomicPolicy('balanced').propose(world.observe(MERCHANT))
        self.assertEqual((plan['type'], plan['params']['resource'], plan['params']['direction']),
                         ('trade', 'food', 'buy'), plan)

    def test_a_merchant_consigns_held_goods_when_the_margin_covers_risk_and_provisions(self):
        world, _ = build_market_scenario('price_gap', 42)
        world.settlements[RIVERMARK].food -= 8
        world.agents[MERCHANT].inventory['food'] += 8
        plan = EconomicPolicy('balanced').propose(world.observe(MERCHANT))
        self.assertEqual(plan['type'], 'consign', plan)
        self.assertEqual((plan['params']['resource'], plan['params']['destination']), ('food', HIGHFEN))

    def test_no_food_shipment_without_a_margin_or_a_road(self):
        for scenario in ('matched_supply', 'blocked_route'):
            with self.subTest(scenario=scenario):
                world, _ = build_market_scenario(scenario, 42)
                food = [c for c in self.candidates(world) if c[1].get('resource') == 'food'
                        and (c[0] == 'consign' or 'consign' in c[3])]
                self.assertEqual(food, [])

    def test_a_recent_loss_raises_the_margin_a_merchant_requires(self):
        world, _ = build_market_scenario('price_gap', 42)
        self.assertTrue(self.candidates(world))
        world.agents[MERCHANT].memory.extend(
            dict(kind='consignment', outcome='lost', destination=HIGHFEN, gain=-5., tick=0) for _ in range(3))
        self.assertEqual(self.candidates(world), [])


class WageAndPurchaseTests(unittest.TestCase):
    def test_workers_decline_a_job_paying_less_than_selling_would(self):
        for wage, works in ((1., False), (None, True)):
            with self.subTest(wage=wage):
                world = SocietyWorld(seed=42)
                fair = offered_wage(world.market_prices[RIVERMARK]['iron'])
                _, order = funded_order(world, quantity=4, wage=wage or fair)
                plan = EconomicPolicy('personal').propose(world.observe(MINER))
                self.assertEqual(plan['type'] == 'work', works, plan)

    def test_councils_reject_wages_above_what_their_market_pays_sellers(self):
        for wage in (1., 5.):
            with self.subTest(wage=wage):
                world = SocietyWorld(seed=42)
                council = add_council(world)
                world.tick = 2
                decision = proposal(world, council, 'work_order', dict(resource='wood', quantity=2, unit_wage=wage),
                                    approved=False)
                plan = EconomicPolicy('balanced').propose(world.observe(FARMER))
                self.assertEqual(plan['type'], 'vote', plan)
                self.assertEqual(plan['params']['proposal'], decision['id'])
                self.assertEqual(plan['params']['approve'], wage <= bid_price(world.market_prices[RIVERMARK]['wood']))

    def test_a_hungry_person_without_food_buys_from_the_market(self):
        world = SocietyWorld(seed=42)
        farmer, town = world.agents[FARMER], world.settlements[RIVERMARK]
        town.food += farmer.inventory['food'] + town.deposits['food']  # transfers: nothing to gather or eat
        farmer.inventory['food'], town.deposits['food'] = 0., 0.
        farmer.hunger = 50.
        plan = EconomicPolicy('balanced').propose(world.observe(FARMER))
        self.assertEqual((plan['type'], plan['params']['resource'], plan['params']['direction']),
                         ('trade', 'food', 'buy'), plan)

    def test_surplus_is_offered_for_sale_only_while_the_price_is_at_least_base(self):
        world = SocietyWorld(seed=42)
        sells = lambda: [c for c in EconomicPolicy()._market_candidates(
            world.observe(MINER), market_view(world.observe(MINER)), [])
            if c[0] == 'trade' and c[1]['direction'] == 'sell' and c[1]['resource'] == 'iron']
        self.assertGreaterEqual(world.market_prices[RIVERMARK]['iron'], 4)
        self.assertTrue(sells())
        world.market_prices[RIVERMARK]['iron'] = 3.
        self.assertEqual(sells(), [])


class MarketPersistenceTests(unittest.TestCase):
    def test_prices_trades_and_shipments_resume_exactly(self):
        world, _ = build_market_scenario('price_gap', 18)
        world.run(1)
        self.assertTrue(world.trade_history)
        restored = restore_checkpoint(json.loads(json.dumps(checkpoint(world), allow_nan=False)))
        for _ in range(6):
            world.step()
            restored.step()
        self.assertEqual(restored.export(), world.export())
        self.assertEqual(restored.price_history, world.price_history)


class MarketExperimentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = run_market_experiments(seed=42, years=2)
        cls.cases = {case['name']: case for case in cls.data['cases']}

    def test_setups_move_food_without_changing_totals(self):
        totals = [build_market_scenario(name, 42)[0].resource_totals() for name in self.cases]
        for other in totals[1:]:
            for resource, amount in totals[0].items():
                self.assertAlmostEqual(other[resource], amount)
        gap, matched = self.cases['price_gap']['summary'], self.cases['matched_supply']['summary']
        self.assertGreater(gap['start_highfen_food_price'], matched['start_highfen_food_price'])
        self.assertEqual(matched['start_highfen_food_price'], matched['start_rivermark_food_price'])

    def test_food_follows_the_price_only_with_a_margin_and_a_road(self):
        gap, matched, blocked = (self.cases[n]['summary'] for n in ('price_gap', 'matched_supply', 'blocked_route'))
        self.assertGreaterEqual(gap['food_shipments_to_highfen'], 1)
        self.assertGreater(gap['food_delivered_to_highfen'], 0)
        self.assertEqual(blocked['food_shipments_to_highfen'], 0)
        first = matched['first_food_departure_tick']
        self.assertTrue(first is None or first >= 4, first)  # not before a harvest opens a gap

    def test_no_shipment_leaves_expecting_a_loss(self):
        for name, case in self.cases.items():
            with self.subTest(case=name):
                self.assertEqual(case['summary']['negative_expected_departures'], 0)
                world_residual = case['history']['final_totals']
                self.assertTrue(all(math.isfinite(v) for v in world_residual.values()))

    def test_experiment_is_repeatable_and_accounting_reconciles(self):
        first, second = (run_market_experiments(seed=42, years=1) for _ in range(2))
        self.assertEqual([c['summary'] for c in first['cases']], [c['summary'] for c in second['cases']])
        world, _ = build_market_scenario('price_gap', 42)
        world.run(2)
        self.assertLess(summarize(world)['ledger_max_residual'], 1e-6)

    def test_cli_writes_matched_cases_and_rejects_single_world_options(self):
        with tempfile.TemporaryDirectory() as folder:
            run = lambda *args: subprocess.run([sys.executable, 'main.py', *map(str, args)], cwd=ROOT,
                                               text=True, capture_output=True)
            result = run('--market-experiment', '--years', 1, '--output', folder)
            self.assertEqual(result.returncode, 0, result.stderr)
            data = json.loads((Path(folder) / 'summary.json').read_text(encoding='utf-8'))
            self.assertEqual([c['name'] for c in data['cases']], ['price_gap', 'matched_supply', 'blocked_route'])
            self.assertIn('Does food follow the price?', (Path(folder) / 'report.html').read_text(encoding='utf-8'))
            self.assertIn('id="marketPanel"', (Path(folder) / 'price_gap' / 'report.html').read_text(encoding='utf-8'))
            self.assertNotEqual(run('--market-experiment', '--save', Path(folder) / 'x.json').returncode, 0)


if __name__ == '__main__':
    unittest.main()
