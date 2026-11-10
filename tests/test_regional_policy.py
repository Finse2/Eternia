"""Regional choices use advertised terms and local interests, not private peers."""
import copy
import unittest

from eternia.institutional_world import InstitutionalWorld
from eternia.regional_policy import RegionalPolicy


class RegionalPolicyTests(unittest.TestCase):
    def observation(self, *, role='merchant', purpose='guild', openness=.7):
        world = InstitutionalWorld(shock_year=0)
        actor = world.agents[0]
        actor.role = role
        actor.inventory.update(food=5, wood=0, iron=0, coins=50)
        actor.knowledge = 2
        actor.skills = ['foraging', 'trading', 'mining', 'woodcutting', 'carpentry']
        actor.structures['house'] = 3
        observation = world.observe(actor.id)
        observation['tick'] = 10
        observation['actor'].update(openness=openness, preferred_purpose=purpose)
        town = observation['settlement']
        town.update(food=town['population'] * 1.5, wood=25, iron=15,
                    farmland=120, fertility=.8, forest=.2, ore=1.0)
        town['deposits'] = {'food': 24, 'wood': 24, 'iron': 12}
        observation['regional'] = {'prices': {'food': .2, 'wood': .5, 'iron': 1.5},
                                   'diplomacy': {}, 'routes': [],
                                   'local_named_count': 6, 'borders': {}}
        observation['institutions'] = []
        observation['market'] = []
        return observation

    def institution(self, observation, *, identifier=0, purpose='guild', members=None,
                    settlement=None):
        actor = observation['actor']
        members = [actor['id'], 1] if members is None else members
        institution = {'id': identifier, 'name': f'Institution {identifier}', 'purpose': purpose,
                       'settlement_id': observation['settlement']['id'] if settlement is None else settlement,
                       'members': members, 'active': True, 'founded': 0,
                       'rules': {'tax_rate': 0, 'communal_labor': 0}, 'decisions': []}
        if actor['id'] in members:
            institution.update(inventory={'food': 0, 'wood': 0, 'iron': 0}, treasury=6)
        observation['institutions'].append(institution)
        return institution

    def decision(self, institution, *, identifier=0, kind='trade_terms', params=None, votes=None):
        decision = {'id': identifier, 'kind': kind, 'params': params or {},
                    'status': 'open', 'created': 5, 'expires': 17,
                    'electorate': list(institution['members']),
                    'votes': votes if votes is not None else {
                        person: {'approve': True, 'tick': 6} for person in institution['members']}}
        institution['decisions'].append(decision)
        return decision

    def foreign_offer(self, observation, *, price=.2):
        neighbor = observation['neighbors'][0]
        neighbor.update(food=neighbor['population'] * 2, forest=.2, ore=.1,
                        farmland=neighbor['population'] * 2, fertility=1.2)
        institution = self.institution(observation, identifier=10, settlement=neighbor['id'], members=[20, 21])
        terms = {'destination': observation['settlement']['id'], 'resource': 'food',
                 'direction': 'export', 'unit_price': price, 'quota': 10}
        self.decision(institution, identifier=10, params=terms)
        return neighbor, institution

    def test_professions_can_form_different_kinds_of_organization(self):
        for role, purpose in (('merchant', 'guild'), ('farmer', 'cooperative'), ('councillor', 'council')):
            with self.subTest(purpose=purpose):
                proposal = RegionalPolicy().propose(self.observation(role=role, purpose=purpose))
                self.assertEqual(proposal['type'], 'form_institution')
                self.assertEqual(proposal['params']['purpose'], purpose)

    def test_a_guild_can_form_beside_an_existing_cooperative(self):
        observation = self.observation()
        self.institution(observation, purpose='cooperative', members=[1, 2])
        proposal = RegionalPolicy().propose(observation)
        self.assertEqual(proposal['type'], 'form_institution')
        self.assertEqual(proposal['params']['purpose'], 'guild')

    def test_joining_uses_a_public_purpose_without_reading_shared_accounts(self):
        observation = self.observation()
        institution = self.institution(observation, members=[1, 2])
        self.assertNotIn('inventory', institution)
        proposal = RegionalPolicy().propose(observation)
        self.assertEqual(proposal['type'], 'join_institution')
        self.assertEqual(proposal['params']['institution'], institution['id'])

    def test_a_useful_public_offer_motivates_an_independently_voted_counterpart(self):
        observation = self.observation()
        observation['settlement']['food'] = 0
        self.institution(observation)
        neighbor, _ = self.foreign_offer(observation)
        proposal = RegionalPolicy().propose(observation)
        self.assertEqual(proposal['type'], 'propose')
        self.assertEqual(proposal['params']['kind'], 'trade_terms')
        terms = proposal['params']['params']
        self.assertEqual(terms, {'destination': neighbor['id'], 'resource': 'food',
                                'direction': 'import', 'unit_price': .2, 'quota': 10})

    def test_a_bad_foreign_price_is_not_copied_into_matching_terms(self):
        observation = self.observation()
        observation['settlement']['food'] = 0
        self.institution(observation)
        self.foreign_offer(observation, price=3)
        proposal = RegionalPolicy().propose(observation)
        self.assertNotEqual(proposal.get('params', {}).get('params', {}).get('unit_price'), 3)

    def test_import_offers_change_with_public_resource_scarcity(self):
        quotes = []
        for stock in (130, 0):
            observation = self.observation()
            observation['settlement']['food'] = stock
            self.institution(observation)
            neighbor, foreign = self.foreign_offer(observation)
            foreign['decisions'] = []
            proposal = RegionalPolicy().propose(observation)
            self.assertEqual(proposal['params']['kind'], 'trade_terms')
            self.assertEqual(proposal['params']['params']['direction'], 'import')
            quotes.append(proposal['params']['params']['unit_price'])
        self.assertGreater(quotes[1], quotes[0])

    def test_an_existing_route_prevents_repeated_duplicate_negotiations(self):
        observation = self.observation()
        observation['settlement']['food'] = 0
        institution = self.institution(observation)
        neighbor, _ = self.foreign_offer(observation)
        observation['regional']['routes'].append({
            'resource': 'food', 'exporter': neighbor['id'], 'importer': observation['settlement']['id'],
            'exporter_institution': 10, 'importer_institution': institution['id'],
            'status': 'active', 'expires': 30})
        self.decision(institution, params={'destination': neighbor['id'], 'resource': 'food',
                                          'direction': 'import', 'unit_price': .2, 'quota': 10})
        proposal = RegionalPolicy().propose(observation)
        self.assertNotEqual(proposal['type'], 'enact')
        self.assertFalse(proposal['type'] == 'propose'
                         and proposal['params'].get('kind') == 'trade_terms'
                         and proposal['params']['params'].get('resource') == 'food')

    def test_a_person_can_vote_against_exploitative_import_terms(self):
        observation = self.observation()
        observation['settlement']['food'] = 0
        institution = self.institution(observation)
        neighbor = observation['neighbors'][0]
        self.decision(institution, params={'destination': neighbor['id'], 'resource': 'food',
                                          'direction': 'import', 'unit_price': 3, 'quota': 10},
                      votes={1: {'approve': True, 'tick': 6}})
        proposal = RegionalPolicy().propose(observation)
        self.assertEqual(proposal['type'], 'vote')
        self.assertFalse(proposal['params']['approve'])

    def test_matching_old_majorities_can_motivate_execution(self):
        observation = self.observation()
        observation['settlement']['food'] = 0
        institution = self.institution(observation)
        neighbor, _ = self.foreign_offer(observation)
        self.decision(institution, params={'destination': neighbor['id'], 'resource': 'food',
                                          'direction': 'import', 'unit_price': .2, 'quota': 10})
        proposal = RegionalPolicy().propose(observation)
        self.assertEqual(proposal['type'], 'enact')

    def test_same_tick_votes_do_not_look_like_an_old_mandate(self):
        observation = self.observation()
        observation['settlement']['food'] = 0
        institution = self.institution(observation)
        neighbor, _ = self.foreign_offer(observation)
        self.decision(institution, params={'destination': neighbor['id'], 'resource': 'food',
                                          'direction': 'import', 'unit_price': .2, 'quota': 10},
                      votes={person: {'approve': True, 'tick': 10} for person in institution['members']})
        proposal = RegionalPolicy().propose(observation)
        self.assertNotEqual(proposal['type'], 'enact')

    def test_a_distrustful_person_can_seek_an_embargo(self):
        observation = self.observation(openness=.1)
        institution = self.institution(observation)
        destination = observation['neighbors'][0]['id']
        observation['regional']['diplomacy'][destination] = -.8
        proposal = RegionalPolicy().propose(observation)
        self.assertEqual(proposal['type'], 'propose')
        self.assertEqual(proposal['params'], {'institution': institution['id'], 'kind': 'embargo',
                                              'params': {'destination': destination, 'enabled': True}})

    def test_a_majority_council_can_seek_a_restrictive_border_policy(self):
        observation = self.observation(role='councillor', purpose='council', openness=.1)
        observation['settlement']['food'] = 0
        self.institution(observation, purpose='council', members=[0, 1, 2, 3])
        proposal = RegionalPolicy().propose(observation)
        self.assertEqual(proposal['type'], 'propose')
        self.assertEqual(proposal['params']['kind'], 'migration_policy')
        self.assertFalse(proposal['params']['params']['open'])

    def test_professional_migration_is_independent_of_poverty_and_food_emergency(self):
        observation = self.observation(role='miner')
        observation['actor']['inventory']['coins'] = 100
        observation['actor']['available_inventory']['coins'] = 100
        institution = self.institution(observation)
        institution['rules']['specialization'] = 'iron'
        observation['settlement']['deposits']['iron'] = 0
        neighbor = observation['neighbors'][0]
        neighbor['deposits']['iron'] = 12
        proposal = RegionalPolicy().propose(observation)
        self.assertEqual(proposal['type'], 'migrate')
        self.assertEqual(proposal['params']['destination'], neighbor['id'])

    def test_professional_migration_respects_a_closed_destination(self):
        observation = self.observation(role='miner')
        observation['actor']['inventory']['coins'] = 1
        observation['actor']['available_inventory']['coins'] = 1
        observation['settlement']['deposits']['iron'] = 0
        for neighbor in observation['neighbors']:
            neighbor['permissions']['migrate'] = False
        proposal = RegionalPolicy().propose(observation)
        self.assertNotEqual(proposal['type'], 'migrate')

    def test_specialization_can_follow_different_public_endowments(self):
        choices = []
        for forest, ore in ((.2, 1), (1.2, .1)):
            observation = self.observation()
            observation['neighbors'] = []
            observation['settlement'].update(forest=forest, ore=ore)
            self.institution(observation)
            proposal = RegionalPolicy().propose(observation)
            self.assertEqual(proposal['params']['kind'], 'specialization')
            choices.append(proposal['params']['params']['resource'])
        self.assertEqual(choices, ['iron', 'wood'])

    def test_competing_labor_proposals_use_remaining_public_capacity(self):
        observation = self.observation(role='farmer', purpose='cooperative')
        observation['settlement']['food'] = 0
        own = self.institution(observation, purpose='cooperative')
        own['rules']['specialization'] = 'food'
        other = self.institution(observation, identifier=2, purpose='council', members=[1, 2])
        other['rules']['communal_labor'] = .2
        proposal = RegionalPolicy().propose(observation)
        self.assertEqual(proposal['type'], 'propose')
        self.assertEqual(proposal['params']['kind'], 'communal_labor')
        self.assertAlmostEqual(proposal['params']['params']['value'], .1)

    def test_an_approved_over_capacity_mandate_does_not_block_other_choices(self):
        observation = self.observation(role='farmer', purpose='cooperative')
        observation['settlement']['food'] = 0
        own = self.institution(observation, purpose='cooperative')
        own['rules']['specialization'] = 'food'
        self.decision(own, kind='communal_labor', params={'value': .2})
        other = self.institution(observation, identifier=2, purpose='council', members=[1, 2])
        other['rules']['communal_labor'] = .2
        proposal = RegionalPolicy().propose(observation)
        self.assertNotEqual(proposal['type'], 'enact')

    def test_hunger_and_personal_survival_precede_collective_negotiation(self):
        observation = self.observation()
        observation['actor']['inventory']['food'] = 0
        observation['actor']['available_inventory']['food'] = 0
        observation['actor']['hunger'] = 90
        observation['settlement']['deposits']['food'] = 0
        institution = self.institution(observation)
        self.decision(institution, kind='specialization', params={'resource': 'iron'})
        proposal = RegionalPolicy().propose(observation)
        self.assertEqual(proposal['type'], 'migrate')

    def test_hidden_peer_holdings_do_not_change_the_regional_choice(self):
        observation = self.observation()
        first = RegionalPolicy().propose(observation)
        for peer in observation['peers']:
            peer.update(inventory={'food': 99999, 'coins': 999999}, knowledge=2,
                        skills=['carpentry', 'mining'])
        self.assertEqual(RegionalPolicy().propose(observation), first)

    def test_planning_does_not_mutate_any_observed_state(self):
        observation = self.observation()
        self.institution(observation)
        self.foreign_offer(observation)
        before = copy.deepcopy(observation)
        RegionalPolicy().propose(observation)
        self.assertEqual(observation, before)


if __name__ == '__main__':
    unittest.main()
