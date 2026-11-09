"""A replaceable proposal policy and a small, inspectable autonomy experiment.

The included policy is classical, goal-directed utility planning, not an LLM.
It sees public observations and chooses again every turn; it never applies an
action or receives the hidden Aether field. An AI provider can implement the
same ``propose(observation)`` protocol without acquiring world-write access.
"""
from copy import deepcopy
import json
import math
from typing import Protocol


class ProposalPolicy(Protocol):
    """A policy may propose an action, but only the world can execute it."""

    def propose(self, observation: dict) -> dict:
        ...


class GoalPolicy:
    """Choose the best feasible next action from current needs and goals.

    Scores express priorities, not a prescribed action order. Acquiring a
    missing prerequisite advances the house goal; trading and gathering advance
    the wealth goal. Hunger, fatigue, permission changes, depleted deposits and
    remembered rejections can all change the next choice.
    """

    name = 'offline goal-directed utility policy'

    def __init__(self):
        self.reason = ''

    @staticmethod
    def _signature(proposal):
        return json.dumps(proposal, sort_keys=True, separators=(',', ':'))

    def propose(self, observation: dict) -> dict:
        actor = observation['actor']
        town = observation['settlement']
        inventory = actor['inventory']
        skills = set(actor['skills'])
        hunger = actor['hunger']
        energy = actor['energy']
        coins = inventory.get('coins', 0)
        goal = actor.get('wealth_goal', 60)
        rules = observation.get('rules', {})
        prices = rules.get('prices', {'food': 1, 'wood': 2, 'iron': 4})
        house_recipe = rules.get('recipes', {}).get(
            'house', {'wood': 12, 'iron': 2, 'coins': 8})
        gather_limit = rules.get('gather_limit', 8)
        gather_cost = rules.get('gather_energy_per_unit', 2)
        permissions = town.get('permissions', {})
        deposits = town.get('deposits', {})
        owns_house = actor.get('structures', {}).get('house', 0) > 0
        needs_house = not owns_house
        needs_carpentry = needs_house and 'carpentry' not in skills
        # These are public recipe quantities, including the research inputs.
        required = {'food': 2, 'wood': 0, 'iron': 0}
        if needs_house:
            required['wood'] = house_recipe['wood'] + int(needs_carpentry)
            required['iron'] = house_recipe['iron'] + int(needs_carpentry)

        failed = set()
        for memory in actor.get('memory', [])[-8:]:
            result = memory.get('result', {})
            proposal = memory.get('action', memory.get('proposal'))
            if (proposal and result.get('success') is False
                    and observation['year'] - memory.get('year', -100) <= 3):
                failed.add(self._signature(proposal))

        choices = []

        def consider(kind, params, score, reason, cost=0):
            if energy < cost or permissions.get(kind, True) is False:
                return
            proposal = {'actor': actor['id'], 'type': kind,
                        'location': town['id'], 'params': params}
            if self._signature(proposal) in failed:
                return
            choices.append((score, proposal, reason))

        consider('wait', {}, 0,
                 'Needs are met; retain resources while waiting for conditions to change.')
        if energy < 100:
            consider('rest', {}, 3 + max(0, 30 - energy) * 3,
                     'Recover energy before another demanding action.')
        if inventory.get('food', 0) >= 1 and hunger >= 21:
            consider('eat', {}, 45 + hunger,
                     f'Hunger is {hunger:g}; eat from personal supplies.')

        if needs_house and not needs_carpentry:
            if all(inventory.get(resource, 0) >= amount
                   for resource, amount in house_recipe.items()):
                consider('build', {'structure': 'house'}, 78,
                         'Materials and carpentry now permit a house in this settlement.', 15)
        if needs_carpentry:
            if inventory.get('wood', 0) >= 1 and inventory.get('iron', 0) >= 1:
                consider('research', {'topic': 'carpentry'}, 65,
                         'Learn the construction skill needed for the house ownership goal.', 10)

        resource_skill = {'food': 'foraging', 'wood': 'woodcutting', 'iron': 'mining'}
        earning = {}
        for resource in ('food', 'wood', 'iron'):
            stock = inventory.get(resource, 0)
            missing = max(0, required[resource] - stock)
            max_gather = max(0, min(gather_limit, int(deposits.get(resource, 0)),
                                    math.floor(energy / gather_cost)))
            if resource_skill[resource] not in skills or not permissions.get('gather', True):
                max_gather = 0
            earning[resource] = min(gather_limit, deposits.get(resource, 0)) * prices[resource]

            if max_gather and (missing > 0 or (coins < goal and resource != 'food')):
                if missing > 0:
                    amount = min(max_gather, math.ceil(missing))
                    score = 54 if resource != 'food' else 26 + hunger * .65
                    reason = (f'Gather {resource} to cover a missing goal prerequisite.'
                              if resource != 'food' else 'Maintain a personal food reserve.')
                else:
                    amount = max_gather
                    # A sale needs a solvent nearby buyer, not just valuable ore.
                    proceeds = min(amount * prices[resource], town.get('treasury', 0))
                    score = 14 + proceeds * .3
                    reason = f'Gather {resource} for its expected sale value toward {goal:g} coins.'
                consider('gather', {'resource': resource, 'amount': amount},
                         score, reason, amount * gather_cost)

            if 'trading' not in skills:
                continue
            surplus = max(0, math.floor(stock - required[resource]))
            affordable_by_town = math.floor(town.get('treasury', 0) / prices[resource])
            amount = min(8, surplus, affordable_by_town)
            if amount and coins < goal:
                consider('trade', {'resource': resource, 'amount': amount, 'direction': 'sell'},
                         34 + amount * prices[resource] * .2,
                         f'Sell surplus {resource} while preserving food and building materials.', 1)

            # Buy an unavailable prerequisite, or urgent food. Keep construction
            # coins reserved while pursuing a house, when doing so is possible.
            reserve = house_recipe['coins'] if needs_house and resource != 'food' else 0
            spendable = max(0, coins - reserve)
            purchasable = min(8, math.ceil(missing),
                              math.floor(town.get(resource, 0)),
                              math.floor(spendable / prices[resource]))
            if purchasable > 0:
                urgent_food = resource == 'food' and hunger >= 35
                unavailable = max_gather == 0
                if urgent_food or unavailable:
                    score = 28 + hunger if urgent_food else 51
                    consider('trade', {'resource': resource, 'amount': purchasable,
                                       'direction': 'buy'}, score,
                             f'Buy {resource}; current needs cannot wait for local gathering.', 1)

        # Hunger remains a reason to move after the house and wealth goals are
        # complete. Local food must actually be accessible through a permitted
        # gathering action or an affordable market purchase.
        local_food = (
            'foraging' in skills and permissions.get('gather', True)
            and deposits.get('food', 0) >= 1
        ) or (
            'trading' in skills and permissions.get('trade', True)
            and town.get('food', 0) >= 1 and coins >= prices['food']
        )
        needs_food = inventory.get('food', 0) < 1 and not local_food
        if (coins < goal or needs_food) and permissions.get('migrate', True):
            local_return = max((earning[r] for r in ('wood', 'iron')
                                if resource_skill[r] in skills), default=0)
            local_return = min(local_return, town.get('treasury', 0))
            if not permissions.get('gather', True) or not permissions.get('trade', True):
                local_return = 0
            for other in sorted(observation.get('neighbors', []), key=lambda s: s['id']):
                other_permissions = other.get('permissions', {})
                if not other_permissions.get('migrate', True):
                    continue
                if other.get('distance', 0) > 38 or town['population'] <= 10:
                    continue
                remote_food = (
                    'foraging' in skills and other_permissions.get('gather', True)
                    and other.get('deposits', {}).get('food', 0) >= 1
                ) or (
                    'trading' in skills and other_permissions.get('trade', True)
                    and other.get('food', 0) >= 1 and coins >= prices['food']
                )
                if needs_food and remote_food:
                    consider('migrate', {'destination': other['id']},
                             72 + hunger * .5 - other.get('distance', 0) * .05,
                             f'Move to {other["name"]} because no accessible food remains here.', 12)
                if (coins >= goal or not other_permissions.get('gather', True)
                        or not other_permissions.get('trade', True)):
                    continue
                other_return = max((min(gather_limit, other.get('deposits', {}).get(r, 0))
                                    * prices[r] for r in ('wood', 'iron')
                                    if resource_skill[r] in skills), default=0)
                other_return = min(other_return, other.get('treasury', 0))
                gain = other_return - local_return
                if gain > 6:
                    consider('migrate', {'destination': other['id']},
                             27 + gain * .5 - other.get('distance', 0) * .05,
                             f'{other["name"]} offers better earning opportunities after local depletion.', 12)

        if not choices:
            # The world still validates this proposal. A permission denial is a
            # recorded result, rather than a license for the policy to mutate it.
            self.reason = 'No feasible productive action is visible; wait for conditions to change.'
            return {'actor': actor['id'], 'type': 'wait', 'location': town['id'], 'params': {}}
        _, proposal, self.reason = max(choices, key=lambda choice: choice[0])
        return proposal


