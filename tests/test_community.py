"""Behavioral checks for a finite, simultaneous, multi-generation community."""
import copy
import json
import math
import unittest

from eternia.community import CommunityWorld


class CommunityTests(unittest.TestCase):
    def setUp(self):
        self.world = CommunityWorld(seed=42, shock_year=0)

    def action(self, actor, kind, **params):
        return {'actor': actor.id, 'type': kind, 'location': actor.home,
                'params': params}

    def account_for_fixture(self):
        """Fixtures alter starting endowments, not the simulation's accounting."""
        self.world.initial_totals = self.world.resource_totals()

    def offer(self, seller, resource='iron', amount=2, unit_price=3,
              direction='sell'):
        result = self.world.resolve_actions([
            self.action(seller, 'offer', resource=resource, amount=amount,
                        unit_price=unit_price, direction=direction)
        ])[0]
        self.assertTrue(result['result']['success'], result)
        offer = next(o for o in self.world.offers if o['actor'] == seller.id)
        self.world.advance_time()
        return offer

    def test_five_people_begin_with_independent_goals(self):
        self.assertEqual([a.name for a in self.world.agents],
                         ['Edrin', 'Mara', 'Toren', 'Lyra', 'Aldric'])
        self.assertEqual(len({a.id for a in self.world.agents}), 5)
        self.assertEqual(len({a.role for a in self.world.agents}), 5)
        self.assertTrue(all(a.goal for a in self.world.agents))
        self.assertEqual(self.world.year, 0)
        self.assertEqual(self.world.tick, 0)

    def test_every_agent_observes_the_same_detached_tick(self):
        observations = self.world.observe_agents()
        self.assertEqual(set(observations), {a.id for a in self.world.agents})
        self.assertEqual({o['tick'] for o in observations.values()}, {0})
        self.assertEqual({o['year'] for o in observations.values()}, {0})
        actor = self.world.agents[0]
        observation = observations[actor.id]
        self.assertNotIn('aether', observation['settlement'])
        self.assertTrue(all('aether' not in n for n in observation['neighbors']))
        before = copy.deepcopy(actor.inventory)
        observation['actor']['inventory']['coins'] = 10**9
        observation['settlement']['deposits']['food'] = 10**9
        observation['peers'][0]['inventory']['food'] = 10**9
        self.assertEqual(actor.inventory, before)
        self.assertNotEqual(self.world.settlements[actor.home].deposits['food'], 10**9)
        self.assertTrue(all(a.inventory['food'] != 10**9 for a in self.world.agents))

    def test_a_policy_cannot_nominate_a_different_person(self):
        actor, other = self.world.agents[:2]

        class SpoofingPolicy:
            def propose(self, observation):
                return {'actor': other.id, 'type': 'wait', 'params': {}}

        self.world.policies[actor.id] = SpoofingPolicy()
        proposals = self.world.plan(self.world.observe_agents())
        proposal = next(p for p in proposals if p.get('actor') == actor.id)
        result = self.world.resolve_actions([proposal])[0]
        self.assertFalse(result['result']['success'], result)
        self.assertNotIn(other.id, self.world.last_action_year)

    def test_one_policy_exception_does_not_stop_other_people_planning(self):
        failing, healthy = self.world.agents[:2]

        class FailingPolicy:
            def propose(self, observation):
                raise RuntimeError('policy unavailable')

        class WaitingPolicy:
            def propose(self, observation):
                return {'actor': observation['actor']['id'], 'type': 'wait', 'params': {}}

        self.world.policies[failing.id] = FailingPolicy()
        self.world.policies[healthy.id] = WaitingPolicy()
        proposals = self.world.plan(self.world.observe_agents())
        results = self.world.resolve_actions([
            p for p in proposals if p.get('actor') in (failing.id, healthy.id)
        ])
        by_actor = {r['action']['actor']: r for r in results}
        self.assertFalse(by_actor[failing.id]['result']['success'])
        self.assertTrue(by_actor[healthy.id]['result']['success'])

    def test_peer_trade_transfers_existing_goods_and_coins(self):
        seller, buyer = self.world.agents[:2]
        offer = self.offer(seller)
        totals = self.world.resource_totals()
        inventories = copy.deepcopy((seller.inventory, buyer.inventory))
        results = self.world.resolve_actions([
            self.action(buyer, 'accept', offer_id=offer['id'], amount=2)
        ])
        self.assertTrue(results[0]['result']['success'], results)
        self.assertEqual(seller.inventory['iron'], inventories[0]['iron'] - 2)
        self.assertEqual(buyer.inventory['iron'], inventories[1]['iron'] + 2)
        self.assertEqual(seller.inventory['coins'], inventories[0]['coins'] + 6)
        self.assertEqual(buyer.inventory['coins'], inventories[1]['coins'] - 6)
        self.assertEqual(self.world.resource_totals(), totals)

    def test_two_buyers_cannot_purchase_the_same_goods(self):
        seller, buyer, other = self.world.agents[:3]
        offer = self.offer(seller)
        totals = self.world.resource_totals()
        results = self.world.resolve_actions([
            self.action(buyer, 'accept', offer_id=offer['id'], amount=2),
            self.action(other, 'accept', offer_id=offer['id'], amount=2),
        ])
        self.assertEqual(sum(r['result']['success'] for r in results), 1)
        self.assertEqual(self.world.resource_totals(), totals)
        self.assertTrue(all(v >= 0 for a in self.world.agents
                            for v in a.inventory.values()))

    def test_contested_gathering_cannot_overdraw_a_shared_deposit(self):
        first, second = self.world.agents[:2]
        home = self.world.settlements[first.home]
        home.deposits['food'] = 1
        self.account_for_fixture()
        before = self.world.resource_totals()
        results = self.world.resolve_actions([
            self.action(first, 'gather', resource='food', amount=1),
            self.action(second, 'gather', resource='food', amount=1),
        ])
        self.assertEqual(sum(r['result']['success'] for r in results), 1)
        self.assertEqual(home.deposits['food'], 0)
        self.assertEqual(self.world.resource_totals(), before)

    def test_one_actor_cannot_complete_two_actions_in_one_tick(self):
        actor = self.world.agents[0]
        before = copy.deepcopy(actor.inventory)
        results = self.world.resolve_actions([
            self.action(actor, 'gather', resource='food', amount=1),
            self.action(actor, 'gather', resource='iron', amount=1),
        ])
        # Reject both ambiguous intents so their submission order cannot select
        # an action on the person's behalf.
        self.assertTrue(all(not r['result']['success'] for r in results))
        self.assertTrue(all(r['result']['code'] == 'duplicate_action' for r in results))
        self.assertEqual(actor.inventory, before)

    def test_malformed_proposals_are_rejected_and_remain_exportable(self):
        actor = self.world.agents[0]
        inventories = copy.deepcopy([a.inventory for a in self.world.agents])
        totals = self.world.resource_totals()
        results = self.world.resolve_actions([
            None, [], {'actor': True, 'type': 'wait'},
            self.action(actor, 'gather', resource='iron', amount=math.nan),
        ])
        self.assertTrue(all(not r['result']['success'] for r in results))
        self.assertEqual([a.inventory for a in self.world.agents], inventories)
        self.assertEqual(self.world.resource_totals(), totals)
        json.dumps(self.world.export(), allow_nan=False)

    def test_posted_offer_reserves_materials_against_construction(self):
        seller = self.world.agents[0]
        seller.inventory.update(wood=12, iron=2, coins=30)
        seller.skills.append('carpentry')
        self.account_for_fixture()
        self.offer(seller, resource='wood', amount=12, unit_price=2)
        self.assertEqual(self.world.available_inventory(seller)['wood'], 0)
        before = copy.deepcopy(seller.inventory)
        results = self.world.resolve_actions([self.action(seller, 'build', structure='house')])
        self.assertFalse(results[0]['result']['success'], results)
        self.assertEqual(seller.inventory, before)
        self.assertEqual(seller.structures.get('house', 0), 0)

    def test_incoming_trade_goods_cannot_fund_a_plan_from_the_same_tick(self):
        seller, buyer = self.world.agents[:2]
        seller.inventory['wood'] = 12
        buyer.inventory.update(wood=0, iron=2, coins=50)
        buyer.skills.append('carpentry')
        self.account_for_fixture()
        offer = self.offer(buyer, resource='wood', amount=12, unit_price=2,
                           direction='buy')
        results = self.world.resolve_actions([
            self.action(seller, 'accept', offer_id=offer['id'], amount=12),
            self.action(buyer, 'build', structure='house'),
        ])
        by_actor = {r['action']['actor']: r for r in results}
        self.assertTrue(by_actor[seller.id]['result']['success'], results)
        self.assertFalse(by_actor[buyer.id]['result']['success'], results)
        self.assertEqual(buyer.inventory['wood'], 12)
        self.assertEqual(buyer.structures.get('house', 0), 0)

    def test_separate_resolver_calls_cannot_reuse_same_tick_trade_receipts(self):
        seller, buyer = self.world.agents[:2]
        seller.inventory['wood'] = 12
        buyer.inventory.update(wood=0, iron=2, coins=50)
        buyer.skills.append('carpentry')
        self.account_for_fixture()
        offer = self.offer(buyer, resource='wood', amount=12, unit_price=2,
                           direction='buy')
        receipt = self.world.resolve_actions([
            self.action(seller, 'accept', offer_id=offer['id'], amount=12)
        ])[0]
        self.assertTrue(receipt['result']['success'], receipt)
        self.assertEqual(buyer.inventory['wood'], 12)
        before = dict(buyer.inventory)
        result = self.world.resolve_actions([
            self.action(buyer, 'build', structure='house')
        ])[0]
        self.assertFalse(result['result']['success'], result)
        self.assertEqual(buyer.inventory, before)
        self.world.advance_time()
        result = self.world.resolve_actions([
            self.action(buyer, 'build', structure='house')
        ])[0]
        self.assertTrue(result['result']['success'], result)

    def test_municipal_resale_cannot_reuse_goods_received_in_the_same_tick(self):
        seller, first, second = self.world.agents[:3]
        town = self.world.settlements[seller.home]
        town.iron = 2
        first.inventory['coins'] = second.inventory['coins'] = 30
        self.account_for_fixture()
        totals = self.world.resource_totals()
        self.world.rng.seed(5)  # Resolves the sale before the two purchases.
        results = self.world.resolve_actions([
            self.action(seller, 'trade', resource='iron', amount=2, direction='sell'),
            self.action(first, 'trade', resource='iron', amount=2, direction='buy'),
            self.action(second, 'trade', resource='iron', amount=2, direction='buy'),
        ])
        sales = [r for r in results if r['action']['params']['direction'] == 'sell']
        purchases = [r for r in results if r['action']['params']['direction'] == 'buy']
        self.assertTrue(sales[0]['result']['success'], results)
        self.assertEqual(sum(r['result']['success'] for r in purchases), 1)
        self.assertEqual(town.iron, 2)
        self.assertEqual(self.world.resource_totals(), totals)

    def test_new_offers_are_not_available_during_their_creation_tick(self):
        seller, buyer = self.world.agents[:2]
        result = self.world.resolve_actions([
            self.action(seller, 'offer', resource='iron', amount=2,
                        unit_price=3, direction='sell')
        ])[0]
        self.assertTrue(result['result']['success'], result)
        offer = self.world.offers[0]
        before = copy.deepcopy(buyer.inventory)
        result = self.world.resolve_actions([
            self.action(buyer, 'accept', offer_id=offer['id'], amount=2)
        ])[0]
        self.assertFalse(result['result']['success'], result)
        self.assertEqual(buyer.inventory, before)

    def test_learning_does_not_enable_construction_in_the_same_tick(self):
        pupil = self.world.agents[1]
        teacher = self.world.agents[2]
        self.assertIn('carpentry', teacher.skills)
        pupil.skills = [s for s in pupil.skills if s != 'carpentry']
        pupil.inventory.update(wood=12, iron=2, coins=30)
        self.account_for_fixture()
        results = self.world.resolve_actions([
            self.action(teacher, 'teach', target=pupil.id, topic='carpentry'),
            self.action(pupil, 'build', structure='house'),
        ])
        by_actor = {r['action']['actor']: r for r in results}
        self.assertTrue(by_actor[teacher.id]['result']['success'], results)
        self.assertFalse(by_actor[pupil.id]['result']['success'], results)
        self.assertIn('carpentry', pupil.skills)
        self.assertEqual(pupil.structures.get('house', 0), 0)
        self.world.advance_time()
        result = self.world.resolve_actions([
            self.action(pupil, 'build', structure='house')
        ])[0]
        self.assertTrue(result['result']['success'], result)

    def test_separate_resolver_calls_cannot_reuse_a_same_tick_lesson(self):
        pupil = self.world.agents[1]
        teacher = self.world.agents[2]
        pupil.skills = [s for s in pupil.skills if s != 'carpentry']
        pupil.inventory.update(wood=12, iron=2, coins=30)
        self.account_for_fixture()
        lesson = self.world.resolve_actions([
            self.action(teacher, 'teach', target=pupil.id, topic='carpentry')
        ])[0]
        self.assertTrue(lesson['result']['success'], lesson)
        self.assertIn('carpentry', pupil.skills)
        result = self.world.resolve_actions([
            self.action(pupil, 'build', structure='house')
        ])[0]
        self.assertFalse(result['result']['success'], result)
        self.assertEqual(pupil.structures.get('house', 0), 0)
        self.world.advance_time()
        result = self.world.resolve_actions([
            self.action(pupil, 'build', structure='house')
        ])[0]
        self.assertTrue(result['result']['success'], result)

    def test_a_lesson_cannot_be_relayed_with_new_information_in_the_same_tick(self):
        self.world = CommunityWorld(seed=0, shock_year=0)
        teacher, intermediary, pupil = self.world.agents[:3]
        teacher.knowledge, intermediary.knowledge, pupil.knowledge = 2, 1, 0
        results = self.world.resolve_actions([
            self.action(teacher, 'teach', target=intermediary.id, topic='aether'),
            self.action(intermediary, 'teach', target=pupil.id, topic='aether'),
        ])
        self.assertTrue(all(r['result']['success'] for r in results), results)
        self.assertEqual(intermediary.knowledge, 2)
        self.assertEqual(pupil.knowledge, 1)

    def test_observing_carpentry_cannot_reveal_unrelated_mineral_knowledge(self):
        actor = self.world.agents[0]
        actor.knowledge = 2
        actor.inventory.update(wood=1, iron=1)
        self.account_for_fixture()
        results = self.world.resolve_actions([
            self.action(actor, 'research', topic='carpentry')
        ])
        self.assertTrue(results[0]['result']['success'], results)
        self.world.rng.seed(2)  # Includes witnesses who learn from this demonstration.
        self.world.update_relationships(results)
        self.assertTrue(all(a.knowledge == 0 for a in self.world.agents if a.id != actor.id))

    def test_observation_uses_demonstrated_knowledge_before_a_later_lesson(self):
        teacher = self.world.agents[0]
        researcher = self.world.agents[3]
        teacher.knowledge = 2
        for actor in self.world.agents[1:]:
            actor.knowledge = 1
        researcher.inventory.update(wood=2, iron=2)
        self.world.settlements[researcher.home].aether = 0
        self.account_for_fixture()
        # Research resolves before teaching, but both plans were independently
        # feasible. The inconclusive result demonstrates knowledge level one.
        self.world.rng.seed(1)
        results = self.world.resolve_actions([
            self.action(teacher, 'teach', target=researcher.id, topic='aether'),
            self.action(researcher, 'research', topic='aether'),
        ])
        self.assertTrue(all(r['result']['success'] for r in results), results)
        self.assertEqual(researcher.knowledge, 2)
        self.world.rng.seed(2)
        self.world.update_relationships(results)
        self.assertTrue(all(a.knowledge == 1 for a in self.world.agents
                            if a.id not in (teacher.id, researcher.id)))

    def test_a_resource_change_invalidates_a_previously_feasible_plan(self):
        actor = self.world.agents[0]
        home = self.world.settlements[actor.home]
        observation = self.world.observe_agents()[actor.id]
        self.assertGreater(observation['settlement']['deposits']['iron'], 0)
        proposal = self.action(actor, 'gather', resource='iron', amount=1)
        home.iron += home.deposits['iron']
        home.deposits['iron'] = 0
        before = copy.deepcopy(actor.inventory)
        totals = self.world.resource_totals()
        result = self.world.resolve_actions([proposal])[0]
        self.assertFalse(result['result']['success'], result)
        self.assertEqual(actor.inventory, before)
        self.assertEqual(self.world.resource_totals(), totals)

    def test_migration_invalidates_a_counterpartys_old_trade_plan(self):
        seller, buyer = self.world.agents[:2]
        offer = self.offer(seller)
        proposal = self.action(buyer, 'accept', offer_id=offer['id'], amount=2)
        population = sum(s.population for s in self.world.settlements)
        before = copy.deepcopy(buyer.inventory)
        result = self.world.resolve_actions([
            self.action(seller, 'migrate', destination=0)
        ])[0]
        self.assertTrue(result['result']['success'], result)
        self.assertEqual(sum(s.population for s in self.world.settlements), population)
        result = self.world.resolve_actions([proposal])[0]
        self.assertFalse(result['result']['success'], result)
        self.assertEqual(buyer.inventory, before)

    def test_death_transfers_an_estate_without_creating_resources(self):
        parent = self.world.agents[0]
        self.offer(parent)
        totals = self.world.resource_totals()
        inventory = dict(parent.inventory)
        structures = dict(parent.structures)
        successor = self.world.remove_agent(parent.id, cause='test death')
        self.assertNotEqual(successor.id, parent.id)
        self.assertEqual(successor.parent_id, parent.id)
        self.assertEqual(successor.generation, parent.generation + 1)
        self.assertEqual(successor.lineage, parent.lineage)
        self.assertEqual(successor.inventory, inventory)
        self.assertEqual(successor.structures, structures)
        self.assertEqual(self.world.resource_totals(), totals)
        self.assertFalse(any(o['actor'] == parent.id for o in self.world.offers))
        result = self.world.resolve_actions([
            {'actor': parent.id, 'type': 'wait', 'params': {}}
        ])[0]
        self.assertFalse(result['result']['success'], result)

    def test_trade_with_a_dead_counterparty_is_rejected_without_spending(self):
        seller, buyer = self.world.agents[:2]
        offer = self.offer(seller)
        proposal = self.action(buyer, 'accept', offer_id=offer['id'], amount=2)
        self.world.remove_agent(seller.id, cause='test death')
        before = copy.deepcopy(buyer.inventory)
        result = self.world.resolve_actions([proposal])[0]
        self.assertFalse(result['result']['success'], result)
        self.assertEqual(buyer.inventory, before)

    def test_a_successful_exchange_changes_relationships(self):
        seller, buyer = self.world.agents[:2]
        offer = self.offer(seller)
        previous = (seller.trust.get(buyer.id, 0), buyer.trust.get(seller.id, 0))
        results = self.world.resolve_actions([
            self.action(buyer, 'accept', offer_id=offer['id'], amount=2)
        ])
        self.world.update_relationships(results)
        self.assertGreater(seller.trust.get(buyer.id, 0), previous[0])
        self.assertGreater(buyer.trust.get(seller.id, 0), previous[1])

    def test_submit_action_uses_the_community_audit_and_accounting(self):
        actor = self.world.agents[0]
        totals = self.world.resource_totals()
        result = self.world.submit_action(
            self.action(actor, 'gather', resource='food', amount=1))
        self.assertTrue(result.success, result)
        self.assertEqual(self.world.resource_totals(), totals)
        self.assertEqual(self.world.action_log[-1]['tick'], self.world.tick)
        self.assertEqual(self.world.action_log[-1]['action']['actor'], actor.id)
        self.world._assert_invariants()

    def test_submit_action_accounts_for_consumed_resources(self):
        actor = self.world.agents[0]
        actor.hunger = 50
        before = self.world.resource_totals()
        result = self.world.submit_action(self.action(actor, 'eat'))
        self.assertTrue(result.success, result)
        self.assertEqual(self.world.resource_totals()['food'], before['food'] - 1)
        self.assertEqual(self.world.ledger['consumed']['food'], 1)
        self.world._assert_invariants()

    def test_direct_engine_execution_cannot_bypass_community_accounting(self):
        actor = self.world.agents[0]
        inventory = dict(actor.inventory)
        totals = self.world.resource_totals()
        with self.assertRaises(RuntimeError):
            self.world.action_engine.execute(
                self.action(actor, 'gather', resource='food', amount=1))
        self.assertEqual(actor.inventory, inventory)
        self.assertEqual(self.world.resource_totals(), totals)
        self.assertEqual(self.world.action_log, [])

    def test_hundred_year_replay_and_resource_accounting(self):
        first = CommunityWorld(seed=21).run(years=100)
        second = CommunityWorld(seed=21).run(years=100)
        exported = first.export()
        self.assertEqual(exported, second.export())
        self.assertEqual(exported['schema'], 'eternia.v0.3')
        self.assertEqual(exported['mode'], 'community')
        self.assertEqual(first.year, 100)
        self.assertEqual(first.tick, 400)
        self.assertEqual(exported['snapshots'][-1]['year'], 100)
        self.assertTrue(any(a.generation > 0 for a in first.agents))
        totals = first.resource_totals()
        for resource, total in totals.items():
            expected = (first.initial_totals[resource]
                        + first.ledger['produced'][resource]
                        - first.ledger['consumed'][resource])
            self.assertAlmostEqual(total, expected, places=6, msg=resource)
        self.assertTrue(all(len(a.memory) <= 64 for a in first.agents))
        self.assertTrue(any(a.memory for a in first.agents))
        json.dumps(exported, allow_nan=False)


if __name__ == '__main__':
    unittest.main()
