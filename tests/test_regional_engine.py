"""Authority boundaries for regional mandates, independent of policy outcomes."""
import copy
import json
import math
import unittest

from eternia.institutional_world import InstitutionalWorld
from eternia.regional_engine import RegionalEngine, RegionalInstitution
from eternia.civilizations import CivilizationWorld


class EngineWorld(InstitutionalWorld):
    """Small fixture implementing the regional engine's world-facing helpers."""

    def __init__(self):
        super().__init__(shock_year=0)
        self.action_engine = RegionalEngine(self)
        self.routes = []
        self.agents[2].home = self.agents[3].home = 0
        self.tick = 2

    def local_named_count(self, town):
        return sum(person.home == town for person in self.agents)

    def _begin_institution_tick(self):
        changed = self._institution_budget_tick != self.tick
        super()._begin_institution_tick()
        if changed:
            for institution in self.institutions:
                self._institution_frames[institution.id]['local_named_count'] = self.local_named_count(institution.settlement_id)

    def institution_frame(self, institution):
        frame = super().institution_frame(institution)
        if frame is not None and 'local_named_count' not in frame:
            frame['local_named_count'] = self.local_named_count(institution.settlement_id)
        return frame

    def open_route(self, institution, other, proposal, reciprocal):
        route = {'id': len(self.routes), 'resource': proposal['params']['resource'],
                 'sponsors': [institution.id, other.id]}
        self.routes.append(route)
        self.metrics['negotiation_successes'] = self.metrics.get('negotiation_successes', 0) + 1
        return route


