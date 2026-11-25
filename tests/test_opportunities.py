"""v0.9 Stage 1: needs that people cannot meet themselves become opportunities anyone nearby can take.

A person's goal has a next step; what that step consumes and they lack is a
need. They gather it if they can, buy it if the market sells it at a fair price
they can afford, and otherwise post a paid job for it under the ordinary rules,
saying what it is for. The job is a public notice: a neighbor, a player or
nobody may take it, and it exists whether or not anyone plays.
"""
from copy import deepcopy
import json
import unittest

from eternia import interface
from eternia.economic_policy import EconomicPolicy
from eternia.evaluation import opportunity_record
from eternia.goal_engine import next_step
from eternia.market import offered_wage
from eternia.needs import needs, opening
from eternia.playable_session import PlayableSession
from eternia.society import SocietyWorld
from v07_helpers import add_council

BUILDER, MINER, FARMER, RESEARCHER = 3, 1, 0, 4  # Rivermark residents
HOUSE = {'wood': 12., 'iron': 2., 'coins': 8.}


def short_of_iron(world, *, market_has_iron=False):
    """Toren has the wood for a house and lacks only iron, which he cannot mine.

    A minority council gives him no claim on town money. Unless the market keeps
    its iron, the stored iron becomes accessible ore instead: a transfer, so the
    only way to get it is to gather it, which he cannot.
    """
    add_council(world, members=[FARMER, BUILDER])
    builder, town = world.agents[BUILDER], world.settlements[0]
    town.wood -= 4
    builder.inventory['wood'] += 4
    if not market_has_iron:
        town.deposits['iron'] += town.iron
        town.iron = 0.
        world.reset_market_prices()
    return builder, town


def jobs_of(world, person):
    return [o for o in world.work_orders if o['employer'] == {'kind': 'person', 'id': person}]


def hire(world, actor, resource, quantity, wage, purpose=None):
    action = dict(actor=actor, type='hire', resource=resource, quantity=quantity, unit_wage=wage)
    if purpose is not None:
        action['purpose'] = purpose
    return world.submit_action(action)


class NextStepTests(unittest.TestCase):
    def step(self, goal, skills=('carpentry',), structures=None, knowledge=0, food=0.):
        return next_step(goal, skills=list(skills), structures=structures or {}, knowledge=knowledge, food=food,
                         recipes={'house': HOUSE})

    def test_each_goal_names_what_its_next_step_consumes(self):
        self.assertEqual(self.step({'kind': 'houses', 'target': 1}, skills=()),
                         dict(step='carpentry', materials={'wood': 1., 'iron': 1.}, coins=0.))
        self.assertEqual(self.step({'kind': 'houses', 'target': 1}),
                         dict(step='house', materials={'wood': 12., 'iron': 2.}, coins=8.))
        self.assertIsNone(self.step({'kind': 'houses', 'target': 1}, structures={'house': 1}))
        self.assertEqual(self.step({'kind': 'knowledge', 'target': 2})['step'], 'research')
        self.assertIsNone(self.step({'kind': 'knowledge', 'target': 2}, knowledge=2))
        self.assertEqual(self.step({'kind': 'food', 'target': 12}, food=5.),
                         dict(step='reserve', materials={'food': 12.}, coins=0.))
        self.assertIsNone(self.step({'kind': 'food', 'target': 12}, food=12.))
        for kind in ('wealth', 'profit', 'influence'):
            self.assertIsNone(self.step({'kind': kind, 'target': 60}))


class NeedsTests(unittest.TestCase):
    def test_a_builder_lacking_iron_he_cannot_mine_needs_it(self):
        world = SocietyWorld()
        short_of_iron(world)
        (need,) = needs(world.observe(BUILDER))
        price = world.market_prices[0]['iron']
        self.assertEqual((need['resource'], need['amount'], need['step']), ('iron', 2, 'house'))
        self.assertEqual((need['gather'], need['buy'], need['wage']), (False, False, offered_wage(price)))
        self.assertEqual(need['supply'], int(world.settlements[0].deposits['iron']))

    def test_needs_are_read_only_from_the_persons_own_view(self):
        world = SocietyWorld()
        short_of_iron(world)
        before = needs(world.observe(BUILDER))
        hidden = deepcopy(world)
        for other in hidden.agents:
            if other.id != BUILDER:
                other.inventory['coins'] += 500.  # private holdings
                other.inventory['iron'] += 50.
                other.trust = {k: -1. for k in other.trust}
        for town in hidden.settlements:
            town.ore = 0.  # buried reserves
        self.assertEqual(needs(hidden.observe(BUILDER)), before)

    def test_a_goal_without_materials_has_no_needs(self):
        world = SocietyWorld()
        self.assertEqual(world.agents[MINER].goal['kind'], 'wealth')
        self.assertEqual(needs(world.observe(MINER)), [])


