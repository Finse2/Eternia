"""v0.8 Stage 4: play Eternia in a browser, served from this computer.

``python main.py --web`` starts a small server on 127.0.0.1 and opens the game
in the default browser. Python stays the only authority: the page sends a
menu choice by its number (with any changed values), a question, a wait or a
save, and gets back a view built by ``interface.py``. It never computes a
price, resolves an action or changes anyone's state itself.

Every request that changes the world names the version of the view it was made
from; one made from a view the world has since moved past is refused, so a
double click cannot spend two seasons or pick a choice that has changed.

The server uses only the standard library and accepts requests only from the
page it served: it listens on the loopback address, checks the Host header,
and requires a token minted at launch and embedded in that page.
"""
from datetime import datetime
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import threading
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from . import interface
from .playable_session import PlayableSession

ASSETS = Path(__file__).resolve().parent / 'webui'
STATIC = {'/app.js': ('app.js', 'text/javascript; charset=utf-8'),
          '/style.css': ('style.css', 'text/css; charset=utf-8')}
SLOT = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_-]{0,39}$')
POLICY_STYLES = ('balanced', 'personal', 'collective')
MAX_BODY = 64 * 1024
MAX_WAIT = 40  # cycles one wait may run: ten years
AUTOSAVE = 'autosave'
CSP = ("default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; "
       "base-uri 'none'; form-action 'none'; frame-ancestors 'none'")


class Stale(ValueError):
    """A request made from a view the world has since moved past."""


