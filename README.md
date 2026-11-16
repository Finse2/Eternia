# Eternia — Society Engine (v0.7)

Eternia is a small simulated society that writes its own history. Named people
with needs, goals, memories and relationships live in settlements. They gather
and trade, form guilds, cooperatives and councils, vote, send caravans along
roads that wear out, and take paid work, sometimes in another town. Every run
produces an offline HTML report that you can step through year by year.

It is a runnable **proof of concept**, not a finished game, an MMORPG or general
artificial intelligence. People act on programmed utility rules; no language
model or network service is involved.

**Current version: v0.7, The Living Economy.** Stage 1 of 4, a regional labor
market, is implemented. Stages 2–4 (prices that respond to supply and demand,
ambitions that change over a lifetime, and social consequences of inequality)
are proposed in the [roadmap](#roadmap-the-living-economy).

## Contents

- [Quick start](#quick-start)
- [What you can run](#what-you-can-run)
- [How the simulation works](#how-the-simulation-works)
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
`Year 10: 264.5 coins paid in wages; 13 voluntary actions.` and writes three
files to `output/society/`:

| File | What it is |
|---|---|
| `report.html` | The offline explorer. Open it in any browser. |
| `history.json` | The full record behind the report. |
| `world.save.json` | A checkpoint you can [resume](#save-and-resume). |

Run every command from the repository root, the folder that contains `main.py`
and this README. If you also keep an older starter copy with its own `main.py`
in a parent folder, do not run that one: it is an earlier version.

Three things to try next:

```powershell
# Will a miner travel to another town for a paid job? Four matched cases.
python main.py --labor-experiment --seed 42

# Compare 36 runs across seeds, starting conditions and priorities.
python main.py --evaluate-society --years 5 --evaluation-seeds 18,42,73

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
| [Society](#the-current-society-in-detail) (v0.7) | `--society` | Three towns and 18 named people with councils, funded jobs and a regional labor market | 10 years | `output/society` |
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
took about 50 seconds. The `output/` folder is ignored by Git.

Run `python main.py --help` for every option.

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
- **Everyone plans from the same snapshot.** A decision cycle freezes all
  observations before anyone plans. Competing claims are then settled with a
  seeded shuffle, and anything received during a cycle cannot be spent again in
  that cycle.
- **Nothing is minted.** Trades, wages and contributions transfer existing goods
  and coins. Wages and caravan payments are placed in escrow before the work or
  journey starts. Resources enter through production and leave through explicit
  sinks such as consumption, construction and cargo lost on the road, and a
  ledger records both.
- **Collective decisions need authority.** A vote needs a recorded electorate,
  at least two voters in favour, a strict majority, and votes cast in an earlier
  cycle than the one that enacts the decision.
- **The same seed gives the same history.** Replay is deterministic for the same
  seed, settings and policies.
- **Time has two speeds.** People decide four times per simulated year by
  default. The aggregate economy (production, consumption, births and deaths)
  advances once a year.

Each version's world extends the previous one, so the v0.7 society still
contains the offers, institutions, negotiated trade, caravans and finite mines
described under [Earlier modes](#earlier-modes).

## Roadmap: The Living Economy

v0.7 is planned in four stages. Stage 1 gives Eternia the foundations of a
working labor market. The remaining stages are meant to make that economy
dynamic, give individuals ambitions that evolve, and introduce social
consequences. Each stage has a pass condition, so "done" means a measured
result and not a list of features.

| Stage | Aim | Status |
|---|---|---|
| 1. Regional labor market | People hire, take paid work and travel between towns for a job | Implemented |
| 2. Dynamic markets | Prices emerge from local supply and demand | Proposed |
| 3. Adaptive goals | People reconsider what they want from life | Proposed |
| 4. Inequality and social consequences | Economic conditions shape relationships, institutions and collective decisions | Proposed |

Stages 2–4 are proposals. They describe intent, and the details may change as
each stage is built.

### Stage 1: Regional labor market (implemented)

People can hire others, accept paid work, and travel between settlements for
employment. Councils, voluntary organizations and individuals can each fund a
job, and each must have the money first: the full wage budget goes into escrow
before anyone works.

In the matched [labor experiment](#labor-experiment), miners travelled for a
well-paid job in all 9 runs that offered one and in none of the 27 control runs
(low wage, comparable work at home, or blocked roads). The mechanics are
described under [Paid work across the region](#paid-work-across-the-region).

Three things are still fixed in stage 1: wages come from a reference table
without negotiation, people accept any local funded job without comparing
wages, and only travel is dangerous, never the work itself.

### Stage 2: Dynamic markets, supply and demand (proposed)

**Objective:** make prices emerge from economic conditions and not from fixed
values.

**Today:** every town's market posts the same fixed prices (food 1, wood 2 and
iron 4 coins per unit), and wage offers start from a similar reference table. A
settlement in famine values food exactly as much as one with enormous reserves.

**Proposal:** every settlement develops its own market prices from availability,
consumption, population needs and economic activity. For example:

| Settlement | Situation | Food supply | Illustrative food price |
|---|---|---|---|
| Rivermark | Abundant agricultural production | High | 2 coins per unit |
| Highfen | Remote mountain settlement | Low | 6 coins per unit |

A merchant in Rivermark could recognize the difference, buy food, hire a
caravan, and sell the food in Highfen. This would only be profitable when the
revenue exceeds the purchase cost, transport, journey provisions, losses and
other expenses.

The result is an economy that reacts to conditions. Food shortages could attract
merchants, profitable mines could attract workers, and new trade routes could
change which settlements become prosperous.

**How we'll know it works:** in controlled tests, people trade when the price
difference makes transport worthwhile and avoid trade when it would produce a
loss. Resource and currency conservation remain intact.

### Stage 3: Adaptive goals, individuals with changing ambitions (proposed)

**Objective:** allow people to reconsider what they want from life.

**Today:** individuals pursue the goal they were assigned. Their circumstances
may change radically, but their underlying ambitions stay largely fixed.

Take Edrin, a miner who wants to accumulate 60 coins. He mines, saves, and
eventually succeeds. What happens next? Should he keep mining forever because
that was his original goal?

**Proposal:** a system for the emergence, revision and abandonment of personal
goals. Edrin's life might develop like this:

1. **Young Edrin: survival.** He has little money and wants economic security.
   His goal is to accumulate 60 coins.
2. **Successful Edrin: ambition.** After earning a stable income, he becomes
   interested in establishing a mining business.
3. **Experienced Edrin: responsibility.** After working alongside other miners,
   he develops relationships and might decide to establish a guild.
4. **Older Edrin: legacy.** He may become more interested in teaching,
   supporting his community, or leaving something for his successor.

These are possible developments, not a progression that everyone follows.

Goals would grow out of motivations such as economic security, achievement,
belonging, influence, curiosity and responsibility. Experiences and memories
could change how much each one matters to a person.

A person must also be able to refuse a new ambition. Two miners who experience
the same success should not both necessarily become entrepreneurs.

Every change would enter the historical record: the previous goal, the new
goal, and the evidence or experience that contributed to the decision.

**How we'll know it works:** repeated success, repeated failure and meaningful
life events sometimes produce explainable goal changes, while ordinary
short-term fluctuations do not constantly rewrite personalities.

### Stage 4: Inequality and social consequences (proposed)

**Objective:** make economic circumstances influence social relationships,
institutions and collective decisions.

**Today:** differences in wealth have limited consequences for broader social
development.

Consider a settlement with prosperous merchants, poorly paid miners and limited
access to food. Several reactions are possible:

- Workers might seek better-paid employment elsewhere, form a cooperative,
  demand higher wages, join a guild, or propose public assistance.
- Wealthier individuals might invest in infrastructure, create businesses,
  build alliances, or seek political influence.

These behaviors would emerge from individual preferences and available
opportunities. There would be no rule that automatically makes poor people
rebellious or rich people selfish.

The important part is connecting economic conditions to mechanics that already
exist: trust, reputation, institutions, migration and voting.

Over time this could produce real historical differences between societies. One
settlement might develop strong worker cooperatives while another becomes
dominated by a few economically powerful organizations.

**How we'll know it works:** wealth distributions, trust, institution membership
and migration decisions respond to economic conditions across repeated
experiments, without forcing identical outcomes in every simulation.

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
town, or contribute voluntarily. These are programmed utility priorities, not
LLM reasoning or a predetermined sequence of actions. Use `--policy-style`
with `balanced`, `personal` or `collective` to change those priorities.

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
the same job and split it. Builders and researchers who cannot gather a material
their goal needs may hire someone for it at 60% of the posted market price.
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
| Paid opportunity | Both miners in 7 runs; one in 2 (the other gathered provisions but never left) | Completed by migrants in 9 of 9 |
| Low wage | None in 9 of 9; nobody proposed moving | Expired unworked in 9 of 9 |
| Comparable work at home | None in 9 of 9 | Expired unworked in 9 of 9 |
| Roads blocked | None in 9 of 9 | Expired unworked in 9 of 9 |

Wages earned in Highfen after arriving totalled 32–47 coins per run. No miner
moved in any control run, though controls can record other people's journeys: in
one comparable-work run (seed 18, collective) a merchant and a farmer from Deepwood
moved to Rivermark for a funded food-gathering job and earned 8–9 coins each.
The starting job is an initial condition,
so this tests the decision to travel and its consequences, not job creation; see
the `labor_shortage` evaluation scenario below for the unscripted version.

Each case also gets its own folder with a full `history.json` and `report.html`;
`summary.json` holds the comparison.

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
or sell up to eight units per action at the existing posted market prices,
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
capacity, caravans and migrants, private reserves, ledgers and recorded history.
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

The default matrix has 36 runs: three seeds, four initial scenarios (baseline,
accessible-iron scarcity in every town, initially blocked roads, and
`labor_shortage`), and three policy priorities (`balanced`, `personal`,
`collective`). The scarcity setup moves existing accessible material into
municipal storage; `labor_shortage` only removes mining knowledge from Highfen's
residents. Neither creates resources, posts a job or schedules a journey.
Annual replenishment or autonomous road repair can later change the control
conditions; future actions are never injected.

`evaluation.json` and its filterable report record final goal completion and
progress, paid work, private hires, organization commissions, moves followed by
paid work in the destination, wages earned after moving, voluntary actions,
choices with paid alternatives, hunger, road repairs, shipments, migrations,
ledger residuals and source provenance.
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
  goods and coins against the local market's stocks and treasury. Fixed prices
  are food 1, wood 2, iron 4; goods and money are conserved by each trade.
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
`dispatch_caravan`, `work` and `hire`; see the mode sections above.

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

### What's not implemented

- A connected language model, conversations or open-ended reasoning.
- Full households and reproduction, complex ecology, or population-wide migration.
- An economy calibrated to real markets; community offers use a small utility model.
- Living Economy stages 2–4 (see the [roadmap](#roadmap-the-living-economy)):
  town prices still come from a fixed table, wages from fixed reference values
  (no negotiation or counteroffers), goals never change, and wealth gaps do not
  yet affect trust, membership or migration.
- Workplace danger: only travel is hazardous, so nobody refuses risky work.
- Wage comparison for local work: people take any local funded job they can;
  only the decision to travel compares wages against alternatives.
- A continuously simulated field / scientifically rich magic physics.
- Rich government agents, faction politics, wars or player-controlled agents.
- Cross-version checkpoint migration, continuous crash journals or multiplayer persistence.
- 3D map, game client, matchmaking, security or MMO infrastructure.
- Realistic centuries-long historical dynamics; parameter values are illustrative.

**Important:** Discoveries are conditional stochastic events based on an explicit
simplified rule; there is no hidden date that forces magic discovery. This is a
placeholder for a much richer experiment/physics system, not actual open-ended
scientific discovery.

### After the Living Economy

Candidates for later versions, in rough order:

1. Measure where wages, relationships, specialization and knowledge change opportunities.
2. Extend municipal representation, economic jurisdiction and genuine counteroffers.
3. Explore culture, shared memories and historical identity after the evaluation baseline.
4. Replace the toy Aether rule with testable multi-factor experiments.
5. Add checkpoint-version migrations, richer history queries and scaling measurements.
6. Consider an optional LLM policy only after establishing useful community baselines.

## Tests

```powershell
python -m unittest discover -s tests -v
```

The suite has 345 tests and takes about a minute. It needs no network access and
no third-party packages. GitHub Actions runs the same command on Windows and
Linux with Python 3.10 and 3.12 for every push and pull request.

## File layout

Entry point and output:

- `main.py`: CLI runner for every mode
- `eternia/report.py`: offline HTML report generation
- `tests/`: regression tests, one module per area
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

- `eternia/society.py`: municipal authority, council/organization/private employers, job board, purposes and rollback
- `eternia/economic_policy.py`: observation-only economic choices, including job valuation and travel for work
- `eternia/labor_experiments.py`: matched labor-market scenarios and moves-then-paid-work measurement
- `eternia/persistence.py`: whitelisted JSON checkpoints, exact continuation and provenance
- `eternia/evaluation.py`: multi-seed, scenario and priority comparisons
