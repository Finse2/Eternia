# Eternia — Society Engine (v0.4)

A runnable **proof of concept**, NOT a finished MMORPG or general artificial intelligence.

The prototype starts in Year Zero with seven settlements, 1,000 inhabitants,
50 individually represented NPCs, a simple aggregate population/economy,
a hidden Aether parameter, individual observation/experimentation, and recorded
history. It can fast-forward 1,000 years and generate an offline HTML explorer.
Version 0.2 added a world action engine and a separate one-NPC goal experiment.
Version 0.3 adds a five-person community experiment with a shared market,
independent goals, relationships, memories, and successive generations.
Version 0.4 connects that community to institutions with membership, shared
holdings, proposals, votes, and authority over economic decisions.

## Requirements

Python 3.10+; **no packages to install**. Runs on Windows, Linux or macOS.

## Run the v0.4 institution experiment

Run from the repository root, beside `main.py`:

```powershell
python main.py --institutions --years 100 --seed 42
start .\output\institutions\report.html
```

The offline report shows organizations, their members and holdings, proposal
votes, enacted rules, and settlement policy alongside individual histories.
The underlying record is `output/institutions/history.json`. Existing modes
keep their own output locations.

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
meaningful mineral experiments, and rich constitutional politics remain future
work. No LLM or external service is connected.

The configured mining shock is a controlled scenario, rather than an emergent
geological event. Compare a seeded experiment with and without that scenario:

```powershell
python main.py --institutions --years 100 --seed 42
python main.py --institutions --years 100 --seed 42 --shock-year 0 --output output/institutions-baseline
```

Distinct organizational purposes, membership requirements, inter-settlement
political authority, and simulated environmental hazards remain later work.

## Reproduce a checkout

The repository contains its entry point, package, documentation, and tests.
Generated reports and Python bytecode are ignored. From a fresh clone:

```powershell
git clone https://github.com/Finse2/Eternia.git
cd Eternia
python -m unittest discover -s tests -v
python main.py --institutions --years 100 --seed 42
```

GitHub Actions runs the same tests on Windows and Linux with Python 3.10 and
3.12. Running tests does not require network access or third-party packages.

## Run the v0.3 community experiment

Run commands from the cloned repository root, beside `main.py` and `tests/`.
The importable Python package is in `eternia/`:

```powershell
python main.py --community --years 100 --seed 42
start .\output\community\report.html
```

On Linux/macOS use `python3` and open `output/community/report.html` in a browser.
The report is fully offline; its underlying record is
`output/community/history.json`. Community output has a separate directory so
the existing annual society and one-NPC reports remain available.

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

### The community cycle

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
fewer opportunities to act within each year. Replay is deterministic for the
same seed, settings, initial state, and policies.

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
No LLM, provider key, paid API, or network call is involved.

## Run in Windows PowerShell

```powershell
cd Eternia
py -3 main.py --years 1000 --seed 42
start .\output\report.html
```

If `py` is unavailable, try `python main.py --years 1000 --seed 42`.

## Run on Linux/macOS

```bash
python3 main.py --years 1000 --seed 42
```

Open `output/report.html` in any web browser. The JSON history is in
`output/history.json`.

To try a different world:

```bash
python main.py --years 500 --seed 18
```

## Run the Edrin autonomy experiment

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
The demo writes its own `history.json` and `report.html` under `output/autonomy`,
preserving the existing long-run society report. Use `--output another-folder`
to keep multiple experiments.

**This is classical goal-based AI, not an LLM or general intelligence.** It is a
small, inspectable autonomy milestone. A turn is one personal decision; the
aggregate annual economy and biological aging are paused in this experiment.
Hunger and fatigue affect decisions; starvation, illness, rent and housing
benefits are not modeled yet.

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

Personal deposits are a simple finite abstraction, separate from the existing
aggregate annual farming/forestry/mining model. Construction and research consume
materials; food consumption, construction fees and founding costs are explicit
sinks. Full ecological and monetary accounting remain future work.

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

## Test

```bash
python -m unittest discover -s tests -v
```

## What's implemented

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

## What's NOT implemented

- A connected language model, conversations or open-ended reasoning.
- Full households and reproduction, complex ecology, or population-wide migration.
- An economy calibrated to real markets; community offers use a small utility model.
- A continuously simulated field / scientifically rich magic physics.
- Rich government agents, faction politics, wars or player-controlled agents.
- Persistent game save/load for resumable multiplayer worlds.
- 3D map, game client, matchmaking, security or MMO infrastructure.
- Realistic centuries-long historical dynamics; parameter values are illustrative.

**Important:** Discoveries are conditional stochastic events based on an explicit
simplified rule; there is no hidden date that forces magic discovery. This is a
placeholder for a much richer experiment/physics system, not actual open-ended
scientific discovery.

## Suggested next sequence

1. Compare community runs across seeds, disruptions, and alternative utility policies.
2. Measure where relationships, specialization, and knowledge change other people's opportunities.
3. Extend housing benefits, contracts, and households based on observed failures.
4. Extend institutional contracts, representation, and constitutional rules.
5. Add geography, travel times, and ecological constraints.
6. Replace the toy Aether rule with testable multi-factor experiments.
7. Add resumable save/load and richer history queries.
8. Consider an optional LLM policy only after establishing useful community baselines.

## File layout

- `eternia/model.py`: world entities
- `eternia/actions.py`: authoritative validation, effects and action audit
- `eternia/autonomy.py`: replaceable proposal policy and Edrin experiment
- `eternia/simulation.py`: annual world transitions
- `eternia/community.py`: v0.3 community cycle, reservations, social actions, and generations
- `eternia/society_policy.py`: independent observation-only community utility planner
- `eternia/institutions.py`: institutional entities, proposals, voting, and authoritative actions
- `eternia/institutional_world.py`: institutional lifecycle and aggregate economy coupling
- `eternia/institution_policy.py`: observation-only institutional decisions
- `eternia/report.py`: offline HTML report generation
- `main.py`: CLI runner
- `tests/`: simulation, action-boundary, autonomy, and community regression tests
