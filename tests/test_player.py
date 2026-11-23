"""v0.8: a human player is one more person in the same cycle, under the same rules.

Stage 1 covers integration; Stage 2 covers guided choices, politics, reputation and the journal.
"""
from copy import deepcopy
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from eternia import player as player_view
from eternia.economic_policy import EconomicPolicy, market_view
from eternia.evaluation import goal_history, summarize
from eternia.player_history import journal, journal_text
from eternia.persistence import load_world, save_world
from eternia.playable_session import PlayableSession
from eternia.society import SocietyWorld

ROOT = Path(__file__).resolve().parents[1]
MERCHANT = 2  # Rivermark's trader


def exported(world):
    data = world.export()
    data.pop('provenance', None)
    return json.dumps(data, sort_keys=True)


def option(session, kind, **params):
    """The first menu choice of a kind (and matching parameters), as a player would pick it."""
    for choice in session.options():
        proposal = choice['proposal']
        if proposal['type'] == kind and all(proposal['params'].get(k) == v for k, v in params.items()):
            return proposal
    raise AssertionError(f'No {kind} option with {params}: {[c["label"] for c in session.options()]}')


def play_turns(session):
    """A short, varied stretch of play: gather, sell, buy, eat, wait and a refused attempt."""
    outcomes = [session.act(option(session, 'gather', resource='food'))]
    outcomes.append(session.act(option(session, 'trade', resource='food', direction='sell')))
    outcomes.append(session.act(option(session, 'trade', resource='food', direction='buy')))
    outcomes.append(session.act(option(session, 'eat')))
    outcomes.append(session.act())
    outcomes.append(session.act({'type': 'gather', 'params': {'resource': 'iron', 'amount': 2}}))
    return outcomes


def menu(session, action, **params):
    """The first menu choice (the whole entry) of a kind whose parameters match."""
    for choice in session.options():
        proposal = choice['proposal']
        inner = proposal["params"].get("params", {}) if action == "propose" else {}
        if proposal["type"] == action and all(proposal["params"].get(k, inner.get(k)) == v for k, v in params.items()):
            return choice
    raise AssertionError(f"No {action} choice with {params}")


def livelihood(session):
    """Menus only: found a cooperative, gather and sell food three times, then hire someone for wood."""
    session.act(option(session, 'form_institution', purpose='cooperative'))
    for _ in range(3):
        session.act(option(session, 'gather', resource='food'))
        session.act(option(session, 'trade', resource='food', direction='sell'))
    session.act(option(session, 'hire', resource='wood'))
    for _ in range(4):
        session.act()


class PlayerJoinsTests(unittest.TestCase):
    def test_a_player_arrives_as_an_ordinary_accounted_newcomer(self):
        world = SocietyWorld(seed=42)
        town = world.settlements[0]
        population, people = town.population, len(world.agents)
        person = world.add_player('Ilsa', home='Rivermark')
        self.assertEqual((town.population, len(world.agents)), (population + 1, people + 1))
        self.assertEqual(world.active_players(), {person.id})
        self.assertEqual((person.home, person.role, person.goal), (0, 'newcomer', {}))
        self.assertEqual(sorted(person.skills), ['foraging', 'trading'])
        self.assertEqual(person.inventory, {'food': 3., 'wood': 0., 'iron': 0., 'coins': 10.})
        self.assertNotIn(person.id, world.minds)  # nobody decides for the player
        world._assert_invariants()  # belongings are an explicit, accounted inflow
        self.assertEqual(world.player_log[-1]['event'], 'joined')
        self.assertTrue(world.events[-1]['player'])

    def test_joining_is_validated(self):
        world = SocietyWorld(seed=42)
        for name, home, inventory in (('', 0, None), ('x' * 41, 0, None), ('Edrin of Rivermark', 0, None),
                                      ('Rivermark', 0, None), ('Ilsa', 'Atlantis', None), ('Ilsa', 0, {'gold': 5}),
                                      ('Ilsa', 0, {'coins': -1}), ('Ilsa', 0, {'coins': math.inf})):
            with self.subTest(name=name, home=home, inventory=inventory), self.assertRaises(ValueError):
                world.add_player(name, home, inventory)
        self.assertEqual(world.players, set())
        world._resolving = True
        with self.assertRaises(ValueError):
            world.add_player('Ilsa')
        world._resolving = False
        self.assertEqual(world.add_player('Ilsa', 'Highfen', {'coins': 3}).inventory['coins'], 3.)


