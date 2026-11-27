# Eternia — Society Engine (v0.9 in progress)

Eternia is a small simulated society that writes its own history. Named people
with needs, goals, memories and relationships live in settlements. They gather
and trade, form guilds, cooperatives and councils, vote, send caravans along
roads that wear out, take paid work, sometimes in another town, and buy and sell
at prices each town sets from its own supply and demand. What they want can
change with what they live through, and how fairly they feel treated shapes
whether they organize, give, tax themselves or leave. Every run produces an
offline HTML report that you can step through year by year, and you can now
step into the society yourself as one of its people.

It is a runnable **proof of concept**, not a finished game, an MMORPG or general
artificial intelligence. People act on programmed utility rules; no language
model or network service is involved.

**Current version: v0.9, Emergent Opportunities, all four stages implemented.** v0.7, The
Living Economy, is complete: a regional labor market, local markets whose prices
respond to supply and demand, goals that people revise as their experiences
change their motives, and the social consequences of inequality. v0.8 makes
that society playable, and all four of its stages are implemented: you play one
newcomer in Rivermark, under exactly the rules everyone else follows; through
ordinary menus you can make a living, hire, ship goods to other towns, found
organizations, propose and vote; you can talk to the people who live there, who
answer only from what they have seen, done or been told, while news passes from
person to person; and you can play all of it in your browser as well as in the
terminal (see [Play Eternia](#play-eternia-v08) and the
[roadmap](#roadmap-the-first-player)). v0.8.1 was a reliability pass: the page
is tested in a real browser, saves cannot silently drift apart, and long
sessions are measured. v0.9 asks whether the world gives a player reasons to
act. In Stage 1, people whose goals stall on something they cannot gather or buy
now post paid jobs for it, saying what it is for, whether or not anyone plays;
in Stage 2 those needs travel by word of mouth and go out of date, and anyone
with the goods can answer one by trade; in Stage 3 people act on the needs they
hear of, answering the ones worth answering and declining the rest, and what
comes of each answer travels as news; Stage 4 measures what becomes of needs,
makes people follow through, tests whether a stalled goal should raise what
people pay, and makes long runs faster (see
[v0.9](#roadmap-emergent-opportunities-and-player-purpose-v09)).

## Contents

- [Quick start](#quick-start)
- [What you can run](#what-you-can-run)
- [Play Eternia (v0.8)](#play-eternia-v08)
- [How the simulation works](#how-the-simulation-works)
- [Roadmap: Emergent Opportunities and Player Purpose (v0.9)](#roadmap-emergent-opportunities-and-player-purpose-v09)
- [Roadmap: The First Player](#roadmap-the-first-player)
- [Roadmap: The Living Economy](#roadmap-the-living-economy)
- [The current society in detail](#the-current-society-in-detail)
- [Earlier modes](#earlier-modes)
- [World action engine](#world-action-engine)
- [Replace the proposal policy](#replace-the-proposal-policy)
- [Scope](#scope)
- [Tests](#tests)
- [File layout](#file-layout)

## Quick start

You need Python 3.10 or newer. There is nothing to install: the project uses
only the standard library and runs on Windows, Linux and macOS.

```powershell
git clone https://github.com/Finse2/Eternia.git
cd Eternia
python main.py --society --years 10 --seed 42
start .\output\society\report.html
```

On Linux or macOS, use `python3` and open the report with `xdg-open` or `open`.
On Windows, try `py -3` if `python` is not found.

The run takes a few seconds, prints a summary that begins
`Year 10: 247.11 coins paid in wages; 9 voluntary actions; 20 market purchases;
1 merchant consignments; 15 goals reached and 28 changed.` and writes three files
to `output/society/`:

| File | What it is |
|---|---|
| `report.html` | The offline explorer. Open it in any browser. |
| `history.json` | The full record behind the report. |
| `world.save.json` | A checkpoint you can [resume](#save-and-resume). |

Run every command from the repository root, the folder that contains `main.py`
and this README. If you also keep an older starter copy with its own `main.py`
in a parent folder, do not run that one: it is an earlier version.

Things to try next:

```powershell
# Play one newcomer in Rivermark while everyone else decides for themselves.
python main.py --web --player-name Ilsa      # in your browser
python main.py --play --player-name Ilsa     # in the terminal

# Does inequality change a society? Three matched starting distributions over 30 years.
python main.py --inequality-experiment --years 30 --seed 42

# Does experience change what a miner wants? Four cases, adaptive and fixed goals.
python main.py --goal-experiment --years 20 --seed 42

# Does food follow the price? Three matched food distributions.
python main.py --market-experiment --seed 42

# Will a miner travel to another town for a paid job? Four matched cases.
python main.py --labor-experiment --seed 42

# Compare 45 runs across seeds, starting conditions and priorities.
python main.py --evaluate-society --years 5 --evaluation-seeds 18,42,73

# What becomes of needs, with willingness to pay fixed or rising? Six 25-year runs.
python main.py --opportunity-experiment --evaluation-seeds 18,42,73

# Run the test suite.
python -m unittest discover -s tests -v
```

## What you can run

Each version of Eternia added a mode and kept the earlier ones. All of them use
`python main.py` with the flag below and write a `report.html` to their output
folder; `--output` changes that folder. Single-world modes also write the full
`history.json`, and the comparison modes write a summary with one history per
case.

| Mode | Flag | What it simulates | Default length | Output folder |
|---|---|---|---|---|
| [Play in the browser](#play-in-your-browser) (v0.8) | `--web [FILE]` | The same game on a local page: map, character, people, economy, politics, timeline and journal | until you stop the server | `output/play` |
| [Play](#play-eternia-v08) (v0.8) | `--play [FILE]` | You play one newcomer in the v0.7 society, one cycle per turn; give a checkpoint to continue | until you quit | `output/play` |
| [Replay](#replay-a-session) (v0.8) | `--replay FILE` | Rebuilds a played session exactly from its recorded `inputs.json` | the recorded session | `output/play-replay` |
| [Society](#the-current-society-in-detail) (v0.7) | `--society` | Three towns and 18 named people with councils, funded jobs, a regional labor market, local prices and changing goals (`--fixed-goals` for a control) | 10 years | `output/society` |
| [Opportunity experiment](#stage-4-measurement-follow-through-willingness-to-pay-and-speed-implemented) (v0.9) | `--opportunity-experiment` | The same seeded societies with willingness to pay fixed or rising: what becomes of needs, what blocks them, and what it costs (writes `summary.json`) | 25 years | `output/opportunity-experiment` |
| [Inequality experiment](#inequality-experiment) (v0.7) | `--inequality-experiment` | Three matched starting distributions of wealth and public funds | 30 years | `output/inequality-experiment` |
| [Goal experiment](#the-changing-miner) (v0.7) | `--goal-experiment` | One miner in four matched circumstances, each with adaptive and with fixed goals | 20 years | `output/goal-experiment` |
| [Market experiment](#market-experiment) (v0.7) | `--market-experiment` | Three matched food distributions that test whether trade follows prices | 2 years | `output/market-experiment` |
| [Labor experiment](#labor-experiment) (v0.7) | `--labor-experiment` | Four matched cases that test whether people travel for paid work | 3 years | `output/labor-experiment` |
| [Evaluation](#compare-seeds-and-scenarios) (v0.7) | `--evaluate-society` | A matrix of seeds, scenarios and policy priorities | 5 years | `output/society-evaluation` |
| [Resume](#save-and-resume) (v0.7) | `--resume FILE` | Continues a saved society checkpoint | adds 0 years | `output/society-resumed` |
| [Physical world](#physical-world-v061) (v0.6.1) | `--physical-world` | Roads, rivers, caravans, road repair and finite mines | 100 years | `output/physical-world` |
| [Migration experiment](#controlled-migration-experiment) (v0.6.1) | `--migration-experiment` | Three matched cases that test whether a miner migrates for work | 3 years | `output/migration-experiment` |
| [Civilizations](#civilizations-v05) (v0.5) | `--civilizations` | Three settlements with negotiated trade, borders and specialization | 100 years | `output/civilizations` |
| [Institutions](#institutions-v04) (v0.4) | `--institutions` | Five people who form organizations, pool resources and vote | 100 years | `output/institutions` |
| [Community](#community-v03) (v0.3) | `--community` | Five people with a shared market, relationships and generations | 100 years | `output/community` |
| [Edrin experiment](#edrin-autonomy-experiment-v02) (v0.2) | `--npc-demo` | One miner pursuing two goals through a mine closure | 40 turns | `output/autonomy` |
| [Original simulator](#original-thousand-year-simulator) | (no flag) | Seven settlements, 1,000 inhabitants and 50 NPCs | 1,000 years | `output` |

Short society runs finish in seconds. Long regional runs are heavier: a
100-year `--physical-world` run took about 40 seconds on the development machine
and wrote roughly 70 MB of history and report. The default evaluation matrix
takes one to two minutes. The `output/` folder is ignored by Git.

Run `python main.py --help` for every option.

## Play Eternia (v0.8)

```powershell
python main.py --play --player-name Ilsa
```

You arrive in Rivermark as a newcomer with 3 food, 10 coins and the two skills
every new adult has, foraging and trading. You have no profession, office or
special privilege. Edrin is working toward his own ambitions, merchants are
trading and the council is voting; you can take part, but the world does not
wait for you. Each turn is one decision cycle, a season. Every turn shows what
you know and your choices, grouped by kind. This is the second turn of
`python main.py --play --player-name Ilsa --years 2`, which lets the society run
for two years before you arrive (some lines shortened):

```text
Year 2, cycle 9. You are Ilsa, living in Rivermark.
Food 11 | Wood 0 | Iron 0 | Coins 10.00 | Hunger 7/100 | Energy 90/100
Skills: foraging, trading
Market here (buy / sell), stock: food 0.67 / 0.54 (301.32) | wood 3.82 / 3.06 (19.78) | ...
Highfen buys at: food 2.21 | wood 2.5 | iron 1.6
Job 5 (the Rivermark council): 6 of 6 iron left at 5 coins each
Organization: Rivermark Municipal Council, a council of 5
  Needs
    1. Wait and watch what happens
    2. Eat a meal (1 food)
    3. Rest
  Work
    4. Gather 8 food (2 energy each) [amount 1-8]
  Market
    5. Buy 8 food at 0.67 each (5.36 coins) [amount 1-8]
    6. Sell 8 food at 0.54 each (4.32 coins) [amount 1-8]
  Trade and hiring
    8. Offer neighbors 11 food at 0.64 each (for 4 cycles) [amount 1-11, price 0.1-100]
   12. Ship 8 food to Highfen's market for 2.21 each (17.68 coins on delivery in about 4 cycles, ...) [amount 1-8]
   15. Hire workers to gather 4 wood for you at 2.29 each (9.16 coins held in escrow until delivered) [quantity 1-24, wage 0.1-5]
  Building and learning
   17. Help Toren of Rivermark build (5 energy; if they want help) (the cycle decides)
  Organizations
   18. Found a cooperative named "Rivermark Cooperative of Ilsa" (2 coins, 2 energy) [name: any text]
   21. Join Rivermark Municipal Council, a council of 5
  Travel
   23. Move to Highfen (about 4 cycles on the road; take 3 food or more); job there: 10 iron at 1.66 each
>
```

| Type | To |
|---|---|
| a number | take that choice as shown |
| a number and values | change what is in brackets, in order: `4 5` gathers 5 food, `8 6 0.9` offers 6 food at 0.9 each, `15 6 2.5` hires for 6 wood at 2.5 each, `18 The Free Traders` names a cooperative |
| `w`, `w 4` | wait one cycle, or four (a year) |
| `t`, `t 3`, `t 3 2` | [talk to someone](#talking-to-people): list the people here, list what you can ask person 3, ask them question 2 (talking takes no season) |
| `h` | show your [journal](#your-journal) |
| `m` | show your situation and the menu again |
| `j {"type": "work", "params": {"order": 1, "amount": 4}}` | propose any action the [action engine](#world-action-engine) knows, as JSON |
| `s` | save and quit (the end of input does the same) |
| `q` | quit without saving |

A changed choice gets the same check as the menu before the turn is spent: if
the rules would refuse it, you are told why and choose again. After each turn
you see what became of your choice and what happened around you in that cycle.
`--home Highfen` or `--home Deepwood` starts you elsewhere, `--years 5` lets the
society run for five years before you arrive, and `--seed` and `--policy-style`
work as in `--society`. On quitting, `output/play/` holds `world.save.json`,
`history.json`, `report.html`, `inputs.json`, and your journal as `journal.txt`
and `journal.json`. To carry on:

```powershell
python main.py --play output/play/world.save.json
```

A checkpoint saved by `--society` has no player yet; `--play` with it brings
you into that society as a newcomer.

### Play in your browser

```powershell
python main.py --web --player-name Ilsa
```

This starts a small server on your own computer and opens the game at
`http://127.0.0.1:8765/` in your default browser. Nothing is installed and
nothing leaves the machine. It is the same game as the terminal, with the same
session, menu, conversations, saves and replays, laid out on one page:

| Part of the page | What it holds |
|---|---|
| Character (left) | Your goods, hunger and energy, skills, buildings, memberships and reminders |
| Act | Every menu choice, by section, with its editable fields; choosing one spends the season for everyone |
| Town & roads | A map of the towns you know; your town's stores, deposits and policies; every posted price; road condition, risk and capacity; for a neighboring town, its route and jobs, and the choices to move or ship goods there |
| People | Who is here and how you feel about them; what you can ask each of them (asking takes no season), their answers so far, and what you have heard |
| Economy | The market with its buy and sell choices, jobs here and in neighboring towns, neighbors' offers, trading and hiring, and your coins accounted |
| Politics | Each organization with its proposals, votes so far and your vote, and the choices to join, give, vote, carry out or propose; founding your own; your political record |
| Timeline | Posted prices in each town since you arrived, and season by season what you did and what happened where you lived |
| Journal | The [journal](#your-journal) |
| Season report (right) | After each turn: what became of your choice, what changed for you, in prices, in your town, its jobs and its politics, and what happened around you |
| Save & load | Save under a name, resume a checkpoint exactly or rebuild it from its inputs, start a new life, write the historian's report |

`--web output/play/world.save.json` continues a checkpoint, including one saved
by the terminal; `--port` changes the port (0 picks a free one; a busy port is
replaced by a free one), `--no-browser` only prints the address, and
`--player-name`, `--home`, `--years`, `--seed` and `--policy-style` work as with
`--play`. Saves go to `output/play/` (or `--output`) as `NAME.save.json` with
`NAME.inputs.json`. Stop the server with Ctrl+C; play you have not saved is kept
as `autosave.save.json`.

**The browser only draws.** The page sends the number of a menu choice and any
values you changed, a question, a wait or a save. The server turns it into the
same proposal or conversation the terminal would send, runs it through the
session and returns a new view. Every price, wage, check and outcome on the
page comes from the simulation, and the page computes none of them. A changed
value is checked against the rules before the season is spent, as in the
terminal. Each request names the view it was made from, so a double click or an
old tab cannot spend a second season, and an old tab cannot save, load or start
a new life over play it never showed. The server answers only the page it
served: it listens on 127.0.0.1, checks the Host and Origin headers, and
requires a token minted at launch.

**Saves are a checked pair.** A save writes the checkpoint and the inputs that
replay it, each in one step, so a crash leaves the old file or the new one and
never half of either; the inputs record the checkpoint's own checksum and
cycle. The save list shows a pair that was not written together (a save
interrupted between the two files) instead of trusting it, and inputs written
by the terminal or an earlier version as unverified. A new life or a load keeps
play you never saved as `autosave` first (`autosave-previous` when you are
loading the autosave itself). A checkpoint resumes only with the exact
simulation source that wrote it; after an update, Replay rebuilds the save from
its inputs.

### What you can do

The menu has an entry for every action the engine knows, built from what you
can see:

- **Needs and work:** eat, rest, gather what your skills allow, and take any
  funded job in town (a council's, an organization's or a neighbor's).
- **Market:** buy and sell at the posted prices, take up a neighbor's offer, or
  post your own offer to buy or sell at a price you set.
- **Trade and hiring:** ship goods to a neighboring town's market at its
  buying price, paid on delivery if the shipment survives the road, and hire
  others for food, wood or iron at a wage you set, held in escrow until they
  deliver.
- **Building and learning:** study carpentry or experiment with the Aether,
  build a house or workshop, teach what you know, or help a builder.
- **Organizations and politics:** found a cooperative, guild or council, join or
  leave one, give to one, and, as a member, propose anything the charter allows
  (a levy, food from the shared stores, a granary, a paid commission, public
  work from the town treasury, trade terms with a neighbor, an embargo, a
  specialization, closing or opening the town, road repairs), vote on open
  proposals you are entitled to vote on, carry out approved ones, and send
  contract caravans.
- **Travel:** move to a neighboring town, with the jobs posted there.

Members vote on your proposals by their own interests, as they do on anyone's:
in seed 42 the Rivermark council voted down a player's public-work budget at
4.9 coins per unit of wood, when the market there paid 3.06 for wood, and
passed the same budget at 1.5.

### Talking to people

Type `t` to see who is here, `t 3` for what you can ask the third of them, and
`t 3 2` to ask. Asking takes no season: the world does not move while you talk.
Each person answers up to three questions a season, then has other things to do.
You can ask about work, what has been happening, trade and the roads, local
politics, how they are doing and what they want, what they think of you or of
someone else, how they would vote on an open proposal, and whether they would
work for you at a wage, join your organization or teach you something. You can
also pass on something you have heard. Since v0.9, asking about work also tells
you what the person needs and cannot get, and needs they have heard of.

This exchange comes from seed 18, thirteen years after the founding, with
`--seed 18 --years 13`:

```text
> t 2 3
Mara of Rivermark: "Here, food sells for 0.6 and the market pays 0.48; wood sells for 1.8 and the market pays 1.44; ..."
Mara of Rivermark: "Highfen pays 1.26 for food, more than it costs here, if you can get it there."
Mara of Rivermark: "The upland road to Highfen is in poor repair."
Mara of Rivermark: "My shipment of food to Highfen was lost: an accident on the upland route (I saw it myself about 2 years ago)."
Mara of Rivermark: "My last shipment arrived; I made 2.94 coins on it."
(You learned 1 new thing; h shows what you have heard.)
> t 2 13 0.2
Mara of Rivermark: "Not at 0.2: the market pays 0.48 for food, and gathering and selling it myself pays better. I'd want at least 0.24 a unit."
> t 2 5
Mara of Rivermark: "I'd rather keep my own affairs to myself with someone I barely know."
> t 1 5
Edrin of Rivermark: "I'm trying to hold 120 coins, since about 7 years ago."
Edrin of Rivermark: "Before that I managed to hold 60 coins."
Edrin of Rivermark: "I want to be well off."
Edrin of Rivermark: "My food is running low."
```

- **People know only what they know.** An answer is built from the speaker's own
  view: what they can see in town, public notices such as prices and job
  postings, their memories, their own goals, motives and feelings, and the news
  they have heard. They cannot tell you anyone's coins or anything they have no
  way of knowing.
- **Answers differ from person to person.** They depend on the speaker's skills,
  goals, temperament, how fairly they feel treated and how much they trust you.
  A guarded person keeps their affairs to themselves with a stranger, and
  someone who distrusts you may refuse to talk at all. Two people can read the
  same event differently: a famine is a warning to one and a price opportunity
  to another.
- **They tell you how they would vote and why**, by the same criteria they vote
  with, and remember how they voted afterwards. When unsure, they say so.
- **Answers to requests are not promises.** "Would you work for me?" gets an
  answer from the rules the person acts on (their skills, the market's price,
  whether they distrust you). Anything with consequences, such as posting the
  job, is still an ordinary action that takes your turn.
- **News comes with its source and age.** "Lyra told me about a year ago" and "I
  saw it myself" are kept apart, each retelling loses some certainty, and what
  you hear goes into your journal. You can pass on only what you actually know.

### Your journal

Type `h` during play for your journal: coins on arrival and now, with every coin
of income and spending by kind, the jobs you worked and the jobs you posted
(who worked them and what they were paid), shipments, organizations you founded
or joined, your proposals and votes and what became of them, goods you won or
lost to someone else in the same cycle, and how you feel about the people you
have dealt with, and what you have heard with its source and age. It is built from the world's own records, so it never drifts
from what happened and survives saving, loading and replay. `journal.txt` and
`journal.json`, written when you quit, add the historian's view: how others
regard you, which nobody inside the world can read.

### The same rules for everyone

- **Your choice is a proposal, resolved with everyone else's.** It is not
  carried out before the others. Each turn runs one ordinary cycle: all 18
  autonomous people plan from the same tick-start snapshot, and your proposal
  joins theirs in a single batch settled in the world's seeded order. Over 12
  turns in seed 42 you came 4th, 1st, 16th, 9th, 9th, 13th, 11th, 15th, 19th,
  16th, 11th and 16th of 19.
- **The same checks, costs and conflicts.** Gathering costs 2 energy a unit and
  needs the right skill or knowledge; purchases need coins at the posted price;
  if you and the merchant both try to buy a town's last six units of food, one
  of you gets them and the other's purchase fails as a conflict. Nobody can act
  for someone else.
- **The same consequences.** A refused action spends nothing but the turn.
  Hunger rises every season, eating takes a turn and a unit of food, and two
  years of starvation are fatal, for you as for anyone. Your heir then inherits
  the estate under the ordinary rules and you continue as them.
- **You see what anyone sees.** Your view is the same observation an
  autonomous person receives, without the motives the simulation keeps for
  them. The menu is built from that view. Choices whose rules read only public
  facts or your own state are checked against the rules at the start of the
  cycle; one can still fail if someone else claims the goods first. Taking up a
  neighbor's offer, teaching and helping depend on the other person's private
  circumstances (whether they still have the goods, want the help, trust you),
  so those are marked "the cycle decides".
- **People judge you by what you do.** Trust between people changes by the same
  rules whoever they are: fair or poor pay, help, gifts, contested goods and
  political choices all count, and people who distrust someone will not work
  for them or join an organization they lead.
- **Nobody decides for you.** You have no simulated motives or goal reviews,
  you are left out of the goal statistics, and if you choose nothing you wait.
- **Nothing is minted for you.** The goods you arrive with are recorded in the
  conservation ledger as an inflow; after that, everything you have, you earned,
  bought or inherited.

### Replay a session

The world records every human input in its `player_log`: when and where you
joined and with what, and which proposal you chose in which cycle. `inputs.json`
holds those inputs and the world's settings, and

```powershell
python main.py --replay output/play/inputs.json
```

rebuilds the session from them alone, reproducing the same history; so does
loading a checkpoint saved between turns.

### From Python

```python
from eternia.playable_session import PlayableSession

session = PlayableSession.start('Ilsa', 'Rivermark', seed=42)
print('\n'.join(session.situation()))
choice = session.options()[1]
outcome = session.act(choice['proposal'])   # one full cycle for everyone
print(outcome['result']['message'])
session.save('output/play/world.save.json')
same = PlayableSession.replay(session.input_history())
```

### Not there yet

More than one player comes later; the browser interface is a page for one
player on their own computer, not a hosted game. Conversations are structured questions with rule-based answers, not free text,
and nobody lies: people pass on only what they know, though what they heard
may be out of date. Nobody bargains: wages, prices and contract terms are
offered and accepted or ignored, never countered. Councils restrict trade only
through embargoes, which their members otherwise propose only when relations
with a neighbor are poor; no council restricts food exports on its own because
of a shortage, although a player can propose it.

## How the simulation works

A few rules run through the whole project, and most of the tests exist to
protect them. The planning, voting and timing rules apply from the community
mode (v0.3) onward.

- **People propose; the world decides.** Each person's policy receives an
  observation and returns one proposed action as plain data. The action engine
  checks it against the person's location, permissions, knowledge, materials
  and energy, then applies it or rejects it with a recorded reason. A rejected
  action spends nothing.
- **Knowledge is limited.** Observations are detached copies of public
  information. They leave out other people's inventories and skills, buried
  mineral reserves and the hidden Aether parameter. The HTML report is a
  historian's view and shows more than any person in the world can see.
- **News travels by word of mouth.** Since v0.8 Stage 3, what people experience
  and witness becomes claims that they pass on one person at a time, with source
  and age. Nothing reaches another town unless someone carries it there.
- **Everyone plans from the same snapshot.** A decision cycle freezes all
  observations before anyone plans. Competing claims are then settled with a
  seeded shuffle, and anything received during a cycle cannot be spent again in
  that cycle.
- **Nothing is minted.** Trades, wages and contributions transfer existing goods
  and coins. Wages and caravan payments are placed in escrow before the work or
  journey starts, and goods only reach another town on a physical journey. Resources enter through production and leave through explicit
  sinks such as consumption, construction and cargo lost on the road, and a
  ledger records both.
- **Collective decisions need authority.** A vote needs a recorded electorate,
  at least two voters in favour, a strict majority, and votes cast in an earlier
  cycle than the one that enacts the decision.
- **The same seed gives the same history.** Replay is deterministic for the same
  seed, settings and policies.
- **Prices are fixed within a cycle.** In the v0.7 society each town posts its
  prices before anyone plans, and every trade in that cycle uses them.
- **Goals change only between decisions.** In the v0.7 society, motives and
  goals are reviewed once per cycle, after outcomes are known. Hunger and fatigue
  are handled before any goal, whatever it is.
- **Time has two speeds.** People decide four times per simulated year by
  default. The aggregate economy (production, consumption, births and deaths)
  advances once a year.

Each version's world extends the previous one, so the v0.7 society still
contains the offers, institutions, negotiated trade, caravans and finite mines
described under [Earlier modes](#earlier-modes).

## Roadmap: Emergent Opportunities and Player Purpose (v0.9)

v0.8 answered whether a player can take part in the society. v0.9 asks whether
the autonomous world gives them interesting reasons to: needs that arise from
the society itself and that a player can discover and answer, without quests
written for them.

- **Opportunities emerge from the world.** A builder short of iron for a house,
  a council that needs hands to repair a road, a cooperative trying to find food
  in a lean year: each comes from existing goals, resource limits and political
  decisions, never from something spawned for the player.
- **They use the systems that exist.** Jobs, contracts, offers, trust and news
  make a need discoverable and actionable, by anyone; nothing is reserved for
  the player.
- **The world does not wait.** A person keeps pursuing their need whether or
  not the player answers, and someone else may answer first.
- **Nothing is invented.** Responding moves goods, coins, trust and knowledge
  under the ordinary rules; there are no rewards from nowhere.

| Stage | What it adds | Status |
|---|---|---|
| 1. Autonomous needs and opportunities | People identify what blocks their goals, and needs they cannot meet themselves become paid jobs under the ordinary rules; a read-only view of opportunities for the browser | Implemented |
| 2. Discovery and information | Players learn of opportunities through conversations, notices, rumors and observation; information stays local and can go out of date; an opportunity can be missed or taken by someone else; a need can be answered by trade as well as by work | Implemented |
| 3. Consequences and emergent stories | People judge needs they hear of from their own knowledge and answer the ones worth it by ordinary trade; answering or ignoring one changes goals, wealth, relationships and knowledge, through existing resources and rules, with no quest rewards | Implemented |
| 4. Evaluation and long-term behavior | Measure across seeds what becomes of needs and what blocks them, make people follow through on what they start, test whether a stalled goal should raise what people pay, and remove the copying that slows long runs | Implemented |

**Acceptance test for v0.9:** a person develops a genuine need, creates an
opportunity under the normal rules, the player discovers it and responds, and
the consequences change both people's circumstances without inventing rewards
or resources.

### Stage 1: Autonomous needs and opportunities (implemented)

A person's goal has a next step, and the step consumes something: wood and iron
for a house, a unit of each to study carpentry or to run an Aether experiment,
food for a reserve (`next_step` in `eternia/goal_engine.py`). What they lack of
it is a **need** (`eternia/needs.py`), judged only from their own observation.
They close it the simplest way the rules allow: gather it if they can, or buy it
if the market sells it at a fair price they can afford. When neither works and
someone else could gather it here, they **post a paid job** for as many units as
they can pay for, keeping a few meals and what the goal itself will still cost
(`eternia/economic_policy.py`). It is an ordinary work order: the wages are
escrowed from their own coins, and the notice is public in their town and the
neighboring ones. How pressing posting it is depends on how much their motives
favor the goal, like any step toward it (5 less than doing the step oneself, 20
less for a food reserve, which buying usually meets), and grows by 2 for every
cycle the goal has stalled, up to 20. A person knows how long their own goal has
stalled.

A job may now say what it is for: "Toren of Rivermark escrowed 6.24 personal
coins to hire 2 iron for a house". The engine accepts the statement only if it
names the next step of the employer's own goal and a material that step uses,
so nobody can claim a purpose they do not have, and a player, who has no
simulated goal, posts without one (`eternia/society.py`). A read-only
projection lists the opportunities a player can see: open jobs here and in
neighboring towns and neighbors' standing offers, each with what it is for,
what it pays against the market and what taking it would need
(`opportunities` in `eternia/interface.py`). The browser shows it at the top of
the Economy tab, with the choice to answer each one. Nothing here is a second
quest system: every opportunity is an existing job or offer, and the world keeps
no record that exists for the player.

**Pass condition:** in societies nobody plays, needs that people cannot meet
themselves become public opportunities under the ordinary rules; others take
them up or they lapse; and the same opportunity exists whether or not anyone
plays.

| Condition | Evidence |
|---|---|
| Needs come from the person's own view | A builder with the wood for a house but no iron, who cannot mine, needs 2 iron; giving everyone else 500 more coins and 50 iron, turning their feelings and burying the ore leaves his needs unchanged (tests) |
| Only needs nobody nearer can meet become jobs | A need the market sells at a fair, affordable price is bought; a need with no ore left in town is not put out as work; only the wages a person can spare are offered (one unit of the two he lacks when coins are short, none when not even one wage can be spared) (tests) |
| Opportunities emerge without a player | Over 25 years with seeds 18, 42 and 73, people posted 4, 5 and 3 jobs for steps of their own goals, against 1, 2 and 1 under the earlier rule; every one asked for iron, for a house or for an Aether experiment (figures as of Stage 3, whose answered needs changed these runs) |
| Others take them up, or nobody does | 8 of those 12 jobs were worked, all by the town's miner, the only person there who can mine; 4 lapsed untouched. After a job was worked, the employer took the step it served in 4 cases: in seed 42 Toren of Rivermark, who lacked 2 iron for a house, bought one from Aldren when Aldren heard of his need (Stage 3) and hired the other at 5 coins in year 6; Edrin delivered it and Toren built the house three cycles later (record from `opportunity_record` in `eternia/evaluation.py`) |
| The world does not wait for a player | With and without a newcomer in Rivermark, Toren posts the same job for the same iron, for the same house; without one, Edrin takes it and Toren builds (tests) |
| Consequences without invented rewards | A newcomer able to mine (set up in the test) sees the job, with "To take it you would need the mining skill" until then; takes it, earns its 6.26 escrowed coins; Toren receives the iron and builds the house it was for. Nothing is minted (tests) |
| Stated purposes are true | A job's purpose appears on the public notice in every town that sees it; a purpose the employer is not pursuing, a malformed one, or one for a material the step does not use is refused and nothing is escrowed; a player cannot state one (tests) |
| Earlier results | Every mode before v0.7 is byte-identical. v0.7 societies nobody plays change wherever someone now posts a job. Re-deriving every figure in this README changed the quick start (269.58 coins in wages instead of 241.93, 8 voluntary actions instead of 16, 15 goals reached instead of 8), the year-10 prices, the [Changing Miner](#the-changing-miner), the [inequality experiment](#inequality-experiment) except seed 42's unequal starts, and one [market](#market-experiment) figure (Highfen's population after two years with a price gap, 107–116 instead of 113–123); all are updated in place. The labor experiment and the other market results are unchanged. Five earlier tests relied on histories that no longer happen and now use new ones: Stage 2's livelihood and lost shipment come from seed 42 after one year instead of two, and Stage 3's conversations about Mara's lost shipment from seed 18 after thirteen years, where she lost it in year 10 |

What Stage 1 does not do yet:

- **A newcomer cannot take most of these jobs.** Nearly everyone forages and
  most can cut wood, so the needs that arise are for iron, which only miners
  mine. A newcomer forages and trades: they see the opportunity and what it
  would take, but cannot supply it by working the job. (Stage 2 lets them
  answer by trade instead.)
- **Jobs only.** People already post buy offers for inputs they cannot get
  locally and accept neighbors' offers for their goal's materials (rules from
  v0.3), at low priority; needs do not yet become offers.
- **Materials only.** Needs cover what a goal's next step consumes. A person
  who needs to be taught carpentry, or needs help to build, does not yet ask
  for it.

### Stage 2: Discovery and information (implemented)

A need now travels as knowledge, and can be answered by trade as well as by work.

**People know what they need.** When the next step of a person's goal lacks
something they can neither gather nor buy at a fair price, they hold that as a
claim of their own, like anything else they know: "I need 2 iron for a house;
I am ready to buy it at up to 6 a unit", with the job they posted for it, if
any (`note_needs` in `eternia/social_memory.py`, from the same tick-start view
they plan from). They keep it current while the need lasts and drop it once it
is met.

**Others hear of it by word of mouth**, under the Stage 3 rules: each season
everyone at home tells one neighbor one piece of news that neighbor has not
heard, and each retelling loses some certainty. Who needs what comes last: it
is passed on only when a teller has no fresher news of events, and forgotten
first when memory is full, so it never displaces other news. What others heard
keeps its source and date, and can be out of date: the need may have been met
since.

**Asked, people say so.** Asked about work, a person says what they need
(unless they distrust the listener) and mentions needs they have heard of, with
source and age; asked how they are doing, they say what they are short of, if
they confide. The player's journal keeps what they heard, and the Economy tab
lists "Needs you have heard of", each with who said so and when, what answering
it would take, and the menu's own sell offer with the amount and the price they
said they would pay filled in.

**A second route.** Besides working the job, anyone with the goods can answer a
need by offering them for sale: a person takes up a neighbor's standing offer
of what their goal lacks at a fair price (up to 1.5 times the base price) and
what they can spare, whoever made it (`opening` in `eternia/needs.py`). Buying
it that way weighs like doing the step oneself, since the offer will not wait.
That is how a newcomer who cannot mine can supply iron: by bringing it.

**Pass condition:** a person's unmet need becomes knowledge that travels by the
ordinary rules and goes out of date; a player can learn of it by asking or
being told; and it can be answered by more than one legitimate route, under the
same rules for everyone.

| Condition | Evidence |
|---|---|
| People know what they need | With the iron for his house out of reach (Rivermark's iron moved to Highfen for the test), Toren holds "2 iron for a house, up to 6 a unit" as his own claim; a need the market still meets at a fair price is not one (tests) |
| Asked, they say so | "I need 2 iron for a house; I am ready to buy it at up to 6 a unit." Toren says what he is short of to someone he trusts a little, and talks no business with someone he distrusts (tests) |
| Word of mouth, with its source | Within four seasons at least three neighbors knew of Toren's need, each naming who told them, and nobody outside Rivermark. Over 25 years with seeds 18, 42 and 73, people knew of 33, 32 and 30 needs of their own (iron or wood for a house, iron for an experiment, a food reserve); about two in three were passed on, to up to 5 or 6 people through up to 4 or 5 retellings |
| It displaces no other news | Events still go first and a need is forgotten first (tests). At Stage 2, switching need-knowledge off left everything else identical: in a six-year test, and in all three 25-year runs. Since Stage 3 people act on it, and only on it: with it off, nobody answers a need (tests) |
| It goes out of date | Once Toren has bought his iron he no longer says he needs it, while Mara still says "Toren of Rivermark needs 2 iron for a house", with how long ago she heard it (tests). At the end of the 25-year runs, 4 of 8, 41 of 41 and 60 of 69 of the needs people held were already over |
| A second route | A newcomer who cannot mine, arrived with 3 iron, asks Toren about work, learns of his need and offers the iron at 5.5 a unit. Toren buys 2 and Lyra, who needs iron for an experiment, the third; the newcomer earns 16.5 coins and Toren builds the house (tests) |
| The same rules for everyone | The same offer from Mara is taken up by the same two people, and the house is built; an offer above the fair price is not taken, and nothing is bought once the need is met (tests). In the 25-year runs it happened once with nobody playing: in seed 42 Toren of Highfen bought 2 iron for his house from Edrin of Highfen at 0.97 each |
| Earlier results | Every figure in this README is unchanged, and every mode before v0.7 is byte-identical. Knowing needs changes nothing by itself; taking up a fair offer for a need happened once in the 25-year runs (seed 42, year 10), which changed that run's later years, so Stage 1's job counts above are updated. No earlier test needed a new anchor |

What Stage 2 does not do yet:

- **Needs stay in town.** Nobody travelled between towns to answer a need in
  these runs; a need reaches another town only with someone who moves there, a
  merchant's market contact or a player.
- **Nobody acts on a need they heard of.** People take up offers for their own
  needs and work posted jobs; nobody yet brings goods to someone because they
  heard of their need. That, and what answering or ignoring a need does to
  people, is [Stage 3](#stage-3-acting-on-what-people-hear-implemented).
- **Buying only.** A need is answered by a job or by the person taking up an
  offer; they do not post requests of their own beyond the low-priority buy
  offers people have made since v0.3.

### Stage 3: Acting on what people hear (implemented)

Stage 2 let needs travel; Stage 3 makes people act on them. Over the same three
25-year runs, nobody brought goods to a need they had heard of before; now people
answer needs on their own, and decline the ones not worth answering.

**Judging a need heard of.** Each season, a person weighs every need they know
of as a chance, from their own knowledge only (`prospects` in
`eternia/needs.py`):

- **Capability:** goods they can spare after their own goal's next step and a
  few meals, or the skill and local ore or forage to gather some first. A
  merchant can also buy them at a neighboring market and have them carried
  here, never while short of the same goods for their own goal.
- **Profitability:** the price the needy person said they would pay, against
  what the market here would pay for the same goods, if it has the coins.
- **Relationships:** nobody deals with someone they distrust (trust -0.3 or
  less). Someone they trust, or caring about belonging, makes them willing to
  sell below what the market would pay, by up to 30%. After someone leaves
  one's own offers for their needs untaken, what they say they need counts for
  half as much, for each offer in the last four years.
- **Risk:** news over two years old is not acted on. So is news that is
  corrected, comes with no price the buyer could pay, or is about someone not
  here. They also pass over a need they can see a job or another seller's offer
  already covers, or that they heard was supplied. Less certain news is worth
  less.

Each heard need comes out with a route (offer the goods, gather them first, or
fetch them from another town), how many units, and the coins it is expected to
bring beyond the market, or with a reason to decline: "the market pays 12.8 for
iron, more than the 6 they would pay".

**Fetching from another town.** A new action, `procure`, buys up to eight units
at a neighboring market's posted price and has them carried home by caravan,
over the same roads, with the same risks, as any shipment. The buyer pays for
the goods and for food for the road at that market's prices when the caravan
leaves. The goods are the buyer's from then on, at the buyer's risk, and are not
counted as stock arriving for the home market (`eternia/society.py`).
Merchants alone arrange shipments between towns, as they already did for
consignments. A merchant weighs one caravan for every need for those goods they
have heard of in town. Each need counts at its price, discounted by how sure
the news is and by the risk on the road. The caravan must earn 2 coins beyond
its cost, as a consignment must, and three times that after a recent loss on
that road. Once the goods arrive, offering them is the ordinary offer route.

**Priority.** A neighbor paying for goods one holds is much like paid work, and
weighs like it (`economic_policy.py`). It scores 80, plus up to 6 for the
expected gain, 9 if the person wants coins, and up to 9 for kindness. Gathering
or fetching first scores 4 less. Whether to answer this season is then settled against
everything else they could do, a council vote or their own goal included.

**An ordinary transaction.** The answer is an ordinary sell offer at the price
the person said, which states whose need it is for. The engine accepts the
statement only from someone who has heard of that need and has not heard it
may be over, and only for goods offered for sale. The offer is public, and anyone
may take it. The needy person takes it up by the Stage 2 rule, which since
Stage 3 also weighs trust: among fair offers, one from someone they trust is
worth up to 1 coin a unit more, and one from someone they distrust is not taken.

**Consequences, from what happened.** Nothing is awarded:

- **Goods and coins:** the goods and coins move by the ordinary trade, and the
  ordinary trade rule makes buyer and seller trust each other a little more.
  That makes the seller a little kinder to that buyer next time, and the buyer
  more inclined to buy from that seller again.
- **What both of them saw:** "Mara of Rivermark supplied Toren of Rivermark with
  2 iron for a house" becomes conduct both of them saw (`record_supply` in
  `eternia/social_memory.py`). It travels as news, and each person who hears of
  it thinks a little better of the seller, by the same rule as any conduct. The
  seller knows the need is met, and nobody believes older news of a need they
  know was supplied.
- **An offer nobody took up:** it lapses, and the seller's version of the need
  becomes a correction (`mark_unanswered`): "Lyra of Rivermark did not take up
  Aldren of Rivermark's offer of iron for an Aether experiment; they may no
  longer need it". It replaces the copies others heard as it spreads.
- **A need that changes:** new terms (how much, at what price, with what job)
  reach people who heard the old ones.
- **Goods lost on the road:** goods fetched from another town that never arrive
  are the buyer's loss. The buyer remembers it, and that road needs a larger
  margin for a while.
- **Offers left untaken:** besides the correction, the seller has less faith in
  what that person next says they need.

**Seeing it.** In the Economy tab, an offer made for someone says so ("wants to
sell 2 iron to Toren of Rivermark for a house"). Each need you have heard of
shows what you know came of it: an offer posted for it, word that someone
supplied it or that an offer went untaken, its job still open, goods you bought
for it still on the road. You can answer it yourself with an offer that names
whose need it is for, at the price they said, and buy goods in a neighboring
town to be carried to you; your journal accounts for both (`interface.py`,
`player.py`, `player_history.py`). Your answer counts like anyone's.

**Measuring it.** `consequence_record` (`eternia/evaluation.py`) lists every
answer from the recorded actions: who answered whose need, by which route, and
whether the goods went to the person they were for, to someone else, or lapsed;
for goods fetched from another town, whether they arrived.
For goods that went to the person they were for, it records whether that person
then took the step the goods served. It also counts how far word of needs,
corrections and supplies spread.

**Pass condition:** with nobody playing, a person hears of a need, chooses on
their own to answer it, completes an ordinary transaction, and changes another
person's circumstances; and the same person declines an unprofitable or
outdated opportunity.

| Condition | Evidence |
|---|---|
| Heard, chosen, transacted, with nobody playing | Toren lacks 2 iron for a house and Rivermark has none to mine or buy; Mara holds iron she can spare, and the market there has no coins to buy it (both moved from Highfen for the test). Toren tells her; in cycle 5 she offers it: "Offer 2 iron to Toren of Rivermark for a house at the 6 a unit they would pay; Toren of Rivermark told me they need it, and the market here cannot pay for it." In cycle 7 he buys both for 12 coins; in cycle 8 he builds the house (tests) |
| Another person's circumstances change | Toren has a house, 12 fewer coins and more trust in Mara, and she in him. Both hold "Mara of Rivermark supplied Toren of Rivermark with 2 iron for a house"; it reaches people who were not party to it, and hearing it moves each one's trust in her up a little. She drops his need and does not offer again. In the same run Edrin and Aldren both answer Lyra's need for iron: she buys Edrin's, and Aldren's lapses into a correction that spreads (tests) |
| The same merchant declines what does not pay | While the market can pay, it pays 12.8 for iron, more than the 6 Toren would pay, and Mara makes no offer; nor does she when he says nothing he could pay. News over two years old, a correction, someone she distrusts, or iron she needs herself are each a reason to decline (tests) |
| Kindness has a limit | Trusted enough (0.75), a buyer is offered iron at 6 when the market would pay 7.5, a knowing loss; at 8.8, more than 30% above his price, even a friend is declined (tests) |
| Trust shapes who buys from whom | Among fair offers a buyer takes 6 from a seller he trusts (0.3) over 5.8 from a stranger, and never 5 from someone he distrusts (tests) |
| Goods fetched for a need heard of | With no iron anywhere in Rivermark (moved to Highfen, with some of Rivermark's spare food, for the test), Mara has heard that Toren needs 2 iron and Lyra 1. In cycle 5 she buys 3 in Highfen: "Buy 3 iron in Highfen at 1.35 each and have it carried here to meet Toren of Rivermark's need for a house, at the 6 a unit they would pay; Toren of Rivermark told me they need it. With provisions it costs 8.1 coins, and after the 8% risk on the road it should earn about 3.52 more." It arrives in cycle 9. While Rivermark's market would pay 12.8 for it she does not offer it to Toren; in cycle 16 the market runs short of coins, and in cycle 17 she offers him 2 at 6. He buys the one he still lacks (tests) |
| Fetching has to pay | Lyra's 1 iron alone, heard third hand, does not pay for the road's provisions; with Toren's 2 it does. Someone who is not a merchant does not fetch for others, nor does a merchant short of the same goods for her own goal. Goods lost on the road are the buyer's loss, and the same chance no longer pays on that road (tests) |
| Failure changes what people do next | A correction replaces the need it corrects; after one of her offers to Toren went untaken, Mara counts his next stated need at half the certainty (tests) |
| It happens on its own | (Figures as of Stage 3; see [Stage 4](#stage-4-measurement-follow-through-willingness-to-pay-and-speed-implemented) for the current ones.) Over 25 years with seeds 18, 42 and 73 nobody plays: people answered needs they had heard of 3, 3 and 4 times (7 offers and 3 gatherings, by 2, 3 and 4 different people), against none before. 2 offers were taken up by the person they were for, both by a Toren short of iron, and both went on to build the house it was for. 5 offers lapsed untaken and became corrections; in seed 42, Edrin answered Toren in the same season as Aldren, and Mara in the season Toren hired for the rest. Fetching from another town would have paid once in the 75 years, and the merchant had more pressing things that season |
| Most chances are rightly declined | (As of Stage 3, counted when a person's policy reached the question.) In those runs people weighed a heard need 5,106 times, once a season for each need they knew of. They declined 5,002 times: the news was too old to act on (3,819), the buyer said nothing they could pay (496), the market paid more (240), they had nothing to spare, gather or profitably fetch (154), they knew it was corrected, covered by a job or another offer, or supplied (282), or the person was not here (11). An answer was worth considering 104 times, and people chose it 10 times; the rest of the time something else mattered more that season |
| Rules and replay | An offer for a need its seller has not heard of, a buy offer stating a need, or a gathering or purchase for an unheard need is refused; a purchase in another town needs an open market there, at most eight units, and the coins for goods and provisions. Fetched goods are counted while on the road, and nothing is created. A checkpoint taken with such an offer open resumes the same history. A player's answer is recorded, saved and loaded like any other action (tests) |
| Earlier results | Every mode before v0.7 is byte-identical. v0.7 societies nobody plays change wherever someone answers a need. Re-deriving every figure in this README changed the quick start (247.11 coins in wages instead of 269.58, 9 voluntary actions instead of 8, 20 market purchases instead of 22, 28 goal changes instead of 27), the year-10 prices in Rivermark and Deepwood, Stage 1's 25-year job counts, one path in the [Changing Miner](#the-changing-miner) (in seed 42 the curious miner stays with a food reserve instead of going back to 80 coins) with the adaptive and fixed averages, and the [inequality experiment](#inequality-experiment) in every seed; all are updated in place. Two inequality findings no longer hold in every seed and are restated: an unequal start alone no longer makes food insecurity clearly more common, and where merchants hold the public funds the levies now bring the Gini down in every seed. The labor and market experiments, the evaluation matrix and the figures quoted for play are unchanged. One Stage 2 test, which showed that knowing needs changed nothing else, now shows that answers come only from knowing them; no other test needed a new anchor |

What Stage 3 does not do yet:

- **The buyer's price is the brake.** Answers are rare because the economics
  are, not because people lack goods or information: in the long runs, having
  nothing to spare, gather or fetch was the reason for about 1 decline in 30. When a town runs out of
  something, its posted price soon rises far above the 1.5 times base a buyer
  thinks fair. From then on, the market pays a seller more than the needy person
  would, unless the market has run out of coins or the seller is a friend. And
  496 times the needy person had too few spare coins to name a price at all. A
  need that stays unmet does not raise what its holder offers ([Stage 4](#stage-4-measurement-follow-through-willingness-to-pay-and-speed-implemented)
  tested that as a switch).
- **Fetching rarely pays.** For a few units, the food for the road costs about
  as much as the goods, and needs heard of in town are usually small, so a
  merchant fetches mostly when several needs for the same goods add up.
- **Needs stay in their own town.** A person answers needs in the town where
  they live; nobody yet carries goods to a need in another town.
- **Gathering for a need rarely ends in a sale.** Of 3 gatherings for someone's
  need in the long runs, only 1 was followed by an offer, three seasons later,
  and it lapsed untaken. Nothing commits a gatherer to finish: once gathered, the
  goods compete with everything else they could do with them. (Stage 4 makes
  people follow through.)
- **Simultaneous answers.** People plan from the same view of the season, so two
  may answer the same need at once. One is then left with an offer nobody takes,
  which at least tells the town the need may be over.

### Stage 4: Measurement, follow-through, willingness to pay and speed (implemented)

Stage 3 showed that people act on what they hear, but rarely, and that the
buyer's price looked like the brake. Stage 4 measures that properly, makes
people finish what they start, tests whether paying more for a stalled goal
would help, and makes long runs cheaper.

**What becomes of needs.** The world now keeps a historian's record that no one
in it reads (`_record_needs` in `eternia/society.py`). Each cycle, for every need
a person cannot meet themselves, it notes whether the market here had the goods
but above what they would pay, had none, or a neighbor in town held some to
spare. It also counts every judgment people made about needs they had heard of,
by reason, and follows each need from the cycle it arises to how it ends:

- **can gather it:** the goods came within reach of the person themselves;
- **market sells it:** the market now sells them at a price they will pay;
- **offered:** someone offered the goods for it;
- **got the goods:** they got them some other way;
- **moved on:** they took the step, or their goal changed.

Keeping the record changes nothing: the same worlds with and without it have
byte-identical histories (tests).

**Following through.** For two years after someone gathers or fetches goods for
a heard need, the news counts as current to them. Offering those goods weighs
15 more, so it outranks routine council business: "Offer 4 food to Lyra of
Deepwood toward a food reserve at the 1.5 a unit they would pay; I got it for
them" (`needs.py`, `economic_policy.py`). The market is still compared: if it
would pay more than the person in need, they still sell to the market.

**Willingness to pay, as a switch.** `SocietyWorld(rising_willingness=True)`
lets a stalled goal raise what its holder will pay for its materials. Each cycle
without progress adds a tenth of the fair price, up to twice it (12 for iron).
A person who cannot pay that much names what they can (`willingness` in
`eternia/needs.py`). The new `--opportunity-experiment` runs the same seeded
societies with it off and on (`eternia/opportunity_experiments.py`).

**Faster long runs.** Building each person's view of the world no longer copies
the same things twice. Each person's last twelve local events are found by
reading back from the newest instead of through the whole history. Counting
the people at home no longer scans every journey once per person. Histories are
byte-identical to before (checked across five worlds and every earlier mode).
Back to back on the same computer, forty years of the seed-42 society take 11.5
seconds instead of 18.3, and a year in the fourth decade 0.37 seconds instead
of 0.61, with Stage 4's record and everyone's judgments included.

**Pass condition:** the long-run behavior of needs, answers and their costs is
measured across seeds; the question whether willingness to pay should rise is
settled by evidence; someone who gathers for a need follows through; and long
runs cost less without changing what happens in them.

Over 25 years with seeds 18, 42 and 73, nobody playing:

| Measure | Fixed willingness (the default) | Rising willingness |
|---|---|---|
| Needs people could not meet themselves | 70 / 70 / 68 | 53 / 17 / 49 |
| Food among them | 62 / 59 / 60 | 48 / 9 / 38 |
| Typical length (median cycles) | 2 / 3 / 3 | 3 / 3 / 2 |
| Need-cycles the market had the goods above what they would pay | 53% / 54% / 54% | 15% / 16% / 15% |
| Need-cycles a neighbor held some to spare | 49% / 63% / 48% | 47% / 79% / 57% |
| How needs ended: could gather it, market sold it, offered, moved on | 118, 33, 9, 36 of 208 | 40, 38, 2, 24 of 119 |
| Needs answered by others / supplied to the one in need | 4, 3, 10 / 1, 1, 2 | 8, 6, 3 / 1, 1, 0 |
| Goals reached | 11 / 27 / 19 | 17 / 13 / 13 |
| Houses built | 4 / 6 / 4 | 5 / 4 / 4 |
| Mean coins at the end | 40.9 / 40.3 / 39.1 | 30.9 / 34.7 / 29.7 |
| Hunger (share of person-cycles) | 2.6% / 1.3% / 2.9% | 1.5% / 1.8% / 3.0% |
| Wealth Gini | 0.44 / 0.45 / 0.42 | 0.47 / 0.47 / 0.41 |

| Condition | Evidence |
|---|---|
| Economic constraints are measured | With a fixed willingness to pay, in more than half of all need-cycles the market here had the goods, at a price above what the person would pay. In half or more, a neighbor held some to spare. Most needs were short: food shortages that ended by themselves within two or three cycles, when forage regrew or the market restocked (151 of 208). That is why the most common reason to decline news of a need was that it was too old to act on (5,937 of 8,532 judgments); then that the buyer could pay nothing (801), that it had been corrected (597), and that the market paid more (511) |
| Willingness to pay is evaluated | Letting it rise cut the needs people could not meet by a quarter to three quarters, and the share priced out of a stocked market from about 54% to 15%. But the coins went: people ended with 6 to 10 fewer each, goals reached fell in two of the three seeds, houses did not increase, and others answered needs no more often. It stays off by default, as a switch for experiments |
| People follow through | Every gathering for someone's need in the long runs was followed by an offer to that person within two years (4 of 4), against 1 of 3 at Stage 3. In seed 73, Mara of Deepwood gathers 6 food for Lyra in cycle 44 and offers it to her in cycle 46, the first cycle she is not eating (tests). With that, the default runs answered 4, 3 and 10 needs instead of 3, 3 and 4 |
| Keeping records changes nothing | The same worlds with and without the record are byte-identical, and the judgments people make are computed once, before they plan, from the same view (tests) |
| Long runs cost less | Forty years in 37% less time, the last decade's years in 40% less; five worlds (three societies, the community and the original simulator) are byte-identical with and without the speed-ups. A person's last twelve events are the same as reading the whole history, and a policy that changes its own view changes nothing in the world (tests) |
| Earlier results | Every mode before v0.7 is byte-identical, and the speed-ups change no history. Following through changed one case among the README's figures: the inequality experiment where merchants also hold the public funds, in every seed, now updated in place. Its findings stand, with cooperative membership after an unequal start at 48–64% and food insecurity with merchant-held funds at 9–26%. The quick start, prices, labor, market, goal and evaluation figures are unchanged. Stage 3's long-run counts are marked as of Stage 3; the current ones are above |

What Stage 4 does not settle:

- **Whether paying more is right is left open, not refuted.** A rising price that
  stops at twice the fair one, with nothing else changed, spends coins people
  also need for their other goals. A builder who values the house more than the
  coins, or a merchant who stocks up when a town runs short, may change the
  answer.
- **The player's part over the long run** is shown in single sessions (a player
  can answer a need, fetch goods and see what came of it), not yet measured
  across many.
- **Memories and knowledge fill up** to their limits in the first decade, and a
  cycle costs more until they have; the costs after that are flat.

## Roadmap: The First Player

v0.8 makes Eternia playable instead of adding another large simulation system:
a person enters Rivermark with a small inventory, little money and no special
privileges, and takes part in a society that does not revolve around them.

| Stage | What it adds | Completion criterion | Status |
|---|---|---|---|
| 1. Player integration | A player character with an identity, inventory, location and manual action selection | Player and NPCs act in the same simulation cycle | Implemented |
| 2. Player agency | Guided menus for every action, hiring, contracts and trade; organizations, proposals and votes; reputation through the existing trust system; a personal journal | The player can earn, spend, trade and influence the economy and politics without writing actions by hand | Implemented |
| 3. NPC interaction | Conversations grounded in each person's knowledge, opinions shaped by personality and trust, and news that spreads from person to person | People respond from their own information and circumstances | Implemented |
| 4. Playable interface | A terminal interface first, then a local browser interface with a town view, inventory and event feed | A complete session can be played, saved and resumed | Implemented |

Deliberately postponed: multiplayer servers, advanced graphics, combat and a
language-model conversation system.

### Stage 1: Human player integration (implemented)

A player is an ordinary person in the world whose proposals come from a human
instead of a policy (`eternia/player.py`, `eternia/playable_session.py`). The
world holds the player's chosen proposal until the next cycle and adds it to the
same batch as everyone else's, so the common snapshot and conflict resolution
apply unchanged. See [Play Eternia](#play-eternia-v08) for how it plays.

**Pass condition:** start a society, create a human player in Rivermark, choose
an action, let every autonomous person act during the same cycle, and verify
that the consequences persist, across several turns and after saving and
loading.

| Condition | Evidence |
|---|---|
| Player and NPCs act in the same cycle | Each turn is one ordinary cycle: one batch with one proposal from each of the 19 living people, the player's included (tests) |
| The player does not act before everyone else | The player's place in the seeded order changes from cycle to cycle (1st to 19th in 12 turns) |
| The same permissions, costs and constraints | Missing knowledge, insufficient coins and needless rest are refused with the engine's reasons; gathering costs the same energy; a contested purchase of the last units is settled like anyone else's; a player cannot act for someone else (tests) |
| Consequences persist | Goods, coins, hunger, energy and town deposits carry over from turn to turn; a world saved between turns and loaded again continues exactly like one that never stopped (tests) |
| Replay is reproducible | Rebuilding from the recorded inputs alone gives an identical history, also across a save, from a joined `--society` checkpoint and after an heir takes over (tests, `--replay`) |
| A world without a player is unchanged | At Stage 1, a society nobody plays produced the same history as before v0.8; Stage 2's general trust rules have since changed some long-run outcomes ([below](#stage-2-player-agency-implemented)). Every earlier mode is byte-identical |

### Stage 2: Player agency (implemented)

Stage 2 lets a player pursue their own ambitions through ordinary menus and
makes society respond to them, with one principle throughout: no separate
rules for players. It has four parts.

1. **A fully interactive economy** (`eternia/player.py`, `main.py`). Every
   engine action has a menu entry, with fields for quantities, prices, wages
   and names. A changed choice is checked before the turn is spent.
2. **Political participation.** Founding organizations, every proposal a
   charter allows, votes, enactment of approved decisions and contract
   caravans. People keep voting from their own interests and beliefs.
3. **Reputation and consequences** (`eternia/society.py`,
   `eternia/economic_policy.py`), through the existing trust system and for
   everyone alike:
   - losing contested goods (the market's last units, an exhausted deposit, a
     job's last paid units) to someone in the same cycle lowers the loser's
     trust in the winner by 0.03;
   - a gift to an organization raises each other member's trust in the giver by
     0.02;
   - nobody takes a private job from an employer they trust at -0.3 or less, and
     nobody joins an organization whose members they trust at -0.35 or less on
     average, which was already the rule for some decisions;
   - an embargo enacted by a town's governing council now also stops private
     shipments between the two towns.
   Pay, help, food aid and contested levies already moved trust before.
4. **A personal journal** (`eternia/player_history.py`), derived entirely from
   the world's records: see [Your journal](#your-journal).

**Pass condition:** a player can build a livelihood without writing an action,
influence a town without guaranteed authority, see society react to what they
do, and understand the lasting effects of their decisions.

| Condition | Evidence |
|---|---|
| A livelihood without writing an action | In seed 42, after a year of history, a newcomer founds a cooperative, gathers and sells 8 food three times and hires for wood through the menus alone; Aldren takes the job and delivers 8 wood (tests) |
| Every action is reachable | All 23 engine actions have menu entries; contract caravans appear to members of an exporting organization (tests) |
| Influence without guaranteed authority | A council member's public-work proposal at 4.9 coins per wood was voted down by every other member; at 1.5 it passed unanimously, and the player carried it out, escrowing 12 coins of the town's money (tests) |
| Society reacts to the player | A job posted by someone the town distrusts (trust -0.5) stayed untouched for eight cycles while the same job from a stranger was completed; an aggrieved neighbor who would join a newcomer's cooperative declines once they distrust its founder; a gift raised a fellow member's trust by 0.02 (tests) |
| The same rules for everyone | In the contested-purchase test an autonomous buyer got the last food, and the player and the merchant who missed out lowered their trust in that buyer by the same 0.03; the rules never ask who is a player (tests) |
| Lasting effects are visible | The journal accounts for every coin: in the livelihood above, 10 on arrival + 12.24 from sales − 2 founding fee − 18.32 in wages = 1.92 now, nothing unexplained; it is identical after saving, loading and replay (tests) |
| Earlier results | Every earlier mode is byte-identical. In 25-year v0.7 societies nobody plays, people act exactly as before until year 7 (seed 42), 10 (seed 18) or 15 (seed 73), and throughout in seed 18 with collective priorities; after that, trust set by the new rules changes some choices (in seed 42 a teacher picked a different pupil). Re-deriving every v0.7 figure in this README changed two: mean trust at the end of the inequality experiment fell from 0.06–0.08 to 0.04–0.07, and the 10-year quick-start run has 16 voluntary actions instead of 17. The market, labor, goal and other inequality results are unchanged |

The plan's example now plays out: food was scarce in Highfen, which bought it at
1.83 coins while Rivermark's market paid 0.61, so a player who arrived after a
year bought 8 food for 5.92 coins and shipped it there for 14.64 on delivery.
The shipment was lost to an accident on the upland road, which carries about an
8% risk, and the journal recorded the loss (tests). (Figures as of v0.9 Stage 1,
whose new hiring changed this history: with two years of history the road had no
room left that cycle.)

### Stage 3: NPC interaction and knowledge exchange (implemented)

Stage 3 lets a player talk to the people who live in Eternia and find out what
they know, in three parts.

1. **Conversations grounded in knowledge** (`eternia/dialogue.py`). A person
   answers from their own observation, which since this stage includes the
   claims they hold, and from nothing else. Asking takes no season, so a
   conversation is not an action. Each one is recorded in the input history
   for replay.
2. **Opinions and relationships.** Answers depend on personality, goals,
   memories, trust and interests. People can be unsure, decline, or explain how
   they would vote; their stated stance comes from the same criteria they vote
   by.
3. **Information spreads** (`eternia/social_memory.py`). Experiences and things
   seen become claims: an employer's pay, help received, goods someone got
   first, a lost shipment, a famine, a death, an arrival, a public decision. A
   claim records who knew it first, who passed it on, when it happened and
   when it was heard, how often it was retold and how sure its holder is. Each
   season everyone at home may tell one neighbor, chosen in turn, one piece of
   news they have not heard, and only someone they do not distrust. Each
   retelling keeps 80% of the confidence. News leaves a town only with someone
   who moves, through a merchant's market contact, or with a player. Hearing how
   someone treats people moves the hearer's trust in them by up to 0.02, and a
   merchant who hears of a shipment lost on a route asks a larger margin before
   using it. There are no random draws: replay stays exact.

**Pass condition:** a player can talk to several inhabitants, get different
answers grounded in each one's knowledge, learn something useful, and see trust
or new information change later decisions; conversations and their
consequences survive saving, loading and replay.

| Condition | Evidence |
|---|---|
| Answers come only from the speaker's knowledge | Changing anything a speaker cannot see (other people's coins, feelings, beliefs and what they know, buried ore) leaves every answer unchanged (tests) |
| Different people, different answers | In seed 18, thirteen years on, Mara, Edrin and Toren gave three different accounts of what had been happening; Mara spoke of her own lost shipment, which nobody else in town described as theirs (tests) |
| Something useful is learned | Mara's lost shipment told the player the upland road to Highfen is dangerous, which is not in the player's view; the journal keeps it with its source and age (tests) |
| Personality and trust shape answers | In seed 42, seven years on, Toren keeps his affairs to himself with a stranger and opens up at trust 0.3; Edrin shares his goals, but refuses to talk at trust -0.6. In seed 18 it is Mara who is guarded (tests) |
| Stances match votes | Every council member who told the player how they would vote on the player's public-work budget voted that way: against at 4.9 coins per wood, for at 1.5 (tests) |
| News spreads but never becomes universal | After 10 years, claims had passed through up to five retellings in seed 42 and four in seed 18, and every retold claim names its source. In seed 18, where nobody moved between the towns, each Highfen famine was known only to Highfen's six residents. In seed 42 the first one also reached Rivermark, and only one way: Mara heard of it through her shipment to Highfen's market and it passed through four retellings there (tests) |
| Trust and new information change decisions | Hearing that an employer underpaid someone moved a worker from trust -0.29 to -0.306 in that employer, past the -0.3 at which nobody takes their jobs; a merchant expecting 2.5 coins from shipping food to Highfen stopped once she heard of a loss on that road, which raised her required gain from 2 to 3.6 (tests) |
| Survives saving and replay | Conversations, what they taught and what followed are identical after saving and loading and after replay from the recorded inputs; a tampered conversation is detected (tests) |
| Earlier results | Every earlier mode is byte-identical. Compared with Stage 2, v0.7 societies nobody plays behave exactly as before for all 25 years in seeds 18 and 42 and in seed 18 with collective priorities, and until year 15 in seed 73. Re-deriving every v0.7 figure changed one case: in seed 42 with an unequal start, the last decade's Gini is 0.52 instead of 0.53, fairness 0.35 instead of 0.37, cooperative membership 55% instead of 49%, poverty 25% instead of 26%, food insecurity 10% instead of 4%, the poorest third's wealth 12 instead of 11, and levies 339 coins instead of 322. Mean trust moved by at most 0.005; the market, labor, goal and quick-start results are unchanged |

### Stage 4: The playable browser interface (implemented)

Stage 4 makes the systems of Stages 1 to 3 playable on a page instead of a
terminal, without adding simulation mechanics. Python stays the authority
(`eternia/interface.py`, `eternia/web.py`, `eternia/webui/`): views are built
from the player's own observation, journal and public records, and every change
goes through the same session the terminal uses. See
[Play in your browser](#play-in-your-browser).

1. **World and town view:** the map, the current town and its neighbors, roads,
   prices and the events of each season.
2. **Character:** goods, needs, skills, buildings, work and every available
   action.
3. **People:** choosing inhabitants, asking them questions and reading back what
   they said.
4. **Economy and politics:** jobs, markets, offers, organizations and open
   proposals, with the choices that act on each next to it.
5. **Timeline and journal:** how prices and the player's town changed, cycle by
   cycle, and a report of what changed after each decision.
6. **Save and resume** through the existing checkpoints and recorded inputs.

**Pass condition:** a complete session can be played, saved and resumed in the
browser, and the browser never calculates a price, resolves an action or
changes anyone's state.

| Condition | Evidence |
|---|---|
| A complete session in the browser | Through the server's own entry points, a newcomer gathers 5 food, sells 4, asks Mara about trade, founds "The Free Traders", waits two seasons and eats; the world afterwards is identical to the one the same choices produce in the terminal (tests) |
| Saved and resumed | Saved from the browser, that session resumes from its checkpoint, and rebuilds from its recorded inputs, to an identical history; one more turn in each keeps all three identical (tests). Unsaved play is saved when the server stops (tests) |
| Python is the only authority | The menu, its numbering and its proposals are the terminal's; every price shown is the town's posted price and the market's 80% of it, computed by the simulation (tests). The page sends choice numbers and values; changed values pass the terminal's own field checks and dry run, and one the rules would refuse spends nothing (tests) |
| Views neither reveal nor change anything | Building every view leaves the world's state and its random sequence untouched; giving everyone else 500 more coins, turning their feelings, beliefs and knowledge, and burying the ore leaves the player's view unchanged (tests) |
| Society's response is visible | After each turn the page lists what changed for the player and, in prices, their town, its jobs and its organizations; the timeline follows the player from town to town, showing no town's events on the road and only the new town's after arriving (tests) |
| One season per decision | A request made from an outdated view (a double click, an old tab) is refused and changes nothing (tests) |
| Only the page it served can play | Without the launch token, through another host name (DNS rebinding) or from another site, requests are refused and the world is unchanged; save names cannot leave the save folder (tests) |
| Earlier results | Stage 4 adds no simulation rules: every earlier mode and every figure in this README is unchanged |

### v0.8.1: Playability and reliability (implemented)

A review of the finished v0.8 found three things worth fixing before adding
anything, and one to measure. This pass changes no simulation rule.

| Finding | What changed | Evidence |
|---|---|---|
| The page itself was never clicked in a real browser | `tests/test_browser.py` drives it in headless Chromium or Edge with Playwright, and checks the world the server holds after each step: every tab in both themes, a choice with a changed amount, a choice the rules refuse, a conversation, a journey to Deepwood and arrival, saving, resuming and replaying through the dialog, an old tab, and the price charts. CI runs them in their own job; without Playwright they are skipped, so the main suite still needs only the standard library | 8 browser tests. On their first run they found a bug the Python tests could not see: the chart tooltip printed `[object HTMLDivElement]` instead of each town's price (fixed) |
| A checkpoint and its inputs were written separately, so a crash between the two could leave them out of step | Both are written in one step each, and the inputs are stamped with the checkpoint's checksum and cycle; the save list marks pairs that do not belong together, and inputs that are unstamped or unreadable | A newer checkpoint beside older inputs is reported as not belonging together; a write that fails part way leaves the previous save whole and no temporary file (tests) |
| A new game or a load ignored the view's version, so an old tab could replace newer, unsaved play | Saving, loading and starting a new life carry the view's version like every other request, and unsaved play is kept as `autosave` before another session replaces it | From an outdated view, all seven kinds of request are refused and neither the world nor the save folder changes; loading or starting over keeps unsaved play, without overwriting the autosave being loaded (tests, browser tests) |
| The timeline rebuilt its history from the whole event and action logs on every request | The household's history is indexed incrementally, outside the world, and rebuilt only when an heir takes over or a log was rolled back; only the cycles shown are assembled | Identical to the full rescan in 556 comparisons through a journey, conversations and two heirs |

Measured on the development machine, playing one newcomer for 100 years (402
cycles, 12,768 events) after the founding:

| | Before | After |
|---|---|---|
| Timeline, the 40 newest cycles with the price charts | 101 ms | 26 ms |
| The whole page's view, rebuilt after each turn | 182 ms | 119 ms, of which the journal is 62 ms |
| One simulation cycle for everyone | 0.9–1.1 s | unchanged |

The interface is no longer what slows a long session down: the simulation is.
One cycle takes about 50 ms at the founding, 0.5 s after 25 years and 1.1 s
after 100, mostly in copying each person's observation, which carries every
organization's whole decision history, and in the snapshot each cycle keeps to
roll back a failed cycle. Thousands of years through the browser need that
cost addressed first (see [After the Living Economy](#after-the-living-economy)).

## Roadmap: The Living Economy

v0.7 was built in four stages. Stage 1 gives Eternia the foundations of a
working labor market, Stage 2 makes that economy react to conditions, Stage 3
lets people's ambitions evolve, and Stage 4 connects economic circumstances to
relationships, organizations and collective decisions. Each stage has a pass
condition, so "done" means a measured result and not a list of features.

| Stage | Aim | Status |
|---|---|---|
| 1. Regional labor market | People hire, take paid work and travel between towns for a job | Implemented |
| 2. Dynamic markets | Prices emerge from local supply and demand | Implemented |
| 3. Adaptive goals | People reconsider what they want from life | Implemented |
| 4. Inequality and social consequences | Economic conditions shape relationships, institutions and collective decisions | Implemented |

**Next: v0.8, The First Player**, now under way; see
[Roadmap: The First Player](#roadmap-the-first-player).

### Stage 1: Regional labor market (implemented)

People can hire others, accept paid work, and travel between settlements for
employment. Councils, voluntary organizations and individuals can each fund a
job, and each must have the money first: the full wage budget goes into escrow
before anyone works.

In the matched [labor experiment](#labor-experiment), miners travelled for a
well-paid job in all 9 runs that offered one and in none of the 27 control runs
(low wage, comparable work at home, or blocked roads). The mechanics are
described under [Paid work across the region](#paid-work-across-the-region).

Since Stage 2, wages follow local prices and workers compare a job with selling
the same goods. Still fixed: nobody negotiates a wage or counters an offer, and
only travel is dangerous, never the work itself.

### Stage 2: Dynamic markets, supply and demand (implemented)

**Objective:** make prices emerge from economic conditions and not from fixed
values.

Before Stage 2, every town posted the same fixed prices (food 1, wood 2 and
iron 4 coins per unit), so a settlement in famine valued food exactly as much as
one with enormous reserves. Now each town sets its own prices, and they reflect
its geography. In the default world, Highfen's food is soon the dearest in the
region and its iron the cheapest, while Rivermark, with fertile land and almost
no ore, is the reverse. After ten years of the seed-42 quick start:

| Settlement | Food | Wood | Iron |
|---|---|---|---|
| Rivermark (fertile, little ore) | 0.61 | 2.45 | 8.57 |
| Highfen (mines, poor farmland) | 2.10 | 2.89 | 1.05 |
| Deepwood (forests) | 0.72 | 0.67 | 10.62 |

Stage 2 was built in four steps:

- **A. Local price formation.** Each town posts a price per good every cycle,
  from its stored, accessible and incoming goods and last year's production,
  compared with expected use and a customary reserve. Changes are bounded and
  smoothed. A price history is recorded, saved and shown in the report. See
  [Local markets](#local-markets).
- **B. Purchasing decisions.** People buy food they cannot gather, keep coins for
  a few meals before spending on other things, buy materials their goal needs
  when the price is reasonable, sell surpluses while prices are at least at
  their base, and gather scarce goods to sell.
- **C. Price-driven regional trade.** Merchants consign goods to a dearer
  neighboring market, and councils negotiate trade contracts priced between the
  two towns' posted prices. Both count transport capacity, provisions and
  journey risk, and goods still travel as physical caravans.
- **D. Prices feed employment.** Councils and private employers offer wages at
  60% of the local price, councils refuse wages above what their market pays
  sellers, and workers decline a job when gathering and selling the same goods
  would pay more.

**How we know it works.** The pass conditions, and the evidence for each:

| Condition | Evidence |
|---|---|
| A food shortage raises local prices relative to otherwise comparable conditions | With the same total food, moving Highfen's stores to Rivermark starts Highfen at 1.99 coins and Rivermark at 0.83, against 1.13 in both when stores are shared evenly ([market experiment](#market-experiment), unit tests) |
| Increased supply reduces scarcity pressure | Adding stock or incoming cargo raises a town's coverage and lowers its price at the next cycle (unit tests) |
| Agents with appropriate goals and information recognize profitable opportunities | In all 9 price-gap runs, Rivermark's merchant bought cheap food and consigned it to Highfen in the first two cycles. When Stage 2 was added, councils also agreed food contracts into Highfen in 6 of them; since Stage 3, members spend more turns on their own goals and none forms within two years |
| Agents do not repeatedly enter unprofitable trades | No shipment left expecting a loss in any of the 27 market-experiment runs or three 20-year societies; none was shipped when food coverage was matched or roads were blocked; after a loss a merchant needs a larger margin on that route |
| No goods or coins are created through market exchanges | Every trade, consignment and delivery is checked against the conservation ledger; ledger residuals stay below 1e-6 |
| Save/resume reproduces prices and transactions | A resumed world matches the uninterrupted one, including price and trade histories (tests) |

Two results set the limits. First, trade is small next to need: one merchant
shipment carries 8 food to a town that eats about 150 a year, and Highfen's
roads wear and suffer landslides until they only fit caravans too small to pay
for their provisions. Over two years Highfen kept 113–123 of its 150 people with
the price gap, 107–117 with its roads blocked, and 146–152 when food was shared
evenly. Second, councils pay wages from local prices, so cheap Highfen iron is
worth less to mine. When Stage 2 was added (measured with the 5-year evaluation
before Stage 3), moves for work into Highfen in the `labor_shortage` scenario
fell from 0.67–1.0 per run to 0–0.33, mean goals met in the baseline rose from
0–0.33 to 0.33–1.33 per run, and hungry person-cycles fell from about 1.4% to
0%, mostly because people could now buy food.

### Stage 3: Adaptive goals, individuals with changing ambitions (implemented)

**Objective:** allow people to reconsider what they want from life, without
prescribing their life's trajectory.

Before Stage 3, people pursued the goal they were assigned forever. Edrin, a
miner who wants 60 coins, would keep chasing coins after reaching them, and a
researcher who could never reproduce the Aether effect would never give up.
Now each person has six **motives** (security, wealth, belonging, curiosity,
influence and legacy) that their experiences move slowly. Their goal is kept,
raised, replaced or allowed to rest according to those motives and their own
evidence. The mechanics are under [Motives and goals](#motives-and-goals).

Goals are limited to kinds the world already measures and the action engine
already serves: holding coins (`wealth`, or `profit` for merchants), keeping a
food reserve, owning houses, reaching Aether knowledge, and carrying out
approved public decisions (`influence`). A person's goal now steers what they
do. A miner who adopts a knowledge goal runs experiments, a houses goal without
carpentry starts with study, and a food-reserve goal leads to gathering.

The principles from the proposal hold by construction:

- No goal changes because of age or the calendar.
- An unfinished goal is replaced only when an alternative scores clearly higher,
  and every goal is held for at least two years.
- A person can decline a new ambition after success; how much pull they need
  depends on their ambition trait.
- Every change records the previous goal, the new one, the scores, and the
  experiences and evidence behind it.
- Hunger and fatigue are handled before any goal.

**How we know it works.** In the [Changing Miner](#the-changing-miner)
experiment, 20 years across seeds 18, 42 and 73 (figures from the complete v0.7,
including Stage 4):

| Condition | Evidence |
|---|---|
| Repeated success sometimes produces an explainable change | Having reached 60 coins, Edrin aimed for 120–130 in all seven runs with seeds 18 and 42 in which he reached it, and three times went on to aim for 240–280; in seed 73, with a less ambitious temperament, he took on nothing new in all three cases where he reached it |
| Repeated failure sometimes produces an explainable change | In three runs he gave up on 120–130 coins after 19–23 cycles (about five years) without progress, twice for a food reserve and once, in seed 42, for Aether research; in seed 18 he secured the reserve, went back to coins, reached 140 and aimed for 280. Where he never reached even 60 coins (the struggling miner in seeds 42 and 73), he gave up after 21 cycles for a food reserve and later settled for 70 |
| Meaningful events can change ambitions | The reasons cite them: in seed 18, "Stopped trying to hold 130 coins after 21 cycles without progress", with evidence including "was helped through hardship"; in seed 42, "was poor with no paid work on offer" and "saw their organization deliver for its members" |
| Short-term fluctuations do not rewrite personalities | One hunger episode raises security by at most 0.03, and the motive drifts back toward temperament by 3% of the gap every cycle; temperament itself moves only 0.5% per cycle toward lived motives; with a two-year minimum per goal, people changed goals about once every seven years |
| Completed goals are never erased by later ones | Lifetime completions, revisions, abandonments, refusals and active goals are counted separately (tests) |
| Save/resume reproduces motives and goal histories | A resumed world matches the uninterrupted one (tests) |

Across the 12 runs per condition, people with adaptive goals reached 13.8 goals
per run (9–22) against 6.2 (5–7) with every goal fixed. At the end, though,
fewer were meeting their current goal (0.8 against 2.8), because people aimed
higher after success. They held more food (4.0 against 2.1 on average), with
similar hunger, wasted actions and coins. Three results are limits rather than
successes. Relationships never led the connected miner to an influence goal,
because his wealth motive stayed stronger than the belonging that trust builds.
Curiosity led the curious miner to research only once, in seed 42, and only
after 23 cycles without progress toward 120 coins; he stopped after two
inconclusive experiments. And people abandon goals more often than they reach
them (about 38 abandonments against 14 completions per run), because progress in
this economy is slow. (Figures as of v0.9 Stage 3; see
[what it changed](#stage-3-acting-on-what-people-hear-implemented).)

### Stage 4: Inequality and social consequences (implemented)

**Objective:** make economic circumstances influence social relationships,
institutions and collective decisions, without scripting either outcome.

Before Stage 4, wealth differences had no social consequences, and nothing
measured them. The stage was built in the five steps of the plan:

1. **Measure inequality.** Wealth, income, poverty, food insecurity, Gini
   coefficients and rank mobility for the named people, every year, for the
   region and each town ([Inequality and fairness](#inequality-and-fairness)).
2. **Model perceptions.** A fairness belief built only from a person's own
   experiences: being underpaid, priced out of food, poor without work, helped
   through hardship, or seeing their organization deliver. Economic life also
   moves trust.
3. **Connect perceptions to actions.** Existing actions only: joining or founding
   cooperatives, asking for aid, paying members for work, voting and proposing
   levies, giving, leaving, and weighing jobs in other towns. One rule changed: a
   majority council's levy now funds the town treasury, so a council can tax its
   members to pay for public work.
4. **Controlled experiments.** `--inequality-experiment` compares matched
   starting distributions of wealth and public funds
   ([Inequality experiment](#inequality-experiment)).
5. **Evaluate causality.** The same comparison across seeds 18, 42 and 73.

**How we know it works.** 30 years, 9 runs:

| Condition | Evidence |
|---|---|
| Wealth distributions respond to economic conditions | An equal start drifted from a Gini of 0.08 to 0.44–0.51; unequal starts stayed unequal (0.47–0.54), though where merchants held the public funds the heaviest levies (680–979 coins) brought it down from 0.57 to 0.48–0.54 |
| Institution membership responds | Cooperative membership averaged 14–22% after an equal start and 48–64% after either unequal one |
| Living standards respond | The poorest third held about 13–17 in wealth after an equal start, 9–12 after an unequal one and 7–11 when merchants held the public funds; food insecurity was 4–6% after an equal start and 4–9% after an unequal one, and rose to 9–26% when merchants held the public funds |
| Responses come from perception, not rule | Mean fairness fell from about 0.45 to 0.33 and 0.26 with the starting distribution; people with the same circumstances but no grievance do not organize (tests) |
| Outcomes are not forced to be identical | Seeds differ, and towns diverge within a run: with an equal start in seed 18, Highfen ended at a Gini of 0.31 and Rivermark at 0.52 |

Two outcomes named in the pass condition did **not** respond: trust and
migration showed no consistent difference between starting distributions. Mean
trust between neighbors ended at 0.04–0.09 in every case, and moves remain rare
(1–6 per run) because they need a job notice in another town and provisions for
the road. (Figures as of v0.9 Stage 4.)

## The current society in detail

```powershell
python main.py --society --years 10 --seed 42
start .\output\society\report.html
```

### Who lives there

The society has three settlements with different resources: **Rivermark** has
fertile land, **Highfen** has minerals, and **Deepwood** has forests. A river,
an upland road and a mountain pass connect them. Each town has an aggregate
population (480 inhabitants in total at the start) and six individually
simulated people:

| Role | Personal goal |
|---|---|
| Farmer | Hold a food reserve of 12 units |
| Miner | Hold 60 coins |
| Merchant | Hold 120 coins |
| Builder | Own 3 houses |
| Researcher | Reach knowledge level 2 |
| Councillor | Carry out 12 approved institutional decisions |

Agents observe limited public information, propose actions, and receive
authoritative world results. The v0.7 policy may seek a council, vote on public
work, choose funded employment, hire someone, travel to a paid job in another
town, buy and sell at the local market, ship goods to a dearer market, negotiate
municipal trade contracts, or contribute voluntarily. These are programmed
utility priorities, not LLM reasoning or a predetermined sequence of actions.
Use `--policy-style` with `balanced`, `personal` or `collective` to change those
priorities.

### Local markets

Every town posts a price for food, wood and iron at the start of each cycle.
Everyone plans from those posted prices, and every trade in the cycle uses them.
The rule, in [eternia/market.py](eternia/market.py), is explicit and illustrative,
not calibrated to real markets:

```text
coverage = (stored + accessible + incoming + expected production)
           / (expected annual use + customary reserve)
target   = base price / coverage, kept between 1/4 and 4 times the base
posted   = previous posted price moved toward the target by at most 25%
```

- **Base prices** are the old fixed table: food 1, wood 2 and iron 4 coins.
- **Supply** counts the town's stores, goods accessible for gathering, cargo
  already on the road to it, and last year's recorded production. Before the
  first harvest, a town is assumed to produce what it uses.
- **Demand** is expected annual use (each resident eats 1 food a year; households
  use 0.05 wood and 0.015 iron) plus a customary reserve of 1.12 food, 0.25 wood
  and 0.12 iron per resident, the same stock targets councils use to judge
  import needs.
- A town that expects to produce what it uses and holds its reserve therefore
  posts the base price. A famine raises the price; a glut lowers it.

The market sells at its posted price and **buys at 80%** of it, paying from the
town treasury. That spread means buying and reselling in one town always loses
money. Prices, coverage and last year's production are public in the home town
and neighboring towns, like job notices.

**Who uses the prices:**

- **People** buy food they cannot gather, holding back enough coins for three
  meals before spending on anything else. Builders and researchers buy a
  missing material when its price is no more than 1.5 times its base, and
  otherwise hire someone at a lower wage. People sell surpluses while the price
  is at least its base, and gather scarce goods to sell when the price is 25%
  above base.
- **Merchants** consign goods to a neighboring market with the `consign`
  action (1–12 units). The goods and provisions leave as a physical caravan, the
  destination market escrows payment at its posted buying price, and the
  merchant is paid only if the caravan arrives. A merchant ships only when the
  payment, discounted by the quoted journey risk, beats the goods' value at
  home plus the provisions by at least 2 coins. After a loss on a route the
  required margin rises for two years: three times as large after one loss,
  five times after two.
- **Councils** propose trade contracts priced halfway between the two towns'
  posted prices (allowing for risk), answer a neighbor's offer when it profits
  their town, and dispatch contract caravans only when the agreed price beats
  the goods' value at home. A council negotiates separately with each neighbor
  for each good.
- **Employers** offer wages at 60% of the local price (within the 0.1–5 coin
  job limits). Councils vote against wages above what their market pays sellers.
  Workers decline a job when gathering and selling the same goods would earn
  more per action (selling takes a second action).

Every shipment records what its cargo and provisions were worth at home when it
left and, once settled, what it gained or lost against that value. The society
report has a markets panel with each town's prices, coverage, price history and
trades.

### Motives and goals

Each person has six motives between 0.05 and 0.95: **security, wealth,
belonging, curiosity, influence and legacy**. The rules are in
[eternia/motivations.py](eternia/motivations.py) and
[eternia/goal_engine.py](eternia/goal_engine.py).

- **Temperament** is where motives settle when nothing in particular happens. It
  comes from the person's profession (a farmer cares more about security, a
  researcher about curiosity), their curiosity, ambition and openness traits,
  and a private personal draw that never uses the world's random generator, so
  earlier histories are unchanged. Heirs take after their predecessor by half.
- **Experiences** move motives by small amounts, at most 0.08 per motive per
  cycle. They come from authoritative outcomes only: hunger raises security,
  earned coins raise wealth (more for ambitious people), cooperation and trusted
  neighbors raise belonging, votes and enacted decisions raise influence,
  experiments and learning raise curiosity, building, teaching and the death of
  a neighbor raise legacy, and goods lost on the road raise security.
- Each cycle, motives drift 3% of the way back toward temperament, and
  temperament moves 0.5% toward the motives actually lived. A single event fades;
  experiences repeated over years leave a lasting mark.

Once per cycle, after outcomes are known, each person reviews their goal:

```text
score = appeal x feasibility
appeal       the goal's motive weights applied to current motives
feasibility  the person's own evidence: skills, memberships, savings, posted
             prices, inconclusive experiments, and doubt left by goals given up
```

| Goal | Weighted motives |
|---|---|
| Hold coins (`wealth`, or `profit` for merchants) | wealth 0.75, security 0.25 |
| Keep a food reserve | security 0.85, belonging 0.15 |
| Own houses | legacy 0.5, security 0.3, belonging 0.2 |
| Reach Aether knowledge | curiosity 0.85, legacy 0.15 |
| Carry out public decisions (`influence`) | influence 0.6, belonging 0.4 |

- A goal is held for at least **8 cycles** (two years).
- An **unfinished goal** is replaced only when another scores at least 0.12
  higher. After 3 years without progress, doubt cuts its feasibility, by up to
  70% over the next 6 years. Progress includes earning coins, building, a
  discovery or an enacted decision, not only a new record holding. A goal given
  up after a long stall keeps part of that doubt for five years, so people do
  not flip straight back to it.
- After **reaching a goal**, its main motive eases (less for ambitious people).
  The person then chooses a larger version of the goal, a different goal, or
  nothing new. They take on something new only if it scores at least
  0.25 + 0.25 × (1 − ambition), so a less ambitious person can stay content.
- Every event enters `goal_log` with the previous and new goals, the scores, a
  plain-language reason and the evidence behind it: the experiences since the
  previous goal began that pushed toward the new one, the motives behind it,
  and any stall or failed experiments.

A person's goal steers their actions. Gathering toward a food reserve,
experimenting toward knowledge, and studying carpentry or building toward houses
score 70–100, more when the person cares more about that goal; an influence goal
favors joining councils and enacting decisions; coin goals keep steering paid
work and sales. Survival comes first: hunger and fatigue are handled before any
goal. Run with `--fixed-goals` to keep every goal fixed as a control. The
society report's ambitions panel shows each person's current goal, motives and
temperament, and the town's goal history with reasons.

### Inequality and fairness

[eternia/inequality.py](eternia/inequality.py) measures the named people every
year, for the region and for each town:

| Measure | Meaning |
|---|---|
| Wealth | Coins, plus goods at the home market's buying price, plus structures at the cost of their materials |
| Wealth Gini | 0 when everyone holds the same; 0.94 when one of eighteen people holds everything |
| Income Gini | The same for coins received in the past year (wages, sales, consignment payments) |
| Poverty share | Wealth below half the group's median |
| Food insecure | Cannot cover three meals from food held plus coins at the home food price |
| Rank mobility | 1 minus the rank correlation of lineage wealth ten years apart (0 means everyone kept their place) |

These are an observer's numbers. Nobody in the world sees anyone else's wealth.
Instead, each person holds a **fairness** belief between 0.05 and 0.95 about how
the local economy treats them, starting at a neutral 0.5. Only their own
experiences move it, and it drifts 2% of the way back to neutral every cycle:

| Experience | Fairness | Also |
|---|---|---|
| Paid less than half of what the market pays sellers for the same goods | −0.04 | belonging down slightly |
| Paid at least three quarters of it | +0.01 | |
| Hungry, with food for sale but no means to buy it | −0.05 | security up |
| Poor (under 10 coins), no income and no paid work on offer | −0.015 | security up |
| Received food aid from an organization | +0.05 | belonging up; trust in those who voted for it |
| An organization they belong to delivered for its members | +0.015 | belonging up; trust in those who voted for it |
| Paid a levy | −0.01 | wealth up slightly |

Economic life also changes trust: a worker trusts a private employer more after
fair pay and less after poor pay, an employer trusts a worker who delivered,
and members who vote on opposite sides of a levy that passes trust each other
less.

**Responses use existing actions**, chosen from a person's own fairness,
motives and holdings:

- People who feel unfairly treated, cannot cover their meals, or are poor and
  doubtful join a cooperative, or found one, more readily the more they value
  belonging. Inside it they ask for food from its stores, propose that its coins
  pay members to gather food, or propose a small levy.
- People with coins to spare who care about belonging and legacy give to a
  cooperative. People who care about wealth and feel the town is fair leave an
  organization whose levy costs them a lot.
- A council with municipal authority can vote a levy on its members, which now
  goes into the **town treasury** and funds public work and a market that can
  buy. Members propose one when the treasury runs low and they are poor, feel
  unfairly treated or care strongly about public life, and propose ending it
  when it burdens them or the treasury has recovered. Each member votes by their
  own cost, solidarity and sense of fairness, so who sits on a council shapes
  what it decides.
- Feeling unfairly treated weakens the pull of home when a person weighs a paid
  job in another town.

Inequality never causes conflict by rule. A poor person who feels fairly
treated, or who cares little about belonging, simply carries on.

### Municipal work orders

Municipal **work orders** require a council representing a strict majority of
local named residents at tick start and now, plus the ordinary prior-cycle
majority and at least two consenting voters. An approved order moves its entire
wage budget from the town treasury into escrow. Any living, present resident
with the required skill can propose `work` against it. Work transfers finite
accessible food, wood or iron into municipal storage and transfers escrowed
coins into the worker's inventory in the same authoritative action.

Orders cover 1–24 whole units, wages of 0.1–5 coins per unit, and expire after
twelve cycles. Each work action extracts 1–8 units and costs two energy per unit.
Expired orders or collapsed sponsors refund unused escrow. Already funded wages
are contractual commitments; loss of council majority alone does not confiscate
them. No wages are minted, and competing workers cannot spend the same escrow.

Personal gathering records owned-inventory production. Voluntary preparation
names a live institution and project; contributions, teaching and construction
aid carry explicit purposes. The work history distinguishes paid extraction,
goods sales, personal production, and unpaid collective activity. A recorded
paid alternative is a public planning-time quote, not guaranteed counterfactual
income: another worker might claim it first. The society report exposes orders,
escrow, compensation and purposes alongside the existing votes and journeys.

### Paid work across the region

Three kinds of employer can fund a job. Each escrows the full wage budget before
anyone works, so no wage is ever promised without money behind it:

| Employer | How a job is created | Paid from | Output goes to |
|---|---|---|---|
| Council | `work_order` proposal, majority council, prior-cycle vote | Town treasury | Town storage |
| Guild or cooperative | `commission` proposal, prior-cycle majority, two consenting members | The organization's own coins | The organization's holdings |
| Individual | `hire` action (one open private job per person) | The person's own available coins | The employer's inventory |

Councils cannot commission; they spend town money only through the charter.
Unused escrow returns to whoever funded it when a job expires after twelve cycles.
A collapsed organization's escrow follows its other reserves back to its town. A
private job stops accepting work as soon as its employer leaves or travels,
because output is never teleported to an absent employer, and closes at the next
cycle. Its escrow returns to the employer, or to the successor's estate if the
employer has died. Nobody can be paid from their own job.

Open jobs are **public notices in neighboring towns** from the cycle after they
are funded. A notice shows its terms and how many units remain, not the
employer's other accounts or buried reserves. To decide whether a job elsewhere
is worth moving for, the policy estimates from public facts only:

- how many units will probably still be available on arrival, projecting the
  claims observed so far as local competition (a brand-new notice gives no
  evidence yet, so nobody moves for it);
- the route's turn-back risk and the worker's energy over the job's remaining life;
- minus provisions eaten on the road, a cost of leaving home that grows with
  institutional memberships and falls with openness, and the value of comparable
  work at home.

A person moves only when this beats staying by at least three coins, and gathers
or buys journey food first if needed. The estimate is a programmed heuristic, not
foresight: it does not anticipate other migrants, so two miners can travel for
the same job and split it. Builders and researchers who cannot gather or buy a
material their goal needs may hire someone for it at 60% of the local price.
Organization members may propose a commission for road-repair material.

### Labor experiment

Will someone travel for paid work?

```powershell
python main.py --labor-experiment --seed 42
start .\output\labor-experiment\report.html
```

Highfen has iron, but its resident miner lacks mining knowledge (as when a
successor does not inherit the skill). Every town starts with a council of its
residents. Four matched cases vary only the starting job and the roads: a
16-unit iron job at 2 coins per unit, the same job at 0.5 coins per unit,
comparable funded iron work at the miners' own homes, or the roads into Highfen
blocked. No later action is injected. Across seeds 18, 42 and 73 and all three
policy styles (36 runs of three years):

| Case | Miners who moved for the job | Highfen job |
|---|---|---|
| Paid opportunity | Both miners in 9 of 9 | Completed by migrants in 9 of 9 |
| Low wage | None in 9 of 9; nobody proposed moving | Expired unworked in 9 of 9 |
| Comparable work at home | None in 9 of 9 | Expired unworked in 9 of 9 |
| Roads blocked | None in 9 of 9 | Expired unworked in 9 of 9 |

Wages earned in Highfen after arriving totalled 32 coins in every run, the full
16-unit job. Nobody else moved in any control run. (With the Stage 1 economy,
both miners moved in 7 runs and one in 2.) The starting job is an initial
condition, so this tests the decision to travel and its consequences, not job
creation; see the `labor_shortage` evaluation scenario below for the unscripted
version.

Each case also gets its own folder with a full `history.json` and `report.html`;
`summary.json` holds the comparison.

### Market experiment

Does food follow the price?

```powershell
python main.py --market-experiment --seed 42
start .\output\market-experiment\report.html
```

Three matched cases hold the same total food and vary only where the stored
food starts and whether Highfen's roads are open: Highfen's stores moved to
Rivermark (a price gap), the stores shared so every town starts with equal food
coverage, or the price gap with both roads into Highfen impassable. No purchase,
contract or shipment is injected. Across seeds 18, 42 and 73 and all three
policy styles (27 runs of two years):

| Case | Food price at start (Highfen / Rivermark) | Food shipped to Highfen | Highfen population after 2 years |
|---|---|---|---|
| Price gap | 1.99 / 0.83 | 9 of 9 runs: Rivermark's merchant consigned 8 food at tick 1 | 107–116 of 150 |
| Matched supply | 1.13 / 1.13 | None in 9 of 9 | 146–152 |
| Roads blocked | 1.99 / 0.83 | None in 9 of 9 | 107–117 |

No shipment of any good left expecting a loss, and none settled at a loss. All
consignments were delivered and earned their merchant 4.9 coins over the value
of the goods and provisions at home. No council contract carried food within
two years. When Stage 2 was added, councils agreed food contracts in 6 of the 9
price-gap runs, but the roads into Highfen left room only for loads too small to
pay for their provisions (in seed 42 a landslide at tick 8 cut the upland road
to 29% condition). Since Stage 3, council members spend more turns on their own
goals and no food contract forms within two years. Wood and iron prices also
differ between towns, so trade in those goods can occur in any case.

This tests whether trade responds to a price gap and to transport, not whether
markets prevent famine: one consignment is small next to a town that eats about
150 food a year.

### The Changing Miner

Does experience change what a person wants?

```powershell
python main.py --goal-experiment --years 20 --seed 42
start .\output\goal-experiment\report.html
```

Edrin of Rivermark, a miner, starts every case wanting 60 coins. Four matched
cases change only his starting circumstances, with the same total resources:

| Case | Starting circumstance |
|---|---|
| Successful miner | 54 coins, six short of his goal (moved from the town treasury) |
| Struggling miner | No accessible ore at home (moved into town storage) and 2 coins |
| Connected miner | Strong mutual trust with his five neighbors, in one council of all six |
| Curious miner | The highest possible curiosity, with wood and iron in hand for experiments |

Each case runs twice, with adaptive goals and with every goal fixed, so the
difference isolates goal revision. All eighteen people live under the same
rules and policy; nothing about Edrin's later goals is injected. Across seeds
18, 42 and 73 (24 runs of 20 years), Edrin's adaptive goals went:

| Case | Seed 18 | Seed 42 | Seed 73 |
|---|---|---|---|
| Successful | 60 → 130 coins → food reserve → 140 → 280 coins | 60 → 130 → 260 coins | Reached 60 coins, then nothing new |
| Struggling | Reached 60 coins after 8 years → 120 coins → food reserve | Gave up on 60 coins after 9 years → food reserve → 70 coins | Gave up on 60 coins after 11 years → food reserve → 70 coins |
| Connected | 60 → 120 coins | 60 → 120 coins | Reached 60 coins, then nothing new |
| Curious | 60 → 120 → 240 coins | 60 → 120 coins → Aether knowledge → food reserve | Reached 60 coins, then nothing new |

Every change has a recorded reason, for example "Stopped trying to hold 130
coins after 21 cycles without progress; to keep a reserve of 12 food now scores
0.48 against 0.35 for the current goal", with evidence such as "belonged to an
organization (26 cycles; belonging +0.05)" and "was helped through hardship (1
cycle; belonging +0.03)". With fixed goals, Edrin reached his 60 coins once in
every run and chased nothing else.

For all eighteen lineages, the report also compares goals reached, changed and
abandoned, current goals met, hunger, wasted actions, civic participation, coins
and food between adaptive and fixed goals (summarized under
[Stage 3](#stage-3-adaptive-goals-individuals-with-changing-ambitions-implemented)).
The run takes a few minutes: eight 20-year worlds.

### Inequality experiment

Does inequality change a society?

```powershell
python main.py --inequality-experiment --years 30 --seed 42
start .\output\inequality-experiment\report.html
```

Three matched starts keep the same coins in every town and differ only in who
holds them. Each town's six named residents either share their coins equally,
or its merchant holds 75% of them; in the third case the merchant also holds 80%
of the town treasury, leaving less public money for paid work. Everyone keeps the
same goals, motives and policy, and nothing later is injected. Averages over the
last ten of 30 years, for seeds 18, 42 and 73 (9 runs):

| Measure | Equal start | Unequal start | Unequal, merchants hold public funds |
|---|---|---|---|
| Wealth Gini at the start | 0.08 | 0.47 | 0.57 |
| Wealth Gini, last decade | 0.44 / 0.51 / 0.49 | 0.47 / 0.51 / 0.50 | 0.48 / 0.53 / 0.54 |
| Fairness | 0.46 / 0.40 / 0.50 | 0.33 / 0.37 / 0.30 | 0.28 / 0.23 / 0.26 |
| Share in a cooperative | 22% / 14% / 21% | 62% / 48% / 64% | 52% / 54% / 53% |
| Poverty share | 20% / 22% / 26% | 27% / 27% / 32% | 26% / 29% / 14% |
| Food insecure | 4% / 6% / 4% | 6% / 9% / 4% | 26% / 18% / 9% |
| Poorest third, mean wealth | 17 / 13 / 14 | 12 / 12 / 9 | 7 / 7 / 11 |
| Levies paid over 30 years | 368 / 517 / 294 | 216 / 292 / 485 | 875 / 979 / 680 |
| Migrations | 1 / 4 / 2 | 6 / 6 / 4 | 4 / 2 / 2 |

The differences that held in every seed: an unequal start left people feeling
less fairly treated and made cooperative membership far more common (48–64%
against 14–22%); the poorest third ended poorer in five of the six unequal runs
and no richer in the sixth. When merchants also held the public funds, members
paid 1.9 to 2.4 times as much in levies as with an equal start, fairness fell
further in every seed, and food insecurity was two to seven times as common
(9–26% against 4–6%); an unequal start alone made little difference to it.
Inequality did not simply persist or explode. An equal start drifted to a Gini
of 0.44–0.51 on its own; unequal starts stayed unequal, though where merchants
held the public funds the heavy levies brought the Gini down from 0.57 in every
seed, most in seed 18 (to 0.48). Towns diverged without any script: with an
equal start in seed 18, Highfen ended at a Gini of 0.31 and Rivermark at 0.52.
Trust and migration showed no consistent difference: an unequal start alone
brought somewhat lower trust and more moves in every seed, but not when
merchants also held the public funds. Rank mobility stayed low everywhere (about
0.11–0.23 per decade). The three runs take about two minutes per seed. (Figures
as of v0.9 Stage 4; see
[what it changed](#stage-4-measurement-follow-through-willingness-to-pay-and-speed-implemented).)

### Municipal authority

The v0.7 charter explicitly applies to the **represented local electorate**,
not the entire aggregate population. A guild's commercial agreement does not
grant access to municipal funds. Both caravan sponsors need current majority
council authority; municipal specialization, communal labor and border decisions
also require that authority. Voluntary organizations still control their own
contributed holdings and approved member levies.

Public-road maintenance grants no private ownership. Restricting a public
connection requires matching prior-cycle approvals from majority councils at
both endpoints. The standing retail charter permits any local resident to buy
or sell up to eight units per action at the town's posted prices,
subject to available stocks, coins, knowledge and permissions. This is a small,
explicit constitution, not a complete representation or property-rights model.

### Save and resume

Society runs write `output/society/world.save.json` automatically:

```powershell
python main.py --resume output/society/world.save.json --years 10
start .\output\society-resumed\report.html
```

`--years` adds biological years to the saved clock. A resume without `--years`
adds zero years and exports the restored state. The default resumed output is
separate from the original run. Use `--save path/to/state.json` and `--output`
for explicit locations. Integrated earlier modes can also request `--save`.
The isolated NPC demo and multi-world migration comparison are excluded: they
do not expose the same resumable single-world step loop.

Checkpoints preserve RNG state, integer keys and sets, memories, policies,
electorates and votes, offers, frozen spending budgets, work escrow, route
capacity, caravans, consignments and migrants, private reserves, posted prices
and their history, trade records, motives, temperaments, fairness beliefs and
goal histories, yearly inequality records, ledgers and recorded history.
The loader creates no new world decisions. A saved continuation must match an
uninterrupted continuation, including when saving after a completed resolution
batch partway through a tick.

The format is versioned JSON with a checksum, atomic file replacement, an exact
source fingerprint, base Git revision, working-tree status, seed, policy and
clock settings. It uses no pickle or arbitrary class loading. Checkpoints contain
**private world truth** and must not be used as NPC observations. Saving is allowed
only outside active planning/resolution transactions. Only registered built-in
worlds and policies are supported; custom policies fail explicitly rather than
silently losing state. The same simulation source and Python major/minor version
are required. Cross-version save migration is not implemented, and the checksum
detects accidental corruption rather than authenticating a file's author.

Unexpected exceptions during a v0.7 tick or direct resolution batch restore active
state, RNG, accounting and append-only histories. Expected action rejections
remain audited world outcomes. This is in-process recovery, not a distributed
transaction system or continuous crash journal; the last completed checkpoint
is the durable recovery point.

### Compare seeds and scenarios

```powershell
python main.py --evaluate-society --years 5 --evaluation-seeds 18,42,73
start .\output\society-evaluation\report.html
```

The default matrix has 45 runs: three seeds, five initial scenarios (baseline,
accessible-iron scarcity in every town, initially blocked roads,
`labor_shortage` and `food_shortage`), and three policy priorities (`balanced`,
`personal`, `collective`). The scarcity setup moves existing accessible material
into municipal storage; `labor_shortage` only removes mining knowledge from
Highfen's residents; `food_shortage` moves Highfen's stored food to Rivermark.
None creates resources, posts a job, places an order or schedules a journey.
Prices are re-posted from the scenario's conditions before the first cycle.
Annual replenishment or autonomous road repair can later change the control
conditions; future actions are never injected.

`evaluation.json` and its filterable report record final goal completion and
progress, paid work, private hires, organization commissions, moves followed by
paid work in the destination, wages earned after moving, voluntary actions,
choices with paid alternatives, hunger, road repairs, shipments, migrations,
market purchases and sales, consignments, contract caravans, shipments that left
expecting a loss or settled at a loss, food delivered to Highfen, final food
prices, goals reached during the run, goal changes, goals abandoned, goals
declined after success, goals left unfinished at death, current goal kinds,
wealth and income Gini coefficients, poverty and food insecurity shares, mean
fairness, cooperative membership, levies paid, ledger residuals and source
provenance. Goals reached during the run are counted
separately from whether the current goal is met, so a miner who reaches 60 coins
and then aims for 120 keeps the first success.
Means and observed ranges summarize the chosen seeds; they are not confidence
intervals. Use `--policy-style personal` to restrict an evaluation or set a
society run's priorities.

Goal success is measured, not awarded. Final living agents' coin targets are
holdings targets, including the earlier `profit` label, not net accounting
profit. Completing paid work does not imply reaching a lifetime goal. These
small comparisons can reveal poverty, coordination costs and personal/collective
tradeoffs; they do not establish realistic economics or general emergence.

v0.7 does not add an LLM, families, warfare, a server, multiplayer, or
scientifically rich Aether experiments.

## Earlier modes

The modes below keep their original mechanics and output folders. Their rules
still apply in the v0.7 society unless the section above says otherwise.

### Physical world (v0.6.1)

```powershell
python main.py --physical-world --years 100 --seed 42
start .\output\physical-world\report.html
```

The physical experiment extends the three-settlement region with rivers,
overland roads, and a mountain pass. Every connection has a distance, transport
capacity, speed, condition, and delivery risk. Paths are chosen from passable
connections. Terrain and road condition affect the time and supplies needed;
an alternate route can be substantially less attractive than a direct crossing.
At the default four cycles per year, each movement cycle represents a season.
Increasing `--ticks-per-year` changes that time scale; this is an abstract
transport model rather than travel measured in real-world days.
The bounded planner chooses the fastest open path with enough remaining capacity
on every leg. If a direct crossing is occupied, it considers slower alternatives.
Caravan load includes the provisions needed for the entire alternative journey;
longer detours can therefore be infeasible even when the cargo alone would fit.
This search enumerates simple paths in the small regional graph. Larger maps
will need a more scalable search.

Quoted accident risk uses the same condition-adjusted hazard as movement and
compounds it for every expected travel cycle on each leg:
`1 - product((1 - per_tick_hazard) ** leg_ticks)`.
It assumes observed route conditions stay constant. It does not predict future
weather, blockages, border changes, or supply exhaustion. A journey records this
estimate at departure so the historical report can show what was anticipated.

A voted commercial agreement grants permission to trade. A member of its
exporting sponsor must still organize a `dispatch_caravan` action. Dispatch
reserves finite cargo, buyer funds in escrow, transport capacity, and food for
the journey. Departure removes those resources from their source accounts and
keeps them in the journey accounts until delivery, consumption, or loss.
Escrow represents a settlement payment commitment; physical coin carriage is
not modeled. Unused caravan provisions are delivered to the importing town.
Capacity includes cargo and provisions, and remains reserved on untraversed
legs until a journey passes them. It is not available again merely because a
new cycle begins.
Merely signing an agreement does not move goods. Supplies consumed and cargo
lost in accidents are explicit accounting sinks. Caravans can arrive too late
to solve a shortage, stall behind a damaged road, or fail altogether.

Migration also takes a journey. Travelers cannot work or participate in local
institutions while absent. Population accounting includes people in transit;
the destination gains a resident only on arrival. Destination border rules are
checked when departure is planned and when the traveler reaches the destination.
Rejected or stranded migrants can turn back through a physical return journey.
Returning people use slower emergency passage that ignores administrative
closures, so that a road restriction cannot trap a traveler permanently.
Retirement and succession are deferred until arrival or return. Buildings stay
in their original settlement.

Institutions can approve **repair_route** projects using shared wood, iron,
and coins. Unowned connections can acquire an institutional maintainer, and
that organization can vote on **route_access** restrictions. Road projects
use the same prior-cycle voting and frozen-resource authority rules as other
collective decisions. Ordinary wear and seeded environmental hazards alter
connections over time, so isolation can result from geography as well as
failed diplomacy. Aggregate mines draw from finite unextracted reserves;
exhaustion reduces future mining opportunities rather than creating endless
annual ore. Buried iron is included in the initial resource total, and extraction
transfers existing stock into the economy. A configured `--shock-year` remains a
separate controlled scenario; the physical mode defaults to no scheduled shock.

Exact buried reserves stay inside the authoritative simulation. NPC observations
include `physical.geology`: the latest remembered personal or inherited iron
gathering outcome at each settlement, with its tick, source, and amount collected.
Both a successful attempt and an unavailable accessible stock leave the total
reserve unknown (`reserve_estimate: null`). A failed gathering attempt does not
establish that the underground seam is exhausted. Evidence keeps its original
location after migration and can disappear as bounded memories are forgotten.
Survey estimates and dedicated geological teaching are not modeled yet.

The offline explorer adds a physical map, route conditions and ownership,
caravans and migrants in progress, journey outcomes, consumed supplies, and
remaining mineral reserves for the historical observer, not the NPCs.
The regional panels still show institutions,
trade negotiations, local production, migration, and individual decisions.
The full record is `output/physical-world/history.json`.

Compare another seed without replacing the first experiment:

```powershell
python main.py --physical-world --years 100 --seed 18 --output output/physical-world-seed18
```

#### Controlled migration experiment

```powershell
python main.py --migration-experiment --years 3 --seed 42
start .\output\migration-experiment\report.html
```

Three matched cases retain the ordinary eighteen agents and `LogisticsPolicy`:
a miner with exhausted accessible local work and a foreign opportunity, the same
miner with local work available, and the foreign opportunity with initially
impassable connections. Personal starting goods are transferred to/from municipal
stocks, preserving the resource total. Only initial conditions change: no
migration proposals are injected and no replacement policy chooses the outcome.
Normal competition, needs, infrastructure repair, and environmental events continue.

The comparison records the first decision and rationale, migration proposals,
departures, physical arrivals and returns, mining after arrival, and personal
goal progress. `summary.json` contains conditions and focal decision evidence;
each case has its own `history.json` and interactive `report.html`. The default
is three years at four cycles per year without a scheduled shock. Longer runs
can change the control conditions, for example when an institution repairs a road.
These scenarios test whether the existing planner responds to a concrete work
opportunity; they do not establish that migration is frequent in default runs.

This milestone concentrates on physical consequences. Final trade terms still
require matching independent mandates; genuine counteroffers remain future
work. Council authority still uses named local participants rather than a
constituency model for the entire aggregate population. Families, childhood,
armies, exploration, players, ruins, and experimental Aether discovery also
remain outside this version.

### Civilizations (v0.5)

```powershell
python main.py --civilizations --years 100 --seed 42
start .\output\civilizations\report.html
```

The regional experiment starts with three settlements and six individually
represented people in each. Rivermark has fertile land, Highfen has mineral
resources, and Deepwood has forests. Their aggregate populations and annual
economies continue alongside the 18 represented households. There are no
preassigned institutions, alliances, or trade routes.

Individuals retain personal goals, needs, limited observations, and memories.
Their profession, political preferences, observed opportunities, and experience
can lead them to form or join a **cooperative**, **guild**, or **council**. Different
organizations can compete in the same settlement. Guild participation requires
trading knowledge; cooperative participation requires foraging knowledge.
Council authority over incoming migration requires a majority of the current
local represented population, in addition to the normal voting rules.

The v0.5 action engine extends institutional mandates with:

- **Trade terms:** an institution proposes a destination, resource, import or
  export direction, unit price, and annual quota. A counterpart must independently
  approve matching terms in the opposite direction. Different prices or quotas
  do not silently become an agreement. Unmatched proposals may expire or fail.
- **Specialization:** an approved food, wood, or iron focus changes production.
  Competing local mandates are resolved by their current membership support,
  rather than adding every bonus together.
- **Embargoes:** an institution can suspend its own sponsored routes. An embargo
  does not automatically dictate every other organization's choices.
- **Migration policy:** a sufficiently representative council can open or close
  incoming migration. Personal migration still transfers one resident and their
  inventory while leaving buildings in their original settlement. Border closure
  controls entry; residents remain free to leave. A newly opened border becomes
  usable on the next tick, preserving the common planning snapshot.

Opening a route does not create resources or guarantee a shipment. Annual trade
uses finite settlement stocks and coins, available surplus, import need, and the
negotiated price and quota. A contract lasts twenty ticks (five years at the
default frequency), after which renewal needs new independent mandates. The
same sponsoring pair cannot duplicate an unexpired contract for the same
resource. Routes can be blocked, become unfunded, lose their sponsors, or expire.
Production and explicit consumption remain the sources and
sinks in the accounting ledger; trade transfers existing resources. Shared food
distribution and the earlier institutional projects remain available.

The offline report compares settlement population, recorded coin holdings,
production, imports, exports, migration, and institutional purposes. Its map
shows resource flows and routes; local views expose negotiation outcomes,
votes, diplomacy, border decisions, and personal histories. The settlement
selector limits the detailed view to one community at a time. Production,
imports, exports, and migration profiles are cumulative records; the flow map
also accumulates recorded shipments. Coin holdings are a stock, rather than
GDP. A person's influence score counts approved institutional enactments they
performed; political legitimacy and a broader constitutional model remain
outside this measure. Exported history is in `output/civilizations/history.json`.

Successful cooperation is not the pass condition. Inspect isolation, refused or
expired terms, resource competition, suspended routes, migration, and institutional
collapse alongside agreements and specialization. Initial resource differences
and explicit utility rules shape the available opportunities; this remains a
classical, bounded experiment rather than a model of realistic states or warfare.

The v0.5 default has **no scheduled mining shock**. Compare seeds and an optional
controlled disruption without replacing earlier results:

```powershell
python main.py --civilizations --years 100 --seed 18 --output output/civilizations-seed18
python main.py --civilizations --years 100 --seed 42 --shock-year 8 --output output/civilizations-shock
```

Families, childhood, travel times, scientific mineral experimentation, and
simulated geological hazards are outside this mode. The report sees exported world
state; individual policies still cannot inspect foreign private accounts or
other people's private inventories and knowledge.

### Institutions (v0.4)

```powershell
python main.py --institutions --years 100 --seed 42
start .\output\institutions\report.html
```

The offline report shows organizations, their members and holdings, proposal
votes, enacted rules, and settlement policy alongside individual histories.
The underlying record is `output/institutions/history.json`.

Institutions begin through individual proposals rather than preassigned
organizations. People may join, contribute existing food, materials, or coins,
propose collective decisions, vote, and execute approved decisions. Their shared
holdings remain distinct from personal and settlement holdings. Formation costs
two coins; contributions and transfers conserve resources. A granary consumes
10 wood, 2 iron, and 6 coins.

Decisions require at least two affirmative voters and a strict majority of the
eligible electorate. Electorates are recorded when proposals are created;
newcomers cannot rewrite a pending decision's authority. Enactment requires
votes from earlier ticks, current authority, and resources already available at
the start of the tick. A new contribution cannot fund an earlier plan in the
same tick. Membership, voting, spending, and execution pass through the action
engine and enter the audit history. Unapproved, expired, or unfunded decisions
are rejected without partially spending resources.

The first collective decisions are:

- A **communal granary**, which increases settlement food storage.
- A **membership levy**, with a voted rate from 0 to 15 percent. It transfers
  available coins from members into their institution; it does not mint money
  or impose taxes on unrepresented residents.
- **Communal labor**, with a voted allocation from 0 to 30 percent, which shifts
  aggregate production effort toward food and away from wood and iron.
- A **trade agreement**, which needs independently approved reciprocal consent
  before settlements exchange food through the annual aggregate market.
- **Food distribution**, which moves an approved amount from shared reserves
  into the institution's settlement or a named eligible member's inventory.
  The release transfers existing food; it does not produce food or reduce
  hunger by itself. Settlement releases enter the annual consumption supply,
  while members still need to choose an `eat` action.

Food distributions use the normal proposal, vote, and `enact` cycle. A proposal
has kind `distribute_food` and either `{"destination": "settlement", "amount": 20}`
or `{"destination": "member", "member": 0, "amount": 2}` as its parameters.
For a member release, the recipient must remain a living local member from the
recorded electorate.
Execution requires the same prior-tick majority and shared-resource budget as
other mandates. New contributions cannot fund a release in the same tick, and
members cannot immediately spend food received during that tick. Policies can
pool personal surpluses, propose releases for an observed shortage, and vote
on bounded public aid requests without seeing anyone's private inventory.

Aggregate production, consumption, and population change remain mathematical
world processes. In institution mode, the legacy automatic agriculture/mining
upgrades are disabled. Storage, member levies, labor allocation, and access to
inter-settlement food exchange now depend on institutional decisions. This is
a small coupling between individual agency and the aggregate economy, not a
complete government or jurisdiction model.

Institutions can survive a member's death. A successor inherits the personal
estate but must join voluntarily and receives no automatic vote or authority.
An organization with no members collapses after four ticks, releasing its
remaining holdings to its settlement. There is no automatic transfer of those
holdings into a successor's personal inventory.

Members can oppose a costly proposal, vote to end a levy once shared reserves
are sufficient, or leave a burdensome or distrusted organization. Trade proposals
respond to public neighboring organizations and reciprocal requests; partners
and voting outcomes are not assigned in advance.

Agent observations expose public identity, roles, structures, advertised offers,
and evidence learned through interactions. They do not reveal a peer's full
inventory, skills, or mineral knowledge. The report is a historical observer's
view of exported world state and is deliberately more informative than an
individual policy's observation.

The Aether rule remains a conditional stochastic placeholder, and generations
remain immediate adult estate successors. Families, childhood, scientifically
meaningful mineral experiments, and rich constitutional politics are not
modeled.

The configured mining shock is a controlled scenario, rather than an emergent
geological event. Compare a seeded experiment with and without that scenario:

```powershell
python main.py --institutions --years 100 --seed 42
python main.py --institutions --years 100 --seed 42 --shock-year 0 --output output/institutions-baseline
```

The v0.4 mode retains its cooperative focus. Purpose-specific institutions and
regional political choices are available in the separate v0.5 experiment.

### Community (v0.3)

```powershell
python main.py --community --years 100 --seed 42
start .\output\community\report.html
```

The underlying record is `output/community/history.json`.

Five initial people make their own decisions:

- Edrin, a miner, wants to earn 60 coins.
- Mara, a merchant, wants to increase her trading wealth.
- Toren, a builder, wants to build three houses.
- Lyra, a researcher, wants to reproduce an unusual mineral effect.
- Aldric, a farmer, wants to secure a personal food reserve.

Everyone also has food and energy needs. Specializations and scarce personal
supplies create reasons to exchange resources. The same policy evaluates
currently visible opportunities for each person; it contains no named trading
pairs or scheduled cooperation sequence. Reaching every goal is not guaranteed.

The community mode adds:

- **Shared economy:** people post finite buy/sell offers, and other people
  independently decide whether to accept. Posting reserves goods or coins;
  settlement resources and personal resources are separate holdings.
- **Independent goals:** hunger, energy, missing materials, prices, and personal
  objectives compete for each person's next action.
- **Relationships:** trust and reputation affect whom people deal with and
  how they value social actions. Successful exchanges and cooperation can
  strengthen relationships; competing claims can create tensions.
- **Knowledge transfer:** people can teach other people; discoveries still
  require the world's experimental conditions rather than a scheduled date.
- **Persistent memories:** remembered outcomes affect later choices. Working
  memory is bounded, while the exported event and decision histories preserve
  the run's record.
- **Historical simulation:** the annual population economy continues while
  named people age and are replaced by successors. Property and imperfect
  knowledge transmission connect generations.

The five named lineages are tracked alongside the aggregate population of
1,000 initial inhabitants. Aggregate births/deaths are not a one-for-one model
of the five individuals. Named successors are estate inheritors: the simulation
does not currently model couples, pregnancy, or child development. They receive
their predecessor's remaining inventory and property, a small sample of memories,
and probabilistic skill/knowledge inheritance. Trust in the deceased individual
does not automatically become trust in the successor. Knowledge can therefore
persist through teaching or disappear with its last holder.

#### The community cycle

Each decision cycle freezes public observations for all living agents before
asking any policy to plan. Policies receive detached copies, including the
previously visible market. The world then resolves proposals, checks current
resources and locations again, updates needs and relationships, records outcomes,
and advances time. A person cannot plan using another person's same-cycle result.
Resolution starts from sorted actor IDs and uses a seeded shuffle to break
competing claims without permanently favoring the first person. All proposals
are checked against the planning state before execution and checked again
against remaining resources. Resources received during a cycle cannot fund a
second spending decision in that same cycle. Duplicate proposals from one actor
are both rejected. An offer cannot spend resources already reserved by another
offer, and only one buyer can take the last available units. Offers expire after
four ticks, releasing their reservations. Death or migration cancels stale offers.
Rejections are recorded with reasons.

The default is four decision cycles per simulated year. The annual aggregate
economy models production, food consumption, demographic change, and finite
transfers into accessible deposits. Production and consumption are recorded as
resource flows; transactions transfer existing goods and coins. The ledger
records net stock changes for each aggregate phase and explicit action sinks;
it is not a unit-by-unit ecological balance sheet. There is no claim that
resources are conserved across explicit production or consumption.

```powershell
# Compare against a run without the environmental disruption
python main.py --community --years 100 --seed 42 --shock-year 0 --output output\community-baseline

# Change the seed or the number of decisions in each biological year
python main.py --community --years 100 --seed 18 --ticks-per-year 8 --output output\community-seed18
```

`--shock-year` defaults to year 8; `0` disables the environmental disruption.
Changing the decision frequency changes the experiment: people have more or
fewer opportunities to act within each year.

The report provides a year slider, living-person cards and goals, an open-offer
book, a trust network, individual memories and decisions, historical event
filters, population/wealth/knowledge histories, and resource accounting. Inspect
trades, failed claims, knowledge transfer, migrations, and generations rather
than treating a single successful run as proof of emergence.

**Scope:** v0.3 is a classical multi-agent experiment. Goals, action rules,
utility scores, learning, and inheritance are programmed. Their combinations
can produce contingent social histories; this is not evidence of open-ended
reasoning, realistic economics, or general intelligence. Successors are a small
lineage abstraction rather than a full household, fertility, or genetics model.

### Edrin autonomy experiment (v0.2)

```powershell
python main.py --npc-demo --turns 40 --shock-turn 8
start .\output\autonomy\report.html
```

Edrin is a miner with personal food, materials, coins, hunger, energy, a bounded
memory, and two goals: own a house and hold at least 60 coins. On each turn an
offline utility planner reads his public observations and proposes one action.
There is no action queue or predetermined decision sequence. The planner scores
feasible choices against his current needs and missing goal prerequisites.

A rockfall closes his current iron deposit on turn 8. The same planner sees the
changed environment and can gather something else, buy materials, or migrate.
Use `--shock-turn 0` for a baseline, or change the closure turn. If `--turns` is
shorter than eight and no closure turn is supplied, the closure is disabled.
With the default
40-turn experiment he builds a house, migrates after the rockfall, and ends with
68 coins. The house remains where it was built; ownership survives migration.

The report includes a turn slider, personal inventory and needs, a decision
journal with reasons and accepted/rejected results, public perceptions, and a map.

**This is classical goal-based AI, not an LLM or general intelligence.** It is a
small, inspectable autonomy milestone. A turn is one personal decision; the
aggregate annual economy and biological aging are paused in this experiment.
Hunger and fatigue affect decisions; starvation, illness, rent and housing
benefits are not modeled yet.

### Original thousand-year simulator

```powershell
python main.py --years 1000 --seed 42
start .\output\report.html
```

With no mode flag, Eternia starts in Year Zero with seven settlements, 1,000
inhabitants, 50 individually represented NPCs, a simple aggregate population
and economy, a hidden Aether parameter, individual observation and
experimentation, and recorded history. It fast-forwards the requested number of
years in under a second and writes `output/report.html` and
`output/history.json`. Try a different world with another seed:

```powershell
python main.py --years 500 --seed 18
```

## World action engine

Policies propose data; `ActionEngine` validates and applies the world rules.
For example, in a world containing an agent named Edrin:

```python
proposal = {
    'actor': 'Edrin',
    'type': 'build',
    'structure': 'house',
    'location': 'Rivermark',
}
result = world.submit_action(proposal)
print(result.to_dict())
```

The actor must be present, have permission, know carpentry, own 12 wood, 2 iron
and 8 coins, and have 15 energy. Without these, the world rejects the action with
a reason. It does not partially spend resources or advance randomness. The
attempt is audited and the actor remembers its result. `world.action_engine.validate`
performs a pure dry run; execution always checks the current state again.

Actors and locations accept stable integer IDs or exact, unique names. Parameters
can be flat, as above, or grouped in `params`. Unknown parameters, nonfinite
quantities, remote actions, and invalid amounts are rejected. Each actor may
complete one accepted action per tick; rejection leaves that budget available.

Supported actions:

- `gather`: `resource`, `amount` (1–8 whole units of food, wood or iron).
  Moves material from finite accessible deposits into personal inventory;
  requires the corresponding gathering skill and 2 energy per unit.
- `build`: `structure` (`house` or `workshop`). Checks carpentry and its material,
  coin and energy costs; records personal ownership and a physical town building.
- `trade`: `resource`, `amount`, `direction` (`buy` or `sell`). Transfers personal
  goods and coins against the local market's stocks and treasury. Earlier modes
  use fixed prices (food 1, wood 2, iron 4); the v0.7 society uses each town's
  posted prices and buys at 80% of them. Goods and money are conserved by each trade.
- `research`: `topic` (`carpentry` or `aether`). Spends 1 wood, 1 iron and 10 energy.
  Practical carpentry study teaches a skill. Aether experiments use hidden world
  conditions; an accepted experiment can return an inconclusive result.
- `migrate`: `destination`. Requires an open destination within 38 map units,
  transfers one resident and their home, and leaves their property in place.
- `found_settlement`: `name`, `x`, `y`, optional `settlers` (default 65).
  Requires a councillor, a site within 24 units and at least 8 from other towns,
  and sufficient parent population and supplies. Transfers 70 food, 40 wood,
  5 iron and 35 treasury; spends another 25 treasury on founding. Includes the
  actor among the settlers. Supports at most 25 settlements.
- `negotiate`: `destination`, `treaty` (`trade`). A councillor can sign a reciprocal
  relationship with a willing settlement within 38 units. Treaty pricing effects
  are not modeled yet.
- `eat`, `rest`, `wait`: satisfy hunger, recover energy, or spend an idle turn.

Later versions add their own actions on top of these, such as offers, votes,
`dispatch_caravan`, `work`, `hire` and `consign`; see the mode sections above.

Personal deposits are a simple finite abstraction, separate from the existing
aggregate annual farming/forestry/mining model. Construction and research consume
materials; food consumption, construction fees and founding costs are explicit
sinks. Full ecological and monetary accounting are not modeled.

## Replace the proposal policy

`ProposalPolicy` in `eternia/autonomy.py` requires only
`propose(observation: dict) -> dict`. Implement it with another planner or a
language-model adapter, then pass it to `run_demo(policy=your_policy)`.

The observation is a detached copy of the agent, public local conditions, nearby
settlements, known prices/recipes, and recent relevant events. It excludes the
hidden Aether field. Changing this copy cannot change the world. The adapter gets
no world reference; its returned proposal passes through the same engine as the
offline planner. No provider credentials, network calls, or paid API are needed
for the included experiment. This is an application boundary, not a sandbox for
running arbitrary third-party Python code.

## Scope

### What's implemented

- Seven geographically different founding settlements; 1,000 residents.
- Annual production, consumption, demographic change and food trade.
- Rule-driven settlement investment decisions.
- Fifty finite-lived named NPCs with distinct curiosity and occupations.
- An unknown Aether parameter known only to the simulation.
- NPC observations and material experiments subject to a tiny Aether rule.
- Knowledge sharing and occasional new settlements.
- A seeded random number generator, saved events, 10-year snapshots.
- Offline map, population graph, interactive timeline.
- Validated personal action proposals, finite deposits, inventories, skills,
  construction, markets, migration, founding and basic treaties.
- One goal-driven NPC experiment with needs, bounded memory and disruption replay.
- Audited accepted/rejected actions and a proposal-policy interface.
- A separate five-person v0.3 community with finite peer offers, reservations,
  competing goals, trust, reputation, social learning, and generational history.
- A v0.4 institutional layer with voluntary membership, shared holdings,
  majority decisions, authority checks, and effects on the aggregate economy.
- Three interconnected v0.5 economies and v0.6 physical journeys, infrastructure,
  finite mines, private geological evidence and capacity-aware transport.
- v0.7 council-funded work escrow, explicit economic purposes, a municipal charter,
  exact-version checkpoints, recovery checks and multi-seed behavioral comparisons.
- v0.7 Living Economy stage 1: private hiring and organization commissions on the
  same escrow model, jobs visible across neighboring towns, expected-value travel
  for paid work, and a matched labor-market experiment.
- v0.7 Living Economy stage 2: posted local prices formed from supply and demand,
  a price history, purchasing and selling decisions, merchant consignments and
  price-based council contracts carried by physical caravans, wages and job
  choices that follow local prices, and a matched market experiment.
- v0.7 Living Economy stage 3: six motives shaped by temperament and experience,
  goal reviews that keep, raise, replace or rest a goal with recorded reasons and
  evidence, goal-driven actions, lifetime goal metrics, a fixed-goal control and
  the Changing Miner experiment.
- v0.7 Living Economy stage 4: yearly inequality measures for the named people,
  a fairness belief built from personal experience, trust effects of economic
  life, responses through cooperatives, aid, levies, giving and migration,
  municipal levies that fund the town treasury, and a matched inequality
  experiment.
- v0.8 The First Player, stage 1: a human-controlled newcomer whose chosen
  proposals resolve in the same cycle and under the same rules as everyone
  else's, a terminal game, inheritance of control by an heir, checkpoints
  between turns and an input history that replays a session exactly.
- v0.8 The First Player, stage 3: conversations grounded in each person's own
  observation and knowledge, opinions and stances from personality, goals,
  trust and voting criteria, and news that spreads person to person with source,
  age and confidence, shaping trust and merchants' route choices.
- v0.8 The First Player, stage 2: guided menus with editable fields for every
  action, political participation, trust reactions to contested goods and
  gifts that apply to everyone, embargoes that stop private shipments, and a
  personal journal.
- v0.8 The First Player, stage 4: a local browser interface with a map, the
  character, people and conversations, economy, politics, a timeline, the
  journal, a report of each turn's consequences, and saving, resuming and
  replay, with Python as the only authority.
- v0.9 Emergent Opportunities, stage 1: needs read from a person's own view of
  their goal's next step, paid jobs for the needs they cannot meet themselves,
  with a stated purpose the engine checks, and a read-only view of
  opportunities in the browser.
- v0.9 Emergent Opportunities, stage 2: needs as knowledge that travels by word
  of mouth after news of events and goes out of date, told when people are
  asked about work, shown to the player as needs they have heard of, and
  answerable by selling the goods at a fair price as well as by working the job.

### What's not implemented

- A connected language model or open-ended reasoning; conversations are
  structured questions with rule-based answers.
- Full households and reproduction, complex ecology, or population-wide migration.
- An economy calibrated to real markets; community offers use a small utility model.
- Inequality across the aggregate population: measures cover the named people
  only, and the aggregate population has no individual holdings.
- Strikes, wage bargaining or open conflict: discontent works through
  cooperatives, levies, aid, giving and migration; nobody negotiates a wage.
- New kinds of ambition: goals are limited to what the world already measures
  (coins, a food reserve, houses, Aether knowledge, public decisions carried
  out). A business, a guild of one's own, teaching or helping an heir need their
  own mechanics first. Motives and goal scores are explicit rules, not a model
  of human psychology.
- Bargaining: wages and contract prices follow posted prices by fixed rules;
  nobody negotiates or makes a counteroffer.
- Broad municipal revenue: a town treasury gains coins only from a council
  levy on its members, from named people buying at its market, from contract
  exports, or when escrow returns. The aggregate population eats from town
  stores without paying, so a town without a levy still drains its treasury over
  long runs, and a market with an empty treasury stops buying.
- Travelling merchants: merchants consign goods without travelling; a payment
  reaches them on delivery wherever they are, since coin carriage is not modeled.
- Workplace danger: only travel is hazardous, so nobody refuses risky work.
- A continuously simulated field / scientifically rich magic physics.
- Rich government agents, faction politics or wars.
- More than one player, or a hosted game: the browser interface serves one
  player on their own computer (multiplayer is postponed). People never lie
  or exchange news in words with each other; they pass on claims.
- Cross-version checkpoint migration, continuous crash journals or multiplayer persistence.
- 3D map, game client, matchmaking, security or MMO infrastructure.
- Realistic centuries-long historical dynamics; parameter values are illustrative.

**Important:** Discoveries are conditional stochastic events based on an explicit
simplified rule; there is no hidden date that forces magic discovery. This is a
placeholder for a much richer experiment/physics system, not actual open-ended
scientific discovery.

### After the Living Economy

**v0.8, The First Player**, paused the headless simulator to build a minimal
playable prototype, in which a player enters a settlement, interacts with
autonomous people, takes part in the economy and sees the consequences. All
four stages and a reliability pass (v0.8.1) are implemented. The current
milestone is [v0.9, Emergent Opportunities and Player Purpose](#roadmap-emergent-opportunities-and-player-purpose-v09):
whether the world gives a player reasons to act. Stages 1 and 2 are implemented.

Other candidates, in rough order:

1. Measure where wages, relationships, specialization and knowledge change opportunities.
2. Extend municipal representation, economic jurisdiction and genuine counteroffers.
3. Add new kinds of ambition once their mechanics exist, such as running a business or teaching.
4. Explore culture, shared memories and historical identity after the evaluation baseline.
5. Replace the toy Aether rule with testable multi-factor experiments.
6. Make long runs cheaper and add checkpoint-version migrations: one cycle grows
   from about 50 ms at the founding to 1.1 s after 100 years, mostly in copying
   observations that carry every organization's whole decision history and in
   the per-cycle rollback snapshot ([measurements](#v081-playability-and-reliability-implemented)).
7. Consider an optional LLM policy only after establishing useful community baselines.

## Tests

```powershell
python -m unittest discover -s tests -v
```

The suite has 555 tests and takes a few minutes. It needs no network access and
no third-party packages. GitHub Actions runs the same command on Windows and
Linux with Python 3.10 and 3.12 for every push and pull request.

Eight of them click through the browser interface in a real browser and are
skipped unless Playwright is installed:

```powershell
python -m pip install -r requirements-browser.txt
python -m playwright install chromium
python -m unittest tests.test_browser -v
```

To use an installed Edge or Chrome instead of downloading Chromium, set
`ETERNIA_BROWSER=msedge` or `chrome`; `ETERNIA_SCREENSHOTS=folder` keeps a
screenshot of every tab in both themes. CI runs them in a separate job on Linux
and keeps those screenshots.

## File layout

Entry point and output:

- `main.py`: CLI runner for every mode
- `eternia/report.py`: offline HTML report generation
- `tests/`: regression tests, one module per area; `tests/test_browser.py` drives the browser interface in a real browser
- `requirements-browser.txt`: Playwright, needed only for the browser tests
- `docs/status-review-2026-11-16.md`: a status review of v0.6.1, written before v0.7

Core world and actions:

- `eternia/model.py`: world entities
- `eternia/simulation.py`: annual world transitions
- `eternia/actions.py`: authoritative validation, effects and action audit
- `eternia/autonomy.py`: replaceable proposal policy and Edrin experiment

Community and institutions (v0.3–v0.4):

- `eternia/community.py`: community cycle, reservations, social actions, and generations
- `eternia/society_policy.py`: independent observation-only community utility planner
- `eternia/institutions.py`: institutional entities, proposals, voting, and authoritative actions
- `eternia/institutional_world.py`: institutional lifecycle and aggregate economy coupling
- `eternia/institution_policy.py`: observation-only institutional decisions

Region and physical world (v0.5–v0.6.1):

- `eternia/civilizations.py`: regional population, flows, diplomacy, and measurements
- `eternia/regional_engine.py`: purpose-specific charters and authoritative regional mandates
- `eternia/regional_policy.py`: independent local and regional decision policy
- `eternia/physical_world.py`: physical journeys, finite geology, and capacity-aware paths
- `eternia/logistics_engine.py`: authoritative transport and infrastructure actions
- `eternia/logistics_policy.py`: observation-only transport and route decisions
- `eternia/experiments.py`: matched autonomous migration scenarios and recorded evidence

The Living Economy (v0.7):

- `eternia/society.py`: municipal authority, council/organization/private employers, job board, posted prices, consignments, motives, fairness and goal reviews, municipal levies, purposes and rollback
- `eternia/market.py`: the price rule: coverage, bounded smoothing, market spread and wage share
- `eternia/motivations.py`: the six motives, temperament, experiences and their slow drift
- `eternia/goal_engine.py`: candidate goals, scores, cooldown, margin, doubt, contentment and recorded reasons
- `eternia/economic_policy.py`: observation-only economic choices: job valuation, travel for work, goal-driven actions, purchases, sales, consignments, council trade, and responses to fairness (cooperatives, aid, levies, giving)
- `eternia/labor_experiments.py`: matched labor-market scenarios and moves-then-paid-work measurement
- `eternia/market_experiments.py`: matched food-distribution scenarios and shipment measurement
- `eternia/goal_experiments.py`: the Changing Miner, with adaptive and fixed-goal controls
- `eternia/inequality.py`: wealth, income, poverty, food insecurity, Gini coefficients and rank mobility
- `eternia/inequality_experiments.py`: matched starting distributions of wealth and public funds, measured yearly
- `eternia/persistence.py`: whitelisted JSON checkpoints, exact continuation and provenance
- `eternia/evaluation.py`: multi-seed, scenario and priority comparisons

The First Player (v0.8):

- `eternia/player.py`: the player's situation and the menu of every action with editable fields, built only from their own observation and checked against the rules where public facts allow
- `eternia/player_history.py`: the player's journal of coins, work, hiring, shipments, memberships, votes, contests, relationships, conversations and what they have heard, derived from the world's records
- `eternia/dialogue.py`: conversation topics and answers built only from the speaker's own observation and knowledge
- `eternia/social_memory.py`: claims with source, age and confidence, how people record them, and how they pass from person to person
- `eternia/playable_session.py`: a turn-based session: start, join, act (one full cycle for everyone), save, load and exact replay from recorded inputs
- `eternia/interface.py`: everything the browser shows (character, towns, roads, prices, jobs, organizations, people, timeline and each turn's changes), built from the player's own observation, journal and public records
- `eternia/web.py`: the local server: one session per game, versioned requests, saves and replays, and the loopback, host and token checks
- `eternia/webui/`: the page itself (`index.html`, `app.js`, `style.css`), which only draws what the server sends

Emergent Opportunities (v0.9):

- `eternia/needs.py`: what a goal's next step lacks, from the person's own view, how they would close it (a fair offer to take up, preferring a trusted seller, or a job to post), the needs they know they cannot meet, and since Stage 3 `prospects`, the needs they heard of judged as chances to answer or reasons to decline, held to for a while once acted on; since Stage 4, `willingness`, the most a person would pay
- `eternia/social_memory.py`: since Stage 2, `note_needs`, a person's own needs as claims that travel after news of events and go out of date; since Stage 3, `record_supply` and `mark_unanswered`, what came of an answer, and newer terms of a need replacing older ones
- `eternia/goal_engine.py`: `next_step`, what each goal's next step consumes
- `eternia/evaluation.py`: `opportunity_record`, every job posted for a goal and what became of it; `consequence_record`, every answer to a heard need and what came of it
- `eternia/opportunity_experiments.py`: since Stage 4, the same societies with willingness to pay fixed or rising, and what became of their needs
- `eternia/society.py`: since Stage 3, offers, gathering and purchases that state the need they answer, and `procure`, buying goods at a neighboring market to be carried home; since Stage 4, `_record_needs`, a historian's record of what blocked needs and what became of them, and the `rising_willingness` switch
