"""v0.7 Stage 3: candidate ambitions, their scores, and keep-or-revise decisions.

Only goals the world already measures and the action engine already serves are
considered: holding coins (``wealth``, or ``profit`` for merchants), keeping a
food reserve, owning houses, reaching Aether knowledge, and carrying out
approved institutional decisions (``influence``).

    score = appeal x feasibility, both between 0 and 1
    appeal       the goal's motive weights applied to the person's current motives
    feasibility  the person's own evidence: skills, memberships, savings, posted
                 prices, inconclusive experiments, and how long the goal has stalled

A goal is held for at least COOLDOWN cycles. An unfinished goal is replaced only
when an alternative beats it by SWITCH_MARGIN. After completing a goal a person
chooses between a larger version of it, a different ambition, or contentment;
a less ambitious person needs a stronger pull before taking on anything new.
Nothing depends on age or the calendar.
"""
import math

from .motivations import clamp, describe

GOAL_KINDS = ('wealth', 'profit', 'food', 'houses', 'knowledge', 'influence')
VALUE_WEIGHTS = {
    'wealth': {'wealth': .75, 'security': .25},
    'profit': {'wealth': .75, 'security': .25},
    'food': {'security': .85, 'belonging': .15},
    'houses': {'legacy': .5, 'security': .3, 'belonging': .2},
    'knowledge': {'curiosity': .85, 'legacy': .15},
    'influence': {'influence': .6, 'belonging': .4},
}
MAX_TARGETS = {'wealth': 600, 'profit': 600, 'food': 48, 'houses': 6, 'knowledge': 2, 'influence': 60}
COOLDOWN = 8                # cycles a goal is held before it can change: two years at four cycles a year
SWITCH_MARGIN = .12         # how much an alternative must outscore an unfinished goal
STALL_GRACE = 12            # cycles without progress before doubt sets in: three years
STALL_HORIZON = 24          # further cycles over which doubt cuts feasibility to its floor
STALL_FLOOR = .3
# Experiences that count as progress even when the measured holding does not
# reach a new high, for example income spent on food.
PROGRESS = {'wealth': 'income', 'profit': 'income', 'houses': 'built', 'knowledge': 'discovery',
            'influence': 'enactment'}
DOUBT_MEMORY = 20           # cycles over which doubt about an abandoned goal fades: five years
CONTENT_BASE, CONTENT_RANGE = .25, .25   # after success, adopt only above .25 + .25 x (1 - ambition)
SATISFACTION = .15          # reaching a goal lowers its main motive by up to this much
LASTING_SATISFACTION = .3   # share of that drop that settles into temperament


def goal_value(actor, goal):
    """The measured quantity a goal's target refers to."""
    kind = goal.get('kind')
    if kind in ('wealth', 'profit'):
        return actor.inventory.get('coins', 0.)
    if kind == 'houses':
        return actor.structures.get('house', 0)
    if kind == 'knowledge':
        return actor.knowledge
    if kind == 'food':
        return actor.inventory.get('food', 0.)
    if kind == 'influence':
        return actor.influence
    return 0.


STUDY = {'wood': 1., 'iron': 1.}  # what one practical study or experiment consumes
STEPS = {'house': 'houses', 'carpentry': 'houses', 'research': 'knowledge', 'reserve': 'food'}


def next_step(goal, *, skills, structures, knowledge, food, recipes):
    """v0.9: what a goal needs next, from a person's own state; None if it needs no materials.

    A house needs carpentry first, which is studied with a unit of wood and of
    iron; then the house recipe's materials and coins. An Aether goal needs the
    materials of one experiment. A food reserve needs the food still missing.
    Coin, profit and influence goals consume no materials.
    """
    kind, target = goal.get('kind'), goal.get('target', 0)
    if kind == 'houses' and structures.get('house', 0) < goal.get('target', 3):
        if 'carpentry' not in skills:
            return dict(step='carpentry', materials=dict(STUDY), coins=0.)
        recipe = recipes.get('house', {})
        return dict(step='house', materials={r: float(v) for r, v in recipe.items() if r != 'coins'},
                    coins=float(recipe.get('coins', 0.)))
    if kind == 'knowledge' and knowledge < min(2, goal.get('target', 2)):
        return dict(step='research', materials=dict(STUDY), coins=0.)
    if kind == 'food' and food + 1e-9 < target:
        return dict(step='reserve', materials={'food': float(target)}, coins=0.)
    return None