class SameCycleTests(unittest.TestCase):
    def setUp(self):
        self.session = PlayableSession.start('Ilsa', 'Rivermark', seed=42)
        self.world, self.me = self.session.world, self.session.player_id

    def test_acceptance_choices_resolve_with_everyone_and_their_consequences_persist(self):
        """Start a society, play a person in Rivermark, let every NPC act in the same cycle, repeat."""
        world, me = self.world, self.me
        batches = []
        resolve = world.resolve_actions
        world.resolve_actions = lambda proposals: batches.append(list(proposals)) or resolve(proposals)

        living = len(world.agents)
        deposits, energy = world.settlements[0].deposits['food'], self.session.person.energy
        gather = option(self.session, 'gather', resource='food')
        outcome = self.session.act(gather)
        # One batch, one proposal from each living person, the player's among them.
        self.assertEqual(len(batches), 1)
        self.assertEqual(sorted(p['actor'] for p in batches[0]), sorted(a.id for a in world.agents))
        self.assertEqual(outcome['actions_resolved'], living)
        self.assertTrue(outcome['result']['success'], outcome['result'])
        amount = gather['params']['amount']
        person = self.session.person
        self.assertEqual(person.inventory['food'], 3. + amount)
        self.assertEqual(person.energy, min(100., energy - 2 * amount + 6))  # same costs and recovery
        self.assertLessEqual(world.settlements[0].deposits['food'], deposits - amount)
        npc_actions = [r for r in world.action_log if r['tick'] == outcome['tick'] and r['action']['actor'] != me]
        self.assertEqual(len(npc_actions), living - 1)

        # Later turns build on what the earlier ones left behind.
        coins = person.inventory['coins']
        sell = option(self.session, 'trade', resource='food', direction='sell')
        sold = self.session.act(sell)
        self.assertTrue(sold['result']['success'], sold['result'])
        self.assertAlmostEqual(person.inventory['coins'], coins + sold['result']['effects']['price'])
        self.assertEqual(person.inventory['food'], 3. + amount - sell['params']['amount'])
        hunger = person.hunger
        ate = self.session.act(option(self.session, 'eat'))
        self.assertTrue(ate['result']['success'])
        self.assertLess(person.hunger, hunger + 7)
        self.assertEqual(person.inventory['food'], 3. + amount - sell['params']['amount'] - 1)
        self.assertEqual(len(batches), 3)
        self.assertEqual(world.tick, 3)
        self.assertEqual([e['tick'] for e in world.player_log if e['event'] == 'action'], [0, 1, 2])
        world._assert_invariants()

    def test_the_player_is_not_resolved_first(self):
        positions = []
        for _ in range(12):
            tick = self.world.tick
            self.session.act()
            batch = [r['action']['actor'] for r in self.world.action_log if r['tick'] == tick]
            positions.append(batch.index(self.me))
        self.assertGreater(len(set(positions)), 3)  # the seeded order of the whole batch decides
        self.assertNotEqual(set(positions), {0})

    def test_contested_last_units_are_settled_like_anyone_elses(self):
        world, me = self.world, self.me
        town = world.settlements[0]
        merchant = world.agents[MERCHANT]
        self.assertIn('trading', merchant.skills)
        moved = town.food - 6
        town.food -= moved
        world.ledger['consumed']['food'] += moved
        buy = lambda actor: {'actor': actor, 'type': 'trade', 'params': {'resource': 'food', 'amount': 6, 'direction': 'buy'}}
        for actor in (me, merchant.id):
            self.assertTrue(world.action_engine.validate(buy(actor)).success)
        results = world.resolve_actions([buy(me), buy(merchant.id)])
        outcome = {r['action']['actor']: r['result'] for r in results}
        self.assertEqual(sorted(r['success'] for r in outcome.values()), [False, True])
        loser = next(r for r in outcome.values() if not r['success'])
        self.assertEqual(loser['code'], 'conflict')
        self.assertEqual(town.food, 0)

    def test_the_same_rules_bind_the_player(self):
        with self.assertRaises(ValueError):
            self.session.act({'actor': 0, 'type': 'rest', 'params': {}})  # nobody acts for someone else
        refused = self.session.act({'type': 'gather', 'params': {'resource': 'iron', 'amount': 2}})
        self.assertFalse(refused['result']['success'])
        self.assertEqual(refused['result']['code'], 'missing_knowledge')
        rested = self.session.act({'type': 'rest', 'params': {}})
        self.assertEqual(rested['result']['code'], 'not_needed')
        broke = self.session.act({'type': 'trade', 'params': {'resource': 'iron', 'amount': 9, 'direction': 'buy'}})
        self.assertEqual(broke['result']['code'], 'insufficient_resources')
        self.assertEqual(self.session.person.inventory['coins'], 10.)
        # Refusals still cost the turn: time passed and hunger rose.
        self.assertEqual(self.world.tick, 3)
        self.assertGreater(self.session.person.hunger, 0)

    def test_a_player_who_chooses_nothing_waits(self):
        outcome = self.session.act()
        self.assertEqual(outcome['action']['type'], 'wait')
        self.assertTrue(outcome['result']['success'])
        self.assertEqual(self.world.player_log[-1]['chosen'], False)
        self.assertEqual(self.world._rationales[self.me], 'The player waited.')

    def test_the_player_sees_what_anyone_sees(self):
        mine, npc = self.session.observation(), self.world.observe(0)
        self.assertEqual(set(mine), set(npc))
        self.assertEqual(set(mine['actor']), set(npc['actor']) - {'mind'})
        self.assertEqual(mine['settlement'], npc['settlement'])
        self.assertEqual(mine['prices'], npc['prices'])
        self.assertNotIn('rng', json.dumps(mine))
        text = '\n'.join(self.session.situation())
        self.assertIn('You are Ilsa, living in Rivermark.', text)
        text.encode('ascii')

    def test_every_menu_option_comes_from_the_observation_and_passes_the_rules(self):
        for _ in range(9):
            before = exported(self.world)
            choices = self.session.options()
            self.assertEqual(exported(self.world), before)  # a dry run changes nothing
            candidates = [c['label'] for c in player_view.candidate_actions(deepcopy(self.session.observation()))]
            self.assertTrue({c['label'] for c in choices} <= set(candidates))
            for choice in choices:
                if choice['checked']:
                    self.assertTrue(self.world.action_engine.validate(choice['proposal']).success, choice['label'])
                else:  # it depends on someone else's private state, so only the cycle can tell
                    self.assertIn(choice['proposal']['type'], player_view.UNCHECKED)
            self.assertEqual(choices[0]['proposal']['type'], 'wait')
            self.session.act(choices[min(len(choices) - 1, 1 + self.world.tick % 4)]['proposal'])

    def test_goal_statistics_cover_autonomous_people_only(self):
        self.session.act()
        history = goal_history(self.world)
        self.assertEqual(history['goals_active'], len(self.world.agents) - 1)
        self.assertNotIn(None, history['current_goal_kinds'])
        summary = summarize(self.world)
        self.assertEqual(summary['named_agents'], len(self.world.agents))


