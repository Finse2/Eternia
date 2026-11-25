"""v0.9 Stage 2: needs travel as knowledge, go out of date, and can be answered by more than one route.

A person knows what they need and cannot get themselves, and says so when asked
about work. Others pass it on by word of mouth, after any fresher news of
events, and keep the version they heard after it has been met. Besides working
a job, anyone with the goods may answer by offering them at a fair price: the
person takes up such an offer from anyone, a newcomer who cannot mine included.
"""
from copy import deepcopy
import json
import unittest
from unittest import mock

from eternia import interface
from eternia.needs import needs, opening
from eternia.playable_session import PlayableSession
from eternia.player import customize
from eternia.social_memory import LIMIT, firsthand, news_for, remember
from eternia.society import SocietyWorld
from v07_helpers import add_council

BUILDER, MINER, FARMER, MERCHANT, RESEARCHER = 3, 1, 0, 2, 4  # Rivermark residents


def no_iron_here(world):
    """Toren has the wood for a house and no iron, and Rivermark has none to mine or buy: it all lies in Highfen.

    Moving the iron is a transfer between towns, so nothing is created; no job
    can help, because nobody could gather iron here.
    """
    add_council(world, members=[FARMER, BUILDER])  # a minority council: no claim on town money
    builder, town, highfen = world.agents[BUILDER], world.settlements[0], world.settlements[1]
    town.wood -= 4
    builder.inventory['wood'] += 4
    highfen.iron += town.iron
    highfen.deposits['iron'] += town.deposits['iron']
    town.iron = town.deposits['iron'] = 0.
    world.reset_market_prices()
    return builder


def need_claims(world, holder, subject=BUILDER, resource='iron'):
    return [c for c in world.knowledge.get(holder, []) if c['kind'] == 'need'
            and c['subject'] == subject and c['facts']['resource'] == resource]


def with_iron(seed=42):
    """A newcomer who arrived with three iron, in the town where Toren needs it."""
    session = PlayableSession.start('Ilsa', 'Rivermark', seed=seed, inventory={'food': 3, 'coins': 10, 'iron': 3})
    return session, no_iron_here(session.world)


def offer_iron(session, text):
    choice = next(c for c in session.options() if c['proposal']['type'] == 'offer'
                  and c['proposal']['params']['direction'] == 'sell' and c['proposal']['params']['resource'] == 'iron')
    return session.act(customize(choice, text))


class KnowingANeedTests(unittest.TestCase):
    def test_a_person_knows_the_need_they_cannot_meet_and_says_so(self):
        world = SocietyWorld(seed=42)
        no_iron_here(world)
        world.step()
        (claim,) = need_claims(world, BUILDER)
        self.assertEqual({k: claim['facts'][k] for k in ('amount', 'step', 'price', 'wage')},
                         {'amount': 2, 'step': 'house', 'price': 6.0, 'wage': None})
        self.assertEqual((claim['source'], claim['hops'], claim['confidence']), (None, 0, 1.))
        session = PlayableSession(world)
        world.add_player('Ilsa', 'Rivermark')
        lines = session.talk(BUILDER, 'work')['lines']
        self.assertIn('"I need 2 iron for a house; I am ready to buy it at up to 6 a unit."', lines)

    def test_a_need_they_can_meet_themselves_is_not_a_need_to_tell(self):
        world = SocietyWorld(seed=42)
        add_council(world, members=[FARMER, BUILDER])
        world.settlements[0].wood -= 4
        world.agents[BUILDER].inventory['wood'] += 4  # the market still sells iron at a fair price
        world.step()
        self.assertEqual(need_claims(world, BUILDER), [])

    def test_how_much_is_said_depends_on_trust(self):
        session, builder = with_iron()
        session.act()
        me = session.player_id
        builder.trust[me] = .3  # someone he knows a little
        self.assertIn('"What I\'m short of is 2 iron for a house."', session.talk(BUILDER, 'themselves')['lines'])
        builder.trust[me] = -.4  # someone he distrusts hears no business from him
        self.assertFalse(any('I need' in line for line in session.talk(BUILDER, 'work')['lines']))