def describe_step(step):
    return {'house': 'for a house', 'carpentry': 'to study carpentry', 'research': 'for an Aether experiment',
            'reserve': 'toward a food reserve'}.get(step, step)


def describe_goal(goal):
    kind, target = goal.get('kind'), goal.get('target', 0)
    return {'wealth': f'hold {target:g} coins', 'profit': f'hold {target:g} coins from trade',
            'food': f'keep a reserve of {target:g} food',
            'houses': f'own {target:g} house' + ('' if target == 1 else 's'),
            'knowledge': f'reach Aether knowledge level {target:g}',
            'influence': f'carry out {target:g} public decisions'}.get(kind, f'pursue {kind} {target}')


def appeal(kind, motivations):
    return sum(weight * motivations[motive] for motive, weight in VALUE_WEIGHTS[kind].items())


def feasibility(kind, actor, context):
    if kind in ('wealth', 'profit'):
        return .8
    if kind == 'food':
        return .9 if context.get('food_access') else .45
    if kind == 'houses':
        skill = .85 if 'carpentry' in actor.skills else .4
        savings = min(1., actor.inventory.get('coins', 0.) / max(1., context.get('house_cost', 40.)))
        return skill * (.4 + .6 * savings)
    if kind == 'knowledge':
        # Materials in hand are a research opportunity; inconclusive experiments are discouraging.
        opportunity = .65 if context.get('materials') else .45
        return 0. if actor.knowledge >= 2 else opportunity * .8 ** context.get('inconclusive', 0)
    if kind == 'influence':
        return .9 if context.get('council_member') else .7 if context.get('member') else .35
    return 0.


def stall_factor(stalled):
    if stalled <= STALL_GRACE:
        return 1.
    return max(STALL_FLOOR, 1 - (stalled - STALL_GRACE) / STALL_HORIZON)


def doubt(mind, kind, tick):
    """A goal abandoned after a stall keeps part of that discouragement for a few years."""
    record = mind.get('doubts', {}).get(kind)
    if not record:
        return 1.
    fade = min(1., max(0., (tick - record['tick']) / DOUBT_MEMORY))
    return record['factor'] + (1 - record['factor']) * fade


def content_threshold(ambition):
    return CONTENT_BASE + CONTENT_RANGE * (1 - min(1., max(0., ambition)))


def _round_up(value, step=10):
    return int(math.ceil(value / step - 1e-9) * step)


def candidate_goals(actor, goal, completed):
    """Supported ambitions with targets above what the person already has."""
    kind = goal.get('kind')
    coins, food = actor.inventory.get('coins', 0.), actor.inventory.get('food', 0.)
    houses, influence = actor.structures.get('house', 0), int(actor.influence)
    coins_kind = kind if kind in ('wealth', 'profit') else ('profit' if actor.role == 'merchant' else 'wealth')
    options = []
    for option in (coins_kind, 'food', 'houses', 'knowledge', 'influence'):
        if option == kind and not completed:
            continue  # the current goal is judged separately
        held = goal.get('target', 0) if option == kind else 0
        target = {'wealth': _round_up(max(held * 2, 60, coins + 40)),
                  'profit': _round_up(max(held * 2, 60, coins + 40)),
                  'food': max(held + 6, 12, math.ceil(food) + 6),
                  'houses': max(held, houses) + 1,
                  'knowledge': max(held, actor.knowledge) + 1,
                  'influence': max(held, influence) + 6}[option]
        if target <= MAX_TARGETS[option] and target > goal_value(actor, {'kind': option}) + 1e-9:
            options.append({'kind': option, 'target': target})
    return options


