"""v0.7 Stage 4: measuring inequality, perceptions of fairness, and the responses they shape."""
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from eternia.economic_policy import EconomicPolicy
from eternia.inequality import decade_mobility, food_insecure, gini, person_wealth, rank_mobility, structure_value
from eternia.inequality_experiments import INEQUALITY_SCENARIOS, build_inequality_scenario, run_inequality_case
from eternia.institution_policy import levy_vote
from eternia.market import BASE_PRICES
from eternia.motivations import update_fairness
from eternia.society import SocietyWorld
from v07_helpers import add_council, funded_order, proposal

ROOT = Path(__file__).resolve().parents[1]
FARMER, MINER, MERCHANT, BUILDER = 0, 1, 2, 3  # Rivermark residents


def totals_equal(test, before, after):
    for resource, total in before.items():
        test.assertTrue(math.isclose(total, after[resource], abs_tol=1e-9), (resource, total, after[resource]))


def set_mind(world, person, fairness=.5, **motives):
    mind = world.minds[person]
    mind['fairness'] = fairness
    for motive, value in motives.items():
        mind['motivations'][motive] = value
    return mind


def reserve_met(world, person=FARMER):
    """The farmer's own goal, a 12-food reserve, is already met (food from town stores)."""
    farmer, town = world.agents[person], world.settlements[world.agents[person].home]
    town.food -= 12 - farmer.inventory['food']
    farmer.inventory['food'] = 12.


class MeasureTests(unittest.TestCase):
    def test_gini_spans_equality_to_concentration(self):
        self.assertEqual(gini([5, 5, 5]), 0.)
        self.assertAlmostEqual(gini([0, 0, 0, 1]), .75)
        self.assertEqual(gini([]), 0.)
        self.assertEqual(gini([0, 0]), 0.)
        self.assertLess(gini([1, 2, 3]), gini([0, 0, 6]))

    def test_rank_mobility_compares_orders_not_amounts(self):
        before = {'a': 1, 'b': 2, 'c': 3, 'd': 4}
        self.assertEqual(rank_mobility(before, {k: v * 10 for k, v in before.items()}), 0.)
        self.assertEqual(rank_mobility(before, {'a': 4, 'b': 3, 'c': 2, 'd': 1}), 2.)
        self.assertIsNone(rank_mobility({'a': 1, 'b': 2}, {'a': 2, 'b': 1}))
        self.assertIsNone(rank_mobility(before, dict.fromkeys(before, 1)))

    def test_wealth_counts_coins_goods_and_structures_at_home_prices(self):
        world = SocietyWorld(seed=42)
        person, prices = world.agents[BUILDER], world.market_prices[0]
        person.structures['house'] = 1
        wealth = person_wealth(person, prices)
        self.assertAlmostEqual(wealth['structures'], structure_value('house', prices))
        self.assertAlmostEqual(wealth['total'], wealth['coins'] + wealth['goods'] + wealth['structures'])
        person.inventory.update(food=0., coins=0.)
        self.assertTrue(food_insecure(person, BASE_PRICES))

    def test_every_yearly_snapshot_records_named_people_only(self):
        world = SocietyWorld(seed=42).run(2)
        for snap in world.snapshots:
            record = snap['inequality']
            self.assertEqual(record['region']['people'], len(snap['agents']))
            self.assertEqual(set(record['towns']), {0, 1, 2})
        self.assertEqual(decade_mobility(world.snapshots, span=1)[0]['start'], 0)