class WordOfMouthTests(unittest.TestCase):
    def test_a_need_passes_person_to_person_with_its_source(self):
        world = SocietyWorld(seed=42)
        no_iron_here(world)
        for _ in range(4):
            world.step()
        heard = {holder: claim for holder in world.knowledge for claim in need_claims(world, holder)
                 if holder != BUILDER}
        self.assertGreaterEqual(len(heard), 3)
        for holder, claim in heard.items():
            self.assertIsNotNone(claim['source'])
            self.assertGreater(claim['hops'], 0)
            self.assertLess(claim['confidence'], 1.)
            self.assertEqual(world._resolve_agent(holder).home, 0)  # nobody carried it to another town
        self.assertTrue(any(c['source'] == BUILDER for c in heard.values()))

    def test_news_of_events_comes_first_and_is_never_forgotten_for_a_need(self):
        world = SocietyWorld(seed=42)
        world.tick = 5
        firsthand(world, MINER, 'need', place=0, subject=MINER, facts=dict(resource='wood', amount=1, step='house',
                                                                          act='house wood'), stamp=5)
        firsthand(world, MINER, 'death', place=0, subject=99, facts=dict(cause='old age'), subject_name='Old Bram',
                  stamp=1)
        world.knowledge[MINER][-1]['observed'] = 1  # an older event still outranks a newer need
        self.assertEqual([c['kind'] for c in news_for(world, MINER, FARMER, limit=2)], ['death', 'need'])
        store = world.knowledge.setdefault(FARMER, [])
        for index in range(LIMIT):
            firsthand(world, FARMER, 'arrival', place=0, subject=100 + index, subject_name=f'Settler {index}',
                      stamp=index)
        events = deepcopy(store)
        need = deepcopy(world.knowledge[MINER][0])
        self.assertFalse(remember(world, FARMER, need))  # no room: the need goes, not the news
        self.assertEqual(world.knowledge[FARMER], events)

    def test_knowing_who_needs_what_changes_nothing_else_in_a_society_nobody_plays(self):
        def history(world):
            data = world.export()
            data.pop('provenance', None)
            data.pop('knowledge', None)
            return json.dumps(data, sort_keys=True)

        def events_known(world):
            return {holder: sorted(json.dumps(c, sort_keys=True) for c in store if c['kind'] != 'need')
                    for holder, store in world.knowledge.items()}

        told = SocietyWorld(seed=42).run(6)
        with mock.patch('eternia.society.unmet', return_value={}):
            silent = SocietyWorld(seed=42).run(6)
        self.assertGreater(sum(c['kind'] == 'need' for s in told.knowledge.values() for c in s), 0)
        self.assertEqual(history(told), history(silent))
        self.assertEqual(events_known(told), events_known(silent))


class OutOfDateTests(unittest.TestCase):
    def test_what_others_heard_outlives_the_need(self):
        session, builder = with_iron()
        world = session.world
        for _ in range(4):
            session.act()
        mara = next(p['id'] for p in session.partners() if p['name'].startswith('Mara'))
        self.assertTrue(need_claims(world, mara))
        offer_iron(session, '3 5.5')
        for _ in range(4):
            session.act()
        self.assertEqual(builder.inventory['iron'], 2)  # he bought what he lacked
        self.assertEqual(need_claims(world, BUILDER), [])  # and knows he needs it no longer
        (stale,) = need_claims(world, mara)
        self.assertLess(stale['observed'], world.tick - 3)
        said = session.talk(mara, 'work')['lines']
        self.assertTrue(any('Toren of Rivermark needs 2 iron for a house' in line and 'ago' in line for line in said))
        self.assertFalse(any('I need' in line for line in session.talk(BUILDER, 'work')['lines']))