def new_mind(temperament, actor, tick, origin):
    return dict(motivations=dict(temperament), temperament=dict(temperament), goal_since=tick,
                goal_origin=origin, completed_tick=None, content_since=None,
                best_value=goal_value(actor, actor.goal), best_tick=tick, experience={},
                research=dict(attempts=0, inconclusive=0), doubts={}, history=[], fairness=.5)


def record_experience(mind, kind, deltas, count=1):
    entry = mind['experience'].setdefault(kind, [0, {}])
    entry[0] += count
    for motive, change in deltas.items():
        entry[1][motive] = round(entry[1].get(motive, 0.) + change, 6)


def _satisfy(mind, goal, ambition):
    """Reaching a goal eases the motive behind it, less for ambitious people."""
    weights = VALUE_WEIGHTS.get(goal.get('kind'), {})
    if not weights:
        return {}
    motive = max(weights, key=weights.get)
    drop = SATISFACTION * (1 - min(1., max(0., ambition)))
    mind['motivations'][motive] = round(clamp(mind['motivations'][motive] - drop), 6)
    mind['temperament'][motive] = round(clamp(mind['temperament'][motive] - drop * LASTING_SATISFACTION), 6)
    record_experience(mind, 'achievement', {motive: -drop})
    return {motive: -round(drop, 6)}


def _evidence(mind, previous, chosen, stalled, inconclusive):
    """What led here: a completed goal, the motives behind the new one, and the experiences
    since the previous goal began that pushed toward it."""
    old, new = VALUE_WEIGHTS.get(previous.get('kind'), {}), VALUE_WEIGHTS.get(chosen.get('kind'), {})
    evidence = []
    if mind['completed_tick'] is not None:
        evidence.append(f'reached the goal to {describe_goal(previous)} at cycle {mind["completed_tick"]}')
    drivers = sorted(new, key=lambda m: (-new[m], m))[:2]
    evidence.append('motives behind the new goal: '
                    + ', '.join(f'{m} {mind["motivations"][m]:.2f}' for m in drivers))
    pushes = []
    for kind, (count, totals) in mind['experience'].items():
        push = sum((new.get(m, 0) - old.get(m, 0)) * change for m, change in totals.items())
        if push > 1e-6:
            changes = ', '.join(f'{m} {change:+.2f}' for m, change in sorted(totals.items()) if abs(change) >= .005)
            pushes.append((push, kind, count, changes))
    pushes.sort(key=lambda item: (-item[0], item[1]))
    for _, kind, count, changes in pushes[:3]:
        label = 'reached the previous goal' if kind == 'achievement' else describe(kind)
        evidence.append(f'{label} ({count} cycle{"s" if count != 1 else ""}; {changes})' if changes
                        else f'{label} ({count} cycles)')
    if stalled > STALL_GRACE and mind['completed_tick'] is None:
        evidence.append(f'no progress toward the goal to {describe_goal(previous)} for {stalled} cycles')
    if previous.get('kind') == 'knowledge' and inconclusive:
        evidence.append(f'{inconclusive} inconclusive experiment{"s" if inconclusive != 1 else ""}')
    return evidence


def _adopt(actor, mind, chosen, event, tick, *, reason, scores, stalled, inconclusive):
    previous = dict(actor.goal)
    outcome = 'completed' if mind['completed_tick'] is not None else 'abandoned'
    if outcome == 'abandoned' and stalled > STALL_GRACE:
        mind.setdefault('doubts', {})[previous['kind']] = dict(tick=tick, factor=round(stall_factor(stalled), 4))
    mind['history'].append(dict(goal=previous, adopted=mind['goal_since'], closed=tick, outcome=outcome,
                                completed=mind['completed_tick'], origin=mind['goal_origin']))
    evidence = _evidence(mind, previous, chosen, stalled, inconclusive)
    actor.goal = dict(chosen)
    mind.update(goal_since=tick, goal_origin=event, completed_tick=None, content_since=None,
                best_value=goal_value(actor, chosen), best_tick=tick, experience={})
    return dict(event=event, goal=dict(chosen), previous=previous, previous_outcome=outcome,
                reason=reason, evidence=evidence, scores=scores)


