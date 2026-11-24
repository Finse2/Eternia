"""v0.8 Stage 4: the browser interface draws; Python stays the only authority.

A session played through the browser's server is the same session the terminal
plays: the same proposals, the same conversations, the same saves and replays.
Building a view changes nothing and shows nothing a person could not know.
"""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock
import urllib.error
import urllib.request

from eternia import interface
from eternia import player as player_view
from eternia.market import bid_price
from eternia.persistence import checkpoint
from eternia.playable_session import PlayableSession
from eternia.web import Game, Stale, make_server

ROOT = Path(__file__).resolve().parents[1]


def exported(world):
    data = world.export()
    data.pop('provenance', None)
    return json.dumps(data, sort_keys=True)


def frozen(world):
    """Everything authoritative about a world, including its random state."""
    return json.dumps(checkpoint(world)['payload']['state'], sort_keys=True), world.rng.getstate()


def index_of(session, kind, **params):
    """The menu number of the first choice of a kind, as the browser sends it."""
    for entry in interface.menu(session):
        if entry['type'] == kind and all(entry['params'].get(k) == v for k, v in params.items()):
            return entry['index']
    raise AssertionError(f'No {kind} choice with {params}')


def partner(session, first):
    return next(p['id'] for p in session.partners() if p['name'].split()[0] == first)


class ViewTests(unittest.TestCase):
    """What the browser is sent is built in Python, from what the player knows, and changes nothing."""

    def setUp(self):
        self.session = PlayableSession.start('Ilsa', 'Rivermark', seed=42, years=2)

    def test_building_any_view_changes_nothing(self):
        session = self.session
        session.act(session.options()[index_of(session, 'gather', resource='food')]['proposal'])
        before = frozen(session.world)
        interface.state(session)
        interface.timeline(session)
        interface.digest(session)
        for person in session.partners():
            interface.topics(session, person['id'])
        self.assertEqual(frozen(session.world), before)

    def test_views_never_depend_on_what_the_player_cannot_know(self):
        session = self.session
        me = session.player_id
        before = json.dumps(interface.state(session), sort_keys=True)
        hidden = PlayableSession(deepcopy(session.world))
        for other in hidden.world.agents:
            if other.id == me:
                continue
            other.inventory['coins'] += 500.  # private holdings
            other.trust = {k: -1. for k in other.trust}  # private feelings, including about the player
            if other.id in hidden.world.minds:
                hidden.world.minds[other.id]['fairness'] = 0.  # private beliefs
            hidden.world.knowledge[other.id] = []  # what others know
        for town in hidden.world.settlements:
            town.ore = 0.  # buried reserves
        self.assertEqual(json.dumps(interface.state(hidden), sort_keys=True), before)

    def test_prices_shown_are_the_worlds_posted_prices(self):
        state = interface.state(self.session)
        world = self.session.world
        for town in [state['world']['town'], *state['world']['neighbors']]:
            for good, quote in town['prices'].items():
                self.assertEqual(quote['buy'], world.market_prices[town['id']][good])
                self.assertEqual(quote['sell'], bid_price(world.market_prices[town['id']][good]))
        points = interface.timeline(self.session)['prices']['points']
        self.assertEqual(points[-1]['prices'], {t: dict(p) for t, p in world.market_prices.items()})

    def test_the_menu_is_the_terminals_menu(self):
        menu, options = interface.menu(self.session), self.session.options()
        self.assertEqual([(m['label'], m['section'], m['checked']) for m in menu],
                         [(o['label'], o['section'], o['checked']) for o in options])
        self.assertEqual([{'actor': self.session.player_id, 'type': m['type'], 'params': m['params']} for m in menu],
                         [o['proposal'] for o in options])

    def test_changed_values_follow_the_terminals_rules(self):
        options = self.session.options()
        hire = options[index_of(self.session, 'hire', resource='wood')]
        self.assertEqual(interface.customized(hire, ['3', '1.5']), player_view.customize(hire, '3 1.5'))
        self.assertEqual(interface.customized(hire, None), hire['proposal'])
        for values in (['3'], ['3', '1.5', '2'], ['', '1.5'], ['3', 'lots'], ['30', '1.5'], ['3 4', '1.5'], [3.5, '1']):
            with self.subTest(values=values), self.assertRaises(ValueError):
                interface.customized(hire, values)
        found = options[index_of(self.session, 'form_institution', purpose='cooperative')]
        named = interface.customized(found, ['The Free Traders'])
        self.assertEqual(named['params']['name'], 'The Free Traders')

    def test_a_turn_reports_what_changed_in_the_players_terms(self):
        session = self.session
        before, energy = interface.digest(session), session.person.energy
        session.act(session.options()[index_of(session, 'gather', resource='food')]['proposal'])
        changes = interface.changes(before, interface.digest(session))
        food = next(c for c in changes if c.get('label') == 'Food')
        self.assertEqual((food['before'], food['after'], food['delta'], food['good']), (3., 11., 8., True))
        tired = next(c for c in changes if c.get('label') == 'Energy')
        self.assertEqual((tired['before'], tired['after'], tired['good']), (energy, session.person.energy, False))
        prices = [c for c in changes if c['group'] == 'prices']
        self.assertTrue(prices and prices[0]['label'].endswith('in Rivermark'))  # home first

    def test_the_timeline_follows_the_player_from_town_to_town(self):
        session = PlayableSession.start('Ilsa', 'Rivermark', seed=42)
        session.act(session.options()[index_of(session, 'gather', resource='food')]['proposal'])
        session.act(session.options()[index_of(session, 'migrate', destination=2)]['proposal'])
        while session.observation()['actor'].get('journey'):
            self.assertEqual(interface.state(session)['people'], [])  # nobody walks beside a traveller
            session.act()
        session.act()
        towns = {s.name for s in session.world.settlements}
        cycles = {c['tick']: c for c in interface.timeline(session, limit=50)['cycles']}
        self.assertEqual([cycles[t]['place'] for t in sorted(cycles)],
                         ['Rivermark', 'Rivermark', None, None, 'Deepwood'])
        for tick, cycle in cycles.items():
            for event in cycle['events']:
                if not event['yours']:  # only what happened where the player was
                    source = next(e for e in session.world.events if e['message'] == event['text'] and e['tick'] == tick)
                    self.assertEqual(source['settlement'], cycle['place'])
                    self.assertIn(source['settlement'], towns)
        self.assertEqual(interface.state(session)['world']['town']['name'], 'Deepwood')