def run_demo(seed=42, turns=40, shock_turn=8, policy=None):
    """Run one Edrin experiment without advancing the annual society model.

    A turn is one personal decision, not a biological year. ``World.year`` is
    used as the report's common clock; demo metadata names its unit explicitly.
    The optional mine closure changes only environmental state. It never tells
    the policy which action to choose. ``shock_turn=0`` disables the closure.
    """
    if type(turns) is not int or not 0 <= turns <= 10000:
        raise ValueError('turns must be an integer between 0 and 10000')
    if type(shock_turn) is not int or shock_turn < 0:
        raise ValueError('shock_turn must be a nonnegative integer')
    from .model import Agent
    from .simulation import World

    world = World(seed=seed)
    edrin = Agent(0, 'Edrin', 0, 'miner', .8, .95, 24,
                  inventory={'food': 3, 'wood': 0, 'iron': 0, 'coins': 12})
    edrin.memory.append({'year': 0, 'kind': 'goal',
                         'message': 'Build a house and accumulate 60 personal coins.'})
    world.agents = [edrin]
    world.next_agent_id = 1
    world.snapshots = []
    world.action_log = []
    world.last_action_year = {}
    world.decisions = []
    policy = policy or GoalPolicy()
    world.demo = {'actor_id': edrin.id,
                  'policy': getattr(policy, 'name', type(policy).__name__),
                  'turns': turns, 'shock_turn': shock_turn, 'clock': 'turn',
                  'goal': 'Own a house and hold at least 60 coins.',
                  'society_paused': True}
    world._event('goal', 'Edrin begins with needs, memories, and a personal wealth goal.',
                 world.settlements[edrin.home].name, edrin.name)
    world._snapshot()

    for turn in range(1, turns + 1):
        world.year = turn
        edrin.hunger = min(100, edrin.hunger + 7)
        if turn == shock_turn:
            town = next(s for s in world.settlements if s.id == edrin.home)
            town.deposits['iron'] = 0
            world._event('disruption', f'A rockfall closed the accessible iron deposit in {town.name}.',
                         town.name)
            edrin.memory.append({'year': turn, 'kind': 'observation',
                                 'message': f'The accessible iron deposit in {town.name} is closed.'})
        observation = world.observe(edrin.id)
        proposal = policy.propose(deepcopy(observation))
        result = world.submit_action(proposal)
        rationale = getattr(policy, 'reason', 'External policy proposal.')
        if not isinstance(rationale, str):
            rationale = 'External policy proposal.'
        world.decisions.append({'year': turn,
                                'proposal': deepcopy(world.action_log[-1]['action']),
                                'result': result.to_dict(),
                                'rationale': rationale,
                                'perception': {'hunger': observation['actor']['hunger'],
                                               'energy': observation['actor']['energy'],
                                               'inventory': observation['actor']['inventory'],
                                               'settlement': observation['settlement']['name'],
                                               'deposits': observation['settlement']['deposits']}})
        edrin.memory[:] = edrin.memory[-64:]
        world._assert_invariants()
        world._snapshot()
    return world