class AnotherRouteTests(unittest.TestCase):
    def test_a_newcomer_who_cannot_mine_answers_by_trade_and_both_lives_change(self):
        session, builder = with_iron()
        world = session.world
        session.act()
        self.assertNotIn('mining', session.person.skills)
        heard = session.talk(BUILDER, 'work')
        self.assertTrue(heard['learned'])  # asking about work told the player of his need
        seen = next(o for o in interface.state(session)['opportunities'] if o['kind'] == 'need' and o['who'] == builder.name)
        self.assertEqual((seen['resource'], seen['amount'], seen['unit_price'], seen['needs']), ('iron', 2, 6.0, []))
        coins = session.person.inventory['coins']
        offer_iron(session, '3 5.5')
        for _ in range(4):
            session.act()
        sold = [r for r in world.action_log if r['action']['type'] == 'accept' and r['result']['success']]
        buyers = {world._resolve_agent(r['action']['actor']).name: r['result']['effects']['amount'] for r in sold}
        self.assertEqual(buyers, {'Toren of Rivermark': 2, 'Lyra of Rivermark': 1})  # two people with the same need
        self.assertAlmostEqual(session.person.inventory['coins'], coins + 3 * 5.5)
        for _ in range(4):
            if builder.structures.get('house'):
                break
            session.act()
        self.assertEqual(builder.structures.get('house'), 1)  # the house the iron was for

    def test_the_same_offer_from_anyone_is_taken(self):
        world = SocietyWorld(seed=42)
        builder = no_iron_here(world)
        merchant, highfen = world.agents[MERCHANT], world.settlements[1]
        highfen.iron -= 3  # carried over from Highfen: a transfer
        merchant.inventory['iron'] += 3
        result = world.submit_action(dict(actor=MERCHANT, type='offer', resource='iron', amount=3,
                                          unit_price=5.8, direction='sell'))
        self.assertTrue(result.success, result.message)
        world.advance_time()  # posted in the last cycle: open to anyone from this one, as in play
        for _ in range(3):
            world.step()
        sold = {world._resolve_agent(r['action']['actor']).name: r['result']['effects']['amount']
                for r in world.action_log if r['action']['type'] == 'accept' and r['result']['success']}
        self.assertEqual(sold, {'Toren of Rivermark': 2, 'Lyra of Rivermark': 1})  # the same buyers as for a player
        self.assertEqual(builder.structures.get('house'), 1)  # and the iron went into the house

    def test_an_unfair_or_unneeded_offer_is_not_taken_up(self):
        world = SocietyWorld(seed=42)
        builder = no_iron_here(world)
        merchant, highfen = world.agents[MERCHANT], world.settlements[1]
        highfen.iron -= 4
        merchant.inventory['iron'] += 4
        world.submit_action(dict(actor=MERCHANT, type='offer', resource='iron', amount=2, unit_price=6.5,
                                 direction='sell'))  # above the 6 he thinks fair
        world.advance_time()
        (need,) = needs(world.observe(BUILDER))
        self.assertIsNone(need['offer'])
        self.assertNotEqual((opening(world.observe(BUILDER)) or {}).get('route'), 'accept')
        builder.inventory['iron'] += 2  # met another way (a transfer from the merchant)
        merchant.inventory['iron'] -= 2
        self.assertEqual(needs(world.observe(BUILDER)), [])  # nothing left to buy for the house


class PlayerViewTests(unittest.TestCase):
    def test_heard_needs_show_who_said_so_when_and_what_answering_takes(self):
        session = PlayableSession.start('Ilsa', 'Rivermark', seed=42)
        no_iron_here(session.world)
        session.act()
        session.talk(BUILDER, 'work')
        (seen,) = [o for o in interface.state(session)['opportunities'] if o['kind'] == 'need'
                   and o['who'] == 'Toren of Rivermark' and o['resource'] == 'iron']
        self.assertEqual((seen['purpose'], seen['here'], seen['needs']), ('for a house', True, ['iron to offer']))
        self.assertIn('Toren of Rivermark told me', seen['heard'])
        self.assertTrue(any('Toren of Rivermark needs 2 iron for a house' in h['text']
                            for h in session.journal()['heard']))


if __name__ == '__main__':
    unittest.main()
