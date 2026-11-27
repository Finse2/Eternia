"""v0.9 Stage 3: people act on what they hear, and what they do has consequences.

A person who hears that a neighbor needs something judges it as a chance, from
their own knowledge alone: whether they can spare or gather the goods, whether
the price the neighbor said beats what the market would pay, how much they
trust them, and how old and how sure the news is. When it is worth it they offer
the goods by the ordinary rules, at the price the neighbor said; when it is not,
they decline, and say why. A sale that meets a need is something both people
saw, and word of it travels; an offer nobody it was for took up becomes word
that the need may be over. Nothing is awarded: every effect comes from a trade
that happened, or from hearing of one.
"""
from copy import deepcopy
import json
import tempfile
import unittest
from unittest import mock
from pathlib import Path

from eternia import interface
from eternia.evaluation import consequence_record
from eternia.market import bid_price
from eternia.needs import STALE, kindness, needs, prospects, step_of
from eternia.persistence import checkpoint, restore_checkpoint
from eternia.playable_session import PlayableSession
from eternia.player import customize
from eternia.social_memory import HEARSAY_TRUST, VALENCE, relay
from eternia.society import SocietyWorld
from test_discovery import BUILDER, MERCHANT, MINER, RESEARCHER, no_iron_here, need_claims, with_iron

COUNCILLOR = 5  # Aldren, Rivermark's sixth resident


def toren_needs_iron(world, market_can_pay=False):
    """Toren lacks only the iron for a house, and Rivermark has none to mine or buy; Mara has some to spare.

    Iron and coins move between towns, so nothing is created. Lyra is given the
    iron for her next experiment, so Toren is the one who needs iron. Unless the
    market can pay, Rivermark's treasury goes to Highfen: the market there has no
    coins to buy iron from anyone, so selling it to Toren is the only sale to be had.
    """
    builder = no_iron_here(world)
    town, highfen = world.settlements[0], world.settlements[1]
    highfen.iron -= 4
    world.agents[MERCHANT].inventory['iron'] += 3
    world.agents[RESEARCHER].inventory['iron'] += 1
    if not market_can_pay:
        highfen.treasury += town.treasury
        town.treasury = 0.
    return builder


def done(world, kind, actor=None, **params):
    return [r for r in world.action_log if r['action']['type'] == kind and r['result']['success']
            and (actor is None or r['action']['actor'] == actor)
            and all(r['action']['params'].get(k) == v for k, v in params.items())]


def answers(world, actor=None, subject=BUILDER):
    return [r for r in done(world, 'offer', actor) if (r['action']['params'].get('purpose') or {}).get('subject') == subject]


def supplied(world, holder):
    return [c for c in world.knowledge.get(holder, []) if c['kind'] == 'conduct' and c['facts'].get('act') == 'supplied']


def judged(observation, subject=BUILDER, resource='iron'):
    return next((p for p in prospects(observation) if p['subject'] == subject and p['resource'] == resource), None)


def heard(world, holder, subject=BUILDER, teller=BUILDER):
    """The holder hears of the subject's need from someone who knows it, as in conversation."""
    (claim,) = need_claims(world, teller, subject)
    relay(world, teller, holder, claim)
    return need_claims(world, holder, subject)[0]


def history(world):
    data = world.export()
    data.pop('provenance', None)
    return json.dumps(data, sort_keys=True)


def after_the_supply(cycles=9):
    world = SocietyWorld(seed=42)
    builder = toren_needs_iron(world)
    for _ in range(cycles):
        world.step()
    return world, builder