class Game:
    """One browser-played session and its save folder; every change goes through PlayableSession."""

    def __init__(self, session, folder, slot=None):
        self.session = session
        self.folder = Path(folder)
        self.serial = 0
        self.slot = slot
        self.unsaved = False
        self.last_turn = None
        self.lock = threading.RLock()

    @property
    def version(self):
        world = self.session.world
        return f'{self.serial}.{world.tick}.{len(world.player_log)}'

    def view(self):
        with self.lock:
            out = interface.state(self.session)
            out.update(version=self.version, last_turn=self.last_turn, slot=self.slot, unsaved=self.unsaved,
                       folder=str(self.folder.resolve()))
            return out

    def _current(self, version):
        if version != self.version:
            raise Stale('The world has moved on since this page was drawn, so nothing was done. '
                        'The page now shows the present; choose again.')

    # ----- Playing ------------------------------------------------------------

    def choose(self, version, index, values=None):
        """Take menu choice ``index``, with one value per field if any were changed."""
        with self.lock:
            self._current(version)
            choices = self.session.options()
            if type(index) is not int or not 0 <= index < len(choices):
                raise ValueError('There is no such choice now.')
            choice = choices[index]
            proposal = interface.customized(choice, values)
            if proposal != choice['proposal']:  # a changed choice is checked first, as in the terminal
                check = self.session.check(proposal)
                if check is not None and not check.success:
                    return dict(refused=dict(code=check.code, message=f'That would be refused: {check.message} '
                                                                      'Nothing was spent; choose again.'),
                                state=self.view())
            return self._play(proposal, 1)

    def propose(self, version, proposal):
        """Any action the engine knows, written by hand, as the terminal's j command."""
        with self.lock:
            self._current(version)
            if not isinstance(proposal, dict):
                raise ValueError('Write the action as a JSON object, for example {"type": "rest", "params": {}}.')
            return self._play(proposal, 1)

    def wait(self, version, cycles=1):
        with self.lock:
            self._current(version)
            if type(cycles) is not int or not 1 <= cycles <= MAX_WAIT:
                raise ValueError(f'Wait 1 to {MAX_WAIT} cycles at a time.')
            return self._play(None, cycles)

    def _play(self, proposal, cycles):
        session = self.session
        if session.player_id is None:
            raise ValueError('Your household has ended. Start a new life or load a save.')
        before, start = interface.digest(session), session.world.tick
        results, events, note = [], [], None
        for _ in range(cycles):
            if session.player_id is None:
                break
            try:
                outcome = session.act(proposal)
            except ValueError as error:
                if not results:
                    raise
                note = str(error)
                break
            result = outcome['result']
            results.append(dict(tick=outcome['tick'], type=outcome['action'].get('type'), success=result['success'],
                                code=result['code'], text=result['message']))
            events.extend(dict(tick=e['tick'], kind=e.get('kind'), text=e['message'], routine=interface.routine(e))
                          for e in outcome['events'] if e['message'] != result['message'])
        self.unsaved = True
        self.last_turn = dict(start=interface.when(start, session.world.ticks_per_year), end=interface.clock(session.world),
                              cycles=len(results), results=results, events=events, note=note,
                              changes=interface.changes(before, interface.digest(session)),
                              over=session.player_id is None)
        return dict(turn=self.last_turn, state=self.view())

    # ----- Talking --------------------------------------------------------------

    def topics(self, partner):
        with self.lock:
            return dict(partner=partner, version=self.version, topics=interface.topics(self.session, partner))

    def talk(self, version, partner, index, values=None):
        """Ask or tell one person something; no season passes, and it is recorded for replay."""
        with self.lock:
            self._current(version)
            if type(partner) is not int:
                raise ValueError('Choose someone to talk to.')
            questions = interface.topics(self.session, partner)  # refuses someone who is not here
            if type(index) is not int or not 0 <= index < len(questions):
                raise ValueError('There is no such question now.')
            asked = interface.customized(self.session.conversation(partner)[index], values)
            reply = self.session.talk(partner, asked['type'], **asked['params'])
            self.unsaved = True
            return dict(reply=dict(partner=partner, name=reply['speaker_name'], topic=reply['topic'],
                                   lines=list(reply['lines']), learned=len(reply['learned']),
                                   declined=bool(reply.get('declined'))),
                        state=self.view())

    def timeline(self, limit=interface.TIMELINE_LIMIT):
        with self.lock:
            if type(limit) is not int or not 1 <= limit <= 100000:
                raise ValueError('Ask for 1 or more cycles of history.')
            return dict(version=self.version, **interface.timeline(self.session, limit))

    # ----- Saving and resuming -------------------------------------------------

    def _paths(self, slot):
        if type(slot) is not str or not SLOT.match(slot):
            raise ValueError('A save name is 1 to 40 letters, digits, - or _, starting with a letter or digit.')
        return self.folder / f'{slot}.save.json', self.folder / f'{slot}.inputs.json'

    def _inputs(self, slot):
        """A slot's recorded inputs; the terminal's world.save.json keeps them in inputs.json."""
        _, inputs = self._paths(slot)
        if inputs.exists():
            return inputs
        legacy = self.folder / 'inputs.json'
        return legacy if slot == 'world' and legacy.exists() else None

    def saves(self):
        with self.lock:
            out = []
            if not self.folder.is_dir():
                return dict(folder=str(self.folder.resolve()), saves=out)
            for path in sorted(self.folder.glob('*.save.json'), key=lambda p: -p.stat().st_mtime):
                slot = path.name[:-len('.save.json')]
                if not SLOT.match(slot):
                    continue
                entry = dict(slot=slot, saved=datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec='seconds'),
                             size=path.stat().st_size, replayable=False, tick=None, player=None, seed=None)
                inputs = self._inputs(slot)
                if inputs is not None:
                    try:
                        history = json.loads(inputs.read_text(encoding='utf-8'))
                        joined = next((i for i in history.get('inputs', []) if i.get('event') == 'joined'), {})
                        entry.update(replayable=True, tick=history.get('tick'), player=joined.get('name'),
                                     seed=history.get('settings', {}).get('seed'))
                    except (ValueError, OSError, AttributeError):
                        pass
                out.append(entry)
            return dict(folder=str(self.folder.resolve()), saves=out)

    def save(self, slot):
        """A checkpoint between turns and the inputs that replay it."""
        with self.lock:
            checkpoint, inputs = self._paths(slot)
            self.session.save(checkpoint)
            inputs.write_text(json.dumps(self.session.input_history(), indent=2, allow_nan=False), encoding='utf-8')
            self.slot, self.unsaved = slot, False
            return dict(saved=str(checkpoint.resolve()), inputs=str(inputs.resolve()), state=self.view())

    def load(self, slot, method='checkpoint'):
        """Resume a checkpoint exactly, or rebuild the session from its recorded inputs."""
        with self.lock:
            checkpoint, _ = self._paths(slot)
            if method == 'checkpoint':
                if not checkpoint.exists():
                    raise ValueError(f'There is no save called {slot}.')
                try:
                    session = PlayableSession.load(checkpoint)
                except ValueError as error:
                    if self._inputs(slot) is None:
                        raise
                    raise ValueError(f'{error}. Replay rebuilds this save from its recorded inputs instead.') from None
            elif method == 'replay':
                inputs = self._inputs(slot)
                if inputs is None:
                    raise ValueError(f'The save {slot} has no recorded inputs to replay.')
                try:
                    session = PlayableSession.replay(json.loads(inputs.read_text(encoding='utf-8')))
                except (KeyError, TypeError, AttributeError) as error:
                    raise ValueError(f'The recorded inputs cannot be replayed: {error}') from None
            else:
                raise ValueError('Resume from the checkpoint or replay the inputs.')
            if session.player_id is None and not session.world.player_log:
                raise ValueError('That save holds a society nobody plays; start it with --web and the file.')
            self._replace(session, slot)
            return dict(loaded=slot, method=method, state=self.view())

    def new(self, name='Wanderer', home='Rivermark', seed=42, policy_style='balanced', years=0):
        with self.lock:
            if type(seed) is not int or not 0 <= seed <= 2 ** 31:
                raise ValueError('The seed is a whole number from 0 to 2147483648.')
            if policy_style not in POLICY_STYLES:
                raise ValueError('Priorities are balanced, personal or collective.')
            if type(years) is not int or not 0 <= years <= 200:
                raise ValueError('History before you arrive is 0 to 200 years.')
            if type(name) is not str or type(home) is not str:
                raise ValueError('Give a name and a home town.')
            session = PlayableSession.start(name, home, seed=seed, policy_style=policy_style, years=years)
            self._replace(session, None)
            self.unsaved = True
            return dict(started=True, state=self.view())

    def _replace(self, session, slot):
        self.session, self.slot, self.unsaved, self.last_turn = session, slot, False, None
        self.serial += 1

    def export(self):
        """The historian's record of this session, as the terminal writes it on quitting."""
        with self.lock:
            folder = self.session.write_outputs(self.folder)
            return dict(folder=str(folder.resolve()), report=str((folder / 'report.html').resolve()))

    def close(self):
        """Keep unsaved play when the server stops."""
        with self.lock:
            if self.unsaved and self.session.world.player_log:
                return self.save(AUTOSAVE)['saved']
            return None