class BrowserSessionTests(unittest.TestCase):
    """The browser's controller plays the same session the terminal plays."""

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.game = Game(PlayableSession.start('Ilsa', 'Rivermark', seed=42, years=2), self.folder.name)

    def tearDown(self):
        self.folder.cleanup()

    def play_in_browser(self, game):
        session = game.session
        game.choose(game.version, index_of(session, 'gather', resource='food'), ['5'])
        game.choose(game.version, index_of(session, 'trade', resource='food', direction='sell'), ['4'])
        mara = partner(session, 'Mara')
        game.talk(game.version, mara, next(t['index'] for t in interface.topics(session, mara) if t['topic'] == 'trade'))
        game.choose(game.version, index_of(session, 'form_institution', purpose='cooperative'), ['The Free Traders'])
        game.wait(game.version, 2)
        game.choose(game.version, index_of(session, 'eat'))

    @staticmethod
    def play_in_terminal(session):
        def take(kind, text='', **params):
            choice = next(c for c in session.options() if c['proposal']['type'] == kind
                          and all(c['proposal']['params'].get(k) == v for k, v in params.items()))
            return session.act(player_view.customize(choice, text))
        take('gather', '5', resource='food')
        take('trade', '4', resource='food', direction='sell')
        session.talk(partner(session, 'Mara'), 'trade')
        take('form_institution', 'The Free Traders', purpose='cooperative')
        session.act()
        session.act()
        take('eat')

    def test_a_complete_session_is_played_saved_and_resumed(self):
        """The Stage 4 completion criterion, through the browser's own entry points."""
        game = self.game
        self.play_in_browser(game)
        terminal = PlayableSession.start('Ilsa', 'Rivermark', seed=42, years=2)
        self.play_in_terminal(terminal)
        self.assertEqual(exported(game.session.world), exported(terminal.world))  # the browser adds no rules
        self.assertIn('The Free Traders', [o['name'] for o in interface.state(game.session)['organizations']])

        saved = game.save(game.version, 'ilsa')
        self.assertFalse(game.unsaved)
        self.assertTrue(Path(saved['saved']).exists() and Path(saved['inputs']).exists())
        history = exported(game.session.world)
        listing = game.saves()['saves']
        self.assertEqual([(s['slot'], s['player'], s['tick'], s['replayable']) for s in listing],
                         [('ilsa', 'Ilsa', game.session.world.tick, True)])

        resumed = Game(PlayableSession.start('Other', 'Highfen', seed=7), self.folder.name)
        resumed.load(resumed.version, 'ilsa', 'checkpoint')
        self.assertEqual(exported(resumed.session.world), history)
        replayed = Game(PlayableSession.start('Other', 'Highfen', seed=7), self.folder.name)
        replayed.load(replayed.version, 'ilsa', 'replay')
        self.assertEqual(exported(replayed.session.world), history)
        for other in (resumed, replayed):  # and play continues exactly as if nothing had stopped
            other.choose(other.version, index_of(other.session, 'gather', resource='food'))
        game.choose(game.version, index_of(game.session, 'gather', resource='food'))
        self.assertEqual(exported(resumed.session.world), exported(game.session.world))
        self.assertEqual(exported(replayed.session.world), exported(game.session.world))

    def test_a_request_from_an_outdated_view_changes_nothing(self):
        game = self.game
        game.save(game.version, 'kept')
        old = game.version
        game.wait(old)
        before, session, files = frozen(game.session.world), game.session, sorted(Path(self.folder.name).iterdir())
        for attempt in (lambda: game.wait(old), lambda: game.choose(old, 0),
                        lambda: game.talk(old, partner(game.session, 'Mara'), 0),
                        lambda: game.propose(old, {'type': 'rest', 'params': {}}),
                        lambda: game.save(old, 'other'),  # an old tab neither saves what it never showed
                        lambda: game.load(old, 'kept'),   # nor throws away play it never showed
                        lambda: game.new(old, 'Wren', 'Highfen')):
            with self.assertRaises(Stale):
                attempt()
        self.assertIs(game.session, session)
        self.assertEqual(frozen(game.session.world), before)
        self.assertEqual(sorted(Path(self.folder.name).iterdir()), files)

    def test_a_save_is_a_stamped_pair_written_in_one_step_each(self):
        game, folder = self.game, Path(self.folder.name)
        game.wait(game.version)
        game.save(game.version, 'ilsa')
        pair = lambda: next(s['pair'] for s in game.saves()['saves'] if s['slot'] == 'ilsa')
        self.assertEqual(pair(), 'matched')
        stamp = json.loads((folder / 'ilsa.inputs.json').read_text(encoding='utf-8'))['checkpoint']
        self.assertEqual(stamp['tick'], game.session.world.tick)
        # A crash between the two writes: a newer checkpoint beside the older inputs is detected, not trusted.
        game.wait(game.version)
        game.session.save(folder / 'ilsa.save.json')
        self.assertEqual(pair(), 'mismatched')
        game.save(game.version, 'ilsa')
        self.assertEqual(pair(), 'matched')
        inputs = folder / 'ilsa.inputs.json'
        history = json.loads(inputs.read_text(encoding='utf-8'))
        history.pop('checkpoint')
        inputs.write_text(json.dumps(history), encoding='utf-8')
        self.assertEqual(pair(), 'unverified')  # as the terminal writes them
        inputs.write_text('{"format": "eternia.pl', encoding='utf-8')
        self.assertEqual(pair(), 'unreadable inputs')
        # A write that fails part way leaves the previous file whole and no temporary file behind.
        checkpoint, before = folder / 'ilsa.save.json', (folder / 'ilsa.save.json').read_bytes()
        game.wait(game.version)
        with mock.patch('eternia.persistence.os.replace', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                game.save(game.version, 'ilsa')
        self.assertEqual(checkpoint.read_bytes(), before)
        self.assertEqual(sorted(p.name for p in folder.iterdir() if p.suffix == '.tmp'), [])
        self.assertTrue(game.unsaved)

    def test_a_new_game_or_a_load_keeps_unsaved_play(self):
        game, folder = self.game, Path(self.folder.name)
        game.save(game.version, 'start')
        game.choose(game.version, index_of(game.session, 'gather', resource='food'))
        played = exported(game.session.world)
        response = game.load(game.version, 'start')
        self.assertEqual((response['kept'], game.slot, game.unsaved), ('autosave', 'start', False))
        game.wait(game.version)
        response = game.load(game.version, 'autosave')  # loading the autosave keeps this play elsewhere
        self.assertEqual(response['kept'], 'autosave-previous')
        self.assertEqual(exported(game.session.world), played)
        self.assertTrue((folder / 'autosave-previous.save.json').exists())
        self.assertIsNone(game.load(game.version, 'start')['kept'])  # nothing unsaved, nothing to keep
        game.wait(game.version)
        self.assertEqual(game.new(game.version, 'Wren', 'Highfen')['kept'], 'autosave')

    def test_a_changed_choice_the_rules_would_refuse_spends_nothing(self):
        game = self.game
        tick, log = game.session.world.tick, len(game.session.world.player_log)
        response = game.choose(game.version, index_of(game.session, 'hire', resource='wood'), ['24', '5'])
        self.assertIn('refused', response)  # 120 coins of wages from a purse of 10
        self.assertEqual((game.session.world.tick, len(game.session.world.player_log)), (tick, log))
        with self.assertRaises(ValueError):
            game.choose(game.version, index_of(game.session, 'hire', resource='wood'), ['25', '1'])  # outside the field
        with self.assertRaises(ValueError):
            game.choose(game.version, 999)

    def test_waiting_runs_whole_cycles_for_everyone(self):
        game = self.game
        tick = game.session.world.tick
        turn = game.wait(game.version, 4)['turn']
        self.assertEqual((game.session.world.tick, turn['cycles'], turn['start']['tick'], turn['end']['tick']),
                         (tick + 4, 4, tick, tick + 4))
        self.assertTrue(all(r['type'] == 'wait' for r in turn['results']))
        for cycles in (0, 41, '4'):
            with self.assertRaises(ValueError):
                game.wait(game.version, cycles)

    def test_saves_stay_in_their_folder_and_unsaved_play_is_kept(self):
        game = self.game
        for slot in ('../escape', 'a/b', '', '.hidden', 'x' * 41, 'C:\\temp\\x', None):
            with self.subTest(slot=slot), self.assertRaises(ValueError):
                game.save(game.version, slot)
        with self.assertRaises(ValueError):
            game.load(game.version, 'missing')
        self.assertIsNone(game.close())  # nothing played, nothing to keep
        game.wait(game.version)
        kept = Path(game.close())
        self.assertEqual(kept.name, 'autosave.save.json')
        self.assertEqual(kept.parent.resolve(), Path(self.folder.name).resolve())

    def test_an_ended_household_can_be_read_but_not_played(self):
        game = self.game
        game.wait(game.version)
        game.session.world.players.clear()  # no living character or heir remains
        view = game.view()
        self.assertTrue(view['over'])
        self.assertTrue(view['journal']['people'] and view['latest'])
        self.assertNotIn('menu', view)
        before = frozen(game.session.world)
        for attempt in (lambda: game.wait(game.version), lambda: game.choose(game.version, 0)):
            with self.assertRaises(ValueError):
                attempt()
        self.assertEqual(frozen(game.session.world), before)

    def test_a_new_game_is_validated_and_replaces_the_old(self):
        game = self.game
        for bad in (dict(seed=-1), dict(years=201), dict(policy_style='greedy'), dict(home='Atlantis'), dict(name='')):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                game.new(game.version, **{**dict(name='Wren', home='Highfen', seed=3, policy_style='balanced', years=0), **bad})
        old = game.version
        state = game.new(game.version, 'Wren', 'Highfen', 3, 'personal', 1)['state']
        self.assertNotEqual(state['version'], old)
        self.assertEqual((state['character']['name'], state['character']['town'], state['settings']),
                         ('Wren', 'Highfen', {'seed': 3, 'policy_style': 'personal'}))


class ServerTests(unittest.TestCase):
    """The local server serves the page and answers only that page."""

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.game = Game(PlayableSession.start('Ilsa', 'Rivermark', seed=42), self.folder.name)
        self.server, self.url, self.token = make_server(self.game, port=0)
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs=dict(poll_interval=.05), daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.folder.cleanup()

    def request(self, path, body=None, headers=None, token=True, method=None):
        sent = {'Content-Type': 'application/json', **({'X-Eternia-Token': self.token} if token else {}), **(headers or {})}
        data = body if isinstance(body, bytes) else None if body is None else json.dumps(body).encode()
        request = urllib.request.Request(self.url.rstrip('/') + path, data=data, headers=sent, method=method)
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                return response.status, response.headers, response.read()
        except urllib.error.HTTPError as error:
            return error.code, error.headers, error.read()

    def test_the_page_carries_its_token_and_a_strict_policy(self):
        status, headers, body = self.request('/', token=False)
        self.assertEqual(status, 200)
        self.assertIn(self.token, body.decode())
        self.assertIn("script-src 'self'", headers['Content-Security-Policy'])
        for path in ('/app.js', '/style.css'):
            self.assertEqual(self.request(path, token=False)[0], 200)
        self.assertEqual(self.request('/../main.py', token=False)[0], 404)

    def test_only_the_served_page_on_this_machine_may_use_the_api(self):
        self.assertEqual(self.request('/api/state', token=False)[0], 403)
        self.assertEqual(self.request('/api/state', headers={'X-Eternia-Token': 'guess'}, token=False)[0], 403)
        self.assertEqual(self.request('/api/state', headers={'Host': 'attacker.example'})[0], 403)  # DNS rebinding
        version = json.loads(self.request('/api/state')[2])['version']
        status, _, _ = self.request('/api/wait', {'version': version}, headers={'Origin': 'http://attacker.example'})
        self.assertEqual(status, 403)
        self.assertEqual(self.game.session.world.tick, 0)  # none of it reached the world
        self.assertEqual(self.request('/report', token=False)[0], 403)

    def test_a_turn_through_http(self):
        status, _, body = self.request('/api/state')
        state = json.loads(body)
        self.assertEqual(status, 200)
        gather = next(c for c in state['menu'] if c['type'] == 'gather')
        status, _, body = self.request('/api/choose', {'version': state['version'], 'index': gather['index'], 'values': ['4']})
        turn = json.loads(body)
        self.assertEqual((status, turn['turn']['results'][0]['text']), (200, 'Ilsa gathered 4 food in Rivermark.'))
        status, _, body = self.request('/api/choose', {'version': state['version'], 'index': gather['index']})
        self.assertEqual(status, 409)  # a second click from the old page
        self.assertEqual(json.loads(body)['state']['version'], turn['state']['version'])
        self.assertEqual(self.game.session.world.tick, 1)
        status, _, body = self.request('/api/choose', {'version': turn['state']['version'], 'index': 'one'})
        self.assertEqual((status, json.loads(body)['error']), (400, 'index must be a number.'))
        self.assertEqual(self.request('/api/choose', b'not json')[0], 400)
        self.assertEqual(self.request('/api/choose', b'{' + b' ' * 70000 + b'}')[0], 413)
        self.assertEqual(self.request('/api/unknown', {})[0], 404)
        partner_id = turn['state']['people'][0]['id']
        status, _, body = self.request(f'/api/topics?partner={partner_id}')
        self.assertEqual((status, json.loads(body)['partner']), (200, partner_id))
        status, _, body = self.request('/api/timeline?limit=5')
        self.assertEqual(status, 200)
        self.assertIn('Ilsa gathered 4 food in Rivermark.',
                      [a['text'] for c in json.loads(body)['cycles'] for a in c['actions']])


class CommandLineTests(unittest.TestCase):
    def test_web_arguments_are_checked(self):
        for extra in (['--save', 'x.json'], ['--port', '70000'], ['--years', '500'], ['--ticks-per-year', '2']):
            with self.subTest(extra=extra):
                result = subprocess.run([sys.executable, 'main.py', '--web', '--no-browser', *extra], cwd=ROOT,
                                        capture_output=True, text=True, timeout=60)
                self.assertEqual(result.returncode, 2, result.stderr)


if __name__ == '__main__':
    unittest.main()