class RegionalEngineTests(unittest.TestCase):
    def setUp(self):
        self.world = EngineWorld()

    def action(self, actor=0, action_type='enact', **params):
        return {'actor': actor, 'type': action_type, 'params': params}

    def organization(self, institution_id=0, town=2, members=(0, 1), purpose='guild',
                     kind='trade_terms', params=None):
        institution = RegionalInstitution(institution_id, f'Organization {institution_id}',
                                          town, members=set(members), purpose=purpose)
        self.world.institutions.append(institution)
        self.world.next_institution_id = institution_id + 1
        if params is None:
            params = {'destination': 0, 'resource': 'food', 'direction': 'export',
                      'unit_price': .2, 'quota': 8}
        proposal = self.proposal(institution, kind, params)
        self.world.initial_totals = self.world.resource_totals()
        return institution, proposal

    def proposal(self, institution, kind, params):
        proposal = {'id': self.world.next_proposal_id, 'kind': kind,
                    'params': params, 'electorate': sorted(institution.members),
                    'votes': {member: {'approve': True, 'tick': 0}
                              for member in institution.members},
                    'created': 0, 'expires': 12, 'status': 'open'}
        self.world.next_proposal_id += 1
        institution.decisions.append(proposal)
        return proposal

    def pair(self, price=.2):
        local, first = self.organization()
        remote, second = self.organization(1, town=0, members=(2, 3),
                                          params={'destination': 2, 'resource': 'food',
                                                  'direction': 'import', 'unit_price': price,
                                                  'quota': 8})
        return local, first, remote, second

    def enact(self, institution=0, proposal=0, actor=0):
        return self.world.resolve_actions([
            self.action(actor, institution=institution, proposal=proposal)
        ])[0]

    def test_formation_records_purpose_and_enforces_a_membership_charter(self):
        self.world.agents[0].skills.remove('trading')
        result = self.world.submit_action(self.action(
            0, 'form_institution', name='Unqualified Guild', purpose='guild'))
        self.assertFalse(result.success)
        self.assertFalse(self.world.institutions)
        result = self.world.submit_action(self.action(
            0, 'form_institution', name='Food Cooperative', purpose='cooperative'))
        self.assertTrue(result.success, result.message)
        self.assertEqual(self.world.institutions[0].public_state()['purpose'], 'cooperative')

    def test_charter_checks_use_skills_from_tick_start(self):
        institution, _ = self.organization()
        learner = self.world.agents[4]
        learner.skills.remove('trading')
        self.world.resolve_actions([self.action(0, 'wait')])
        learner.skills.append('trading')
        result = self.world.submit_action(self.action(
            learner.id, 'join_institution', institution=institution.id))
        self.assertFalse(result.success)
        self.assertNotIn(learner.id, institution.members)

    def test_independently_approved_matching_terms_open_one_route(self):
        _, local, _, remote = self.pair()
        before = self.world.resource_totals()
        result = self.enact()
        self.assertTrue(result['result']['success'], result)
        self.assertEqual(result['result']['effects']['route_id'], 0)
        self.assertEqual(len(self.world.routes), 1)
        self.assertEqual(local['status'], 'enacted')
        self.assertEqual(remote['status'], 'enacted')
        self.assertEqual(self.world.resource_totals(), before)

    def test_a_different_price_cannot_bind_a_foreign_organization(self):
        _, local, _, remote = self.pair(price=.3)
        result = self.enact()
        self.assertFalse(result['result']['success'], result)
        self.assertEqual(result['result']['code'], 'no_matching_terms')
        self.assertFalse(self.world.routes)
        self.assertEqual(local['status'], remote['status'])
        self.assertEqual(local['status'], 'open')

    def test_same_tick_foreign_votes_cannot_authorize_a_route(self):
        _, _, _, remote = self.pair()
        for vote in remote['votes'].values():
            vote['tick'] = self.world.tick
        result = self.enact()
        self.assertFalse(result['result']['success'], result)
        self.assertFalse(self.world.routes)

    def test_two_executors_cannot_reuse_a_foreign_mandate(self):
        _, local, _, remote = self.pair()
        results = self.world.resolve_actions([
            self.action(0, institution=0, proposal=local['id']),
            self.action(1, institution=0, proposal=local['id']),
        ])
        self.assertEqual(sum(r['result']['success'] for r in results), 1)
        self.assertEqual(len(self.world.routes), 1)
        self.assertEqual(remote['status'], 'enacted')

    def test_same_tick_reopening_cannot_enable_an_embargoed_route(self):
        institution, trade, _, _ = self.pair()
        institution.rules['embargoes'] = {0: True}
        reopening = self.proposal(institution, 'embargo', {'destination': 0, 'enabled': False})
        result = self.enact(proposal=reopening['id'])
        self.assertTrue(result['result']['success'], result)
        self.assertFalse(institution.rules['embargoes'][0])
        result = self.enact(proposal=trade['id'], actor=1)
        self.assertFalse(result['result']['success'], result)
        self.assertEqual(result['result']['code'], 'embargoed')
        self.assertFalse(self.world.routes)

    def test_a_new_embargo_invalidates_an_existing_trade_plan(self):
        institution, trade, _, _ = self.pair()
        closing = self.proposal(institution, 'embargo', {'destination': 0, 'enabled': True})
        self.world.rng.seed(0)  # The closing mandate resolves before the route.
        results = self.world.resolve_actions([
            self.action(0, institution=0, proposal=closing['id']),
            self.action(1, institution=0, proposal=trade['id']),
        ])
        self.assertEqual([r['action']['actor'] for r in results], [0, 1])
        self.assertTrue(results[0]['result']['success'], results)
        self.assertFalse(results[1]['result']['success'], results)
        self.assertFalse(self.world.routes)

    def test_only_a_representative_council_can_close_migration(self):
        institution, proposal = self.organization(
            purpose='council', kind='migration_policy', params={'open': False})
        result = self.enact(proposal=proposal['id'])
        self.assertTrue(result['result']['success'], result)
        self.assertIs(institution.rules['migration_open'], False)

    def test_a_guild_cannot_claim_citywide_border_authority(self):
        institution, proposal = self.organization(
            kind='migration_policy', params={'open': False})
        result = self.enact(proposal=proposal['id'])
        self.assertFalse(result['result']['success'], result)
        self.assertNotIn('migration_open', institution.rules)

    def test_same_tick_departure_cannot_create_a_council_majority(self):
        self.world.agents[2].home = 2  # Four locals, of whom only two support the council.
        institution, proposal = self.organization(
            purpose='council', kind='migration_policy', params={'open': False})
        result = self.world.submit_action(self.action(4, 'migrate', destination=0))
        self.assertTrue(result.success, result.message)
        self.assertEqual(self.world.local_named_count(2), 3)
        result = self.enact(proposal=proposal['id'])
        self.assertFalse(result['result']['success'], result)
        self.assertNotIn('migration_open', institution.rules)

    def test_validation_of_matching_terms_is_a_pure_dry_run(self):
        self.pair()
        before = copy.deepcopy((self.world.export(), self.world.routes, self.world.rng.getstate(),
                                self.world._institution_budget_tick, self.world._institution_frames))
        result = self.world.action_engine.validate(self.action(0, institution=0, proposal=0))
        self.assertTrue(result.success, result.message)
        self.assertEqual((self.world.export(), self.world.routes, self.world.rng.getstate(),
                          self.world._institution_budget_tick, self.world._institution_frames), before)

    def test_malformed_terms_and_legacy_agreements_are_safe_rejections(self):
        self.organization(kind='specialization', params={'resource': 'food'})
        normal = {'destination': 0, 'resource': 'food', 'direction': 'export',
                  'unit_price': .2, 'quota': 8}
        cases = [{**normal, 'unit_price': value} for value in (True, math.nan, math.inf, 0, 21)]
        cases += [{**normal, 'quota': value} for value in (True, 0, 41, 1.5, math.nan)]
        cases += [{**normal, 'destination': 2}, {**normal, 'direction': 'barter'},
                  {**normal, 'resource': ['food']}, {**normal, 'extra': True}]
        for params in cases:
            with self.subTest(params=params):
                result = self.world.submit_action(self.action(
                    0, 'propose', institution=0, kind='trade_terms', params=params))
                self.assertFalse(result.success)
        result = self.world.submit_action(self.action(
            0, 'propose', institution=0, kind='trade_agreement', params={'destination': 0}))
        self.assertFalse(result.success)
        self.assertEqual(result.code, 'unknown_proposal')
        json.dumps(self.world.export(), allow_nan=False)