class ReplayAndSaveTests(unittest.TestCase):
    def test_recorded_inputs_replay_the_session_exactly(self):
        session = PlayableSession.start('Ilsa', 'Rivermark', seed=18, policy_style='collective', years=1)
        play_turns(session)
        history = json.loads(json.dumps(session.input_history()))
        self.assertEqual([e['event'] for e in history['inputs']].count('joined'), 1)
        self.assertEqual(history['inputs'][0]['tick'], 4)  # arrived after a year of autonomous history
        replayed = PlayableSession.replay(history)
        self.assertEqual(exported(replayed.world), exported(session.world))
        self.assertEqual(replayed.world.player_log, session.world.player_log)
        broken = deepcopy(history)
        broken['inputs'][0]['actor'] += 1
        with self.assertRaises(ValueError):
            PlayableSession.replay(broken)

    def test_save_and_load_between_turns_matches_uninterrupted_play(self):
        straight = PlayableSession.start('Ilsa', 'Rivermark', seed=42)
        resumed = PlayableSession.start('Ilsa', 'Rivermark', seed=42)
        play_turns(straight)
        play_turns(resumed)
        with tempfile.TemporaryDirectory() as folder:
            path = resumed.save(Path(folder) / 'world.save.json')
            resumed = PlayableSession.load(path)
        self.assertEqual(resumed.player_id, straight.player_id)
        for session in (straight, resumed):
            play_turns(session)
        self.assertEqual(exported(resumed.world), exported(straight.world))
        self.assertEqual(resumed.world.player_log, straight.world.player_log)
        # And the full record still replays from inputs alone, across the save.
        self.assertEqual(exported(PlayableSession.replay(resumed.input_history()).world), exported(straight.world))

    def test_a_queued_choice_survives_a_save(self):
        session = PlayableSession.start('Ilsa', 'Rivermark', seed=42)
        session.world.queue_player_action(session.player_id, option(session, 'gather', resource='food'))
        with tempfile.TemporaryDirectory() as folder:
            world = load_world(save_world(session.world, Path(folder) / 'w.json'))
        outcome = PlayableSession(world).act()
        self.assertEqual(outcome['action']['type'], 'gather')

    def test_a_saved_society_can_be_joined(self):
        world = SocietyWorld(seed=42)
        world.run(1)
        with tempfile.TemporaryDirectory() as folder:
            session = PlayableSession.load(save_world(world, Path(folder) / 'w.json'))
        self.assertIsNone(session.player_id)
        session.join('Ilsa', 'Highfen')
        with self.assertRaises(ValueError):
            session.join('Toma', 'Highfen')
        self.assertEqual(session.world.settlements[session.person.home].name, 'Highfen')
        session.act()
        replayed = PlayableSession.replay(session.input_history())
        self.assertEqual(exported(replayed.world), exported(session.world))

    def test_an_heir_continues_after_the_player_starves(self):
        session = PlayableSession.start('Ilsa', 'Rivermark', seed=42)
        first = session.player_id
        while session.player_id == first:
            self.assertLess(session.world.tick, 40)
            session.act()  # never eating has the same end as for anyone
        heir = session.person
        self.assertEqual(heir.parent_id, first)
        self.assertNotIn(heir.id, session.world.minds)
        self.assertEqual(session.world.active_players(), {heir.id})
        self.assertIn('prolonged food deprivation',
                      next(e['message'] for e in session.world.events if e['kind'] == 'death' and e['actor_id'] == first))
        entry = next(e for e in session.world.player_log if e['event'] == 'heir')
        self.assertEqual((entry['predecessor'], entry['actor']), (first, heir.id))
        session.act()
        outcome = session.act(option(session, 'eat'))
        self.assertEqual(outcome['actor'], heir.id)
        self.assertTrue(outcome['result']['success'])
        session.world._assert_invariants()
        replayed = PlayableSession.replay(session.input_history())
        self.assertEqual(replayed.world.player_log, session.world.player_log)

    def test_a_death_on_the_road_passes_control_on_arrival(self):
        session = PlayableSession.start('Ilsa', 'Rivermark', seed=42)
        world, first = session.world, session.player_id
        session.act(option(session, 'gather', resource='food'))  # provisions for the road
        self.assertTrue(session.act(option(session, 'migrate'))['result']['success'])
        self.assertTrue(world.is_traveling(first))
        self.assertEqual(world.remove_agent(first, 'old age').id, first)  # deferred until arrival
        self.assertEqual(world.active_players(), {first})
        self.assertFalse(any(e['event'] == 'heir' for e in world.player_log))
        while session.player_id == first:
            self.assertLess(world.tick, 20)
            session.act()
        heir = session.person
        self.assertEqual((heir.parent_id, world.settlements[heir.home].name), (first, 'Highfen'))
        self.assertNotIn(heir.id, world.minds)
        self.assertEqual([e['actor'] for e in world.player_log if e['event'] == 'heir'], [heir.id])
        world._assert_invariants()