class AutonomousResponseTests(unittest.TestCase):
    def test_with_nobody_playing_a_merchant_hears_of_a_need_meets_it_and_a_house_goes_up(self):
        world = SocietyWorld(seed=42)
        builder = toren_needs_iron(world)
        merchant = world.agents[MERCHANT]
        self.assertFalse(world.active_players())
        coins, trust = merchant.inventory['coins'], builder.trust.get(MERCHANT, 0.)
        for _ in range(9):
            world.step()
        (offer,) = answers(world, MERCHANT)
        params = offer['action']['params']
        self.assertEqual((params['resource'], params['amount'], params['unit_price'], params['direction']),
                         ('iron', 2, 6.0, 'sell'))  # what he lacked, at the price he said he would pay
        self.assertEqual(params['purpose'], {'kind': 'need', 'subject': BUILDER, 'step': 'house'})
        (why,) = [d['rationale'] for d in world.decisions if d['tick'] == offer['tick'] and d['actor'] == MERCHANT]
        self.assertIn('told me they need it', why)  # she heard it from someone, not from the world
        self.assertIn('the market here cannot pay for it', why)
        (bought,) = done(world, 'accept', BUILDER, offer_id=offer['result']['effects']['offer_id'])
        self.assertEqual((bought['result']['effects']['amount'], bought['result']['effects']['coins']), (2, 12.))
        self.assertGreater(bought['tick'], offer['tick'])  # taken up by the ordinary rules, in a later cycle
        (house,) = done(world, 'build', BUILDER, structure='house')
        self.assertGreater(house['tick'], bought['tick'])
        self.assertEqual(builder.structures.get('house'), 1)  # the house the iron was for
        self.assertGreater(merchant.inventory['coins'], coins)
        self.assertGreater(builder.trust[MERCHANT], trust)  # he thinks better of her
        for holder in (MERCHANT, BUILDER):
            (seen,) = [c for c in supplied(world, holder) if c['facts']['buyer'] == BUILDER]
            self.assertEqual((seen['subject'], seen['facts']['amount'], seen['facts']['step'], seen['source']),
                             (MERCHANT, 2, 'house', None))
        self.assertEqual(need_claims(world, MERCHANT), [])  # she knows his need is met and offers no more
        event = next(e for e in world.events if e.get('seller') == MERCHANT and e.get('buyer') == BUILDER)
        self.assertEqual(event['message'], 'Mara of Rivermark supplied Toren of Rivermark with 2 iron for a house.')

    def test_the_record_counts_answers_supplies_lapses_and_steps_taken(self):
        world, _ = after_the_supply(cycles=14)
        record = consequence_record(world)
        summary = record['summary']
        mine = next(a for a in record['answers'] if a['by'] == 'Mara of Rivermark')
        self.assertEqual((mine['to'], mine['outcome'], mine['supplied'], mine['route']),
                         ('Toren of Rivermark', 'supplied', 2, 'offer'))
        self.assertIsNotNone(mine['step_taken'])
        self.assertGreaterEqual(summary['supplied'], 1)
        self.assertGreaterEqual(summary['lapsed'], 1)  # someone answered a need already met
        self.assertEqual(summary['answers'], summary['offers'] + summary['gathered'])
        self.assertEqual(summary['offers'], summary['supplied'] + summary['sold_to_others'] + summary['lapsed']
                         + summary['open'])
        self.assertGreater(summary['supplies_heard'], 0)  # word of it reached people who were not party to it

    def test_the_sale_conserves_goods_and_coins(self):
        world = SocietyWorld(seed=42)
        toren_needs_iron(world)
        sales = 0
        for _ in range(9):
            before = deepcopy({a.id: dict(a.inventory) for a in world.agents})
            tick = world.tick
            world.step()
            for record in done(world, 'accept'):
                if record['tick'] != tick or not (record['result']['effects'].get('purpose') or {}):
                    continue
                sales += 1
                effects = record['result']['effects']
                self.assertAlmostEqual(effects['coins'], effects['amount'] * effects['unit_price'])
                buyer = world._resolve_agent(effects['buyer'])
                # The buyer's one action this cycle was the purchase: the goods came in, the coins went out.
                self.assertEqual(buyer.inventory['iron'] - before[buyer.id]['iron'], effects['amount'])
                self.assertLessEqual(buyer.inventory['coins'], before[buyer.id]['coins'] - effects['coins'] + 1e-9)
            world._assert_invariants()  # every unit in the world is accounted for, cycle by cycle
        self.assertGreater(sales, 0)


