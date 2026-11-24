"""v0.8.1: the browser interface, clicked through in a real browser.

Every test drives the page the way a player does (clicks, typed values, the
dialogs) against a live local server, then checks the world the server holds,
not just what the page says.

These tests need Playwright and a Chromium-based browser:

    python -m pip install -r requirements-browser.txt
    python -m playwright install chromium

Set ETERNIA_BROWSER=msedge (or chrome) to use an installed browser instead of
downloading one. Without Playwright the tests are skipped, so the main suite
still needs only the standard library; CI runs them in their own job, with
ETERNIA_BROWSER_TESTS=required so that a missing browser fails instead.
ETERNIA_SCREENSHOTS=folder keeps a screenshot of every tab in both themes.
"""
import json
import os
from pathlib import Path
import re
import tempfile
import threading
import unittest

from eternia.playable_session import PlayableSession
from eternia.web import Game, make_server

try:
    from playwright.sync_api import expect, sync_playwright
except ImportError:  # the optional browser tests
    sync_playwright = None

REQUIRED = os.environ.get('ETERNIA_BROWSER_TESTS') == 'required'
CHANNEL = os.environ.get('ETERNIA_BROWSER') or None
SCREENSHOTS = os.environ.get('ETERNIA_SCREENSHOTS')
TABS = (('Act', 'Needs'), ('Town & roads', 'The region'), ('People', 'People in Rivermark'),
        ('Economy', 'The Rivermark market'), ('Politics', 'Found an organization'),
        ('Timeline', 'Posted prices since you arrived'), ('Journal', 'Every transaction'))


def exported(world):
    data = world.export()
    data.pop('provenance', None)
    return json.dumps(data, sort_keys=True)


