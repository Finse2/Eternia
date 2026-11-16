import copy
import math
import unittest
from unittest.mock import patch

from eternia.society import SocietyWorld
from eternia.economic_policy import EconomicPolicy
from eternia.evaluation import goal_outcome
from v07_helpers import add_council, proposal, funded_order, chartered_route


class EconomicAgencyTests(unittest.TestCase):
    def test_local_majority_is_required_for_municipal_spending(self):
        world = SocietyWorld()
        council = add_council(world, members=[0, 1, 2])
        before = world.resource_totals()
        result = world.submit_action(dict(actor=0, type='propose', params=dict(institution=council.id,
                                         kind='work_order', params=dict(resource='iron', quantity=8, unit_wage=2))))
        self.assertFalse(result.success)
        self.assertEqual(result.code, 'insufficient_authority')
        self.assertEqual(before, world.resource_totals())
        self.assertFalse(world.work_orders)

    def test_guild_cannot_spend_town_money_even_with_all_local_members(self):
        world = SocietyWorld()
        guild = add_council(world, purpose='guild')
        result = world.submit_action(dict(actor=0, type='propose', params=dict(institution=guild.id,
                                         kind='work_order', params=dict(resource='iron', quantity=8, unit_wage=2))))
        self.assertFalse(result.success)
        self.assertEqual(result.code, 'insufficient_authority')

    def test_real_votes_fund_escrow_only_on_a_later_tick(self):
        world = SocietyWorld()
        council = add_council(world)
        before = world.resource_totals()
        start_coins = world.settlements[0].treasury
        p = world.submit_action(dict(actor=0, type='propose', params=dict(institution=council.id,
                                    kind='work_order', params=dict(resource='iron', quantity=4, unit_wage=2))))
        self.assertTrue(p.success, p.message)
        identity = p.effects['proposal_id']
        world.advance_time()
        for identity_actor in (1, 2, 3):
            self.assertTrue(world.submit_action(dict(actor=identity_actor, type='vote',
                                                    institution=council.id, proposal=identity, approve=True)).success)
        self.assertFalse(world.submit_action(dict(actor=0, type='enact',
                                                  institution=council.id, proposal=identity)).success)
        world.advance_time()
        result = world.submit_action(dict(actor=0, type='enact', institution=council.id, proposal=identity))
        self.assertTrue(result.success, result.message)
        self.assertEqual(world.settlements[0].treasury, start_coins - 8)
        self.assertEqual(world.work_orders[0]['escrow'], 8)
        self.assertEqual(before, world.resource_totals())

    def test_compensation_and_output_transfer_are_atomic_and_traceable(self):
        world = SocietyWorld()
        _, order = funded_order(world, quantity=4)
        worker = world.agents[1]
        town = world.settlements[0]
        before, coins, iron = world.resource_totals(), worker.inventory['coins'], town.iron
        result = world.submit_action(dict(actor=worker.id, type='work', order=order['id'], amount=4))
        self.assertTrue(result.success, result.message)
        self.assertEqual(worker.inventory['coins'], coins + 8)
        self.assertEqual(town.iron, iron + 4)
        self.assertEqual(order['escrow'], 0)
        self.assertEqual(order['status'], 'completed')
        self.assertEqual(before, world.resource_totals())
        self.assertEqual(world.work_history[-1]['coins'], 8)
        self.assertEqual(world.work_history[-1]['order'], order['id'])
        self.assertEqual(world.earnings[worker.id], 8)

    def test_unavailable_work_does_not_pay_or_consume_material(self):
        world = SocietyWorld()
        _, order = funded_order(world)
        world.settlements[0].deposits['iron'] = 0
        before = world.resource_totals()
        coins = world.agents[1].inventory['coins']
        rng = world.rng.getstate()
        result = world.submit_action(dict(actor=1, type='work', order=order['id'], amount=1))
        self.assertFalse(result.success)
        self.assertEqual(world.agents[1].inventory['coins'], coins)
        self.assertEqual(world.resource_totals(), before)
        self.assertEqual(world.rng.getstate(), rng)  # one-proposal shuffle makes no draw

    def test_competing_workers_cannot_claim_the_same_escrow(self):
        world = SocietyWorld()
        _, order = funded_order(world, quantity=2)
        world.agents[2].skills.append('mining')
        before = world.resource_totals()
        records = world.resolve_actions([dict(actor=i, type='work', order=order['id'], amount=2)
                                         for i in (1, 2)])
        self.assertEqual(sum(r['result']['success'] for r in records), 1)
        self.assertEqual(world.economic_metrics['wages_paid'], 4)
        self.assertEqual(world.resource_totals(), before)

    def test_newly_funded_order_cannot_be_worked_in_its_creation_tick(self):
        world = SocietyWorld()
        council, order = funded_order(world)
        order['created'] = world.tick
        result = world.submit_action(dict(actor=1, type='work', order=order['id'], amount=1))
        self.assertFalse(result.success)
        self.assertEqual(result.code, 'order_unavailable')

    def test_unused_escrow_returns_without_minting_money(self):
        world = SocietyWorld()
        _, order = funded_order(world)
        before, town_coins = world.resource_totals(), world.settlements[0].treasury
        world.tick = order['expires']
        world.year = world.tick // world.ticks_per_year
        world._maintain_work_orders()
        self.assertEqual(order['status'], 'expired')
        self.assertEqual(order['escrow'], 0)
        self.assertEqual(world.settlements[0].treasury, town_coins + 16)
        self.assertEqual(before, world.resource_totals())

    def test_work_knowledge_energy_and_permissions_still_apply(self):
        world = SocietyWorld()
        _, order = funded_order(world)
        worker = world.agents[1]
        for field, value in [('energy', 0), ('skills', [] )]:
            world.advance_time()
            old = getattr(worker, field)
            setattr(worker, field, value)
            self.assertFalse(world.submit_action(dict(actor=1, type='work', order=order['id'], amount=1)).success)
            setattr(worker, field, old)
        world.settlements[0].permissions['work'] = False
        self.assertFalse(world.submit_action(dict(actor=1, type='work', order=order['id'], amount=1)).success)

    def test_standing_retail_charter_is_bounded(self):
        world = SocietyWorld()
        result = world.submit_action(dict(actor=0, type='trade', resource='food', amount=9, direction='buy'))
        self.assertFalse(result.success)
        self.assertEqual(result.code, 'retail_limit')

    def test_rule_validation_is_pure(self):
        world = SocietyWorld()
        _, order = funded_order(world)
        before = copy.deepcopy(world.export())
        rng = world.rng.getstate()
        result = world.action_engine.validate(dict(actor=1, type='work', order=order['id'], amount=1))
        self.assertTrue(result.success)
        self.assertEqual(before, world.export())
        self.assertEqual(rng, world.rng.getstate())

    def test_private_production_has_an_explicit_personal_purpose(self):
        world = SocietyWorld()
        result = world.submit_action(dict(actor=1, type='gather', resource='iron', amount=1))
        self.assertTrue(result.success)
        self.assertEqual(result.effects['purpose'], {'kind': 'personal_inventory'})
        self.assertEqual(world.work_history[-1]['mode'], 'personal')

    def test_nonexistent_voluntary_project_is_rejected(self):
        world = SocietyWorld()
        council = add_council(world)
        result = world.submit_action(dict(actor=1, type='gather', resource='iron', amount=1,
                                         purpose=dict(kind='voluntary_project', institution=council.id, proposal=999)))
        self.assertFalse(result.success)
        self.assertEqual(world.economic_metrics['volunteer_actions'], 0)

    def test_policy_styles_make_a_real_paid_vs_collective_tradeoff(self):
        outcomes = {}
        for style in ('personal', 'collective'):
            world = SocietyWorld(policy_style=style)
            council, order = funded_order(world, quantity=8)
            project = proposal(world, council, 'repair_route', {'link': 0}, approved=False)
            project['votes'][1] = {'approve': True, 'tick': world.tick - 1}
            world.links[0]['condition'] = .4
            actor = world.agents[1]
            before_coins = actor.inventory['coins']
            world.policies[actor.id] = EconomicPolicy(style)
            plans = world.plan({actor.id: world.observe(actor.id)})
            result = world.resolve_actions(plans)[0]
            self.assertTrue(result['result']['success'], result)
            outcomes[style] = (result['action']['type'], actor.inventory['coins'] - before_coins,
                               council.inventory['iron'], world.economic_metrics['voluntary_with_paid_option'])
        self.assertEqual(outcomes['personal'][:2], ('work', 8))  # local accessible iron caps four units
        self.assertEqual(outcomes['collective'][0], 'contribute')
        self.assertEqual(outcomes['collective'][1], 0)
        self.assertGreater(outcomes['collective'][2], 0)
        self.assertEqual(outcomes['collective'][3], 1)

    def test_public_maintenance_does_not_acquire_a_private_road(self):
        world = SocietyWorld()
        council = add_council(world)
        for resource, amount in [('wood', 6), ('iron', 1)]:
            setattr(world.settlements[0], resource, getattr(world.settlements[0], resource) - amount)
            council.inventory[resource] += amount
        world.settlements[0].treasury -= 3
        council.treasury += 3
        world.tick = 2
        world.links[0]['condition'] = .4
        decision = proposal(world, council, 'repair_route', {'link': 0})
        result = world.submit_action(dict(actor=0, type='enact', institution=council.id, proposal=decision['id']))
        self.assertTrue(result.success, result.message)
        self.assertIsNone(world.links[0]['owner'])

    def test_public_road_closure_requires_both_endpoint_majorities(self):
        world = SocietyWorld()
        left, right = add_council(world, 0), add_council(world, 2)
        world.tick = 2
        first = proposal(world, left, 'route_access', dict(link=0, closed=True))
        result = world.submit_action(dict(actor=0, type='enact', institution=left.id, proposal=first['id']))
        self.assertFalse(result.success)
        self.assertFalse(world.links[0]['closed'])
        world.advance_time()
        second = proposal(world, right, 'route_access', dict(link=0, closed=True))
        result = world.submit_action(dict(actor=0, type='enact', institution=left.id, proposal=first['id']))
        self.assertTrue(result.success, result.message)
        self.assertTrue(world.links[0]['closed'])
        self.assertEqual(second['status'], 'enacted')

    def test_accounting_failure_rolls_back_the_authoritative_batch(self):
        world = SocietyWorld()
        _, order = funded_order(world, quantity=2)
        before, rng = world.export(), world.rng.getstate()
        original = SocietyWorld._account_action
        def fail_after_account(instance, *args):
            original(instance, *args)
            raise RuntimeError('injected after authoritative mutation')
        with patch.object(SocietyWorld, '_account_action', fail_after_account):
            with self.assertRaises(RuntimeError):
                world.submit_action(dict(actor=1, type='work', order=order['id'], amount=1))
        self.assertEqual(world.export(), before)
        self.assertEqual(world.rng.getstate(), rng)
        self.assertIs(world.action_engine.world, world)

    def test_default_society_generates_paid_work_without_injected_proposals(self):
        world = SocietyWorld().run(3)
        self.assertGreater(world.economic_metrics['wages_paid'], 0)
        self.assertTrue(any(r['mode'] == 'paid' for r in world.work_history))
        self.assertAlmostEqual(sum(world.earnings.values()), world.economic_metrics['wages_paid'])
        world._assert_invariants()

    def test_paid_mining_records_limited_personal_evidence(self):
        world = SocietyWorld()
        _, order = funded_order(world)
        result = world.submit_action(dict(actor=1, type='work', order=order['id'], amount=1))
        self.assertTrue(result.success, result.message)
        observation = world.observe(1)
        evidence = observation['physical']['geology'][-1]
        self.assertIsNone(evidence['reserve_estimate'])
        self.assertEqual(evidence['settlement'], 0)
        self.assertEqual(evidence['amount'], 1)
        before = copy.deepcopy(observation)
        world.mineral_reserves[0] += 1000
        self.assertEqual(world.observe(1), before)

    def test_both_trade_sponsors_need_current_municipal_authority(self):
        world = SocietyWorld()
        _, importer, route = chartered_route(world)
        importer.purpose = 'guild'
        before = world.resource_totals()
        result = world.submit_action(dict(actor=0, type='dispatch_caravan', route=route['id'], amount=4))
        self.assertFalse(result.success)
        self.assertEqual(result.code, 'insufficient_authority')
        self.assertEqual(before, world.resource_totals())
        self.assertFalse(world.journeys)