class RationalRefusalTests(unittest.TestCase):
    def test_the_same_merchant_declines_while_the_market_pays_more_than_the_buyer(self):
        world = SocietyWorld(seed=42)
        toren_needs_iron(world, market_can_pay=True)
        refused = 0
        for _ in range(6):
            observation = world.observe(MERCHANT)
            chance = judged(observation)
            town = observation['settlement']
            bid = bid_price(observation['prices']['posted'][0]['iron'])
            tick = world.tick
            world.step()
            offered = [r for r in answers(world, MERCHANT) if r['tick'] == tick]
            if chance and chance['price'] is not None and town['treasury'] >= bid > chance['price']:
                refused += 1
                self.assertIsNone(chance['route'])
                self.assertEqual(chance['reason'], f'the market pays {bid:g} for iron, more than the 6 they would pay')
                self.assertEqual(offered, [])
        self.assertGreater(refused, 0)

    def test_old_or_corrected_news_is_not_acted_on(self):
        world = SocietyWorld(seed=42)
        toren_needs_iron(world)
        world.step()
        claim = heard(world, MERCHANT)
        self.assertEqual(judged(world.observe(MERCHANT))['route'], 'offer')
        claim['observed'] = world.tick - STALE - 1
        self.assertEqual(judged(world.observe(MERCHANT))['reason'], 'the news is too old to act on')
        claim['observed'] = world.tick
        claim['facts'] = dict(claim['facts'], gone=True)
        self.assertEqual(judged(world.observe(MERCHANT))['reason'],
                         'they did not take up an offer; they may no longer need it')

    def test_no_price_no_trust_or_no_goods_to_spare_is_a_reason_to_decline(self):
        world = SocietyWorld(seed=42)
        toren_needs_iron(world)
        world.step()
        claim = heard(world, MERCHANT)
        merchant = world.agents[MERCHANT]
        merchant.trust[BUILDER] = -.4
        self.assertEqual(judged(world.observe(MERCHANT))['reason'], 'I do not trust them')
        merchant.trust[BUILDER] = 0.
        price = claim['facts']['price']
        claim['facts'] = dict(claim['facts'], price=None)
        self.assertEqual(judged(world.observe(MERCHANT))['reason'], 'they said nothing they could pay')
        claim['facts'] = dict(claim['facts'], price=price)
        researcher = world.agents[RESEARCHER]
        heard(world, RESEARCHER)
        if researcher.inventory['iron'] < 1:  # she used hers; another unit comes over from Highfen
            world.settlements[1].iron -= 1
            researcher.inventory['iron'] += 1
        observation = world.observe(RESEARCHER)
        self.assertEqual(step_of(observation)['materials']['iron'], 1)  # she holds iron, but for her next experiment
        self.assertEqual(judged(observation)['reason'], 'I have no iron to spare and cannot gather it here')

    def test_a_trusted_neighbor_gets_goods_below_what_the_market_would_pay_within_a_limit(self):
        world = SocietyWorld(seed=42)
        toren_needs_iron(world, market_can_pay=True)
        world.step()
        heard(world, MERCHANT)
        observation = world.observe(MERCHANT)
        observation['actor']['mind']['motivations']['belonging'] = .4  # kindness from trust alone
        observation['prices']['posted'][0]['iron'] = 9.38  # the market would pay 7.5 a unit
        observation['settlement']['treasury'] = 100.
        observation['actor']['trust'][BUILDER] = 0.
        self.assertEqual(judged(observation)['reason'], 'the market pays 7.5 for iron, more than the 6 they would pay')
        observation['actor']['trust'][BUILDER] = .75  # 30% below the market is the most anyone goes
        self.assertEqual(kindness(observation['actor'], BUILDER), .3)
        chance = judged(observation)
        self.assertEqual((chance['route'], chance['market'], chance['kindness']), ('offer', 7.5, .3))
        self.assertLess(chance['gain'], 0)  # a sacrifice, knowingly made
        observation['prices']['posted'][0]['iron'] = 11.  # 8.8: more than 30% above what he would pay
        self.assertIn('more than the 6', judged(observation)['reason'])

    def test_a_miner_with_ore_at_hand_would_gather_it_for_the_need(self):
        world = SocietyWorld(seed=42)
        toren_needs_iron(world)
        world.step()
        heard(world, MINER)
        observation = world.observe(MINER)
        observation['actor']['available_inventory']['iron'] = 0.
        observation['settlement']['deposits']['iron'] = 10.
        chance = judged(observation)
        self.assertEqual((chance['route'], chance['units']), ('gather', 2))