# ----- The local server --------------------------------------------------------

def _routes(game):
    def get(payload, key, kind, default=None):
        value = payload.get(key, default)
        if kind is not None and value is not None and type(value) is not kind:
            raise ValueError(f'{key} must be {"a number" if kind is int else "text" if kind is str else "a list"}.')
        return value

    return {
        ('GET', 'state'): lambda p: game.view(),
        ('GET', 'saves'): lambda p: game.saves(),
        ('GET', 'timeline'): lambda p: game.timeline(_integer(p.get('limit', interface.TIMELINE_LIMIT))),
        ('GET', 'topics'): lambda p: game.topics(_integer(p.get('partner'))),
        ('POST', 'choose'): lambda p: game.choose(get(p, 'version', str), get(p, 'index', int), get(p, 'values', list)),
        ('POST', 'propose'): lambda p: game.propose(get(p, 'version', str), p.get('proposal')),
        ('POST', 'wait'): lambda p: game.wait(get(p, 'version', str), get(p, 'cycles', int, 1)),
        ('POST', 'talk'): lambda p: game.talk(get(p, 'version', str), get(p, 'partner', int), get(p, 'index', int),
                                              get(p, 'values', list)),
        ('POST', 'save'): lambda p: game.save(get(p, 'slot', str)),
        ('POST', 'load'): lambda p: game.load(get(p, 'slot', str), get(p, 'method', str, 'checkpoint')),
        ('POST', 'new'): lambda p: game.new(get(p, 'name', str, 'Wanderer'), get(p, 'home', str, 'Rivermark'),
                                            get(p, 'seed', int, 42), get(p, 'policy_style', str, 'balanced'),
                                            get(p, 'years', int, 0)),
        ('POST', 'export'): lambda p: game.export(),
    }


