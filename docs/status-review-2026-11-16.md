# Eternia project status review

**Review date:** 16 November 2026  
**Version reviewed:** v0.6.1, local Git commit `20c70e1`  
**Last local commit:** 11 November 2026, “Refine geological privacy, travel routing, and migration experiments”  
**Repository:** `C:\Users\lukajacquespaul.arev\Desktop\eternia-starter\eternia`  
**Origin configured locally:** `https://github.com/Finse2/Eternia.git`

## Assessment

Eternia is now a functioning, bounded civilization simulation prototype. It has progressed beyond the original seven-settlement simulator and single autonomous miner into an integrated experiment with **18 individually represented people, three settlement economies, institutions, negotiated commerce, physical transport, and finite mineral reserves**.

Its strongest achievement is the separation between what an agent proposes and what the world authorizes. The current test suite provides substantial evidence for internal consistency, authority checks, resource accounting, and deterministic replay. Its next challenge is demonstrating that those mechanics reliably produce meaningful personal and social outcomes.

It is ready for structured behavioral evaluation and further simulation research. It is not yet a persistent game platform, an MMO, a model calibrated to real societies, or an open-ended reasoning system. The included AI consists of programmed utility policies; no LLM is connected.

## Review scope and source of truth

This review inspected the current source, tests, CI configuration, local Git history, two saved 100-year physical-world histories, and the controlled migration experiment. The full test suite was rerun locally on Windows with Python 3.12.4 and passed: **280 tests across 18 test modules**. Two-seed, three-year migration probes were also run in memory without replacing saved outputs.

The original Downloads workspace is currently empty. An older launcher and README remain in the parent Desktop folder, while the actual Git repository is the nested `eternia` directory named above. Run commands and open the IDE from that repository to avoid accidentally using the older v0.3 launcher.

Saved run files are evidence of the recorded runs, not newly rerun 100-year experiments. Their schema is v0.6.1, but they do not record a source commit, so exact attribution to the reviewed revision is unavailable. Remote GitHub branch state and hosted CI results were not checked.

## What is implemented

### World action engine and independent individuals

The action engine validates actor identity, location, permissions, knowledge, materials, energy, and action budgets. It supports gathering, building, trade, research, migration, founding, negotiation, and personal maintenance actions.

Community planning gives each policy a detached observation and binds its proposal to its assigned actor. All people plan from the common tick state; execution then rechecks current authority and resources. Seeded resolution handles competing claims. Reservations and frozen budgets prevent several forms of double spending and same-cycle knowledge or resource reuse.

Individuals have inventories, needs, goals, bounded memories, relationships, reputation, and knowledge transfer. Death and adult succession connect generations through estates and imperfect inheritance. These are not full biological households: pregnancy, childhood, couples, and genealogy remain outside the model.

Sources: [actions.py](../eternia/actions.py), [community.py](../eternia/community.py), [society_policy.py](../eternia/society_policy.py).

### Institutions and regional economies

People can form or join cooperatives, guilds, and councils, contribute to shared holdings, propose decisions, vote, enact approved mandates, or leave. Institutions can persist across individual deaths and collapse when abandoned.

Voting uses recorded electorates, prior-tick votes, current eligibility, at least two affirmative voters, and a strict majority. Approved decisions affect food storage and distribution, member levies, labor allocation, specialization, trade permission, embargoes, and borders.

Three settlements have different resource endowments. Trade contracts require independently approved matching mandates, finite stocks and funds, and respect quotas and expiry. This is bilateral consent, but not yet genuine bargaining with counteroffers. Council representation concerns the small named cohort rather than every aggregate resident.

Sources: [institutions.py](../eternia/institutions.py), [institutional_world.py](../eternia/institutional_world.py), [civilizations.py](../eternia/civilizations.py), [regional_engine.py](../eternia/regional_engine.py).

### Physical world and limited knowledge

Caravans reserve cargo, provisions, buyer funds in escrow, and route capacity. Delivery takes time; cargo can be lost, routes can deteriorate, and institutions must approve maintenance. Agreements alone do not teleport shipments.

Migrants physically depart and arrive, cannot work locally while traveling, lose their prior institutional memberships on departure, and face destination checks. Return journeys and deferred retirement provide deliberate prototype safeguards.

Mines have finite buried reserves. Extraction transfers iron into the economy. NPCs receive personal or inherited mining evidence, with unknown reserve estimates, while the historical observer can inspect authoritative reserves. Policies do not receive the underground truth. Route quotes compound hazard over expected travel cycles and account for cargo plus provisions.

Sources: [physical_world.py](../eternia/physical_world.py), [logistics_engine.py](../eternia/logistics_engine.py), [logistics_policy.py](../eternia/logistics_policy.py).

### Inspectable history

Offline HTML reports expose timelines, settlements, institutions, votes, decisions, journeys, and accounting. JSON exports retain detailed histories. The older simulator, single-NPC, community, institutional, regional, physical-world, and migration-comparison modes remain available separately.

History export is not resumable save/load. The current implementation does not provide a persistent server, multiplayer networking, player client, or production deployment system.

## Evidence from recorded runs

The two saved physical-world runs cover **100 simulated years at four decision cycles per year**, with 18 represented people and three settlements. Each records 7,200 actions and 101 snapshots.

**Seed 42:** aggregate population changes from 480 to 625. There are 181 caravan departures, 175 deliveries, six failures, nine road repairs, and one exhausted mine. Ten institutions form and one collapses; 87 institutional enactments and 39 knowledge transfers are recorded.

