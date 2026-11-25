"""v0.8 Stage 3: conversations grounded in each person's own knowledge, and news that travels."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from eternia import dialogue
from eternia.economic_policy import EconomicPolicy, distrusted_employer, market_view
from eternia.market_experiments import build_market_scenario
from eternia.playable_session import PlayableSession
from eternia.social_memory import HEARSAY_TRUST, RELAY, firsthand, relay, spread
from eternia.society import SocietyWorld

ROOT = Path(__file__).resolve().parents[1]
TOPICS = ('work', 'news', 'trade', 'politics', 'themselves')


def exported(world):
    data = world.export()
    data.pop('provenance', None)
    return json.dumps(data, sort_keys=True)


def session_after(years=8, seed=42):
    return PlayableSession.start('Ilsa', 'Rivermark', seed=seed, years=years)


def after_a_lost_shipment():
    """Seed 18, 13 years on: in year 10 Mara of Rivermark lost a shipment of food on the road to Highfen.

    Nothing here is set up: the loss happened in that history, and she remembers it.
    """
    return session_after(years=13, seed=18)


def person(session, first):
    return next(p['id'] for p in session.partners() if p['name'].split()[0] == first)


class GroundedAnswersTests(unittest.TestCase):
    """3.1: a person answers only from what they have observed, experienced or been told."""

    def test_answers_never_depend_on_what_the_speaker_cannot_know(self):
        session = session_after()
        world, me = session.world, session.player_id
        listener = {'id': me, 'name': 'Ilsa'}
        speakers = [p['id'] for p in session.partners()][:4]
        before = {(s, t): dialogue.respond(world.observe(s), t, {}, listener)['lines'] for s in speakers for t in TOPICS}
        for speaker in speakers:
            hidden = deepcopy(world)
            for other in hidden.agents:
                if other.id == speaker:
                    continue
                other.inventory['coins'] += 500.  # private holdings
                other.trust = {k: -1. for k in other.trust}  # private feelings
                if other.id in hidden.minds:
                    hidden.minds[other.id]['fairness'] = 0.  # private beliefs
                hidden.knowledge[other.id] = []  # what others know
            for town in hidden.settlements:
                town.ore = 0.  # buried reserves
            for topic in TOPICS:
                after = dialogue.respond(hidden.observe(speaker), topic, {}, listener)['lines']
                self.assertEqual(after, before[(speaker, topic)], (speaker, topic))

    def test_a_conversation_passes_no_season_and_is_bounded(self):
        session = session_after()
        world = session.world
        mara, tick = person(session, 'Mara'), world.tick
        state = world.resource_totals()
        for topic in ('news', 'trade', 'work'):
            session.talk(mara, topic)
        self.assertEqual((world.tick, world.resource_totals()), (tick, state))  # nothing moved, no time passed
        with self.assertRaises(ValueError):
            session.talk(mara, 'politics')  # three questions a season
        session.talk(person(session, 'Edrin'), 'news')  # someone else still has time
        session.act()
        session.talk(mara, 'politics')  # a new season
        with self.assertRaises(ValueError):
            session.talk(person(session, 'Mara'), 'gossip')
        far = next(a.id for a in world.agents if a.home != session.person.home)
        with self.assertRaises(ValueError):
            session.talk(far, 'news')  # only people who are here

    def test_different_people_know_different_things(self):
        session = after_a_lost_shipment()
        answers = {first: session.talk(person(session, first), 'news')['lines'] for first in ('Mara', 'Edrin', 'Toren')}
        self.assertEqual(len({tuple(lines) for lines in answers.values()}), 3)
        trade = session.talk(person(session, 'Mara'), 'trade')
        self.assertTrue(any('My shipment of food to Highfen was lost' in line for line in trade['lines']))
        self.assertFalse(any('My shipment' in line for line in session.talk(person(session, 'Toren'), 'trade')['lines']))

    def test_the_player_learns_with_source_and_age(self):
        session = after_a_lost_shipment()
        world, me, mara = session.world, session.player_id, person(session, 'Mara')
        reply = session.talk(mara, 'trade')
        self.assertTrue(reply['learned'])
        learned = [c for c in world.knowledge[me] if c['source'] == mara]
        self.assertTrue(learned)
        for claim in learned:
            original = next(c for c in world.knowledge[mara] if c['key'] == claim['key'])
            self.assertEqual(claim['hops'], original['hops'] + 1)
            self.assertAlmostEqual(claim['confidence'], round(original['confidence'] * RELAY, 4))
            self.assertEqual(claim['learned'], world.tick)
            self.assertLess(claim['observed'], world.tick)  # an old story, and it says so
        heard = session.journal()['heard']
        self.assertTrue(any('Mara of Rivermark told me' in h['source'] for h in heard))


class OpinionTests(unittest.TestCase):
    """3.2: answers depend on personality, goals, memories and trust; people can decline or be unsure."""

    def test_temperament_and_trust_decide_who_confides(self):
        session = session_after(years=7)  # before Toren sets out for Highfen in the eighth year
        world, me = session.world, session.player_id
        toren, edrin = person(session, 'Toren'), person(session, 'Edrin')
        self.assertTrue(session.talk(toren, 'themselves')['declined'])
        shared = session.talk(edrin, 'themselves')
        self.assertFalse(shared['declined'])
        self.assertTrue(any("I'm trying to" in line for line in shared['lines']))
        world._resolve_agent(toren).trust[me] = .3
        self.assertFalse(session.talk(toren, 'themselves')['declined'])
        world._resolve_agent(edrin).trust[me] = -.6
        self.assertTrue(session.talk(edrin, 'news')['declined'])

    def test_the_same_event_means_different_things_to_different_people(self):
        session = session_after()
        world = session.world
        famine = {'kind': 'famine', 'settlement': 'Rivermark', 'message': 'Rivermark faced a food deficit.'}
        listener = {'id': session.player_id, 'name': 'Ilsa'}
        views = []
        for first, security in (('Mara', .8), ('Edrin', .2)):
            identity = person(session, first)
            world.minds[identity]['motivations']['security'] = security
            views.append(dialogue._interpret(dialogue._Speaker(world.observe(identity), listener), famine))
        self.assertNotEqual(views[0], views[1])

    def test_stated_stances_match_how_members_then_vote(self):
        for wage, side in (('4.9', 'against'), ('1.5', 'for')):
            session = PlayableSession.start('Ilsa', 'Rivermark', seed=42, years=2)
            world, me = session.world, session.player_id
            council = next(i for i in world.institutions if i.settlement_id == 0 and i.purpose == 'council')
            join = next(c['proposal'] for c in session.options() if c['proposal']['type'] == 'join_institution'
                        and c['proposal']['params']['institution'] == council.id)
            session.act(join)
            session.act()
            from eternia.player import customize
            choice = next(c for c in session.options() if c['proposal']['type'] == 'propose'
                          and c['proposal']['params']['kind'] == 'work_order'
                          and c['proposal']['params']['params']['resource'] == 'wood')
            session.act(customize(choice, f'8 {wage}'))
            decision = max(council.decisions, key=lambda d: d['id'])
            voters = sorted(set(decision['electorate']) - {me})
            stances = {}
            for voter in voters:
                reply = session.talk(voter, 'proposal', institution=council.id, proposal=decision['id'])
                stances[voter] = reply['stance']['side']
                if side == 'against':
                    self.assertIn('more than the market pays', reply['stance']['text'])
            for _ in range(4):
                session.act()
                if decision['status'] != 'open' or set(voters) <= {int(k) for k in decision['votes']}:
                    break
            votes = {int(k): v['approve'] for k, v in decision['votes'].items()}
            self.assertTrue(set(voters) & set(votes))
            for voter in voters:
                self.assertEqual(stances[voter], side, voter)
                if voter in votes:  # every member who voted voted as they said they would
                    self.assertEqual(votes[voter], side == 'for', voter)
            voted = next(v for v in voters if v in votes)
            after = session.talk(voted, 'proposal', institution=council.id, proposal=decision['id'])
            self.assertIn(f'I voted {side}', after['lines'][-1])  # and remembers it afterwards

    def test_requests_are_answered_by_the_rules_people_act_on(self):
        session = session_after(years=2)
        world, me = session.world, session.player_id
        aldric = person(session, 'Aldric')
        cheap = session.talk(aldric, 'work_for_you', resource='food', wage=.1)
        self.assertEqual(cheap['stance'], 'no')
        fair = session.talk(aldric, 'work_for_you', resource='food', wage=.5)
        self.assertEqual(fair['stance'], 'maybe')
        world._resolve_agent(aldric).trust[me] = -.4
        self.assertEqual(session.talk(aldric, 'work_for_you', resource='food', wage=.5)['stance'], 'no')
        order = {'employer': {'kind': 'person', 'id': me}}
        self.assertTrue(distrusted_employer(order, world.observe(aldric)['actor']))  # and they would not take the job
        self.assertEqual(session.talk(person(session, 'Mara'), 'work_for_you', resource='iron', wage=4.)['stance'], 'no')


class SpreadingNewsTests(unittest.TestCase):
    """3.3: news passes person to person, with its source and age, and never becomes universal by itself."""

    def test_news_travels_hop_by_hop_and_stays_partial(self):
        world = SocietyWorld(seed=42).run(10)
        claims = [c for store in world.knowledge.values() for c in store]
        self.assertTrue(any(c['hops'] >= 2 for c in claims))
        for claim in claims:
            if claim['hops']:
                self.assertIsNotNone(claim['source'])
                self.assertLessEqual(claim['observed'], claim['learned'])
                self.assertLess(claim['confidence'], 1.)
        famines = {tuple(map(str, c['key'])) for c in claims if c['kind'] == 'famine'}
        for key in famines:
            holders = [pid for pid, store in world.knowledge.items() if any(tuple(map(str, c['key'])) == key for c in store)]
            self.assertLess(len(holders), len(world.agents))  # nobody broadcast it
            place = next(c['place'] for c in claims if tuple(map(str, c['key'])) == key)
            for pid in holders:
                holder = world._resolve_agent(pid) if any(a.id == pid for a in world.agents) else None
                claim = next(c for c in world.knowledge[pid] if tuple(map(str, c['key'])) == key)
                if holder is not None and holder.home != place and claim['hops'] == 0:
                    self.assertIsNotNone(claim['via'])  # a distant famine is heard of, not seen
        again = SocietyWorld(seed=42).run(10)
        self.assertEqual(again.knowledge, world.knowledge)

    def test_hearsay_about_conduct_moves_trust_and_then_decisions(self):
        world = SocietyWorld(seed=42)
        teller, hearer, employer = 0, 1, 2
        world.tick = 3
        firsthand(world, teller, 'conduct', place=0, subject=employer,
                  facts=dict(act='underpaid', wage=.2, market=2., resource='wood'))
        world._resolve_agent(hearer).trust[employer] = -.29
        order = {'employer': {'kind': 'person', 'id': employer}}
        self.assertFalse(distrusted_employer(order, world.observe(hearer)['actor']))
        self.assertTrue(relay(world, teller, hearer, world.knowledge[teller][0]))
        self.assertAlmostEqual(world._resolve_agent(hearer).trust[employer], -.29 - HEARSAY_TRUST * RELAY)
        self.assertTrue(distrusted_employer(order, world.observe(hearer)['actor']))
        self.assertFalse(relay(world, teller, hearer, world.knowledge[teller][0]))  # old news changes nothing

    def test_a_merchant_who_hears_of_losses_on_a_route_stops_using_it(self):
        world, _ = build_market_scenario('price_gap', seed=42)
        merchant, witness = 2, 0
        policy = EconomicPolicy('balanced')
        observation = world.observe(merchant)
        self.assertTrue(policy._consignment_candidates(observation, market_view(observation)))
        firsthand(world, witness, 'shipment', place=0, subject=None,
                  facts=dict(outcome='lost', destination=1, destination_name='Highfen', resource='food',
                             reason='an accident on the upland route'), stamp=99)
        relay(world, witness, merchant, world.knowledge[witness][-1])
        observation = world.observe(merchant)
        self.assertEqual(policy._consignment_candidates(observation, market_view(observation)), [])

    def test_the_player_can_pass_news_on_but_not_invent_it(self):
        session = after_a_lost_shipment()
        world, me = session.world, session.player_id
        mara, toren = person(session, 'Mara'), person(session, 'Toren')
        session.talk(mara, 'trade')
        story = next(c for c in world.knowledge[me] if c['kind'] == 'shipment')
        knew = any(str(c['key']) == str(story['key']) for c in world.knowledge.get(toren, []))
        choice = next(c for c in session.conversation(toren) if c['proposal']['type'] == 'tell'
                      and str(c['proposal']['params']['claim']) == str(story['key']))
        reply = session.talk(toren, 'tell', **choice['proposal']['params'])
        held = next(c for c in world.knowledge[toren] if str(c['key']) == str(story['key']))
        self.assertEqual(reply['stance'], 'known' if knew else 'new')
        if not knew:
            self.assertEqual((held['source'], held['hops']), (me, story['hops'] + 1))
        with self.assertRaises(ValueError):
            session.talk(toren, 'tell', claim=['famine', 9, None, None, 0])

    def test_npcs_gossip_with_the_player_too(self):
        session = session_after(years=1)
        world, me = session.world, session.player_id
        mara = person(session, 'Mara')
        # Something only Mara knows: neighbors already share whatever the whole town saw.
        firsthand(world, mara, 'conduct', place=0, subject=person(session, 'Edrin'),
                  facts=dict(act='helped', how='taught carpentry to'))
        key = str(world.knowledge[mara][-1]['key'])
        for _ in range(14):
            session.act()
            if any(str(c['key']) == key for c in world.knowledge.get(me, [])):
                break
        heard = next(c for c in world.knowledge[me] if str(c['key']) == key)
        self.assertIsNotNone(heard['source'])  # a neighbor told the player without being asked
        self.assertFalse([e for e in world.player_log if e['event'] == 'talk'])
        holders = [p for p, store in world.knowledge.items() if any(str(c['key']) == key for c in store)]
        self.assertLess(len(holders), len(world.agents))  # and it is still not universal


class ReplayAndSaveTests(unittest.TestCase):
    def test_conversations_and_their_consequences_survive_saving_and_replay(self):
        session = session_after(years=2)
        mara, toren = person(session, 'Mara'), person(session, 'Toren')
        session.talk(mara, 'news')
        session.act()
        session.talk(mara, 'trade')
        for choice in session.conversation(toren):
            if choice['proposal']['type'] == 'tell':
                session.talk(toren, 'tell', **choice['proposal']['params'])
                break
        session.act()
        history = json.loads(json.dumps(session.input_history()))
        self.assertTrue(any(e['event'] == 'talk' for e in history['inputs']))
        replayed = PlayableSession.replay(history)
        self.assertEqual(exported(replayed.world), exported(session.world))
        with tempfile.TemporaryDirectory() as folder:
            loaded = PlayableSession.load(session.save(Path(folder) / 'w.json'))
        self.assertEqual(loaded.world.knowledge, session.world.knowledge)
        for other in (loaded, session):
            other.talk(person(other, 'Edrin'), 'news')
            other.act()
        self.assertEqual(exported(loaded.world), exported(session.world))
        tampered = deepcopy(history)
        talk = next(e for e in tampered['inputs'] if e['event'] == 'talk')
        talk['lines'] = ['"Something else entirely."']
        with self.assertRaises(ValueError):
            PlayableSession.replay(tampered)


class TalkCommandLineTests(unittest.TestCase):
    def test_talking_in_the_terminal(self):
        with tempfile.TemporaryDirectory() as folder:
            result = subprocess.run([sys.executable, 'main.py', '--play', '--player-name', 'Ilsa', '--years', '2',
                                     '--output', folder], cwd=ROOT, input='t\nt 3\nt 3 2\nh\ns\n',
                                    text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('Mara of Rivermark (merchant)', result.stdout)
            self.assertIn('Ask what has been happening', result.stdout)
            self.assertIn('Mara of Rivermark: "', result.stdout)
            self.assertIn('Year 2, cycle 8.', result.stdout)
            self.assertNotIn('Year 2, cycle 9.', result.stdout)  # talking took no season
            record = json.loads((Path(folder) / 'journal.json').read_text(encoding='utf-8'))
            self.assertEqual(record['conversations'][0]['topic'], 'news')


if __name__ == '__main__':
    unittest.main()