class PerceptionTests(unittest.TestCase):
    def review(self, world, records):
        world._review_minds(records)
        return world.minds

    def test_a_wage_far_below_the_market_feels_unfair_and_a_fair_one_does_not(self):
        for wage, kind in ((.3, 'underpaid'), (5., 'fair_pay')):
            with self.subTest(wage=wage):
                world = SocietyWorld(seed=42)
                _, order = funded_order(world, wage=wage, quantity=2)
                records = world.resolve_actions([dict(actor=MINER, type='work', order=order['id'], amount=1)])
                self.assertTrue(records[0]['result']['success'], records)
                minds = self.review(world, records)
                self.assertIn(kind, minds[MINER]['experience'])
                self.assertEqual(minds[MINER]['fairness'] < .5, kind == 'underpaid')

    def test_private_work_changes_trust_between_worker_and_employer(self):
        world = SocietyWorld(seed=42)
        result = world.submit_action(dict(actor=BUILDER, type='hire', resource='iron', quantity=1, unit_wage=5))
        self.assertTrue(result.success, result.message)
        world.advance_time()
        records = world.resolve_actions([dict(actor=MINER, type='work', order=world.work_orders[-1]['id'], amount=1)])
        self.review(world, records)
        self.assertGreater(world.agents[MINER].trust[BUILDER], 0)
        self.assertGreater(world.agents[BUILDER].trust[MINER], 0)

    def test_aid_in_hardship_builds_fairness_and_trust_in_those_who_approved_it(self):
        world = SocietyWorld(seed=42)
        coop = add_council(world, purpose='cooperative')
        world.settlements[0].food -= 4  # a transfer into the cooperative's stores
        coop.inventory['food'] += 4
        world.tick = 2
        decision = proposal(world, coop, 'distribute_food', dict(destination='member', member=FARMER, amount=3))
        records = world.resolve_actions([dict(actor=MINER, type='enact', institution=coop.id, proposal=decision['id'])])
        self.assertTrue(records[0]['result']['success'], records)
        minds = self.review(world, records)
        self.assertIn('helped', minds[FARMER]['experience'])
        self.assertGreater(minds[FARMER]['fairness'], .5)
        self.assertGreater(world.agents[FARMER].trust[MERCHANT], 0)
        self.assertIn('mutual_aid', minds[BUILDER]['experience'])

    def test_hunger_beside_unaffordable_food_feels_unfair(self):
        world = SocietyWorld(seed=42)
        person, town = world.agents[FARMER], world.settlements[0]
        town.food += person.inventory['food']
        town.treasury += person.inventory['coins']  # transfers: no food, no coins, food still on sale
        person.inventory.update(food=0., coins=0.)
        person.hunger = 50.
        minds = self.review(world, [])
        self.assertIn('priced_out', minds[FARMER]['experience'])
        self.assertLess(minds[FARMER]['fairness'], .5)

    def test_fairness_fades_back_toward_neutral(self):
        value = update_fairness(.5, {'priced_out': 1})
        self.assertLess(value, .5)
        for _ in range(100):
            value = update_fairness(value, {})
        self.assertLess(abs(value - .5), .01)  # about 13% of a one-off change remains after 25 years
        self.assertEqual(update_fairness(.5, {'underpaid': 10}), round(.5 - .08 + .02 * .08, 6))


class LevyTests(unittest.TestCase):
    def test_a_majority_councils_levy_funds_the_town_treasury(self):
        world = SocietyWorld(seed=42)
        council, guild = add_council(world), add_council(world, purpose='guild', members=[MINER, MERCHANT])
        council.rules['tax_rate'], guild.rules['tax_rate'] = .1, .05
        before, treasury = world.resource_totals(), world.settlements[0].treasury
        coins = {a.id: a.inventory['coins'] for a in world.agents if a.home == 0}
        world._collect_member_levies()
        expected = sum(coins[a] * .1 for a in council.members)
        self.assertAlmostEqual(world.settlements[0].treasury, treasury + expected)
        self.assertGreater(guild.treasury, 0)  # a voluntary organization keeps its own levy
        self.assertEqual(council.treasury, 0)
        totals_equal(self, before, world.resource_totals())
        self.assertTrue(all(e.get('municipal') for e in world.events if e['kind'] == 'levy'
                            and e.get('institution_id') == council.id))

    def test_levy_votes_follow_each_members_position(self):
        vote = lambda **change: levy_vote(**{**dict(coins=20, value=.08, current=0, fairness=.5, solidarity=.4,
                                                    wealth_motive=.5), **change})
        self.assertTrue(vote(coins=20))                       # costs 1.6 coins a year
        self.assertFalse(vote(coins=200))                     # costs 16 coins a year
        self.assertTrue(vote(coins=200, solidarity=.6))       # but cares about neighbors and legacy
        self.assertTrue(vote(coins=50, fairness=.2))          # or feels the town is unfair
        self.assertTrue(vote(coins=200, value=0, current=.08, wealth_motive=.7))
        self.assertFalse(vote(coins=200, value=0, current=.08, wealth_motive=.7, fairness=.2))

    def test_a_council_member_proposes_a_levy_when_the_treasury_runs_low(self):
        world = SocietyWorld(seed=42)
        council = add_council(world)
        reserve_met(world)
        moved = world.settlements[0].treasury - 5  # a transfer: too little left even for public work
        world.settlements[0].treasury -= moved
        world.settlements[1].treasury += moved
        set_mind(world, FARMER, fairness=.3)
        plan = EconomicPolicy('balanced').propose(world.observe(FARMER))
        self.assertEqual((plan['type'], plan['params'].get('kind')), ('propose', 'tax_rate'), plan)
        self.assertEqual(plan['params']['institution'], council.id)


