"""v0.9 Stage 4: measuring what becomes of needs, following through, willingness to pay, and speed.

The world keeps a historian's record of what stood between people and the goods
their goals lacked, and of what became of every need; keeping it changes no
decision. Someone who gathered or fetched goods for a need holds to it until
they offer them. Where the world allows it, a goal that stays blocked raises
what its holder will pay. Long histories cost less to run, and nothing in them
changes.
"""
from copy import deepcopy
import hashlib
import json
import unittest
from unittest import mock

from eternia import society
from eternia.needs import FAIR_LIMIT, FOLLOW_THROUGH, STALE, WILLING_LIMIT, needs, prospects, unmet, willingness
from eternia.opportunity_experiments import run_opportunity_experiments
from eternia.society import SocietyWorld
from test_consequences import heard, judged, toren_needs_iron
from test_discovery import BUILDER, MERCHANT, no_iron_here


def digest(world):
    data = world.export()
    data.pop('provenance', None)
    text = json.dumps(data, sort_keys=True, default=str) + json.dumps(world.knowledge, sort_keys=True, default=str)
    return hashlib.sha256(text.encode()).hexdigest()


class MeasurementTests(unittest.TestCase):
    def test_keeping_the_record_changes_nothing(self):
        recorded = SocietyWorld(seed=73).run(8)
        with mock.patch.object(society, 'prospects', lambda observation: None), \
                mock.patch.object(SocietyWorld, '_record_needs', lambda self, *args: None):
            unrecorded = SocietyWorld(seed=73).run(8)  # each person judges for themselves instead
        self.assertEqual(digest(recorded), digest(unrecorded))
        self.assertEqual(len(recorded.opportunity_log), 32)
        self.assertEqual(unrecorded.opportunity_log, [])

    def test_a_need_is_followed_from_when_it_arises_to_how_it_ends(self):
        world = SocietyWorld(seed=42)
        toren_needs_iron(world)
        for _ in range(10):
            world.step()
        (episode,) = [e for e in world.need_episodes if e['person'] == BUILDER and e['resource'] == 'iron']
        self.assertEqual((episode['step'], episode['began'], episode['ended'], episode['outcome']),
                         ('house', 0, 6, 'offered'))  # until Mara's offer for it was there to take up
        self.assertEqual(episode['ended'] - episode['began'], episode['cycles'])
        self.assertEqual(episode['empty_market'], episode['cycles'])  # Rivermark had no iron to sell him
        self.assertGreater(episode['held_nearby'], 0)  # while Mara held iron she could spare

    def test_each_cycle_records_what_blocked_needs_and_how_people_judged_them(self):
        world = SocietyWorld(seed=42)
        toren_needs_iron(world, market_can_pay=True)
        for _ in range(4):
            world.step()
        rows = world.opportunity_log
        self.assertEqual([r['tick'] for r in rows], [0, 1, 2, 3])
        for row in rows:
            self.assertLessEqual(row['priced_out'] + row['unaffordable'] + row['empty_market'], row['needs'])
        judgments = {}
        for row in rows:
            for key, count in row['judgments'].items():
                judgments[key] = judgments.get(key, 0) + count
        self.assertIn('market_pays_more', judgments)  # the market here pays more than the 6 he would

    def test_the_experiment_compares_fixed_and_rising_willingness_in_matched_worlds(self):
        data = run_opportunity_experiments(seeds=[42], years=2)
        self.assertEqual([c['rising_willingness'] for c in data['cases']], [False, True])
        for case in data['cases']:
            self.assertEqual(set(case['blockers']), {'need_cycles', 'priced_out', 'unaffordable', 'empty_market',
                                                     'held_nearby', 'mean_price_ratio', 'judgments'})
            self.assertEqual(sum(case['needs']['outcomes'].values()), case['needs']['needs'])
        with self.assertRaises(ValueError):
            run_opportunity_experiments(seeds=[42, 42])