class GuidedEconomyTests(unittest.TestCase):
    """2.1: a livelihood through ordinary menus, with quantities, prices and wages the player chooses."""

    def test_a_livelihood_without_writing_any_action(self):
        session = PlayableSession.start('Ilsa', 'Rivermark', seed=42, years=2)
        world, me = session.world, session.player_id
        livelihood(session)
        log = [r for r in world.action_log if r['action']['actor'] == me]
        sales = [r for r in log if r['action']['type'] == 'trade' and r['result']['success']]
        self.assertEqual(len(sales), 3)
        self.assertTrue(all(r['result']['success'] for r in log if r['action']['type'] in ('gather', 'hire')))
        order = next(o for o in world.work_orders if o['employer'] == {'kind': 'person', 'id': me})
        self.assertEqual(order['remaining'], 0)  # a neighbor took the job and delivered
        self.assertEqual(session.person.inventory['wood'], order['quantity'])
        self.assertTrue(any(i.name == 'Rivermark Cooperative of Ilsa' and me in i.members for i in world.institutions))
        world._assert_invariants()

    def test_fields_set_amounts_prices_and_wages(self):
        session = PlayableSession.start('Ilsa', 'Rivermark', seed=42, years=2)
        world, me = session.world, session.player_id
        gather = menu(session, 'gather', resource='food')
        self.assertEqual(session.act(player_view.customize(gather, '3'))['result']['effects']['amount'], 3)
        offer = menu(session, 'offer', resource='food', direction='sell')
        posted = session.act(player_view.customize(offer, '4 2.5'))
        self.assertTrue(posted['result']['success'])
        self.assertEqual({k: world.offers[-1][k] for k in ('amount', 'unit_price', 'actor')},
                         {'amount': 4, 'unit_price': 2.5, 'actor': me})
        hire = menu(session, 'hire', resource='food')
        session.act(player_view.customize(hire, '5 0.4'))
        order = next(o for o in world.work_orders if o['employer'] == {'kind': 'person', 'id': me})
        self.assertEqual((order['quantity'], order['unit_wage']), (5, .4))
        for text in ('0', '9', 'two', '1 2 3'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                player_view.customize(gather, text)
        named = menu(session, 'form_institution', purpose='guild')
        self.assertEqual(player_view.customize(named, '  The Free Traders ')['params']['name'], 'The Free Traders')
        # A changed choice gets the same dry run as the menu, and nothing is spent if it would fail.
        buy = menu(session, 'offer', resource='food', direction='buy')
        too_much = player_view.customize(buy, '1000')
        self.assertEqual(session.check(too_much).code, 'insufficient_resources')
        self.assertIsNone(session.check({'type': 'teach', 'params': {'target': 0, 'topic': 'aether'}}))

    def test_every_engine_action_has_a_menu_entry(self):
        session = PlayableSession.start('Ilsa', 'Rivermark', seed=42, years=5)
        world, me = session.world, session.player_id
        person = session.person
        person.skills.append('carpentry')
        person.knowledge = 1
        person.hunger, person.energy = 50., 50.
        kinds = {c['proposal']['type'] for c in player_view.candidate_actions(world.observe(me))}
        world.ledger['produced']['food'] += 40
        world.ledger['produced']['coins'] += 200
        person.inventory['food'] += 40
        person.inventory['coins'] += 200
        for institution in world.institutions:
            if institution.active and institution.settlement_id == person.home:
                institution.members.add(me)
        council = next(i for i in world.institutions if i.active and i.settlement_id == person.home
                       and i.purpose == 'council')
        council.decisions.append(dict(id=world.next_proposal_id, kind='tax_rate', params={'value': .05}, proposer=0,
                                      electorate=sorted(council.members), votes={}, created=world.tick - 1,
                                      expires=world.tick + 5, status='open'))
        world.next_proposal_id += 1
        offer = dict(id=world.next_offer_id, actor=0, home=person.home, resource='wood', amount=3, unit_price=2.,
                     direction='sell', created=world.tick - 1, expires=world.tick + 3)
        world.next_offer_id += 1
        world.offers.append(offer)
        kinds |= {c['proposal']['type'] for c in player_view.candidate_actions(world.observe(me))}
        missing = set(world.action_engine.parameters) - kinds - {'dispatch_caravan'}
        self.assertEqual(missing, set())
        # Contract caravans appear for members of an exporting organization with an active route.
        exporter = next((a for a in world.agents if world.observe(a.id)['physical']['dispatch_options']), None)
        if exporter is not None:
            observed = world.observe(exporter.id)
            self.assertIn('dispatch_caravan', {c['proposal']['type'] for c in player_view.candidate_actions(observed)})

    def test_an_embargo_stops_private_shipments_for_everyone(self):
        session = PlayableSession.start('Ilsa', 'Rivermark', seed=42, years=2)
        world, me = session.world, session.player_id
        session.act(option(session, 'gather', resource='food'))
        session.act(option(session, 'gather', resource='food'))
        ship = menu(session, 'consign', resource='food', destination=1)['proposal']
        merchant = world.agents[MERCHANT]
        merchant.inventory['food'] += 20
        world.ledger['produced']['food'] += 20
        theirs = {**ship, 'actor': merchant.id}
        self.assertTrue(world.action_engine.validate(theirs).success)
        council = next(i for i in world.institutions if i.settlement_id == 0 and i.purpose == 'council')
        self.assertTrue(world.has_municipal_authority(council))
        council.rules.setdefault('embargoes', {})[1] = True
        for proposal in (ship, theirs):
            self.assertEqual(world.action_engine.validate(proposal).code, 'embargoed')
        self.assertNotIn('consign', {c['proposal']['type'] for c in session.options()
                                     if c['proposal']['params'].get('destination') == 1})


class PoliticalParticipationTests(unittest.TestCase):
    """2.2: proposals, votes and enactment; members judge a player's proposals by their own interests."""

    def council_member(self):
        session = PlayableSession.start('Ilsa', 'Rivermark', seed=42, years=2)
        council = next(i for i in session.world.institutions if i.settlement_id == 0 and i.purpose == 'council')
        session.act(option(session, 'join_institution', institution=council.id))
        session.act()
        return session, council

    def propose_and_wait(self, session, council, values):
        choice = menu(session, 'propose', kind='work_order', resource='wood')
        session.act(player_view.customize(choice, values))
        decision = max((d for d in council.decisions if d['proposer'] == session.player_id), key=lambda d: d['id'])
        for _ in range(8):
            enact = [c for c in session.options() if c['proposal']['type'] == 'enact'
                     and c['proposal']['params']['proposal'] == decision['id']]
            if enact:
                return decision, session.act(enact[0]['proposal'])
            session.act()
        return decision, None

    def test_members_reject_an_overpriced_public_budget(self):
        session, council = self.council_member()
        decision, enacted = self.propose_and_wait(session, council, '8 4.9')
        votes = {int(k): v['approve'] for k, v in decision['votes'].items()}
        self.assertTrue(votes.pop(session.player_id))
        self.assertTrue(votes and not any(votes.values()))  # every other member voted against
        self.assertIsNone(enacted)
        self.assertEqual(decision['status'], 'rejected')

    def test_a_fair_budget_passes_and_the_player_can_carry_it_out(self):
        session, council = self.council_member()
        treasury = session.world.settlements[0].treasury
        decision, enacted = self.propose_and_wait(session, council, '8 1.5')
        self.assertTrue(enacted['result']['success'], enacted['result'])
        self.assertEqual(decision['status'], 'enacted')
        self.assertGreaterEqual(sum(v['approve'] is True for v in decision['votes'].values()), 3)
        order = next(o for o in session.world.work_orders if o.get('proposal') == decision['id'])
        self.assertEqual((order['quantity'], order['unit_wage'], order['escrow']), (8, 1.5, 12.))
        self.assertLess(session.world.settlements[0].treasury, treasury)
        session.world._assert_invariants()

    def test_votes_on_open_proposals_are_offered_to_the_electorate_only(self):
        session, council = self.council_member()
        session.act(player_view.customize(menu(session, 'propose', kind='work_order', resource='wood'), '8 1.5'))
        decision = max(council.decisions, key=lambda d: d['id'])
        votes = [c for c in session.options() if c['proposal']['type'] == 'vote']
        older = {c['proposal']['params']['proposal'] for c in votes}
        self.assertNotIn(decision['id'], older)  # already voted by proposing
        self.assertTrue(all(session.player_id in next(d for d in council.decisions if d['id'] == p)['electorate']
                            for p in older))


class ReputationTests(unittest.TestCase):
    """2.3: the existing trust system reacts to what anyone does, the player included."""

    def test_losing_contested_goods_sours_relations_for_anyone(self):
        world = SocietyWorld(seed=42)
        me = world.add_player('Ilsa', 'Rivermark').id
        town = world.settlements[0]
        moved = town.food - 6
        town.food -= moved
        world.ledger['consumed']['food'] += moved
        buy = lambda actor: {'actor': actor, 'type': 'trade', 'params': {'resource': 'food', 'amount': 6, 'direction': 'buy'}}
        third = next(a.id for a in world.agents if a.home == 0 and a.id not in (me, MERCHANT)
                     and a.inventory['coins'] >= 7)
        buyers = {me, MERCHANT, third}
        results = world.resolve_actions([buy(actor) for actor in sorted(buyers)])
        world._social_consequences(results)
        winner = next(r['action']['actor'] for r in results if r['result']['success'])
        losers = buyers - {winner}
        self.assertEqual(len(losers), 2)
        for loser in losers:
            holder = next(a for a in world.agents if a.id == loser)
            self.assertEqual(holder.trust.get(winner), -.03)  # whether the winner is the player or not
            self.assertNotIn(loser, {k for k, v in holder.trust.items() if v})
        entries = journal(world)
        side = 'won' if winner == me else 'lost'
        self.assertEqual(len(entries['contests'][side]), 1)

    def test_a_gift_raises_fellow_members_trust(self):
        session = PlayableSession.start('Ilsa', 'Rivermark', seed=42, years=2)
        world, me = session.world, session.player_id
        coop = next(i for i in world.institutions if i.purpose == 'cooperative' and i.settlement_id == 0)
        session.act(option(session, 'join_institution', institution=coop.id))
        session.act()
        others = sorted(coop.members - {me})
        before = {m: world._resolve_agent(m).trust.get(me, 0.) for m in others}
        self.assertTrue(session.act(option(session, 'contribute', institution=coop.id, resource='coins'))['result']['success'])
        for member in others:
            self.assertAlmostEqual(world._resolve_agent(member).trust.get(me, 0.), before[member] + .02)

    def test_nobody_works_for_an_employer_they_distrust(self):
        outcomes = {}
        for wary in (False, True):
            session = PlayableSession.start('Ilsa', 'Rivermark', seed=42, years=2)
            world, me = session.world, session.player_id
            if wary:
                for person in world.agents:
                    if person.id != me:
                        person.trust[me] = -.5
            session.act(option(session, 'hire', resource='wood'))
            for _ in range(8):
                session.act()
            order = next(o for o in world.work_orders if o['employer'] == {'kind': 'person', 'id': me})
            outcomes[wary] = order['quantity'] - order['remaining']
        self.assertGreater(outcomes[False], 0)
        self.assertEqual(outcomes[True], 0)

    def test_a_distrusted_founder_finds_no_aggrieved_recruits(self):
        session = PlayableSession.start('Ilsa', 'Rivermark', seed=42)
        world, me = session.world, session.player_id
        session.act(option(session, 'form_institution', purpose='cooperative'))
        coop = next(i for i in world.institutions if me in i.members)
        neighbor = next(a for a in world.agents if a.home == 0 and a.id != me and not any(
            a.id in i.members for i in world.institutions if i.purpose == 'cooperative'))
        mind = world.minds[neighbor.id]
        mind['fairness'], mind['motivations']['belonging'] = .3, .6
        policy = EconomicPolicy('balanced')

        def joins():
            observation = world.observe(neighbor.id)
            return {params.get('institution') for kind, params, *_ in policy._social_candidates(
                observation, market_view(observation)) if kind == 'join_institution'}

        self.assertIn(coop.id, joins())
        neighbor.trust[me] = -.5
        self.assertNotIn(coop.id, joins())


class JournalTests(unittest.TestCase):
    """2.4: the player's record of earnings, work, memberships, votes and relationships."""

    def test_the_journal_accounts_for_every_coin(self):
        session = PlayableSession.start('Ilsa', 'Rivermark', seed=42, years=2)
        livelihood(session)
        entries = session.journal()
        coins = entries['coins']
        self.assertEqual(coins['unexplained'], 0)
        self.assertEqual(coins['start'], 10.)
        self.assertAlmostEqual(coins['now'], session.person.inventory['coins'])
        self.assertEqual(set(coins['income']), {'market sales'})
        self.assertEqual(set(coins['spending']), {'organization fees', 'wages put in escrow'})
        job = entries['hired'][0]
        self.assertEqual(job['delivered'], job['quantity'])
        self.assertTrue(job['workers'])
        self.assertEqual([m['name'] for m in entries['memberships']], ['Rivermark Cooperative of Ilsa'])
        self.assertNotIn('regard', entries)
        self.assertIn('regard', session.journal('historian'))
        text = '\n'.join(journal_text(session.journal('historian')))
        self.assertIn('Founded Rivermark Cooperative of Ilsa', text)
        text.encode('ascii')

    def test_the_journal_survives_saving_and_replay(self):
        session = PlayableSession.start('Ilsa', 'Rivermark', seed=42, years=2)
        livelihood(session)
        with tempfile.TemporaryDirectory() as folder:
            loaded = PlayableSession.load(session.save(Path(folder) / 'w.json'))
        replayed = PlayableSession.replay(json.loads(json.dumps(session.input_history())))
        for other in (loaded, replayed):
            self.assertEqual(other.journal('historian'), session.journal('historian'))
            self.assertEqual(exported(other.world), exported(session.world))

    def test_a_risky_shipment_can_lose_money_and_the_journal_says_so(self):
        session = PlayableSession.start('Ilsa', 'Rivermark', seed=42, years=2)
        session.act(option(session, 'gather', resource='food'))
        session.act(option(session, 'trade', resource='food', direction='buy'))
        ship = menu(session, 'consign', resource='food', destination=1)
        self.assertIn("Ship 8 food to Highfen's market for 2.21 each", ship['label'])
        self.assertTrue(session.act(ship['proposal'])['result']['success'])
        for _ in range(6):
            session.act()
        entries = session.journal()
        self.assertTrue(any('was lost' in t['text'] for t in entries['transactions']))
        self.assertNotIn('shipments delivered', entries['coins']['income'])
        self.assertEqual(entries['coins']['unexplained'], 0)
        session.world._assert_invariants()  # the lost cargo left through the ledger, not by vanishing

    def test_the_journal_records_proposals_and_votes(self):
        session, council = PoliticalParticipationTests.council_member(self)
        PoliticalParticipationTests.propose_and_wait(self, session, council, '8 1.5')
        entries = session.journal()
        self.assertEqual(entries['proposals'][-1]['status'], 'enacted')
        self.assertIn('public work: 8 wood at 1.5 each', entries['proposals'][-1]['about'])
        self.assertTrue(any('funded public order' in t['text'] for t in entries['transactions']))


class PlayCommandLineTests(unittest.TestCase):
    def run_main(self, *args, stdin=''):
        return subprocess.run([sys.executable, 'main.py', *map(str, args)], cwd=ROOT, input=stdin,
                              text=True, capture_output=True)

    def test_play_continue_and_replay(self):
        with tempfile.TemporaryDirectory() as folder:
            first, second, again = (Path(folder) / name for name in ('first', 'second', 'replay'))
            result = self.run_main('--play', '--player-name', 'Ilsa', '--output', first,
                                   stdin='2\nw 2\nj {"type": "rest", "params": {}}\nnonsense\ns\n')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('You are Ilsa, living in Rivermark.', result.stdout)
            self.assertIn('Refused (not_needed)', result.stdout)
            for name in ('world.save.json', 'history.json', 'report.html', 'inputs.json'):
                self.assertTrue((first / name).exists(), name)
            # Continue from the checkpoint; end of input saves and quits.
            result = self.run_main('--play', first / 'world.save.json', '--output', second, stdin='1\n')
            self.assertEqual(result.returncode, 0, result.stderr)
            history = json.loads((second / 'history.json').read_text(encoding='utf-8'))
            self.assertEqual(sum(e['event'] == 'action' for e in history['player_log']), 5)
            result = self.run_main('--replay', second / 'inputs.json', '--output', again)
            self.assertEqual(result.returncode, 0, result.stderr)
            replayed = json.loads((again / 'history.json').read_text(encoding='utf-8'))
            for data in (history, replayed):
                data.pop('provenance', None)
            self.assertEqual(replayed, history)
            self.assertNotEqual(self.run_main('--play', first / 'world.save.json', '--seed', 3, stdin='q\n').returncode, 0)
            self.assertNotEqual(self.run_main('--play', '--ticks-per-year', 2, stdin='q\n').returncode, 0)
            self.assertNotEqual(self.run_main('--play', '--home', 'Atlantis', stdin='q\n').returncode, 0)

    def test_play_with_values_and_the_journal(self):
        with tempfile.TemporaryDirectory() as folder:
            result = self.run_main('--play', '--player-name', 'Ilsa', '--output', folder,
                                   stdin='2 3\n3 99\nh\ns\n')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('Done: Ilsa gathered 3 food in Rivermark.', result.stdout)
            self.assertIn('The amount must be from 1 to 8.', result.stdout)
            self.assertIn('Coins: 10 on arrival', result.stdout)
            record = json.loads((Path(folder) / 'journal.json').read_text(encoding='utf-8'))
            self.assertIn('regard', record)
            self.assertTrue((Path(folder) / 'journal.txt').exists())


if __name__ == '__main__':
    unittest.main()