def iron_only_in_highfen(world, food=60.):
    """Toren and Lyra need iron, nobody in Rivermark holds any, and its market cannot buy it.

    Everyone's iron goes to Highfen's market, and some of Rivermark's spare food
    too, so provisions for the road from there are not dear. All are transfers.
    """
    builder = toren_needs_iron(world)
    highfen = world.settlements[1]
    for person in world.agents:
        if person.home == 0:
            highfen.iron += person.inventory['iron']
            person.inventory['iron'] = 0.
    world.settlements[0].food -= food
    highfen.food += food
    world.reset_market_prices()
    return builder


def procured(world, actor=None):
    return [r for r in done(world, 'procure', actor)]


class FetchingTests(unittest.TestCase):
    def test_a_merchant_buys_iron_in_another_town_for_needs_heard_of_and_sells_it_to_the_one_in_need(self):
        world = SocietyWorld(seed=42)
        iron_only_in_highfen(world)
        merchant = world.agents[MERCHANT]
        for _ in range(19):
            world.step()
        (bought,) = procured(world, MERCHANT)
        params, effects = bought['action']['params'], bought['result']['effects']
        self.assertEqual((params['resource'], params['amount'], params['source'], params['purpose']),
                         ('iron', 3, 1, {'kind': 'need', 'subject': BUILDER, 'step': 'house'}))  # for Toren and Lyra
        self.assertEqual((bought['tick'], effects['unit_price'], effects['coins']), (5, 1.35, 8.1))
        (why,) = [d['rationale'] for d in world.decisions if d['tick'] == bought['tick'] and d['actor'] == MERCHANT]
        self.assertEqual(why, 'Buy 3 iron in Highfen at 1.35 each and have it carried here to meet Toren of Rivermark\'s '
                              'need for a house, at the 6 a unit they would pay; Toren of Rivermark told me they need '
                              'it. With provisions it costs 8.1 coins, and after the 8% risk on the road it should '
                              'earn about 3.52 more.')
        (arrived,) = [m for m in merchant.memory if m.get('kind') == 'procurement']
        self.assertEqual((arrived['tick'], arrived['outcome']), (9, 'delivered'))
        (sold,) = done(world, 'accept', BUILDER)
        self.assertEqual((sold['result']['effects']['seller'], sold['result']['effects']['unit_price']), (MERCHANT, 6.))
        record = consequence_record(world)
        fetched = next(a for a in record['answers'] if a['route'] == 'procure')
        self.assertEqual((fetched['arrival'], fetched['outcome'], fetched['cost']), ('arrived', 'supplied', 8.1))
        self.assertEqual(record['summary']['fetched_supplied'], 1)

    def test_buying_elsewhere_moves_goods_and_coins_and_creates_nothing(self):
        world = SocietyWorld(seed=42)
        iron_only_in_highfen(world)
        merchant, highfen = world.agents[MERCHANT], world.settlements[1]
        totals, coins, iron = world.resource_totals(), merchant.inventory['coins'], highfen.iron
        result = world.submit_action(dict(actor=MERCHANT, type='procure', resource='iron', amount=2, source=1))
        self.assertTrue(result.success, result.message)
        cost = result.effects['coins']
        (journey,) = [j for j in world.journeys if j.get('procurement')]
        self.assertAlmostEqual(cost, 2 * result.effects['unit_price'] + journey['supplies']
                               * world.market_prices[1]['food'])
        self.assertAlmostEqual(merchant.inventory['coins'], coins - cost)
        self.assertEqual(highfen.iron, iron - 2)
        self.assertEqual(journey['cargo'], {'iron': 2.})
        for resource, total in world.resource_totals().items():
            self.assertAlmostEqual(total, totals[resource])  # in transit, still counted
        self.assertEqual(world.observe(MERCHANT)['actor']['incoming'][0]['cargo'], {'iron': 2.})
        for _ in range(8):
            if journey['status'] != 'in_transit':
                break
            world.advance_time()
        self.assertEqual(journey['status'], 'delivered')
        self.assertEqual(merchant.inventory['iron'], 2.)  # to the buyer, not the town's market
        self.assertEqual(world._incoming(0, 'iron'), 0.)
        world._assert_invariants()

    def test_goods_lost_on_the_road_are_the_buyers_loss_and_make_that_road_dearer(self):
        world = SocietyWorld(seed=42)
        iron_only_in_highfen(world)
        for _ in range(5):
            world.step()
        observation = world.observe(MERCHANT)
        self.assertEqual(judged(observation)['route'], 'fetch')
        merchant = world.agents[MERCHANT]
        result = world.submit_action(dict(actor=MERCHANT, type='procure', resource='iron', amount=3, source=1))
        coins = merchant.inventory['coins']
        with mock.patch.object(world.rng, 'random', return_value=0.):  # an accident on the first stretch
            world.advance_time()
        (journey,) = [j for j in world.journeys if j.get('procurement')]
        self.assertEqual(journey['status'], 'failed')
        self.assertEqual((merchant.inventory['iron'], merchant.inventory['coins']), (0., coins))  # paid, and gone
        (lost,) = [m for m in merchant.memory if m.get('kind') == 'procurement']
        self.assertEqual((lost['outcome'], lost['gain'], lost['source']), ('lost', -result.effects['coins'], 1))
        world._assert_invariants()
        observation['actor']['memory'] = world.observe(MERCHANT)['actor']['memory']
        observation['tick'] = world.tick
        chance = judged(observation)
        self.assertIsNone(chance['route'])  # the same chance, three times the margin after the loss
        self.assertTrue(chance['reason'].endswith('and bringing it from another town would not pay'))

    def test_only_a_merchant_fetches_for_others_and_not_while_short_of_the_same_goods(self):
        world = SocietyWorld(seed=42)
        iron_only_in_highfen(world)
        for _ in range(5):
            world.step()
        observation = world.observe(MERCHANT)
        self.assertEqual(judged(observation)['route'], 'fetch')
        miner = deepcopy(observation)
        miner['actor'].update(role='miner', goal={'kind': 'wealth', 'target': 60})  # the same chance, not a merchant
        self.assertEqual(judged(miner)['reason'], 'I have no iron to spare and cannot gather it here')
        observation['actor']['goal'] = {'kind': 'houses', 'target': 1}  # her own next step would need iron
        observation['actor']['skills'] = [s for s in observation['actor']['skills'] if s != 'carpentry']
        self.assertEqual(judged(observation)['reason'], 'I need iron myself first')

    def test_one_small_need_does_not_pay_for_the_road_but_two_do(self):
        world = SocietyWorld(seed=42)
        iron_only_in_highfen(world)
        for _ in range(5):
            world.step()
        observation = world.observe(MERCHANT)
        both = [p for p in prospects(observation) if p['route'] == 'fetch']
        self.assertEqual(sorted(p['name'] for p in both), ['Lyra of Rivermark', 'Toren of Rivermark'])
        self.assertEqual(both[0]['fetch']['units'], 3)  # one caravan for both
        observation['actor']['claims'] = [c for c in observation['actor']['claims']
                                          if not (c['kind'] == 'need' and c['subject'] == BUILDER)]
        alone = judged(observation, RESEARCHER)
        self.assertIsNone(alone['route'])  # 1 iron, heard third hand, does not pay for the road's provisions
        self.assertEqual(alone['reason'], 'I have no iron to spare and cannot gather it here, '
                                          'and bringing it from another town would not pay')

    def test_after_offers_to_someone_go_untaken_the_seller_doubts_what_they_say_they_need(self):
        world = SocietyWorld(seed=42)
        toren_needs_iron(world)
        world.step()
        claim = heard(world, MERCHANT)
        before = judged(world.observe(MERCHANT))
        old = dict(deepcopy(claim), key=['need', 0, BUILDER, 'house iron', -1], origin=MERCHANT, source=None,
                   observed=claim['observed'] - 1, facts=dict(claim['facts'], gone=True, offered=2))
        world.knowledge[MERCHANT].append(old)  # an earlier offer of hers he never took up
        after = judged(world.observe(MERCHANT))
        self.assertEqual((after['doubt'], after['confidence']), (1, round(before['confidence'] / 2, 4)))
        self.assertLess(after['expected'], before['expected'])

    def test_a_player_can_buy_in_another_town_and_the_journal_accounts_for_it(self):
        session = PlayableSession.start('Ilsa', 'Rivermark', seed=42)
        (choice,) = [c for c in session.options() if c['proposal']['type'] == 'procure'
                     and c['proposal']['params']['resource'] == 'iron' and c['proposal']['params']['source'] == 1]
        self.assertTrue(choice['label'].startswith('Buy 2 iron in Highfen at '))
        session.act(customize(choice, ''))
        for _ in range(6):
            if session.person.inventory['iron'] >= 2:
                break
            session.act()
        self.assertEqual(session.person.inventory['iron'], 2.)
        entries = session.journal()
        self.assertEqual(entries['coins']['unexplained'], 0)
        texts = [t['text'] for t in entries['transactions']]
        self.assertTrue(any(t.startswith('Bought 2 iron at the Highfen market') for t in texts))
        self.assertIn('2 iron bought in Highfen arrived', texts)


