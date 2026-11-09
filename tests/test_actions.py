"""Action rules must protect world state, even from malformed proposals."""
import copy
import json
import math
import unittest
from dataclasses import asdict

from eternia.actions import Action, ActionEngine
from eternia.simulation import World


class ActionEngineTests(unittest.TestCase):
    def setUp(self):
        self.world = World(seed=42)
        self.engine = ActionEngine(self.world)
        self.actor = self.world.agents[0]
        self.home = self.world.settlements[self.actor.home]

    def action(self, kind, **params):
        return dict(actor=self.actor.id, type=kind, location=self.home.id, **params)

    def authoritative_state(self):
        return copy.deepcopy({
            'year': self.world.year,
            'agents': [asdict(a) for a in self.world.agents],
            'settlements': [asdict(s) for s in self.world.settlements],
            'events': self.world.events,
            'rng': self.world.rng.getstate(),
            'last_action_year': getattr(self.world, 'last_action_year', {}),
        })

    def assert_rejected_atomically(self, proposal):
        before = self.authoritative_state()
        result = self.engine.execute(proposal)
        self.assertFalse(result.success, proposal)
        self.assertEqual(before, self.authoritative_state(), proposal)
        self.assertTrue(result.code)
        self.assertTrue(result.message)
        return result

    def test_validation_is_a_pure_dry_run(self):
        proposal = self.action('gather', resource='iron', amount=3)
        before = self.authoritative_state()
        log_before = copy.deepcopy(getattr(self.world, 'action_log', []))
        result = self.engine.validate(proposal)
        self.assertTrue(result.success, result.message)
        self.assertEqual(before, self.authoritative_state())
        self.assertEqual(log_before, getattr(self.world, 'action_log', []))

    def test_execute_rechecks_a_previously_valid_proposal(self):
        proposal = self.action('gather', resource='iron', amount=3)
        self.assertTrue(self.engine.validate(proposal).success)
        self.home.deposits['iron'] = 0
        self.assert_rejected_atomically(proposal)

    def test_malformed_quantities_are_rejected_without_mutation(self):
        for amount in (True, False, -1, 0, 1.5, math.nan, math.inf, -math.inf, 10**400, '2', None):
            with self.subTest(amount=amount):
                self.assert_rejected_atomically(self.action('gather', resource='iron', amount=amount))

    def test_unknown_or_ambiguous_proposals_are_rejected(self):
        proposals = [
            None, [], 'gather', {},
            {'actor': True, 'type': 'rest'},
            {'actor': 'missing person', 'type': 'rest'},
            {'actor': self.actor.id, 'type': 'teleport'},
            self.action('gather', resource='gold', amount=1),
            self.action('gather', resource='wood', amount=1, secret_override=True),
            self.action('build', structure='castle'),
            dict(actor=self.actor.id, type='rest', location='missing village'),
        ]
        for proposal in proposals:
            with self.subTest(proposal=proposal):
                self.assert_rejected_atomically(proposal)

    def test_flat_named_action_and_action_object_are_supported(self):
        proposal = Action.from_dict(dict(actor=self.actor.name, type='gather',
                                        resource='wood', amount=2, location=self.home.name))
        result = self.engine.execute(proposal)
        self.assertTrue(result.success, result.message)
        self.assertEqual(self.actor.inventory['wood'], 2)

    def test_permission_location_knowledge_and_energy_are_enforced(self):
        self.home.permissions['gather'] = False
        self.assert_rejected_atomically(self.action('gather', resource='iron', amount=1))
        self.home.permissions['gather'] = True
        self.assert_rejected_atomically(dict(actor=self.actor.id, type='gather',
                                            resource='iron', amount=1, location=1))
        self.actor.energy = 0
        self.assert_rejected_atomically(self.action('gather', resource='iron', amount=1))
        self.actor.energy = 100
        self.actor.inventory.update(wood=100, iron=100, coins=100)
        self.actor.skills = [s for s in self.actor.skills if s != 'carpentry']
        self.assert_rejected_atomically(self.action('build', structure='house'))
        self.actor.skills.append('carpentry')
        self.actor.inventory['wood'] = 0
        self.assert_rejected_atomically(self.action('build', structure='house'))

    def test_gather_transfers_from_finite_environment(self):
        before_deposit = self.home.deposits['iron']
        before_inventory = self.actor.inventory['iron']
        result = self.engine.execute(self.action('gather', resource='iron', amount=4))
        self.assertTrue(result.success, result.message)
        self.assertEqual(self.home.deposits['iron'], before_deposit - 4)
        self.assertEqual(self.actor.inventory['iron'], before_inventory + 4)
        self.world.year += 1
        self.home.deposits['iron'] = 0
        self.assert_rejected_atomically(self.action('gather', resource='iron', amount=1))

    def test_one_successful_action_per_turn_and_rejections_do_not_spend_turn(self):
        self.assert_rejected_atomically(self.action('gather', resource='iron', amount=999))
        first = self.engine.execute(self.action('gather', resource='iron', amount=1))
        self.assertTrue(first.success, first.message)
        self.assert_rejected_atomically(self.action('gather', resource='iron', amount=1))
        self.world.year += 1
        following = self.engine.execute(self.action('gather', resource='iron', amount=1))
        self.assertTrue(following.success, following.message)

    def test_trade_conserves_goods_and_money_in_both_directions(self):
        self.actor.inventory.update(iron=6, coins=30)
        for direction in ('sell', 'buy'):
            with self.subTest(direction=direction):
                goods = self.actor.inventory['iron'] + self.home.iron
                money = self.actor.inventory['coins'] + self.home.treasury
                result = self.engine.execute(self.action('trade', resource='iron', amount=2,
                                                        direction=direction))
                self.assertTrue(result.success, result.message)
                self.assertAlmostEqual(goods, self.actor.inventory['iron'] + self.home.iron)
                self.assertAlmostEqual(money, self.actor.inventory['coins'] + self.home.treasury)
                self.world.year += 1

    def test_unfunded_trade_is_atomic(self):
        self.actor.inventory['coins'] = 0
        self.assert_rejected_atomically(self.action('trade', resource='iron', amount=1, direction='buy'))
        self.actor.inventory['iron'] = 1
        self.home.treasury = 0
        self.assert_rejected_atomically(self.action('trade', resource='iron', amount=1, direction='sell'))

    def test_learning_and_building_have_real_costs_and_world_effects(self):
        self.actor.inventory.update(wood=20, iron=5, coins=30)
        result = self.engine.execute(self.action('research', topic='carpentry'))
        self.assertTrue(result.success, result.message)
        self.assertIn('carpentry', self.actor.skills)
        self.assertEqual(self.actor.inventory['wood'], 19)
        self.assertEqual(self.actor.inventory['iron'], 4)
        self.world.year += 1
        result = self.engine.execute(self.action('build', structure='house'))
        self.assertTrue(result.success, result.message)
        self.assertEqual(self.actor.inventory['wood'], 7)
        self.assertEqual(self.actor.inventory['iron'], 2)
        self.assertEqual(self.actor.inventory['coins'], 22)
        self.assertEqual(self.actor.structures['house'], 1)
        self.assertEqual(self.home.buildings['house'], 1)

    def test_inconclusive_research_is_a_valid_experiment_with_costs(self):
        self.actor.inventory.update(wood=2, iron=2)
        self.home.aether = 0
        proposal = self.action('research', topic='aether')
        before = self.authoritative_state()
        self.assertTrue(self.engine.validate(proposal).success)
        self.assertEqual(before, self.authoritative_state())
        result = self.engine.execute(proposal)
        self.assertTrue(result.success, result.message)
        self.assertFalse(result.effects['discovered'])
        self.assertEqual(self.actor.inventory['wood'], 1)
        self.assertEqual(self.actor.inventory['iron'], 1)
        self.assertEqual(self.actor.experiments, 1)

    def test_migration_moves_person_and_population_without_creation(self):
        destination = self.world.settlements[1]
        total = sum(s.population for s in self.world.settlements)
        old_home, old_destination = self.home.population, destination.population
        result = self.engine.execute(self.action('migrate', destination=destination.id))
        self.assertTrue(result.success, result.message)
        self.assertEqual(self.actor.home, destination.id)
        self.assertEqual(self.home.population, old_home - 1)
        self.assertEqual(destination.population, old_destination + 1)
        self.assertEqual(total, sum(s.population for s in self.world.settlements))

    def test_founding_transfers_supplies_and_population(self):
        self.actor.role = 'councillor'
        total_population = sum(s.population for s in self.world.settlements)
        before = {r: sum(getattr(s, r) for s in self.world.settlements)
                  for r in ('food', 'wood', 'iron', 'treasury')}
        result = self.engine.execute(self.action('found_settlement', name='Newhaven',
                                                x=40, y=40, settlers=65))
        self.assertTrue(result.success, result.message)
        self.assertEqual(len(self.world.settlements), 8)
        colony = self.world.settlements[-1]
        self.assertEqual(colony.name, 'Newhaven')
        self.assertEqual(self.actor.home, colony.id)
        self.assertEqual(colony.population, 65)
        self.assertEqual(total_population, sum(s.population for s in self.world.settlements))
        for resource in ('food', 'wood', 'iron'):
            self.assertAlmostEqual(before[resource], sum(getattr(s, resource) for s in self.world.settlements))
        self.assertAlmostEqual(before['treasury'] - 25,
                               sum(s.treasury for s in self.world.settlements))

    def test_founding_requires_authority_and_rejects_overlapping_sites(self):
        self.actor.role = 'miner'
        self.assert_rejected_atomically(self.action('found_settlement', name='Newhaven',
                                                    x=40, y=40, settlers=65))
        self.actor.role = 'councillor'
        self.assert_rejected_atomically(self.action('found_settlement', name='Newhaven',
                                                    x=self.home.x, y=self.home.y, settlers=65))

    def test_negotiation_is_reciprocal_and_requires_authority(self):
        self.actor.role = 'miner'
        self.assert_rejected_atomically(self.action('negotiate', destination=1, treaty='trade'))
        self.actor.role = 'councillor'
        result = self.engine.execute(self.action('negotiate', destination=1, treaty='trade'))
        self.assertTrue(result.success, result.message)
        self.assertEqual(self.home.relations[1], 'trade')
        self.assertEqual(self.world.settlements[1].relations[self.home.id], 'trade')

    def test_attempts_are_audited_with_result(self):
        self.actor.energy = 40
        good = self.engine.execute(self.action('rest'))
        bad = self.engine.execute(self.action('gather', resource='iron', amount=1))
        self.assertTrue(good.success, good.message)
        self.assertFalse(bad.success)
        self.assertEqual(len(self.world.action_log), 2)
        self.assertTrue(self.world.action_log[0]['result']['success'])
        self.assertFalse(self.world.action_log[1]['result']['success'])

    def test_invalid_audit_data_remains_exportable_as_strict_json(self):
        self.engine.execute(self.action('gather', resource='iron', amount=math.nan))
        self.engine.execute(self.action('gather', resource='iron', amount=10**400))
        cyclic = {'actor': self.actor.id, 'type': 'gather'}
        cyclic['params'] = cyclic
        self.engine.execute(cyclic)
        json.dumps(self.world.action_log, allow_nan=False)


if __name__ == '__main__':
    unittest.main()