class ResponseTests(unittest.TestCase):
    def plan(self, world, person):
        return EconomicPolicy('balanced').propose(world.observe(person))

    def test_a_person_who_feels_treated_unfairly_seeks_a_cooperative(self):
        world = SocietyWorld(seed=42)
        add_council(world, members=[MINER, MERCHANT])  # no council business of the farmer's own
        reserve_met(world)
        set_mind(world, FARMER, fairness=.2, belonging=.6)
        plan = self.plan(world, FARMER)
        self.assertEqual((plan['type'], plan['params'].get('purpose')), ('form_institution', 'cooperative'), plan)
        coop = add_council(world, purpose='cooperative', members=[MINER, MERCHANT])
        plan = self.plan(world, FARMER)
        self.assertEqual((plan['type'], plan['params']), ('join_institution', {'institution': coop.id}), plan)

    def test_the_same_circumstances_without_grievance_bring_no_rush_to_organize(self):
        world = SocietyWorld(seed=42)
        add_council(world, members=[MINER, MERCHANT])
        reserve_met(world)
        set_mind(world, FARMER, fairness=.6, belonging=.6)
        self.assertNotEqual(self.plan(world, FARMER)['type'], 'form_institution')

    def test_wealthy_neighbors_who_care_about_their_town_give(self):
        world = SocietyWorld(seed=42)
        add_council(world, members=[MINER, MERCHANT])
        coop = add_council(world, purpose='cooperative', members=[FARMER, MERCHANT])
        reserve_met(world)
        world.settlements[0].treasury -= 100
        world.agents[FARMER].inventory['coins'] += 100  # a transfer: a wealthy farmer
        set_mind(world, FARMER, belonging=.9, legacy=.9)
        plan = self.plan(world, FARMER)
        self.assertEqual((plan['type'], plan['params']['institution'], plan['params']['resource']),
                         ('contribute', coop.id, 'coins'), plan)

    def test_a_wealthy_member_who_resents_a_levy_may_leave(self):
        world = SocietyWorld(seed=42)
        guild = add_council(world, purpose='guild', members=[MINER, MERCHANT])
        guild.rules['tax_rate'] = .1
        world.settlements[0].treasury -= 100
        world.agents[MERCHANT].inventory['coins'] += 100
        set_mind(world, MERCHANT, fairness=.6, wealth=.9, belonging=.2, legacy=.2)
        plan = self.plan(world, MERCHANT)
        self.assertEqual((plan['type'], plan['params']), ('leave_institution', {'institution': guild.id}), plan)

    def test_feeling_unfairly_treated_weakens_the_pull_of_home(self):
        world = SocietyWorld(seed=42)
        _, order = funded_order(world, town=1, resource='iron', quantity=16, wage=3)
        world.advance_time()
        world.advance_time()
        world.work_orders[-1]['remaining'] = 15  # one unit claimed: evidence the job is real
        nets = {}
        for fairness in (.1, .9):
            set_mind(world, MINER, fairness=fairness)
            observation = world.observe(MINER)
            move = EconomicPolicy('balanced')._best_move(observation, .5, 0.)
            nets[fairness] = move['net'] if move else None
        self.assertIsNotNone(nets[.1])
        self.assertTrue(nets[.9] is None or nets[.9] < nets[.1])


class InequalityExperimentTests(unittest.TestCase):
    def test_setups_move_coins_without_changing_totals(self):
        totals = SocietyWorld(seed=42).resource_totals()
        start = {}
        for name in INEQUALITY_SCENARIOS:
            world, metadata = build_inequality_scenario(name, 42)
            totals_equal(self, totals, world.resource_totals())
            start[name] = world.snapshots[0]['inequality']['region']['wealth_gini']
        self.assertLess(start['equal_start'], start['unequal_start'])
        self.assertLess(start['unequal_start'], start['unequal_private_funds'])

    def test_cases_record_yearly_outcomes_and_repeat_exactly(self):
        first, second = (run_inequality_case('unequal_start', 42, years=2) for _ in range(2))
        self.assertEqual(first['summary'], second['summary'])
        self.assertEqual(len(first['series']), 3)
        for key in ('wealth_gini', 'fairness', 'trust', 'cooperative_share', 'migrations', 'levies'):
            self.assertIn(key, first['series'][-1])

    def test_cli_writes_the_comparison(self):
        with tempfile.TemporaryDirectory() as folder:
            run = lambda *args: subprocess.run([sys.executable, 'main.py', *map(str, args)], cwd=ROOT,
                                               text=True, capture_output=True)
            result = run('--inequality-experiment', '--years', 1, '--output', folder)
            self.assertEqual(result.returncode, 0, result.stderr)
            data = json.loads((Path(folder) / 'summary.json').read_text(encoding='utf-8'))
            self.assertEqual([c['name'] for c in data['cases']], list(INEQUALITY_SCENARIOS))
            self.assertEqual(set(data['differences']), {'unequal_start', 'unequal_private_funds'})
            self.assertIn('Does inequality change a society?', (Path(folder) / 'report.html').read_text(encoding='utf-8'))
            self.assertIn('id="inequalityPanel"', (Path(folder) / 'equal_start' / 'report.html').read_text(encoding='utf-8'))
            self.assertNotEqual(run('--inequality-experiment', '--save', Path(folder) / 'x.json').returncode, 0)


if __name__ == '__main__':
    unittest.main()