def review(actor, mind, context, *, tick, adaptive, experienced=()):
    """Track progress, record a completion, then keep or revise the goal. Returns events to log.

    ``experienced`` names this cycle's experiences; one listed in PROGRESS for the
    goal's kind counts as progress even if the measured holding fell back.
    """
    events, goal = [], dict(actor.goal)
    progress = goal_value(actor, goal)
    if progress > mind['best_value'] + 1e-9:
        mind['best_value'], mind['best_tick'] = progress, tick
    elif PROGRESS.get(goal.get('kind')) in experienced:
        mind['best_tick'] = tick
    if progress + 1e-9 >= goal.get('target', 1) and mind['completed_tick'] is None:
        mind['completed_tick'] = tick
        events.append(dict(event='completed', goal=goal, satisfied=_satisfy(mind, goal, actor.ambition),
                           reason=f'Reached the goal to {describe_goal(goal)}.'))
    if not adaptive or tick - mind['goal_since'] < COOLDOWN:
        return events
    motives, completed = mind['motivations'], mind['completed_tick'] is not None
    stalled = tick - mind['best_tick']
    inconclusive = context.get('inconclusive', 0)
    scored = sorted(((round(appeal(c['kind'], motives) * feasibility(c['kind'], actor, context)
                            * doubt(mind, c['kind'], tick), 4), c)
                     for c in candidate_goals(actor, goal, completed)),
                    key=lambda item: (-item[0], GOAL_KINDS.index(item[1]['kind'])))
    if not scored:
        return events
    scores = [dict(goal=c, score=s) for s, c in scored[:4]]
    best_score, best = scored[0]
    if completed:
        threshold = content_threshold(actor.ambition) + (SWITCH_MARGIN if mind['content_since'] is not None else 0)
        if best_score >= threshold:
            event = 'escalated' if best['kind'] == goal['kind'] else 'revised'
            verb = 'aim higher and' if event == 'escalated' else 'move on and'
            reason = (f'Having reached the goal to {describe_goal(goal)}, chose to {verb} {describe_goal(best)}: '
                      f'it scores {best_score:.2f}, above the {threshold:.2f} this person needs to take on something new.')
            events.append(_adopt(actor, mind, best, event, tick, reason=reason, scores=scores,
                                 stalled=stalled, inconclusive=inconclusive))
        elif mind['content_since'] is None:
            mind['content_since'] = tick
            events.append(dict(event='content', goal=goal, scores=scores,
                               reason=f'Reached the goal to {describe_goal(goal)} and took on nothing new: the best '
                                      f'option, to {describe_goal(best)}, scores {best_score:.2f}, below the '
                                      f'{threshold:.2f} this person needs.'))
        return events
    current = round(appeal(goal['kind'], motives) * feasibility(goal['kind'], actor, context)
                    * stall_factor(stalled), 4)
    if best_score >= current + SWITCH_MARGIN:
        if stalled > STALL_GRACE:
            why = f'after {stalled} cycles without progress'
        elif goal['kind'] == 'knowledge' and inconclusive:
            why = f'after {inconclusive} inconclusive experiment{"s" if inconclusive != 1 else ""}'
        else:
            why = 'as their priorities shifted'
        reason = (f'Stopped trying to {describe_goal(goal)} {why}; to {describe_goal(best)} now scores '
                  f'{best_score:.2f} against {current:.2f} for the current goal.')
        events.append(_adopt(actor, mind, best, 'revised', tick, reason=reason,
                             scores=[dict(goal=goal, score=current, current=True)] + scores,
                             stalled=stalled, inconclusive=inconclusive))
    return events