class RegionalFlowTests(unittest.TestCase):
    def setUp(self):
        self.world = CivilizationWorld(seed=42)
        self.world.tick = 2

    def organization(self, identity, town, members, params):
        institution = RegionalInstitution(identity, f'Guild {identity}', town,
                                           members=set(members), purpose='guild')
        self.world.institutions.append(institution)
        proposal = self.proposal(institution, params)
        self.world.next_institution_id = max(self.world.next_institution_id, identity + 1)
        return institution, proposal

    def proposal(self, institution, params):
        proposal = {'id': self.world.next_proposal_id, 'kind': 'trade_terms',
                    'params': params, 'electorate': sorted(institution.members),
                    'votes': {member: {'approve': True, 'tick': 0}
                              for member in institution.members},
                    'created': 0, 'expires': 20, 'status': 'open'}
        self.world.next_proposal_id += 1
        institution.decisions.append(proposal)
        return proposal

    def pair(self, source, target, *, resource='food', price=.2, quota=10,
             source_members=None, target_members=None):
        first_id = self.world.next_institution_id
        terms = {'resource': resource, 'unit_price': price, 'quota': quota}
        source_members = source_members or (source * 6, source * 6 + 1)
        target_members = target_members or (target * 6, target * 6 + 1)
        exporter, offer = self.organization(first_id, source, source_members,
                                            {**terms, 'destination': target, 'direction': 'export'})
        importer, bid = self.organization(first_id + 1, target, target_members,
                                          {**terms, 'destination': source, 'direction': 'import'})
        return exporter, offer, importer, bid

    def enact(self, institution, proposal):
        actor = min(institution.members)
        result = self.world.resolve_actions([
            {'actor': actor, 'type': 'enact',
             'params': {'institution': institution.id, 'proposal': proposal['id']}}
        ])[0]
        return result

    def fixture_totals(self):
        self.world.initial_totals = {
            resource: total - self.world.ledger['produced'][resource]
            + self.world.ledger['consumed'][resource]
            for resource, total in self.world.resource_totals().items()}

    def assert_conserved(self, before):
        for resource, total in before.items():
            self.assertAlmostEqual(self.world.resource_totals()[resource], total)
        self.world._assert_invariants()

    def test_duplicate_unexpired_contract_cannot_multiply_a_negotiated_quota(self):
        exporter, first, importer, _ = self.pair(0, 1)
        self.assertTrue(self.enact(exporter, first)['result']['success'])
        self.world.advance_time()
        offer = self.proposal(exporter, {**first['params'], 'unit_price': .25})
        self.proposal(importer, {**first['params'], 'destination': 0,
                                 'direction': 'import', 'unit_price': .25})
        before = self.world.resource_totals()
        result = self.enact(exporter, offer)
        self.assertFalse(result['result']['success'], result)
        self.assertEqual(result['result']['code'], 'active_route')
        self.assertEqual(len(self.world.routes), 1)
        self.assert_conserved(before)

    def test_expired_contract_can_be_renegotiated_with_new_terms(self):
        exporter, first, importer, _ = self.pair(0, 1)
        self.assertTrue(self.enact(exporter, first)['result']['success'])
        self.world.advance_time()
        self.world.routes[0]['expires'] = self.world.tick
        offer = self.proposal(exporter, {**first['params'], 'unit_price': .25})
        self.proposal(importer, {**first['params'], 'destination': 0,
                                 'direction': 'import', 'unit_price': .25})
        result = self.enact(exporter, offer)
        self.assertTrue(result['result']['success'], result)
        self.assertEqual(len(self.world.routes), 2)
        self.assertEqual(self.world.routes[0]['status'], 'expired')
        self.assertEqual(self.world.routes[1]['unit_price'], .25)

    def test_competing_importers_cannot_overdraw_one_settlements_surplus(self):
        first, offer, _, _ = self.pair(0, 1, quota=4)
        second, other_offer, _, _ = self.pair(0, 2, quota=4, source_members=(2, 3))
        self.assertTrue(self.enact(first, offer)['result']['success'])
        self.assertTrue(self.enact(second, other_offer)['result']['success'])
        source, left, right = self.world.settlements
        reserve = source.population * 1.1
        source.food, left.food, right.food = reserve + 5, 0., 0.
        self.fixture_totals()
        before = self.world.resource_totals()
        self.world._institutional_trade()
        self.assertAlmostEqual(source.food, reserve)
        self.assertAlmostEqual(left.food + right.food, 5)
        self.assertTrue(all(route['volume'] <= 4 for route in self.world.routes))
        self.assert_conserved(before)

    def test_repeated_resolution_cannot_ship_an_annual_quota_twice(self):
        exporter, offer, _, _ = self.pair(0, 1, quota=4)
        self.assertTrue(self.enact(exporter, offer)['result']['success'])
        source, target = self.world.settlements[:2]
        source.food, target.food = 250., 0.
        self.fixture_totals()
        before = self.world.resource_totals()
        self.world._institutional_trade()
        self.world._institutional_trade()
        self.assertEqual(self.world.routes[0]['volume'], 4)
        self.assertEqual(self.world.routes[0]['shipments'], 1)
        self.assertEqual(target.food, 4)
        self.assert_conserved(before)

    def test_incoming_coins_cannot_finance_another_import_in_the_same_year(self):
        food_seller, food_offer, _, _ = self.pair(0, 1, quota=10)
        iron_seller, iron_offer, _, _ = self.pair(1, 0, resource='iron', price=1,
                                                 source_members=(8, 9), target_members=(2, 3))
        self.assertTrue(self.enact(food_seller, food_offer)['result']['success'])
        self.assertTrue(self.enact(iron_seller, iron_offer)['result']['success'])
        first, second = self.world.settlements[:2]
        first.food, second.food = 250., 0.
        first.iron, second.iron = 0., 100.
        first.treasury, second.treasury = 0., 100.
        self.fixture_totals()
        before = self.world.resource_totals()
        self.world.rng.seed(0)  # Food income arrives before the iron route is processed.
        self.world._institutional_trade()
        self.assertGreater(first.treasury, 0)
        self.assertEqual(first.iron, 0)
        self.assertEqual(self.world.routes[1]['shipments'], 0)
        self.world._institutional_trade()
        self.assertEqual(first.iron, 0)
        self.assertEqual(self.world.routes[1]['shipments'], 0)
        self.assert_conserved(before)

    def test_incoming_goods_cannot_be_reexported_in_the_same_year(self):
        first, first_offer, _, _ = self.pair(0, 1, quota=4)
        second, second_offer, _, _ = self.pair(1, 2, quota=4, source_members=(8, 9))
        self.assertTrue(self.enact(first, first_offer)['result']['success'])
        self.assertTrue(self.enact(second, second_offer)['result']['success'])
        source, middle, target = self.world.settlements
        source.food, middle.food, target.food = 250., middle.population * 1.1 - 1, 0.
        self.fixture_totals()
        before = self.world.resource_totals()
        self.world.rng.seed(0)
        self.world._institutional_trade()
        self.assertGreater(middle.food, middle.population * 1.1)
        self.assertEqual(target.food, 0)
        self.assertEqual(self.world.routes[1]['shipments'], 0)
        self.assert_conserved(before)

    def test_a_minority_council_cannot_close_the_border_to_other_people(self):
        council = RegionalInstitution(0, 'Minority Council', 0,
                                       members={0, 1}, purpose='council')
        self.world.institutions.append(council)
        proposal = self.proposal(council, {'open': False})
        proposal['kind'] = 'migration_policy'
        result = self.enact(council, proposal)
        self.assertFalse(result['result']['success'], result)
        self.assertEqual(result['result']['code'], 'insufficient_authority')
        self.assertTrue(self.world.settlements[0].permissions['migrate'])
        result = self.world.resolve_actions([
            {'actor': 6, 'type': 'migrate', 'params': {'destination': 0}}
        ])[0]
        self.assertTrue(result['result']['success'], result)
        self.assertEqual(self.world._resolve_agent(6).home, 0)

    def border_council(self, *, closed=True, opening_proposal=False):
        council = RegionalInstitution(0, 'Highfen Council', 1,
                                       members={6, 7, 8, 9}, purpose='council')
        council.rules['migration_open'] = not closed
        self.world.institutions.append(council)
        proposal = self.proposal(council, {'open': opening_proposal})
        proposal['kind'] = 'migration_policy'
        return council, proposal

    def test_residents_can_leave_their_own_closed_incoming_border(self):
        self.border_council()
        result = self.world.resolve_actions([
            {'actor': 10, 'type': 'migrate', 'params': {'destination': 0}}
        ])[0]
        self.assertTrue(result['result']['success'], result)
        self.assertEqual(self.world._resolve_agent(10).home, 0)
        self.assertFalse(self.world.regional_migration_open(1))

    def test_closed_incoming_border_rejects_arrivals(self):
        self.border_council()
        population = [town.population for town in self.world.settlements]
        result = self.world.resolve_actions([
            {'actor': 0, 'type': 'migrate', 'params': {'destination': 1}}
        ])[0]
        self.assertFalse(result['result']['success'], result)
        self.assertEqual(result['result']['code'], 'permission_denied')
        self.assertEqual(self.world._resolve_agent(0).home, 0)
        self.assertEqual([town.population for town in self.world.settlements], population)

    def test_new_border_closure_invalidates_a_previously_open_arrival_plan(self):
        council, proposal = self.border_council(closed=False)
        self.world.rng.seed(1)  # Council action resolves before the incoming mover.
        results = self.world.resolve_actions([
            {'actor': 6, 'type': 'enact',
             'params': {'institution': council.id, 'proposal': proposal['id']}},
            {'actor': 0, 'type': 'migrate', 'params': {'destination': 1}},
        ])
        self.assertEqual([row['action']['actor'] for row in results], [6, 0])
        self.assertTrue(results[0]['result']['success'], results)
        self.assertFalse(results[1]['result']['success'], results)
        self.assertEqual(results[1]['result']['code'], 'conflict')
        self.assertEqual(self.world._resolve_agent(0).home, 0)

    def test_same_tick_reopening_cannot_enable_an_initially_closed_arrival(self):
        council, proposal = self.border_council(opening_proposal=True)
        self.world.rng.seed(1)
        results = self.world.resolve_actions([
            {'actor': 6, 'type': 'enact',
             'params': {'institution': council.id, 'proposal': proposal['id']}},
            {'actor': 0, 'type': 'migrate', 'params': {'destination': 1}},
        ])
        self.assertEqual([row['action']['actor'] for row in results], [6, 0])
        self.assertTrue(results[0]['result']['success'], results)
        self.assertTrue(self.world.regional_migration_open(1))
        self.assertFalse(results[1]['result']['success'], results)
        self.assertEqual(self.world._resolve_agent(0).home, 0)

    def test_a_later_same_tick_submission_cannot_use_a_new_border_opening(self):
        council, proposal = self.border_council(opening_proposal=True)
        result = self.enact(council, proposal)
        self.assertTrue(result['result']['success'], result)
        self.assertTrue(self.world.regional_migration_open(1))
        movement = {'actor': 0, 'type': 'migrate', 'params': {'destination': 1}}
        result = self.world.resolve_actions([movement])[0]
        self.assertFalse(result['result']['success'], result)
        self.assertEqual(self.world._resolve_agent(0).home, 0)
        self.world.advance_time()
        result = self.world.resolve_actions([movement])[0]
        self.assertTrue(result['result']['success'], result)
        self.assertEqual(self.world._resolve_agent(0).home, 1)

    def test_a_later_same_tick_submission_obeys_a_new_border_closure(self):
        council, proposal = self.border_council(closed=False)
        result = self.enact(council, proposal)
        self.assertTrue(result['result']['success'], result)
        self.assertFalse(self.world.regional_migration_open(1))
        result = self.world.resolve_actions([
            {'actor': 0, 'type': 'migrate', 'params': {'destination': 1}}
        ])[0]
        self.assertFalse(result['result']['success'], result)
        self.assertEqual(self.world._resolve_agent(0).home, 0)

    def test_specialization_at_full_capacity_accounts_output_and_spoilage_separately(self):
        institution = RegionalInstitution(0, 'Forest Guild', 2,
                                           members={12, 13}, purpose='guild')
        self.world.institutions.append(institution)
        proposal = self.proposal(institution, {'resource': 'wood'})
        proposal['kind'] = 'specialization'
        town = self.world.settlements[2]
        town.wood, town.iron = 200., 120.
        self.fixture_totals()
        baseline = copy.deepcopy(self.world)
        result = self.enact(institution, proposal)
        self.assertTrue(result['result']['success'], result)
        self.world.rng.seed(17)
        baseline.rng.seed(17)
        self.world._produce_and_consume()
        baseline._produce_and_consume()
        self.assertEqual(town.wood, max(150., town.population * .7))
        self.assertGreater(self.world.ledger['produced']['wood'], baseline.ledger['produced']['wood'])
        self.assertLess(self.world.ledger['produced']['food'], baseline.ledger['produced']['food'])
        self.assertLess(self.world.ledger['produced']['iron'], baseline.ledger['produced']['iron'])
        self.world._assert_invariants()
        baseline._assert_invariants()


if __name__ == '__main__':
    unittest.main()