class OpeningTests(unittest.TestCase):
    def test_a_need_the_market_meets_fairly_is_bought_not_put_out_as_work(self):
        world = SocietyWorld()
        short_of_iron(world, market_has_iron=True)
        self.assertIsNone(opening(world.observe(BUILDER)))
        plan = EconomicPolicy('balanced').propose(world.observe(BUILDER))
        self.assertEqual((plan['type'], plan['params']), ('trade', {'resource': 'iron', 'amount': 2, 'direction': 'buy'}))

    def test_a_need_nobody_sells_becomes_a_job_that_says_what_it_is_for(self):
        world = SocietyWorld()
        short_of_iron(world)
        policy = EconomicPolicy('balanced')
        plan = policy.propose(world.observe(BUILDER))
        wage = offered_wage(world.market_prices[0]['iron'])
        self.assertEqual((plan['type'], plan['params']),
                         ('hire', {'resource': 'iron', 'quantity': 2, 'unit_wage': wage,
                                   'purpose': {'kind': 'goal', 'step': 'house'}}))
        self.assertIn('for a house', policy.reason)

    def test_only_what_can_be_paid_for_is_asked_for(self):
        world = SocietyWorld()
        builder, town = short_of_iron(world)
        wage = offered_wage(world.market_prices[0]['iron'])
        keep = HOUSE['coins'] + 3 * world.market_prices[0]['food']  # the house's coins and three meals
        moved = builder.inventory['coins'] - (keep + wage + .01)
        builder.inventory['coins'] -= moved  # a transfer to the town, not a loss
        town.treasury += moved
        policy = EconomicPolicy('balanced')
        plan = policy.propose(world.observe(BUILDER))
        self.assertEqual((plan['type'], plan['params']['quantity']), ('hire', 1))
        self.assertIn('all I can pay for now of the 2 I lack', policy.reason)
        builder.inventory['coins'] -= wage  # now not even one wage can be spared
        town.treasury += wage
        self.assertIsNone(opening(world.observe(BUILDER)))

    def test_no_job_is_posted_where_nobody_could_do_the_work(self):
        world = SocietyWorld()
        _, town = short_of_iron(world)
        world.settlements[1].deposits['iron'] += town.deposits['iron']  # the ore lies elsewhere now
        town.deposits['iron'] = 0.
        (need,) = needs(world.observe(BUILDER))
        self.assertEqual((need['supply'], need['hire']), (0, 0))
        self.assertIsNone(opening(world.observe(BUILDER)))


class StatedPurposeTests(unittest.TestCase):
    def test_a_job_states_its_true_purpose_on_the_public_notice(self):
        world = SocietyWorld()
        short_of_iron(world)
        result = hire(world, BUILDER, 'iron', 2, 2, {'kind': 'goal', 'step': 'house'})
        self.assertTrue(result.success, result.message)
        self.assertIn('2 iron for a house', result.message)
        (order,) = jobs_of(world, BUILDER)
        self.assertEqual(order['purpose'], {'kind': 'goal', 'step': 'house'})
        world.advance_time()
        far = next(a.id for a in world.agents if a.home == 1)
        board = world.observe(far)['municipality']['job_board']
        self.assertEqual(next(o for o in board if o['id'] == order['id'])['purpose'], order['purpose'])

    def test_a_false_or_malformed_purpose_is_refused_and_nothing_is_escrowed(self):
        world = SocietyWorld()
        builder, _ = short_of_iron(world)
        coins = builder.inventory['coins']
        for purpose in ({'kind': 'goal', 'step': 'research'},   # not the goal he pursues
                        {'kind': 'goal', 'step': 'carpentry'},  # he already knows carpentry
                        {'kind': 'goal', 'step': 'heaven'}, {'kind': 'charity', 'step': 'house'}, 'a house',
                        {'kind': 'goal', 'step': ['house']}, {'kind': 'goal', 'step': 'house', 'extra': 1}):
            with self.subTest(purpose=purpose):
                result = hire(world, BUILDER, 'iron', 2, 2, purpose)
                self.assertEqual((result.success, result.code), (False, 'invalid_purpose'))
        result = hire(world, BUILDER, 'food', 2, .5, {'kind': 'goal', 'step': 'house'})  # a house needs no food
        self.assertEqual(result.code, 'invalid_purpose')
        self.assertEqual((builder.inventory['coins'], jobs_of(world, BUILDER)), (coins, []))

    def test_a_player_has_no_goal_to_state_but_may_hire_without_one(self):
        session = PlayableSession.start('Ilsa', 'Rivermark', seed=42)
        me = session.player_id
        self.assertEqual(hire(session.world, me, 'wood', 1, 1, {'kind': 'goal', 'step': 'house'}).code,
                         'invalid_purpose')
        self.assertTrue(hire(session.world, me, 'wood', 1, 1).success)
        self.assertNotIn('purpose', jobs_of(session.world, me)[0])