**Seed 18:** aggregate population changes from 480 to 610. There are 199 caravan departures, 182 deliveries, 17 failures, nine road repairs, and one exhausted mine. Twelve institutions form and three collapse; 90 institutional enactments and 34 knowledge transfers are recorded.

These runs demonstrate histories with finite transport, failure, institutional change, and knowledge transmission. They are only two observations, not a statistical validation of the society model. Both record **zero migrant departures**. A working migration mechanism therefore does not imply migration commonly occurs under default conditions.

The final resource totals reconcile with initial totals plus recorded production minus consumption to within `1e-6` units in both files; the largest recomputed residual is below `1e-9`. This verifies the recorded accounting identity, not ecological or economic realism.

Sources: [seed 42 history](../output/physical-world/history.json), [seed 18 history](../output/physical-world-seed18/history.json).

## What the autonomy milestone actually demonstrates

The controlled migration comparison keeps the ordinary 18 agents and policy, changing initial conditions without injecting future decisions.

In fresh three-year checks for seeds 42 and 18, the opportunity case makes Edrin choose migration at tick 0, arrive in Highfen at tick 4, and gather iron at tick 5. The matched local-work and blocked-route cases do not propose migration.

This is useful evidence that public opportunities and physical constraints change autonomous choices. It is not evidence of open-ended reasoning or successful wealth pursuit. In both opportunity checks, the miner finishes with **0 coins against a 60-coin target**. The observed mining action serves a road project; finding work is not equivalent to getting paid or completing a personal goal.

The earlier isolated Edrin demo and its 68-coin outcome remain a separate experiment. That success should not be used to describe the integrated physical-world experiment.

Sources: [experiments.py](../eternia/experiments.py), [recorded migration comparison](../output/migration-experiment/summary.json), [migration tests](../tests/test_migration_experiments.py).

## Engineering quality and remaining risks

**Regression coverage is substantial.** The 280 passing tests cover malformed proposals, atomic rule rejection, pure validation, reservation conflicts, resource transfers, voting authority, hidden-state privacy, physical travel, routing, and replay. CI is configured for Ubuntu and Windows on Python 3.10 and 3.12; that configuration was inspected, not its hosted results.

**Behavioral validation is narrower.** Most tests use fixed seeds and constructed situations. There is no tracked broad seed sweep, policy comparison, ablation study, calibration dataset, or large-world benchmark. Test count must not be presented as a percentage of feature completeness or proof of realistic emergence.

**Crash recovery is not transactional.** Expected rule rejections are atomic, but authoritative effects are applied before final audit/accounting. Unexpected exceptions lack a demonstrated rollback mechanism. This is a recovery risk, not a reproduced normal-path rule failure. See `actions.py:134` and `community.py:410`.

**Economic jurisdiction is simplified.** A qualified member of a sponsoring institution can organize shipments using municipal resources, and a small organization can acquire maintenance authority over an unowned connection. These are explicit rules, but they do not establish population-wide authorization over town accounts and infrastructure. See `logistics_engine.py:63`, `logistics_engine.py:122`, and `physical_world.py:237`.

**Knowledge is protected more than it is reasoned about.** Geological memory is exposed to the policy, but current migration choices chiefly compare accessible deposits. There are no surveys or inferred reserve models. Migration is provision- and capacity-aware; it does not optimize personal risk preferences. Trade negotiation still needs exact matching terms.

**Scaling and presentation need measurements.** The saved histories are about 45 MiB each; their HTML reports are about 23 MiB. Histories and snapshots accumulate, and routing enumerates simple paths on a three-node graph. These are clear scaling considerations, not measured performance failures. The tracked suite has no direct CLI or browser/report tests, coverage measurement, or performance gate.

**Major product systems remain absent.** Resumable persistence, a player-facing client/API, multiplayer, rich ecology, full families, warfare, culture and historical identity, scientifically richer Aether discovery, and LLM-driven conversation are not established by this version.

## Recommended next milestone

Prioritize **measurable, persistent autonomous society** before adding many more agents or another large feature layer.

1. **Establish the canonical workspace and run provenance.** Use the nested Git repository; record revision, full configuration, policy version, seed, and scenario identity in every exported run.
2. **Measure personal and collective outcomes.** Run a repeatable seed/parameter matrix and compare baseline policies. Track goal completion, hunger, income after migration, time to opportunity, failed proposals, institutional survival, deliveries, losses, and isolation. Diagnose why useful work fails to generate personal wealth before treating migration as a completed economic behavior.
3. **Add resumable saves and recovery checks.** Restore RNG state, tick budgets, offers, votes, in-transit cargo, escrow, and capacities. Acceptance test: an uninterrupted run and a save/resume run produce identical subsequent outcomes. Add fault-injection checks around authoritative effects and accounting.
4. **Strengthen authority and usability.** Define municipal and infrastructure jurisdiction, then add CLI smoke checks and browser interaction checks to CI.
5. **Extend behavior from measured needs.** Consider geological inference, risk preferences, genuine counteroffers, or culture/shared history after the evaluation baseline is stable. Keep any later LLM adapter restricted to observations and proposals.

The concrete next pass condition is an exported, reproducible comparison showing when agents reach their own goals, when they sacrifice those goals for institutions, and whether that tradeoff persists across seeds—while preserving the existing accounting and authority guarantees.