def _integer(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ValueError('Expected a whole number.') from None


def make_handler(game, token):
    routes = _routes(game)

    class Handler(BaseHTTPRequestHandler):
        server_version = 'Eternia'
        sys_version = ''

        def log_message(self, format, *args):  # keep the terminal for the game's own messages
            pass

        def _origins(self):
            port = self.server.server_address[1]
            return {f'127.0.0.1:{port}', f'localhost:{port}'}

        def _send(self, status, body, content_type, page=False):
            data = body.encode('utf-8') if isinstance(body, str) else body
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('X-Frame-Options', 'DENY')
            if page:
                self.send_header('Content-Security-Policy', CSP)
            self.end_headers()
            self.wfile.write(data)

        def _json(self, status, payload):
            self._send(status, json.dumps(interface.clean(payload), allow_nan=False), 'application/json; charset=utf-8')

        def _trusted(self, check_token=True):
            """Only the page this server served, on this machine, may use it."""
            if self.headers.get('Host', '') not in self._origins():
                self._json(403, dict(error='Open the game at the address the server printed.'))
                return False
            origin = self.headers.get('Origin')
            if origin is not None and origin.removeprefix('http://') not in self._origins():
                self._json(403, dict(error='Requests from other sites are refused.'))
                return False
            if check_token and not hmac.compare_digest(self.headers.get('X-Eternia-Token', '').encode('utf-8'),
                                                       token.encode('utf-8')):
                self._json(403, dict(error='This page was opened before the server restarted; reload it.'))
                return False
            return True

        def do_GET(self):
            url = urlsplit(self.path)
            if url.path in ('/', '/index.html'):
                if self._trusted(check_token=False):
                    page = (ASSETS / 'index.html').read_text(encoding='utf-8').replace('{{TOKEN}}', token)
                    self._send(200, page, 'text/html; charset=utf-8', page=True)
                return
            if url.path in STATIC:
                if self._trusted(check_token=False):
                    name, kind = STATIC[url.path]
                    self._send(200, (ASSETS / name).read_bytes(), kind)
                return
            if url.path == '/report':
                if not self._trusted(check_token=False):
                    return
                given = parse_qs(url.query).get('token', [''])[-1]
                report = game.folder / 'report.html'
                if not hmac.compare_digest(given.encode('utf-8'), token.encode('utf-8')):
                    self._json(403, dict(error='Open the report from the game page.'))
                elif not report.exists():
                    self._json(404, dict(error='Write the report from the game page first.'))
                else:
                    self._send(200, report.read_bytes(), 'text/html; charset=utf-8')
                return
            if url.path.startswith('/api/'):
                if self._trusted():
                    self._dispatch('GET', url.path[5:], {k: v[-1] for k, v in parse_qs(url.query).items()})
                return
            if self._trusted(check_token=False):
                self._json(404, dict(error='Not found.'))

        def do_POST(self):
            url = urlsplit(self.path)
            if not self._trusted():
                return
            try:
                length = int(self.headers.get('Content-Length') or 0)
            except ValueError:
                length = -1
            if not 0 <= length <= MAX_BODY:
                if MAX_BODY < length <= 16 * MAX_BODY:
                    self.rfile.read(length)  # take it off the wire so the answer arrives cleanly
                self._json(413, dict(error='That request is too large.'))
                return
            try:
                payload = json.loads(self.rfile.read(length) or b'{}')
                if not isinstance(payload, dict):
                    raise ValueError
            except ValueError:
                self._json(400, dict(error='Send a JSON object.'))
                return
            self._dispatch('POST', url.path.removeprefix('/api/'), payload)

        def _dispatch(self, method, name, payload):
            route = routes.get((method, name))
            if route is None:
                self._json(404, dict(error='Not found.'))
                return
            try:
                self._json(200, route(payload))
            except Stale as error:
                self._json(409, dict(error=str(error), state=game.view()))
            except (ValueError, OSError) as error:
                self._json(400, dict(error=str(error)))
            except Exception:  # a bug, not a refusal: say so and keep serving
                traceback.print_exc()
                self._json(500, dict(error='The simulation server hit an unexpected error; see its terminal.'))

    return Handler


class _Server(ThreadingHTTPServer):
    # On Windows, SO_REUSEADDR would let a second server take a port that is already in use.
    allow_reuse_address = os.name != 'nt'
    daemon_threads = True


def make_server(game, port=8765, host='127.0.0.1'):
    """A server for ``game`` on the loopback address; port 0 or a busy port picks a free one."""
    token = secrets.token_urlsafe(24)
    handler = make_handler(game, token)
    try:
        server = _Server((host, port), handler)
    except OSError:
        if port == 0:
            raise
        server = _Server((host, 0), handler)
    server.daemon_threads = True
    return server, f'http://127.0.0.1:{server.server_address[1]}/', token


def serve(game, port=8765, open_browser=True, say=print):
    server, url, _ = make_server(game, port)
    say(f'Eternia is running at {url}')
    say('Play in the browser; press Ctrl+C here to stop. Unsaved play is kept as '
        f'{(game.folder / (AUTOSAVE + ".save.json")).resolve()}')
    if open_browser:
        import webbrowser
        threading.Timer(.3, webbrowser.open, args=(url,)).start()
    try:
        server.serve_forever(poll_interval=.25)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        saved = game.close()
        if saved:
            say(f'Saved unsaved play: {saved}')
    return url