@unittest.skipIf(sync_playwright is None and not REQUIRED, 'Playwright is not installed (see requirements-browser.txt)')
class BrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(channel=CHANNEL, headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.game = Game(PlayableSession.start('Ilsa', 'Rivermark', seed=42, years=2), self.folder.name)
        self.server, self.url, _ = make_server(self.game, port=0)
        threading.Thread(target=self.server.serve_forever, kwargs=dict(poll_interval=.05), daemon=True).start()
        self.errors = []
        self.context = self.browser.new_context(viewport={'width': 1400, 'height': 1000})
        self.page = self.open()

    def tearDown(self):
        self.context.close()
        self.server.shutdown()
        self.server.server_close()
        self.folder.cleanup()
        self.assertEqual(self.errors, [], 'the page raised errors')

    # ----- Helpers ---------------------------------------------------------------

    def open(self, hash='', context=None):
        page = (context or self.context).new_page()
        page.set_default_timeout(20000)
        page.on('pageerror', lambda error: self.errors.append(f'{error}'))
        # Refused requests (409, 400) are part of these tests; the browser logs them as failed loads.
        page.on('console', lambda message: message.type == 'error' and not message.text.startswith(
            'Failed to load resource') and self.errors.append(message.text))
        page.on('dialog', lambda dialog: dialog.accept())  # "leave unsaved play?" is answered yes
        page.goto(self.url + hash)
        expect(page.locator('.sidebar h2')).to_have_text('Ilsa')
        return page

    def idle(self, page=None):
        expect((page or self.page).locator('.busy-note')).to_have_count(0)

    def tab(self, name, page=None):
        page = page or self.page
        page.get_by_role('tab', name=re.compile('^' + re.escape(name))).click()
        self.idle(page)

    def choice(self, text, page=None):
        """The first menu choice whose label starts with ``text``."""
        return (page or self.page).locator('.choice', has_text=re.compile('^' + re.escape(text))).first

    def choose(self, text, *values, page=None):
        page = page or self.page
        row = self.choice(text, page)
        for field, value in zip(row.locator('input').all(), values):
            field.fill(str(value))
        row.get_by_role('button', name='Choose').click()
        self.idle(page)

    def open_section(self, name):
        section = self.page.locator('details.section', has=self.page.locator('summary', has_text=name)).first
        if section.get_attribute('open') is None:
            section.locator('summary').click()
        return section

    def clock(self, page=None):
        return (page or self.page).locator('.clock')

    def dialog(self, page=None):
        page = page or self.page
        page.get_by_role('button', name='Save & load').click()
        dialog = page.locator('#game-dialog')
        expect(dialog.locator('tbody, .empty').first).to_be_visible()
        return dialog

    # ----- Tests ------------------------------------------------------------------

    def test_every_tab_renders_and_a_choice_spends_one_season(self):
        page, world = self.page, self.game.session.world
        expect(self.clock()).to_contain_text('cycle 8')
        for name, heading in TABS:
            self.tab(name)
            expect(page.locator('main')).to_contain_text(heading)
        self.tab('Act')
        self.choose('Gather', 3)
        expect(page.locator('.season')).to_contain_text('Ilsa gathered 3 food in Rivermark.')
        expect(self.clock()).to_contain_text('cycle 9')
        expect(page.locator('.tile', has_text='Food').locator('.value')).to_have_text('6')
        expect(page.locator('.season .changes').first).to_contain_text('Food')
        self.assertEqual((world.tick, self.game.session.person.inventory['food']), (9, 6.))

    def test_a_changed_choice_the_rules_would_refuse_spends_nothing(self):
        self.open_section('Trade and hiring')
        self.choose('Hire workers to gather', 24, 5)  # 120 coins of wages from a purse of 10
        expect(self.page.locator('.toast.warn')).to_contain_text('That would be refused')
        expect(self.clock()).to_contain_text('cycle 8')
        self.assertEqual((self.game.session.world.tick, self.game.unsaved), (8, False))

    def test_talking_to_someone_takes_no_season(self):
        page, world = self.page, self.game.session.world
        self.tab('People')
        page.locator('.person', has_text='Mara of Rivermark').click()
        page.get_by_role('button', name='Ask about trade and the roads').click()
        self.idle()
        talk = world.player_log[-1]
        self.assertEqual((talk['event'], talk['topic'], world.tick), ('talk', 'trade', 8))
        for line in talk['lines']:
            expect(page.locator('.chat .bubble', has_text=line).first).to_be_visible()
        expect(page.locator('.card', has_text='Ask or tell')).to_contain_text('2 of 3 answers left this season')
        expect(self.clock()).to_contain_text('cycle 8')

    def test_travelling_to_another_town(self):
        page = self.page
        self.choose('Gather')  # food for the road and a possible return
        self.tab('Town & roads')
        page.locator('svg.map g.town[aria-label^="Deepwood"]').click()
        self.choose('Move to Deepwood')
        expect(page.locator('.sidebar')).to_contain_text('Travelling from Rivermark to Deepwood')
        self.tab('People')
        expect(page.locator('main')).to_contain_text('nobody is walking beside you')
        for _ in range(8):
            if self.game.session.observation()['actor'].get('journey') is None:
                break
            page.get_by_role('button', name='Wait a season').click()
            self.idle()
        expect(page.locator('.sidebar')).to_contain_text('in Deepwood')
        self.tab('Town & roads')
        expect(page.locator('.card', has_text='Where you live')).to_contain_text('Deepwood')
        self.assertEqual(self.game.session.observation()['settlement']['name'], 'Deepwood')

    def test_saving_resuming_and_replaying_in_the_browser(self):
        page = self.page
        self.choose('Gather')
        dialog = self.dialog()
        dialog.locator('#save-slot').fill('trip')
        dialog.get_by_role('button', name='Save', exact=True).click()
        self.idle()
        expect(page.locator('.toast.good').last).to_contain_text('Saved to')
        expect(dialog.locator('tr', has_text='trip')).to_be_visible()
        saved = exported(self.game.session.world)
        dialog.get_by_role('button', name='Close').click()

        page.get_by_role('button', name='Wait a season').click()
        self.idle()
        expect(self.clock()).to_contain_text('cycle 10')
        dialog = self.dialog()
        dialog.locator('tr', has_text='trip').get_by_role('button', name='Resume').click()  # unsaved play: confirmed
        self.idle()
        expect(page.locator('.toast.good').last).to_contain_text('kept as "autosave"')
        expect(self.clock()).to_contain_text('cycle 9')
        self.assertEqual(exported(self.game.session.world), saved)

        dialog = self.dialog()
        expect(dialog.locator('tr', has_text='autosave')).to_be_visible()
        dialog.locator('tr', has_text='trip').get_by_role('button', name='Replay').click()
        self.idle()
        expect(page.locator('.toast.good').last).to_contain_text('Rebuilt trip from its recorded inputs')
        expect(self.clock()).to_contain_text('cycle 9')
        self.assertEqual(exported(self.game.session.world), saved)

    def test_an_old_tab_cannot_spend_a_second_season_or_discard_play(self):
        first, second = self.page, self.open()
        first.get_by_role('button', name='Wait a season').click()
        self.idle(first)
        expect(self.clock(first)).to_contain_text('cycle 9')
        second.get_by_role('button', name='Wait a season').click()  # drawn at cycle 8
        self.idle(second)
        expect(second.locator('.toast.error')).to_contain_text('The world has moved on')
        expect(self.clock(second)).to_contain_text('cycle 9')  # it now shows the present
        self.assertEqual(self.game.session.world.tick, 9)

        session = self.game.session
        first.get_by_role('button', name='Wait a season').click()
        self.idle(first)
        dialog = self.dialog(second)  # still drawn at cycle 9
        dialog.get_by_role('button', name='Start').click()
        self.idle(second)
        expect(second.locator('.toast.error').last).to_contain_text('The world has moved on')
        self.assertIs(self.game.session, session)
        self.assertEqual(self.game.session.world.tick, 10)

    def test_the_timeline_draws_prices_and_answers_hovering(self):
        page = self.page
        self.choose('Gather')
        page.get_by_role('button', name='Wait a year').click()
        self.idle()
        self.tab('Timeline')
        charts = page.locator('.chart')
        expect(charts).to_have_count(3)
        expect(charts.first.locator('path.series')).to_have_count(3)
        charts.first.locator('rect.hit').hover()
        expect(charts.first.locator('.tooltip')).to_be_visible()
        expect(charts.first.locator('.tooltip')).to_contain_text('Rivermark')
        expect(page.locator('.cycle', has_text='Ilsa gathered 8 food in Rivermark.')).to_be_visible()

    def test_both_themes_render_every_tab(self):
        for scheme in ('light', 'dark'):
            context = self.browser.new_context(viewport={'width': 1400, 'height': 1000}, color_scheme=scheme)
            try:
                page = self.open(context=context)
                for name, heading in TABS:
                    self.tab(name, page)
                    expect(page.locator('main')).to_contain_text(heading)
                    if SCREENSHOTS:
                        Path(SCREENSHOTS).mkdir(parents=True, exist_ok=True)
                        slug = re.sub(r'[^a-z]+', '-', name.lower()).strip('-')
                        page.screenshot(path=str(Path(SCREENSHOTS) / f'{scheme}-{slug}.png'), full_page=True)
            finally:
                context.close()


if __name__ == '__main__':
    unittest.main()
