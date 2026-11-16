import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from eternia.persistence import checkpoint, restore_checkpoint, save_world, load_world
from eternia.society import SocietyWorld
from eternia.physical_world import PhysicalWorld
from eternia.community import CommunityWorld
from eternia.institutional_world import InstitutionalWorld
from eternia.civilizations import CivilizationWorld
from eternia.simulation import World
from v07_helpers import funded_order, chartered_route


class PersistenceTests(unittest.TestCase):
    def test_isolated_demo_cannot_promise_a_different_resume_loop(self):
        from eternia.autonomy import run_demo
        with self.assertRaisesRegex(ValueError, 'isolated NPC demo'):
            checkpoint(run_demo(turns=1, shock_turn=0))

    def test_builtin_modes_roundtrip_without_advancing_randomness(self):
        for cls in (World, CommunityWorld, InstitutionalWorld, CivilizationWorld, PhysicalWorld, SocietyWorld):
            with self.subTest(world=cls.__name__):
                world = cls(seed=18)
                world.step()
                state = world.rng.getstate()
                restored = restore_checkpoint(checkpoint(world))
                self.assertEqual(restored.export(), world.export())
                self.assertEqual(restored.rng.getstate(), state)
                self.assertEqual(world.rng.getstate(), state)
                world.step()
                restored.step()
                self.assertEqual(restored.export(), world.export())

    def test_save_resume_matches_uninterrupted_society_at_every_future_tick(self):
        world = SocietyWorld(seed=18).run(3)
        restored = restore_checkpoint(json.loads(json.dumps(checkpoint(world), allow_nan=False)))
        for _ in range(12):
            world.step()
            restored.step()
            self.assertEqual(restored.export(), world.export())
            self.assertEqual(restored.rng.getstate(), world.rng.getstate())

    def test_escrow_and_pending_authority_survive_a_partial_tick(self):
        world = SocietyWorld()
        _, order = funded_order(world, quantity=4)
        result = world.submit_action(dict(actor=1, type='work', order=order['id'], amount=1))
        self.assertTrue(result.success)
        restored = restore_checkpoint(checkpoint(world))
        self.assertEqual(restored.work_orders, world.work_orders)
        self.assertEqual(restored._tick_remaining, world._tick_remaining)
        for w in (world, restored):
            self.assertFalse(w.submit_action(dict(actor=1, type='work', order=order['id'], amount=1)).success)
            w.advance_time()
            w.step()
        self.assertEqual(world.export(), restored.export())

    def test_checkpoint_rejects_incomplete_resolution(self):
        world = SocietyWorld()
        world._resolving = True
        with self.assertRaises(ValueError):
            checkpoint(world)

    def test_caravan_migrant_offer_and_reserved_capacity_survive_resume(self):
        world = SocietyWorld(seed=18)
        _, _, route = chartered_route(world)
        worker = world.agents[1]
        world.settlements[0].food -= 5
        worker.inventory['food'] += 5
        caravan = world.submit_action(dict(actor=0, type='dispatch_caravan', route=route['id'], amount=4))
        self.assertTrue(caravan.success, caravan.message)
        migrant = world.submit_action(dict(actor=1, type='migrate', destination=1))
        self.assertTrue(migrant.success, migrant.message)
        offer = world.submit_action(dict(actor=2, type='offer', resource='food', amount=1,
                                         unit_price=1, direction='sell'))
        self.assertTrue(offer.success, offer.message)
        restored = restore_checkpoint(checkpoint(world))
        self.assertEqual(restored.journeys, world.journeys)
        self.assertEqual(restored._link_remaining, world._link_remaining)
        self.assertEqual(restored.offers, world.offers)
        for _ in range(8):
            world.step()
            restored.step()
            self.assertEqual(restored.export(), world.export())

    def test_checksum_and_version_errors_are_clear(self):
        data = checkpoint(SocietyWorld())
        data['payload']['world_type'] = 'arbitrary.module.World'
        with self.assertRaisesRegex(ValueError, 'checksum'):
            restore_checkpoint(data)
        data = checkpoint(SocietyWorld())
        data['format'] = 'future-version'
        with self.assertRaisesRegex(ValueError, 'format'):
            restore_checkpoint(data)

    def test_source_mismatch_is_not_silently_loaded(self):
        data = checkpoint(SocietyWorld())
        with patch('eternia.persistence.source_fingerprint', return_value='different-code'):
            with self.assertRaisesRegex(ValueError, 'source version'):
                restore_checkpoint(data)

    def test_custom_policies_do_not_silently_lose_state_or_overwrite_an_older_save(self):
        class UnknownPolicy:
            pass
        world = SocietyWorld()
        world.policies[0] = UnknownPolicy()
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / 'world.json'
            target.write_text('older save', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'Unsupported checkpoint type'):
                save_world(world, target)
            self.assertEqual(target.read_text(encoding='utf-8'), 'older save')
            self.assertEqual(list(Path(folder).glob('*.tmp')), [])

    def test_checkpoint_uses_json_and_restores_integer_keys_and_sets(self):
        world = SocietyWorld().run(1)
        with tempfile.TemporaryDirectory() as folder:
            target = save_world(world, Path(folder) / 'state.json')
            decoded = json.loads(target.read_text(encoding='utf-8'))
            self.assertEqual(decoded['format'], 'eternia.checkpoint.v1')
            restored = load_world(target)
        self.assertTrue(all(isinstance(i.members, set) for i in restored.institutions))
        self.assertTrue(all(type(key) is int for key in restored.last_action_year))
        self.assertEqual(restored.export(), world.export())

    def test_fault_during_time_advancement_rolls_back_rng_and_histories(self):
        world = SocietyWorld().run(1)
        before, rng = copy.deepcopy(world.export()), world.rng.getstate()
        advance = SocietyWorld.advance_time
        def fail(instance):
            advance(instance)
            raise RuntimeError('injected after environment update')
        with patch.object(SocietyWorld, 'advance_time', fail):
            with self.assertRaises(RuntimeError):
                world.step()
        self.assertEqual(world.export(), before)
        self.assertEqual(world.rng.getstate(), rng)

    def test_fresh_process_resume_produces_the_same_future_history(self):
        world = SocietyWorld(seed=73).run(1)
        with tempfile.TemporaryDirectory() as folder:
            target = save_world(world, Path(folder) / 'state.json')
            output = Path(folder) / 'resumed.json'
            script = ('import json,sys;from pathlib import Path;from eternia.persistence import load_world;'
                      'w=load_world(sys.argv[1]);w.run(1);'
                      'Path(sys.argv[2]).write_text(json.dumps(w.export(),allow_nan=False),encoding="utf-8")')
            subprocess.run([sys.executable, '-c', script, str(target), str(output)],
                           cwd=Path(__file__).resolve().parents[1], check=True, capture_output=True, text=True)
            world.run(1)
            self.assertEqual(json.loads(output.read_text(encoding='utf-8')),
                             json.loads(json.dumps(world.export())))