class ConsequenceTests(unittest.TestCase):
    def test_word_of_the_supply_travels_and_moves_what_people_think_of_the_seller(self):
        world, _ = after_the_supply(cycles=14)
        told = {holder: c for holder in world.knowledge for c in supplied(world, holder)
                if c['subject'] == MERCHANT and c['facts']['buyer'] == BUILDER and c['source'] is not None}
        self.assertTrue(told)
        for holder, claim in told.items():
            self.assertNotIn(holder, (MERCHANT, BUILDER))
            self.assertLess(claim['confidence'], 1.)
        # Someone who has not heard yet thinks better of Mara on hearing it, by the rule for any conduct.
        (own,) = [c for c in supplied(world, BUILDER) if c['source'] is None and c['subject'] == MERCHANT]
        hearer = next(a for a in world.agents if a.id not in told and a.id not in (MERCHANT, BUILDER)
                      and not any(c['key'] == own['key'] for c in world.knowledge.get(a.id, [])))
        before = hearer.trust.get(MERCHANT, 0.)
        self.assertTrue(relay(world, BUILDER, hearer.id, own))
        (news,) = [c for c in supplied(world, hearer.id) if c['key'] == own['key']]
        self.assertAlmostEqual(hearer.trust[MERCHANT] - before, VALENCE['supplied'] * HEARSAY_TRUST * news['confidence'])
        self.assertGreater(hearer.trust[MERCHANT], before)

    def test_a_buyer_prefers_a_seller_he_trusts_among_fair_offers_and_shuns_one_he_distrusts(self):
        world = SocietyWorld(seed=42)
        no_iron_here(world)
        observation = world.observe(BUILDER)
        observation['actor']['skills'] = sorted(set(observation['actor']['skills']) | {'trading'})
        tick = observation['tick']
        offer = lambda identity, actor, price: dict(id=identity, actor=actor, resource='iron', amount=2, unit_price=price,
                                                    direction='sell', home=0, created=tick - 1, expires=tick + 3)
        observation['market'] = [offer(7, MERCHANT, 6.), offer(8, MINER, 5.8), offer(9, COUNCILLOR, 5.)]
        observation['actor']['trust'] = {MERCHANT: .3, MINER: 0., COUNCILLOR: -.4}
        (need,) = needs(observation)
        self.assertEqual(need['offer']['actor'], MERCHANT)  # 6 from Mara, whom he trusts, over 5.8; never Aldren
        observation['actor']['trust'][MERCHANT] = .1
        (need,) = needs(observation)
        self.assertEqual(need['offer']['actor'], MINER)  # a little trust is not worth 0.2 a unit

    def test_after_the_sale_each_thinks_better_of_the_other_and_she_would_go_further_for_him(self):
        world, builder = after_the_supply()
        merchant = world.agents[MERCHANT]
        self.assertGreater(merchant.trust[BUILDER], 0)
        self.assertGreater(builder.trust[MERCHANT], 0)
        actor = world.observe(MERCHANT)['actor']
        stranger = dict(actor, trust={})
        self.assertGreater(kindness(actor, BUILDER), kindness(stranger, BUILDER))

    def test_an_offer_for_a_need_already_met_lapses_and_word_of_that_replaces_the_need(self):
        world, _ = after_the_supply(cycles=14)
        lapsed = [e for e in world.events if e.get('lapsed') is not None]
        self.assertTrue(lapsed)
        event = lapsed[0]
        seller = event['seller']
        (own,) = [c for c in world.knowledge[seller] if c['kind'] == 'need' and c['subject'] == event['buyer']
                  and c['facts'].get('gone')]
        self.assertEqual((own['source'], own['confidence'], own['origin']), (None, 1., seller))
        self.assertIn('did not take up', event['message'])
        spread_to = [h for h, store in world.knowledge.items() if h != seller and any(
            c['kind'] == 'need' and c['subject'] == event['buyer'] and c['facts'].get('gone') for c in store)]
        self.assertTrue(spread_to)  # the correction travels, replacing the copies people heard before
        for holder in spread_to:
            copies = [c for c in world.knowledge[holder] if c['kind'] == 'need' and c['subject'] == event['buyer']
                      and c['facts'].get('resource') == event['resource']]
            self.assertTrue(all(c['facts'].get('gone') for c in copies if str(c['key']) == str(own['key'])))
            chance = judged(world.observe(holder), event['buyer'], event['resource']) if holder != event['buyer'] else None
            if chance:
                self.assertIsNone(chance['route'])

    def test_heard_needs_change_terms_reach_those_who_heard_them_before(self):
        world = SocietyWorld(seed=42)
        toren_needs_iron(world)
        world.step()
        claim = heard(world, MERCHANT)
        builder_claim = need_claims(world, BUILDER)[0]
        builder_claim['facts'] = dict(builder_claim['facts'], amount=1)
        builder_claim['observed'] += 1
        self.assertTrue(relay(world, BUILDER, MERCHANT, builder_claim) is False)  # not news: the same need
        (now,) = need_claims(world, MERCHANT)
        self.assertEqual(now['facts']['amount'], 1)  # but its new terms replace the old ones
        self.assertNotEqual(claim['facts']['amount'], now['facts']['amount'])