class OpportunityTests(unittest.TestCase):
    def test_the_opportunity_exists_whether_or_not_anyone_plays(self):
        alone = SocietyWorld(seed=42)
        short_of_iron(alone)
        alone.step()
        session = PlayableSession.start('Ilsa', 'Rivermark', seed=42)
        short_of_iron(session.world)
        session.act()
        terms = lambda world: [(o['resource'], o['quantity'], o['purpose'], o['status']) for o in jobs_of(world, BUILDER)]
        self.assertEqual(terms(alone), [('iron', 2, {'kind': 'goal', 'step': 'house'}, 'open')])
        self.assertEqual(terms(session.world), terms(alone))

    def test_a_neighbor_takes_the_job_and_the_house_gets_built(self):
        world = SocietyWorld(seed=42)
        builder, _ = short_of_iron(world)
        for _ in range(6):
            world.step()
        (order,) = jobs_of(world, BUILDER)
        record = opportunity_record(world)['jobs']
        self.assertEqual(order['status'], 'completed')
        job = next(j for j in record if j['order'] == order['id'])
        self.assertEqual((job['workers'], job['worker_roles'], job['delivered']), (['Edrin of Rivermark'], ['miner'], 2))
        self.assertIsNotNone(job['step_taken'])
        self.assertEqual(builder.structures.get('house'), 1)

    def test_a_newcomer_who_can_do_the_work_sees_it_takes_it_and_both_lives_change(self):
        session = PlayableSession.start('Ilsa', 'Rivermark', seed=42)
        builder, _ = short_of_iron(session.world)
        session.act()
        (order,) = jobs_of(session.world, BUILDER)
        seen = next(o for o in interface.state(session)['opportunities'] if o['kind'] == 'job' and o['id'] == order['id'])
        self.assertEqual((seen['who'], seen['purpose'], seen['needs']), ('Toren of Rivermark', 'for a house',
                                                                           ['the mining skill']))
        self.assertFalse(any(c['proposal']['type'] == 'work' and c['proposal']['params']['order'] == order['id']
                             for c in session.options()))
        session.person.skills.append('mining')  # set up: a newcomer who has learned to mine
        seen = next(o for o in interface.state(session)['opportunities'] if o['id'] == order['id'])
        self.assertEqual(seen['needs'], [])
        work = next(c for c in session.options() if c['proposal']['type'] == 'work'
                    and c['proposal']['params']['order'] == order['id'])
        coins, iron = session.person.inventory['coins'], builder.inventory['iron']
        outcome = session.act(work['proposal'])
        self.assertTrue(outcome['result']['success'], outcome['result'])
        wages = 2 * order['unit_wage']
        self.assertAlmostEqual(session.person.inventory['coins'], coins + wages)
        self.assertEqual(builder.inventory['iron'], iron + 2)
        self.assertEqual(order['status'], 'completed')
        session.act()
        self.assertEqual(builder.structures.get('house'), 1)  # the house the job was for
        self.assertEqual(session.journal()['worked'][-1]['employer'], 'Toren of Rivermark')


class EmergenceTests(unittest.TestCase):
    """In a society nobody plays, needs arise, become jobs, and others take them up."""

    def test_needs_become_jobs_that_others_take_up_in_a_society_nobody_plays(self):
        world = SocietyWorld(seed=42)
        world.run(25)
        record = opportunity_record(world)
        summary = record['summary']
        self.assertGreaterEqual(summary['posted'], 3)
        self.assertGreaterEqual(summary['worked'], 2)
        self.assertEqual(set(summary['worker_roles']), {'miner'})  # iron: only miners can supply it
        self.assertGreaterEqual(summary['step_taken'], 1)
        self.assertGreaterEqual(summary['expired'], 1)  # not every opportunity is taken
        for job in record['jobs']:
            self.assertNotIn(job['employer'], job['workers'])  # nobody is paid from their own escrow
            self.assertIn(job['step'], ('house', 'carpentry', 'research', 'reserve'))
        reasons = [d['rationale'] for d in world.decisions if d['proposal'].get('type') == 'hire'
                   and d['result']['success']]
        self.assertTrue(reasons and all('I cannot gather it myself here' in r for r in reasons))


if __name__ == '__main__':
    unittest.main()
