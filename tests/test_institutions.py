"""Institutional authority, common property, and economic coupling regressions."""
import copy
import json
import math
import unittest

from eternia.institutional_world import InstitutionalWorld


class InstitutionTests(unittest.TestCase):
    def setUp(self):
        self.world = InstitutionalWorld(seed=42, shock_year=0)

    def action(self, actor, action_type, **params):
        return {'actor': actor.id, 'type': action_type, 'location': actor.home, 'params': params}

    def execute(self, actor, action_type, **params):
        return self.world.resolve_actions([self.action(actor, action_type, **params)])[0]

    def assert_success(self, result):
        self.assertTrue(result['result']['success'], result)

    def fixture_totals(self):
        # Account for intentionally supplied starting endowments while keeping
        # earlier action costs and annual flows in the conservation equation.
        totals = self.world.resource_totals()
        self.world.initial_totals = {
            resource: total - self.world.ledger['produced'][resource]
            + self.world.ledger['consumed'][resource]
            for resource, total in totals.items()
        }

    def group(self, count=3):
        founder = self.world.agents[0]
        self.assert_success(self.execute(founder, 'form_institution', name='Highfen Cooperative'))
        institution = self.world.institutions[-1]
        self.world.advance_time()
        if count > 1:
            results = self.world.resolve_actions([
                self.action(a, 'join_institution', institution=institution.id)
                for a in self.world.agents[1:count]
            ])
            self.assertTrue(all(r['result']['success'] for r in results), results)
            self.world.advance_time()
        return institution

    def funded(self, institution):
        institution.inventory.update(wood=10., iron=2.)
        institution.treasury = 6.
        self.fixture_totals()

    def proposal(self, institution, kind='granary', params=None):
        result = self.execute(self.world.agents[0], 'propose', institution=institution.id,
                              kind=kind, params={} if params is None else params)
        self.assert_success(result)
        return institution.decisions[-1]

    def approved(self, institution, kind='granary', params=None):
        proposal = self.proposal(institution, kind, params)
        self.world.advance_time()
        self.assert_success(self.execute(self.world.agents[1], 'vote', institution=institution.id,
                                         proposal=proposal['id'], approve=True))
        self.world.advance_time()
        return proposal

    def test_formation_has_a_declared_cost_and_initial_personal_authority(self):
        founder = self.world.agents[0]
        before = self.world.resource_totals()
        self.assert_success(self.execute(founder, 'form_institution', name='The Cooperative'))
        institution = self.world.institutions[-1]
        self.assertEqual(institution.members, {founder.id})
        self.assertEqual(institution.settlement_id, founder.home)
        self.assertAlmostEqual(self.world.resource_totals()['coins'], before['coins'] - 2)
        self.assertAlmostEqual(self.world.ledger['consumed']['coins'], 2)
        self.world._assert_invariants()

    def test_contributions_move_existing_assets_into_shared_holdings(self):
        institution = self.group()
        contributor = self.world.agents[0]
        before = self.world.resource_totals()
        old_personal = contributor.inventory['iron']
        self.assert_success(self.execute(contributor, 'contribute', institution=institution.id,
                                         resource='iron', amount=2))
        self.assertEqual(contributor.inventory['iron'], old_personal - 2)
        self.assertEqual(institution.inventory['iron'], 2)
        self.assertEqual(self.world.resource_totals(), before)
        self.world._assert_invariants()

    def test_an_outsider_cannot_spend_or_vote(self):
        institution = self.group(count=2)
        self.funded(institution)
        proposal = self.proposal(institution)
        self.world.advance_time()
        outsider = self.world.agents[2]
        before = self.world.resource_totals()
        state = copy.deepcopy(institution.public_state())
        for kind, params in (
            ('vote', {'proposal': proposal['id'], 'approve': True}),
            ('enact', {'proposal': proposal['id']}),
            ('contribute', {'resource': 'wood', 'amount': 1}),
        ):
            with self.subTest(action=kind):
                result = self.execute(outsider, kind, institution=institution.id, **params)
                self.assertFalse(result['result']['success'], result)
        self.assertEqual(institution.public_state(), state)
        self.assertEqual(self.world.resource_totals(), before)

    def test_new_members_do_not_enter_an_existing_electorate(self):
        institution = self.group(count=2)
        self.funded(institution)
        founder, original, newcomer = self.world.agents[:3]
        results = self.world.resolve_actions([
            self.action(founder, 'propose', institution=institution.id, kind='granary', params={}),
            self.action(newcomer, 'join_institution', institution=institution.id),
        ])
        self.assertTrue(all(r['result']['success'] for r in results), results)
        proposal = institution.decisions[-1]
        self.world.advance_time()
        result = self.execute(newcomer, 'vote', institution=institution.id,
                              proposal=proposal['id'], approve=True)
        self.assertFalse(result['result']['success'], result)
        self.assertNotIn(newcomer.id, proposal['votes'])
        self.assert_success(self.execute(original, 'vote', institution=institution.id,
                                         proposal=proposal['id'], approve=True))

    def test_a_new_vote_cannot_authorize_enactment_in_the_same_tick(self):
        institution = self.group()
        self.funded(institution)
        proposal = self.proposal(institution)
        self.world.advance_time()
        voter, executor = self.world.agents[1:3]
        results = self.world.resolve_actions([
            self.action(voter, 'vote', institution=institution.id, proposal=proposal['id'], approve=True),
            self.action(executor, 'enact', institution=institution.id, proposal=proposal['id']),
        ])
        by_type = {r['action']['type']: r for r in results}
        self.assert_success(by_type['vote'])
        self.assertFalse(by_type['enact']['result']['success'], results)
        self.assertEqual(self.world.settlements[institution.settlement_id].buildings.get('granary', 0), 0)
        # Even a second resolver invocation must use the same tick-start votes.
        result = self.execute(executor, 'enact', institution=institution.id, proposal=proposal['id'])
        self.assertFalse(result['result']['success'], result)
        self.world.advance_time()
        self.assert_success(self.execute(executor, 'enact', institution=institution.id, proposal=proposal['id']))

    def test_a_single_founder_cannot_authorize_their_own_project(self):
        institution = self.group(count=1)
        self.funded(institution)
        proposal = self.proposal(institution)
        self.world.advance_time()
        result = self.execute(self.world.agents[0], 'enact', institution=institution.id,
                              proposal=proposal['id'])
        self.assertFalse(result['result']['success'], result)
        self.assertEqual(institution.treasury, 6)

    def test_a_majority_can_reject_a_collective_decision(self):
        institution = self.group()
        proposal = self.proposal(institution, 'communal_labor', {'value': .2})
        self.world.advance_time()
        results = self.world.resolve_actions([
            self.action(a, 'vote', institution=institution.id, proposal=proposal['id'], approve=False)
            for a in self.world.agents[1:3]
        ])
        self.assertTrue(all(r['result']['success'] for r in results), results)
        self.world.advance_time()
        result = self.execute(self.world.agents[0], 'enact', institution=institution.id,
                              proposal=proposal['id'])
        self.assertFalse(result['result']['success'], result)
        self.assertEqual(institution.rules['communal_labor'], 0)

    def test_a_granary_consumes_only_its_declared_shared_costs(self):
        institution = self.group()
        self.funded(institution)
        proposal = self.approved(institution)
        before = self.world.resource_totals()
        self.assert_success(self.execute(self.world.agents[0], 'enact', institution=institution.id,
                                         proposal=proposal['id']))
        after = self.world.resource_totals()
        for resource, cost in (('wood', 10), ('iron', 2), ('coins', 6), ('food', 0)):
            self.assertAlmostEqual(after[resource], before[resource] - cost)
        self.assertEqual(self.world.settlements[institution.settlement_id].buildings['granary'], 1)
        self.assertEqual(proposal['status'], 'enacted')
        self.world._assert_invariants()

    def test_current_resources_are_rechecked_after_a_mandate_is_approved(self):
        institution = self.group()
        self.funded(institution)
        proposal = self.approved(institution)
        # A prior environmental/administrative change moves the shared stock;
        # approval remains valid but is not a license to create missing wood.
        town = self.world.settlements[institution.settlement_id]
        town.wood += institution.inventory['wood']
        institution.inventory['wood'] = 0
        before = self.world.resource_totals()
        result = self.execute(self.world.agents[0], 'enact', institution=institution.id,
                              proposal=proposal['id'])
        self.assertFalse(result['result']['success'], result)
        self.assertEqual(self.world.resource_totals(), before)

    def test_a_new_contribution_cannot_fund_enactment_in_the_same_tick(self):
        institution = self.group()
        institution.inventory['iron'] = 2
        institution.treasury = 6
        contributor = self.world.agents[1]
        contributor.inventory['wood'] = 10
        self.fixture_totals()
        proposal = self.approved(institution)
        results = self.world.resolve_actions([
            self.action(contributor, 'contribute', institution=institution.id, resource='wood', amount=10),
            self.action(self.world.agents[0], 'enact', institution=institution.id, proposal=proposal['id']),
        ])
        by_type = {r['action']['type']: r for r in results}
        self.assert_success(by_type['contribute'])
        self.assertFalse(by_type['enact']['result']['success'], results)
        result = self.execute(self.world.agents[0], 'enact', institution=institution.id, proposal=proposal['id'])
        self.assertFalse(result['result']['success'], result)
        self.world.advance_time()
        self.assert_success(self.execute(self.world.agents[0], 'enact', institution=institution.id,
                                         proposal=proposal['id']))

    def test_departure_does_not_withdraw_common_property(self):
        institution = self.group()
        self.funded(institution)
        member = self.world.agents[0]
        personal = copy.deepcopy(member.inventory)
        shared = (copy.deepcopy(institution.inventory), institution.treasury)
        before = self.world.resource_totals()
        self.assert_success(self.execute(member, 'leave_institution', institution=institution.id))
        self.assertNotIn(member.id, institution.members)
        self.assertEqual(member.inventory, personal)
        self.assertEqual((institution.inventory, institution.treasury), shared)
        self.assertEqual(self.world.resource_totals(), before)

    def test_an_institution_survives_its_founders_death_without_inherited_authority(self):
        institution = self.group()
        self.funded(institution)
        founder = self.world.agents[0]
        before = self.world.resource_totals()
        successor = self.world.remove_agent(founder.id, cause='test death')
        self.assertTrue(institution.active)
        self.assertNotIn(founder.id, institution.members)
        self.assertNotIn(successor.id, institution.members)
        self.assertEqual(institution.inventory['wood'], 10)
        self.assertEqual(self.world.resource_totals(), before)

    def test_empty_institutions_release_common_assets_when_they_collapse(self):
        institution = self.group(count=1)
        self.funded(institution)
        self.assert_success(self.execute(self.world.agents[0], 'leave_institution', institution=institution.id))
        # This checks conservation using the world ledger, because annual
        # population production/consumption also runs during these four ticks.
        for _ in range(4):
            self.world.advance_time()
        self.assertFalse(institution.active)
        self.assertEqual(sum(institution.inventory.values()) + institution.treasury, 0)
        self.world._assert_invariants()

    def test_invalid_mandates_and_quantities_are_rejected_atomically(self):
        institution = self.group()
        member = self.world.agents[0]
        before = self.world.resource_totals()
        for kind, params in (
            ('tax_rate', {'value': .16}), ('tax_rate', {'value': math.nan}),
            ('communal_labor', {'value': -.1}), ('communal_labor', {'value': True}),
            ('granary', {'override': True}), ('war', {}),
        ):
            with self.subTest(kind=kind, params=params):
                result = self.execute(member, 'propose', institution=institution.id, kind=kind, params=params)
                self.assertFalse(result['result']['success'], result)
        self.assertFalse(institution.decisions)
        self.assertEqual(self.world.resource_totals(), before)
        json.dumps(self.world.export(), allow_nan=False)

    def test_approved_rates_change_rules_without_minting_shared_money(self):
        institution = self.group()
        proposal = self.approved(institution, 'tax_rate', {'value': .1})
        before = self.world.resource_totals()
        self.assert_success(self.execute(self.world.agents[0], 'enact', institution=institution.id,
                                         proposal=proposal['id']))
        self.assertEqual(institution.rules['tax_rate'], .1)
        self.assertEqual(self.world.resource_totals(), before)
        shared_before = institution.treasury
        # No individual planning runs here; only the annual aggregate phase and
        # voted member levy can move these coins into shared holdings.
        for _ in range(self.world.ticks_per_year):
            self.world.advance_time()
        self.assertGreater(institution.treasury, shared_before)
        self.world._assert_invariants()

    def test_no_automatic_governance_upgrades_without_a_collective_decision(self):
        # Advancing the economy, rather than running policies, leaves all
        # institutional decisions absent. Resource-rich towns cannot upgrade
        # themselves through the legacy scripted council routine.
        for _ in range(12 * self.world.ticks_per_year):
            self.world.advance_time()
        self.assertFalse(self.world.institutions)
        self.assertTrue(all(s.farming_level == 0 and s.mining_level == 0
                            for s in self.world.settlements))

    def test_a_trade_agreement_requires_independent_reciprocal_consent(self):
        institution = self.group()
        proposal = self.approved(institution, 'trade_agreement', {'destination': 0})
        result = self.execute(self.world.agents[0], 'enact', institution=institution.id,
                              proposal=proposal['id'])
        self.assertFalse(result['result']['success'], result)
        self.assertNotIn(0, self.world.settlements[institution.settlement_id].relations)

    def test_reciprocal_approved_agreements_enable_finite_aggregate_food_trade(self):
        founder, member, _, remote_founder, remote_member = self.world.agents
        for person in (remote_founder, remote_member):
            self.world.settlements[person.home].population -= 1
            person.home = 0
            self.world.settlements[0].population += 1
        results = self.world.resolve_actions([
            self.action(founder, 'form_institution', name='Highfen Cooperative'),
            self.action(remote_founder, 'form_institution', name='Rivermark Cooperative'),
        ])
        self.assertTrue(all(r['result']['success'] for r in results), results)
        local = next(i for i in self.world.institutions if i.settlement_id == founder.home)
        remote = next(i for i in self.world.institutions if i.settlement_id == remote_founder.home)
        self.world.advance_time()
        results = self.world.resolve_actions([
            self.action(member, 'join_institution', institution=local.id),
            self.action(remote_member, 'join_institution', institution=remote.id),
        ])
        self.assertTrue(all(r['result']['success'] for r in results), results)
        self.world.advance_time()
        results = self.world.resolve_actions([
            self.action(founder, 'propose', institution=local.id, kind='trade_agreement',
                        params={'destination': remote.settlement_id}),
            self.action(remote_founder, 'propose', institution=remote.id, kind='trade_agreement',
                        params={'destination': local.settlement_id}),
        ])
        self.assertTrue(all(r['result']['success'] for r in results), results)
        self.world.advance_time()
        results = self.world.resolve_actions([
            self.action(member, 'vote', institution=local.id, proposal=local.decisions[-1]['id'], approve=True),
            self.action(remote_member, 'vote', institution=remote.id, proposal=remote.decisions[-1]['id'], approve=True),
        ])
        self.assertTrue(all(r['result']['success'] for r in results), results)
        self.world.advance_time()
        self.assert_success(self.execute(founder, 'enact', institution=local.id,
                                         proposal=local.decisions[-1]['id']))
        buyer, seller = self.world.settlements[local.settlement_id], self.world.settlements[remote.settlement_id]
        self.assertEqual(buyer.relations[seller.id], 'trade')
        self.assertEqual(seller.relations[buyer.id], 'trade')
        buyer.food, seller.food = 0., 1000.
        self.fixture_totals()
        before = self.world.resource_totals()
        self.world._institutional_trade()
        self.assertGreater(buyer.food, 0)
        self.assertLess(seller.food, 1000)
        self.assertEqual(self.world.resource_totals(), before)

    def test_approved_labor_allocation_changes_output_with_an_opportunity_cost(self):
        institution = self.group()
        proposal = self.approved(institution, 'communal_labor', {'value': .2})
        baseline = copy.deepcopy(self.world)
        self.assert_success(self.execute(self.world.agents[0], 'enact', institution=institution.id,
                                         proposal=proposal['id']))
        before = {resource: self.world.ledger['produced'][resource]
                  for resource in ('food', 'wood', 'iron')}
        for _ in range(self.world.ticks_per_year):
            self.world.advance_time()
            baseline.advance_time()
        actual = {resource: self.world.ledger['produced'][resource] - before[resource] for resource in before}
        comparison = {resource: baseline.ledger['produced'][resource] - before[resource] for resource in before}
        self.assertGreater(actual['food'], comparison['food'])
        self.assertLess(actual['wood'], comparison['wood'])
        self.assertLess(actual['iron'], comparison['iron'])
        self.world._assert_invariants()
        baseline._assert_invariants()

    def test_a_voted_granary_retains_more_of_an_identical_food_surplus(self):
        institution = self.group()
        self.funded(institution)
        proposal = self.approved(institution)
        baseline = copy.deepcopy(self.world)
        self.assert_success(self.execute(self.world.agents[0], 'enact', institution=institution.id,
                                         proposal=proposal['id']))
        for world in (self.world, baseline):
            world.settlements[institution.settlement_id].food = 10000
            world.initial_totals = {
                resource: total - world.ledger['produced'][resource] + world.ledger['consumed'][resource]
                for resource, total in world.resource_totals().items()
            }
        for _ in range(self.world.ticks_per_year):
            self.world.advance_time()
            baseline.advance_time()
        self.assertGreater(self.world.settlements[institution.settlement_id].food,
                           baseline.settlements[institution.settlement_id].food)
        self.assertEqual(self.world.ledger['produced']['food'], baseline.ledger['produced']['food'])
        self.world._assert_invariants()
        baseline._assert_invariants()

    def test_historical_institution_snapshots_are_detached(self):
        institution = self.group()
        for _ in range(self.world.ticks_per_year - self.world.tick):
            self.world.advance_time()
        snapshot = self.world.snapshots[-1]
        state = next(i for i in snapshot['institutions'] if i['id'] == institution.id)
        state['members'].clear()
        state['inventory']['food'] = 99999
        self.assertTrue(institution.members)
        self.assertNotEqual(institution.inventory['food'], 99999)

    def test_hundred_year_institutional_replay_is_deterministic_and_accounted(self):
        first = InstitutionalWorld(seed=21).run(100)
        second = InstitutionalWorld(seed=21).run(100)
        exported = first.export()
        self.assertEqual(exported, second.export())
        self.assertEqual(exported['schema'], 'eternia.v0.4')
        self.assertEqual(exported['mode'], 'institutions')
        self.assertEqual(first.year, 100)
        self.assertEqual(len(exported['snapshots']), 101)
        self.assertTrue(any(a.generation > 0 for a in first.agents))
        for resource, total in first.resource_totals().items():
            expected = (first.initial_totals[resource] + first.ledger['produced'][resource]
                        - first.ledger['consumed'][resource])
            self.assertAlmostEqual(total, expected, places=6)
        json.dumps(exported, allow_nan=False)


if __name__ == '__main__':
    unittest.main()