class FollowThroughTests(unittest.TestCase):
    def test_a_merchant_who_gathered_food_for_a_neighbor_offers_it_next(self):
        world = SocietyWorld(seed=73)
        for _ in range(44):
            world.step()
        mara = next(a for a in world.agents if a.name == 'Mara of Deepwood')
        lyra = next(a for a in world.agents if a.name == 'Lyra of Deepwood')
        world.step()
        (gathered,) = [r for r in world.action_log if r['tick'] == 44 and r['action'].get('actor') == mara.id]
        self.assertEqual(gathered['action']['params']['purpose']['subject'], lyra.id)
        for _ in range(2):
            world.step()
        (offered,) = [r for r in world.action_log if r['tick'] == 46 and r['action'].get('actor') == mara.id]
        self.assertEqual((offered['action']['type'], offered['action']['params']['purpose']['subject']),
                         ('offer', lyra.id))
        (why,) = [d['rationale'] for d in world.decisions if d['tick'] == 46 and d['actor'] == mara.id]
        self.assertIn('I got it for them', why)

    def test_having_acted_on_news_keeps_it_current_for_a_while(self):
        world = SocietyWorld(seed=42)
        toren_needs_iron(world)
        world.step()
        claim = heard(world, MERCHANT)
        merchant = world.agents[MERCHANT]
        claim['observed'] = world.tick - STALE - 1
        self.assertEqual(judged(world.observe(MERCHANT))['reason'], 'the news is too old to act on')
        merchant.memory.append(dict(year=world.year, tick=world.tick - 1, action=dict(
            actor=MERCHANT, type='gather', location=0,
            params=dict(resource='iron', amount=2, purpose=dict(kind='need', subject=BUILDER, step='house'))),
            result=dict(success=True, code='ok', message='', effects=dict(resource='iron', amount=2))))
        chance = judged(world.observe(MERCHANT))
        self.assertTrue(chance['committed'])
        self.assertEqual(chance['route'], 'offer')
        world.tick += FOLLOW_THROUGH + 1  # long after
        self.assertEqual(judged(world.observe(MERCHANT))['reason'], 'the news is too old to act on')


class WillingnessTests(unittest.TestCase):
    def test_a_fair_price_unless_the_world_lets_a_stalled_goal_raise_it(self):
        world = SocietyWorld(seed=42)
        no_iron_here(world)
        observation = world.observe(BUILDER)
        observation['actor']['mind']['best_tick'] = observation['tick'] - 5  # five cycles without progress
        self.assertEqual(willingness(observation, 'iron'), FAIR_LIMIT * 4)
        observation['rules']['rising_willingness'] = True
        self.assertEqual(willingness(observation, 'iron'), 9.)  # 6, half as much again after five cycles
        observation['actor']['mind']['best_tick'] = observation['tick'] - 40
        self.assertEqual(willingness(observation, 'iron'), FAIR_LIMIT * 4 * WILLING_LIMIT)  # never past 12
        observation['actor']['mind']['best_tick'] = observation['tick']
        self.assertEqual(willingness(observation, 'iron'), 6.)

    def test_rising_willingness_reaches_what_a_person_says_and_buys(self):
        world = SocietyWorld(seed=42, rising_willingness=True)
        no_iron_here(world)
        world.step()
        builder = world.agents[BUILDER]
        world.minds[BUILDER]['best_tick'] = world.tick - 4
        observation = world.observe(BUILDER)
        self.assertTrue(observation['rules']['rising_willingness'])
        (need,) = needs(observation)
        self.assertEqual(need['fair'], 8.4)  # 6, two fifths more
        held = observation['actor']['available_inventory']
        reserve = held['coins'] - need['spare']  # the house's own coins and a few meals
        held['coins'] = reserve + 20.
        (stated,) = unmet(observation).values()
        self.assertEqual(stated['price'], 8.4)
        held['coins'] = reserve + 7.
        (stated,) = unmet(observation).values()
        self.assertEqual(stated['price'], 7.)  # as much of it as he can pay
        held['coins'] = reserve + 5.
        self.assertIsNone(next(iter(unmet(observation).values()))['price'])  # not even a fair price
        self.assertEqual(builder.id, BUILDER)
        with self.assertRaises(ValueError):
            SocietyWorld(seed=42, rising_willingness='yes')


class SpeedTests(unittest.TestCase):
    def test_recent_events_are_the_last_twelve_seen_here_as_before(self):
        world = SocietyWorld(seed=18).run(6)
        for person in world.agents[:6]:
            town = next(s for s in world.settlements if s.id == person.home)
            expected = [e for e in world.events if e['settlement'] in (None, town.name)][-12:]
            self.assertEqual(world.observe(person.id)['recent_events'], expected)

    def test_a_policy_that_changes_its_view_changes_nothing_in_the_world(self):
        class Meddler:
            reason = 'Meddles with what it sees.'

            def propose(self, observation):
                observation['actor']['inventory']['coins'] = 10 ** 6
                observation['settlement']['food'] = -5
                observation['recent_events'].clear()
                return {'actor': observation['actor']['id'], 'type': 'rest', 'params': {}}

        world = SocietyWorld(seed=42, policies={MERCHANT: Meddler()})
        coins, food, events = world.agents[MERCHANT].inventory['coins'], world.settlements[0].food, len(world.events)
        world.step()
        self.assertLess(world.agents[MERCHANT].inventory['coins'], coins + 100)
        self.assertGreaterEqual(world.settlements[0].food, 0)
        self.assertGreaterEqual(len(world.events), events)


if __name__ == '__main__':
    unittest.main()