class RulesTests(unittest.TestCase):
    def test_an_offer_can_only_answer_a_need_its_seller_has_heard_of(self):
        world = SocietyWorld(seed=42)
        toren_needs_iron(world)
        world.settlements[0].deposits['iron'] = 2.  # ore the miner could gather, moved back from Highfen
        world.settlements[1].deposits['iron'] -= 2.
        purpose = {'kind': 'need', 'subject': BUILDER, 'step': 'house'}
        sell = dict(actor=MERCHANT, type='offer', resource='iron', amount=2, unit_price=6., direction='sell')
        self.assertEqual(world.submit_action(dict(sell, purpose=purpose)).code, 'invalid_purpose')  # nobody knows yet
        self.assertEqual(world.submit_action(dict(actor=MINER, type='gather', resource='iron', amount=1,
                                                  purpose=purpose)).code, 'invalid_purpose')
        world.step()
        heard(world, MERCHANT)
        self.assertEqual(world.submit_action(dict(sell, direction='buy', purpose=purpose)).code, 'invalid_purpose')
        self.assertEqual(world.submit_action(dict(sell, purpose=dict(purpose, step='workshop'))).code, 'invalid_purpose')
        result = world.submit_action(dict(sell, purpose=purpose))
        self.assertTrue(result.success, result.message)
        self.assertEqual(result.message, 'Mara of Rivermark offered to sell 2 iron at 6 coins each to meet '
                                         'Toren of Rivermark\'s need for a house.')
        (posted,) = [o for o in world.offers if o['actor'] == MERCHANT]
        self.assertEqual(posted['purpose'], purpose)

    def test_buying_in_another_town_follows_the_market_and_road_rules(self):
        world = SocietyWorld(seed=42)
        iron_only_in_highfen(world)
        buy = dict(actor=MERCHANT, type='procure', resource='iron', amount=2, source=1)
        self.assertEqual(world.submit_action(dict(buy, source=0)).code, 'unknown_location')  # not from home
        self.assertEqual(world.submit_action(dict(buy, amount=9)).code, 'invalid_amount')  # eight at a time
        self.assertEqual(world.submit_action(dict(buy, resource='coins')).code, 'invalid_resource')
        self.assertEqual(world.submit_action(dict(buy, purpose={'kind': 'need', 'subject': BUILDER, 'step': 'house'})).code,
                         'invalid_purpose')  # a need she has not heard of
        world.settlements[1].permissions['trade'] = False
        self.assertEqual(world.submit_action(buy).code, 'permission_denied')
        world.settlements[1].permissions['trade'] = True
        self.assertTrue(world.submit_action(buy).success)

    def test_a_checkpoint_with_an_offer_for_a_need_open_resumes_the_same_history(self):
        world = SocietyWorld(seed=42)
        toren_needs_iron(world)
        for _ in range(6):
            world.step()
        self.assertTrue(any(o.get('purpose') for o in world.offers))
        restored = restore_checkpoint(json.loads(json.dumps(checkpoint(world))))
        for other in (world, restored):
            for _ in range(6):
                other.step()
        self.assertEqual(history(restored), history(world))
        self.assertEqual(restored.knowledge, world.knowledge)


