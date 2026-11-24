"""v0.8: a turn-based session in which one person in the society is played by a human.

Each turn the player chooses one proposal from their own observation. The
session queues it and runs one ordinary world cycle: every autonomous person
plans from the same tick-start snapshot, all proposals, the player's included,
resolve together in the world's seeded order, and needs, relationships, minds
and time then advance as usual. Nothing the player does skips that cycle.

The world records every player input in ``player_log``: who joined, where and
with what, and which proposal they chose at which cycle. Replaying those inputs
on a new world with the same settings reproduces the session exactly, and a
checkpoint saved between turns resumes it exactly.

Stage 2 adds guided choices for every action the engine knows (``player.py``)
and a journal of the player's earnings, work, memberships, votes and
relationships (``player_history.py``), both derived from the world's own state.
"""
from copy import deepcopy

from . import player as player_view
from .persistence import load_world, save_world
from .society import SocietyWorld

HISTORY_FORMAT = 'eternia.play.v1'
SETTINGS = ('seed', 'ticks_per_year', 'shock_year', 'policy_style', 'adaptive_goals')


class PlayableSession:
    """One human player in a v0.7 society; the world stays the only authority."""

    def __init__(self, world):
        if type(world) is not SocietyWorld:
            raise ValueError('Play needs a v0.7 society world (python main.py --society).')
        self.world = world

    # ----- Starting, saving and resuming ---------------------------------

    @classmethod
    def start(cls, name='Wanderer', home='Rivermark', *, seed=42, policy_style='balanced',
              inventory=None, years=0, ticks_per_year=4, adaptive_goals=True):
        """A new society; after ``years`` of autonomous history the player arrives in ``home``."""
        world = SocietyWorld(seed=seed, ticks_per_year=ticks_per_year, policy_style=policy_style,
                             adaptive_goals=adaptive_goals)
        world.run(years)
        session = cls(world)
        session.join(name, home, inventory)
        return session

    @classmethod
    def load(cls, path):
        return cls(load_world(path))

    def join(self, name='Wanderer', home='Rivermark', inventory=None):
        """Bring the player into a world that has none (for example a saved society)."""
        if self.player_id is not None:
            raise ValueError('This session already has a player; Stage 1 plays one person at a time.')
        return self.world.add_player(name, home, inventory)

    def save(self, path):
        return save_world(self.world, path)

    def write_outputs(self, output):
        """The record of a session: history, the historian's report, replay inputs and the journal."""
        import json
        from pathlib import Path
        from .player_history import journal_text
        from .report import make_html
        output = Path(output)
        output.mkdir(parents=True, exist_ok=True)
        data = self.world.export()
        (output / 'history.json').write_text(json.dumps(data, indent=2, allow_nan=False), encoding='utf-8')
        (output / 'report.html').write_text(make_html(data), encoding='utf-8')
        (output / 'inputs.json').write_text(json.dumps(self.input_history(), indent=2, allow_nan=False),
                                            encoding='utf-8')
        if self.world.player_log:
            record = self.journal('historian')
            (output / 'journal.json').write_text(json.dumps(record, indent=2, allow_nan=False), encoding='utf-8')
            (output / 'journal.txt').write_text('\n'.join(journal_text(record, limit=40)) + '\n', encoding='utf-8')
        return output

    # ----- What the player knows -----------------------------------------

    @property
    def player_id(self):
        players = sorted(self.world.active_players())
        return players[0] if players else None

    @property
    def person(self):
        identity = self.player_id
        return next((a for a in self.world.agents if a.id == identity), None)

    def _require_player(self):
        identity = self.player_id
        if identity is None:
            raise ValueError('The player has no living character or heir; the session is over.')
        return identity

    def observation(self):
        """The same detached observation an autonomous person receives."""
        return self.world.observe(self._require_player())

    def situation(self):
        return player_view.situation(self.observation())

    def options(self):
        return player_view.options(self.world, self._require_player())

    def check(self, proposal):
        """The same dry run the menu uses, for a changed choice; None when only the cycle can tell.

        Choices that depend on someone else's private circumstances are not checked in advance.
        """
        if proposal.get('type') in player_view.UNCHECKED:
            return None
        proposal = {**proposal, 'actor': self._require_player()}
        return self.world.action_engine.validate(proposal)

    # ----- Talking (Stage 3) ----------------------------------------------

    def partners(self):
        return player_view.partners(self.observation())

    def conversation(self, partner):
        return player_view.conversation(self.observation(), partner)

    def talk(self, partner, topic, **args):
        """Ask or tell a neighbor something; no season passes, and it is recorded for replay."""
        return self.world.talk(self._require_player(), partner, topic, **args)

    def journal(self, view='player'):
        from .player_history import journal
        return journal(self.world, view)

    # ----- Playing --------------------------------------------------------

    def act(self, proposal=None):
        """Queue the player's proposal (None waits) and run one full cycle for everyone."""
        identity = self._require_player()
        if proposal is not None:
            self.world.queue_player_action(identity, proposal)
        before = self.person
        homes = {self.world.settlements[before.home].name}
        tick, cursor = self.world.tick, len(self.world.events)
        results = self.world.step()
        mine = next(r for r in results if r['action'].get('actor') == identity)
        after = self.person
        names = {before.name}
        if after is not None:
            homes.add(self.world.settlements[after.home].name)
            names.add(after.name)
        # What the player could have witnessed: their town(s) and their own story.
        # An organization's action is logged twice (as institution and action); report it once.
        seen, messages = [], set()
        for event in self.world.events[cursor:]:
            if ((event.get('settlement') in homes or event.get('agent') in names or event.get('actor_id') == identity)
                    and event['message'] not in messages):
                messages.add(event['message'])
                seen.append(deepcopy(event))
        return dict(tick=tick, actor=identity, action=deepcopy(mine['action']), result=deepcopy(mine['result']),
                    actions_resolved=len(results), events=seen, player=self.player_id,
                    inventory=dict(after.inventory) if after is not None else None)

    # ----- Reproducible input history -------------------------------------

    def input_history(self):
        """Everything a human decided, with the settings needed to replay it."""
        if getattr(self.world, 'scenario', 'baseline') != 'baseline':
            raise ValueError('Only a society built from its settings can be replayed from inputs.')
        inputs = [deepcopy(e) for e in self.world.player_log
                  if e['event'] in ('joined', 'talk') or (e['event'] == 'action' and e['chosen'])]
        return dict(format=HISTORY_FORMAT, settings={key: getattr(self.world, key) for key in SETTINGS},
                    tick=self.world.tick, inputs=inputs)

    @classmethod
    def replay(cls, history):
        """Rebuild a session from its settings and recorded inputs alone."""
        if type(history) is not dict or history.get('format') != HISTORY_FORMAT:
            raise ValueError('Unsupported play history format.')
        settings = history['settings']
        if set(settings) != set(SETTINGS):
            raise ValueError('Play history settings are incomplete.')
        world = SocietyWorld(**settings)
        pending = sorted(enumerate(history['inputs']), key=lambda pair: (pair[1]['tick'], pair[0]))
        position = 0
        while True:
            while position < len(pending) and pending[position][1]['tick'] == world.tick:
                entry = pending[position][1]
                if entry['event'] == 'joined':
                    person = world.add_player(entry['name'], entry['home'], entry['inventory'])
                    if person.id != entry['actor']:
                        raise ValueError('Replay diverged: a player joined with a different identity.')
                elif entry['event'] == 'action':
                    world.queue_player_action(entry['actor'], entry['proposal'])
                elif entry['event'] == 'talk':
                    reply = world.talk(entry['actor'], entry['partner'], entry['topic'], **entry['args'])
                    if reply['lines'] != entry['lines']:
                        raise ValueError('Replay diverged: a conversation went differently.')
                position += 1
            if world.tick >= history['tick']:
                break
            if position < len(pending) and pending[position][1]['tick'] < world.tick:
                raise ValueError('Replay diverged: an input refers to a cycle that has passed.')
            world.step()
        if position != len(pending):
            raise ValueError('Replay ended with inputs left over.')
        return cls(world)