class PlayerTests(unittest.TestCase):
    def test_a_player_can_answer_a_need_they_heard_of_and_see_what_came_of_it(self):
        session, builder = with_iron()
        world = session.world
        session.act()
        session.talk(BUILDER, 'work')  # he tells the player what he needs
        (choice,) = [c for c in session.options() if c['proposal']['type'] == 'offer'
                     and (c['proposal']['params'].get('purpose') or {}).get('subject') == BUILDER]
        self.assertEqual(choice['label'], 'Offer Toren of Rivermark 2 iron for a house at 6 each, the price they '
                                          'said (for 4 cycles)')
        session.act(customize(choice, '3'))  # all three: Lyra needs one too, and anyone may take it up
        (seen,) = [o for o in interface.state(session)['opportunities'] if o['kind'] == 'need' and o['who'] == builder.name
                   and o['resource'] == 'iron']
        self.assertEqual(seen['status'], 'offered')
        self.assertTrue(any(line.startswith('you offered 3 iron for it at 6 a unit') for line in seen['since']))
        for _ in range(3):
            if builder.inventory['iron'] >= 2 or builder.structures.get('house'):
                break
            session.act()
        self.assertTrue(any(c['facts']['buyer'] == BUILDER for c in supplied(world, session.player_id)))
        others = [o for o in world.knowledge.get(session.player_id, []) if o['kind'] == 'need' and o['subject'] == BUILDER]
        self.assertEqual(others, [])  # met, as far as the player supplied it
        with tempfile.TemporaryDirectory() as folder:
            loaded = PlayableSession.load(session.save(Path(folder) / 'w.json'))
        for other in (loaded, session):
            other.act()
        self.assertEqual(history(loaded.world), history(session.world))

    def test_an_offer_made_for_someone_says_so_on_the_market(self):
        world, _ = after_the_supply(cycles=6)
        session = PlayableSession(world)
        world.add_player('Ilsa', 'Rivermark')
        (listed,) = [o for o in interface.state(session)['opportunities'] if o['kind'] == 'seller' and o.get('for_need')]
        self.assertEqual((listed['who'], listed['for_need'], listed['purpose'], listed['unit_price']),
                         ('Mara of Rivermark', BUILDER, 'to Toren of Rivermark for a house', 6.))


if __name__ == '__main__':
    unittest.main()
