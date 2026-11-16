"""Observation-only v0.7 choices, including the price of collective work.

Job valuation uses only public facts: a notice's terms and claimed units,
neighbors' accessible deposits, and the public route quote. It is a programmed
expected-value estimate, not foresight; other workers may arrive first.
"""
from copy import deepcopy
import math

from .logistics_engine import ROAD_COSTS
from .logistics_policy import LogisticsPolicy
from .regional_policy import _get
from .society_policy import CommunityPolicy

STYLES = ('balanced', 'personal', 'collective')
SKILLS = {'food': 'foraging', 'wood': 'woodcutting', 'iron': 'mining'}
# Programmed reference wages; later market prices can replace this table.
REFERENCE_WAGES = {'food': 1., 'wood': 1.5, 'iron': 2.}
WORKING_SHARE = .75  # turns left after eating and resting
MIN_MOVE_GAIN = 3.   # coins a move must be worth after every estimated cost


def job_value(order, *, tick, energy, regen, deposit, delay=0, risk=0.):
    """Expected (coins, units) from a public order if work can start after ``delay`` ticks.

    Claims observed since the order became workable are projected forward as
    competition. A notice nobody could work yet has no evidence and no value.
    """
    start = tick + delay
    work_ticks = order['expires'] - start
    observed = tick - order['created'] - 1
    if work_ticks < 1 or (delay and observed < 1):
        return 0., 0.
    claim_rate = (order['quantity'] - order['remaining']) / max(1, observed)
    remaining = order['remaining'] - claim_rate * delay
    accessible = deposit - claim_rate * delay
    labor = WORKING_SHARE * min(8 * work_ticks, (max(0., energy) + regen * work_ticks) / 2)
    units = max(0., min(remaining, accessible, labor))
    return units * order['unit_wage'] * (1 - risk), units


class EconomicPolicy(LogisticsPolicy):
    name = 'economic agency under a municipal charter'

    def __init__(self, style='balanced'):
        super().__init__()
        if style not in STYLES:
            raise ValueError('Unknown economic policy style')
        self.style = style

    @staticmethod
    def _mine(order, actor):
        return order.get('employer') == {'kind': 'person', 'id': actor['id']}

    @staticmethod
    def _goal_materials(actor, recipes):
        """Materials the person's own goal consumes next."""
        goal = actor.get('goal', {})
        if (goal.get('kind') == 'houses' and 'carpentry' in actor.get('skills', [])
                and actor.get('structures', {}).get('house', 0) < goal.get('target', 3)):
            return {r: v for r, v in recipes.get('house', {}).items() if r != 'coins'}
        if goal.get('kind') == 'knowledge' and actor.get('knowledge', 0) < goal.get('target', 2):
            return {'wood': 1., 'iron': 1.}  # one research attempt
        return {}

    def _best_move(self, observation, collective, local_value):
        """The most valuable funded job elsewhere, net of travel, risk and leaving home."""
        actor, town = observation['actor'], observation['settlement']
        board = observation.get('municipality', {}).get('job_board', [])
        paths = observation.get('physical', {}).get('paths', {})
        neighbors = {n['id']: n for n in observation.get('neighbors', [])}
        prices = observation.get('rules', {}).get('prices', {'food': 1.})
        tick, energy = observation.get('tick', 0), actor.get('energy', 100)
        regen = 24 / max(1, observation.get('ticks_per_year', 4))
        openness = max(0., min(1., actor.get('openness', .5)))
        ties = len(actor.get('memberships', []))
        best = None
        if town.get('population', 0) <= 10 or any(self._mine(o, actor) for o in
                                                    observation.get('municipality', {}).get('work_orders', [])):
            # The population floor forbids leaving; an open private job needs its employer present.
            return None
        for order in board:
            neighbor, path = neighbors.get(order['settlement']), _get(paths, order['settlement'])
            if (neighbor is None or not path or path.get('capacity', 0) < 1
                    or neighbor.get('permissions', {}).get('migrate', True) is False
                    or SKILLS[order['resource']] not in actor.get('skills', []) or self._mine(order, actor)):
                continue
            duration, risk = path['duration'], min(1., max(0., path.get('risk', 0)))
            gross, units = job_value(order, tick=tick, energy=energy - 12 - duration, regen=regen,
                                     deposit=neighbor.get('deposits', {}).get(order['resource'], 0),
                                     delay=duration, risk=risk)
            provisions = duration * .5 * prices.get('food', 1.)
            attachment = 4 + 3 * ties * (1 + collective) + 8 * (1 - openness)
            net = gross - provisions - attachment - local_value
            if net >= MIN_MOVE_GAIN and (best is None or net > best['net']):
                best = dict(order=order, destination=neighbor, duration=duration, risk=risk,
                            units=units, gross=gross, net=net, food=duration + 2.)
        return best

    def propose(self, observation):
        actor, town = observation['actor'], observation['settlement']
        available = actor.get('available_inventory', actor['inventory'])
        municipality = observation.get('municipality', {})
        authorities = municipality.get('authorities', {})
        orders = municipality.get('work_orders', [])
        tick = observation.get('tick', 0)
        fallback = super().propose(observation)
        reason = self.reason
        hunger, energy = actor.get('hunger', 0), actor.get('energy', 100)
        if actor.get('journey') or fallback['type'] == 'eat' or energy < 15 or (
                hunger >= 35 and available.get('food', 0) < 1) or hunger >= 65:
            return fallback

        organizations = [i for i in observation.get('institutions', [])
                         if i.get('active', True) and i['settlement_id'] == town['id']]
        councils = sorted((i for i in organizations if i.get('purpose') == 'council'),
                          key=lambda i: (-len(i['members']), i['id']))
        member_councils = [i for i in councils if actor['id'] in i['members']]
        # Suppress an old policy's proposed use of municipal resources when the
        # new charter denies authority. This changes proposals, never world rules.
        if fallback['type'] == 'propose' and fallback.get('params', {}).get('kind') in (
                'trade_terms', 'specialization', 'communal_labor', 'migration_policy', 'route_access'):
            target = fallback['params'].get('institution')
            if not _get(authorities, target, False):
                helper = CommunityPolicy()
                fallback = helper.propose(observation)
                reason = helper.reason

        scores = {'gather': 48, 'offer': 46, 'accept': 59, 'build': 82, 'research': 68,
                  'rest': 12, 'migrate': 72, 'enact': 87, 'vote': 78,
                  'propose': 68, 'contribute': 65, 'teach': 20, 'collaborate': 25,
                  'form_institution': 60, 'join_institution': 61, 'leave_institution': 75}
        score = scores.get(fallback['type'], 0)
        collective = {'personal': 0., 'balanced': .5, 'collective': 1.}[self.style]
        if fallback['type'] in ('contribute', 'teach', 'collaborate', 'dispatch_caravan'):
            score += collective * 30
        choices = [(score, fallback, reason)]
        skills = set(actor.get('skills', []))
        permissions = town.get('permissions', {})
        recent_failures = {self._signature(m['action']) for m in actor.get('memory', [])[-16:]
                           if m.get('action') and m.get('result', {}).get('success') is False
                           and tick - m.get('tick', -100) <= 2}

        def consider(kind, params, value, explanation, cost=0):
            if permissions.get(kind, True) is False or energy < cost:
                return
            proposal = dict(actor=actor['id'], type=kind, location=town['id'], params=params)
            if self._signature(proposal) not in recent_failures:
                choices.append((value, proposal, explanation))

        if not councils and available.get('coins', 0) >= 2:
            consider('form_institution', {'name': town['name'] + ' Municipal Council', 'purpose': 'council'},
                     74, 'Seek a local council before authorizing town resources.', 2)
        elif councils and actor['id'] not in councils[0]['members']:
            consider('join_institution', {'institution': councils[0]['id']}, 75,
                     'Join a local council so municipal decisions can represent a majority.', 1)

        for order in orders:
            resource = order['resource']
            skill = SKILLS[resource]
            amount = min(8, order['remaining'], math.floor(town.get('deposits', {}).get(resource, 0)),
                         math.floor(energy / 2))
            if skill in skills and amount >= 1 and not self._mine(order, actor):
                private_need = max(0., actor.get('goal', {}).get('target', 60) - actor['inventory']['coins'])
                paid_score = 98 - collective * 32 + min(6, amount * order['unit_wage'] * .3)
                if actor.get('goal', {}).get('kind') in ('wealth', 'profit') and private_need > 0:
                    paid_score += 9
                consider('work', {'order': order['id'], 'amount': amount}, paid_score,
                         f'Earn {amount * order["unit_wage"]:g} funded coins by delivering {resource}; '
                         'compare this pay with voluntary collective work.', amount * 2)

        # Paid work elsewhere: worth a journey only if it beats staying.
        rules = observation.get('rules', {})
        prices = rules.get('prices', {'food': 1., 'wood': 2., 'iron': 4.})
        regen = 24 / max(1, observation.get('ticks_per_year', 4))
        local_value = max((job_value(o, tick=tick, energy=energy, regen=regen,
                                     deposit=town.get('deposits', {}).get(o['resource'], 0))[0]
                           for o in orders if SKILLS[o['resource']] in skills and not self._mine(o, actor)),
                          default=0.)
        move = self._best_move(observation, collective, local_value)
        if move:
            order, place = move['order'], move['destination']
            summary = (f'{place["name"]} pays {order["unit_wage"]:g} coins per {order["resource"]}; about '
                       f'{move["units"]:.0f} units should remain after a {move["duration"]}-tick journey with '
                       f'{move["risk"]:.0%} turn-back risk, worth about {move["net"]:.1f} coins more than staying.')
            goal = actor.get('goal', {})
            short = goal.get('kind') in ('wealth', 'profit') and actor['inventory']['coins'] < goal.get('target', 60)
            # Priority grows with the stake: a large opportunity outranks a routine
            # vote, though not enacting spending that members already approved.
            value = 84 + min(20, move['net'] * .6) + (6 if short else 0)
            food = available.get('food', 0)
            if food + 1e-9 >= move['food']:
                consider('migrate', {'destination': place['id']}, value, 'Move for paid work: ' + summary, 12)
            else:
                needed = math.ceil(move['food'] - food - 1e-9)
                # Two extra units cover meals eaten while still preparing.
                amount = min(8, needed + 2, math.floor(town.get('deposits', {}).get('food', 0)), math.floor(energy / 2))
                if 'foraging' in skills and amount >= 1:
                    consider('gather', {'resource': 'food', 'amount': amount}, value - 4,
                             'Gather journey provisions before moving for paid work. ' + summary, amount * 2)
                elif (needed <= 8 and town.get('food', 0) >= needed
                      and available.get('coins', 0) >= needed * prices.get('food', 1.)):
                    consider('trade', {'resource': 'food', 'amount': needed, 'direction': 'buy'}, value - 4,
                             'Buy journey provisions before moving for paid work. ' + summary, 1)

        # Hire for what my own goal needs but I cannot gather myself. Wages are
        # escrowed from my coins, so keep what the goal itself will still cost.
        needs = self._goal_materials(actor, rules.get('recipes', {}))
        if needs and not any(self._mine(o, actor) for o in orders):
            reserve = rules.get('recipes', {}).get('house', {}).get('coins', 0) if actor.get('goal', {}).get('kind') == 'houses' else 0
            for resource in ('iron', 'wood', 'food'):
                missing = math.ceil(needs.get(resource, 0) - available.get(resource, 0) - 1e-9)
                if missing < 1 or SKILLS[resource] in skills:
                    continue
                wage = round(min(5., max(.1, prices.get(resource, 1.) * .6)), 2)
                if available.get('coins', 0) + 1e-9 >= missing * wage + reserve:
                    consider('hire', {'resource': resource, 'quantity': missing, 'unit_wage': wage}, 73,
                             f'Hire a worker for {missing} {resource} at {wage:g} coins each, below the posted price; '
                             'my goal needs it and I cannot gather it myself.', 1)
                break

        # Voluntary organizations may pay for a road project's missing material
        # from their own voted holdings instead of waiting for volunteers.
        for institution in organizations:
            members = institution.get('members', [])
            if institution.get('purpose') == 'council' or actor['id'] not in members:
                continue
            identifier, shared = institution['id'], institution.get('available_inventory', {})
            decisions = [p for p in institution.get('decisions', []) if p['status'] == 'open' and p['expires'] > tick]
            project = any(p['kind'] == 'repair_route' for p in decisions)
            for proposal in decisions:
                if proposal['kind'] != 'commission':
                    continue
                params = proposal['params']
                budget = params['quantity'] * params['unit_wage']
                support = (project and shared.get('coins', 0) >= budget + ROAD_COSTS['coins']
                           and shared.get(params['resource'], 0) < ROAD_COSTS.get(params['resource'], 0))
                if actor['id'] in proposal.get('electorate', []) and _get(proposal.get('votes', {}), actor['id']) is None:
                    consider('vote', {'institution': identifier, 'proposal': proposal['id'], 'approve': bool(support)},
                             90, 'Judge a paid commission from its cost and the road project still needing material.')
                if support and self._approved(proposal, members, tick):
                    consider('enact', {'institution': identifier, 'proposal': proposal['id']}, 100,
                             'Escrow the voted commission wages from shared holdings.', 2)
            hiring = any(o.get('employer') == {'kind': 'institution', 'id': identifier} for o in orders)
            if not project or hiring or len(members) < 2 or any(p['kind'] == 'commission' for p in decisions):
                continue
            for resource in ('iron', 'wood'):
                deficit = math.ceil(ROAD_COSTS[resource] - shared.get(resource, 0) - 1e-9)
                wage = REFERENCE_WAGES[resource]
                if deficit >= 1 and shared.get('coins', 0) >= deficit * wage + ROAD_COSTS['coins']:
                    consider('propose', {'institution': identifier, 'kind': 'commission',
                                         'params': {'resource': resource, 'quantity': deficit, 'unit_wage': wage}},
                             80, f'Ask members to pay for {deficit} {resource} the road project lacks, from shared coins.', 1)
                    break

        for council in member_councils:
            identifier = council['id']
            authorized = _get(authorities, identifier, False)
            decisions = [p for p in council.get('decisions', [])
                         if p['status'] == 'open' and p['expires'] > tick]
            for proposal in decisions:
                if proposal['kind'] != 'work_order':
                    continue
                params = proposal['params']
                budget = params['quantity'] * params['unit_wage']
                scarce = town.get('deposits', {}).get(params['resource'], 0) >= 1
                affordable = town.get('treasury', 0) >= budget
                support = scarce and affordable and params['unit_wage'] <= 2
                votes = proposal.get('votes', {})
                if actor['id'] in proposal['electorate'] and _get(votes, actor['id']) is None:
                    consider('vote', {'institution': identifier, 'proposal': proposal['id'], 'approve': bool(support)},
                             94, 'Judge a public work budget from its wage, local material and municipal funds.')
                if authorized and support and self._approved(proposal, council['members'], tick):
                    consider('enact', {'institution': identifier, 'proposal': proposal['id']}, 106,
                             'Reserve the voted wage budget before anybody can claim public pay.', 2)
            if (not authorized or any(p['kind'] == 'work_order' for p in decisions)
                    or town.get('treasury', 0) < 8):
                continue
            # Jobs address an observed municipal stock deficit. Policy candidates
            # are public facts, not hidden resource reserves or other wallets.
            candidates = []
            for resource in ('food', 'wood', 'iron'):
                if any(o['resource'] == resource and o.get('employer', {}).get('kind') == 'municipal'
                       for o in orders):
                    continue
                accessible = math.floor(town.get('deposits', {}).get(resource, 0))
                deficit = self._resource_target(town, resource) - town.get(resource, 0)
                if accessible >= 1 and deficit >= 1:
                    candidates.append((deficit / max(1, self._resource_target(town, resource)), resource, accessible))
            if candidates:
                _, resource, accessible = max(candidates)
                wage = {'food': 1., 'wood': 1.5, 'iron': 2.}[resource]
                quantity = min(24, accessible, math.floor(town['treasury'] * .4 / wage))
                if quantity >= 1:
                    consider('propose', {'institution': identifier, 'kind': 'work_order',
                                        'params': {'resource': resource, 'quantity': quantity, 'unit_wage': wage}},
                             84, 'Propose paid extraction for a public shortage, within forty percent of current town coins.', 1)

        # Attach a verifiable purpose to unpaid material gathering for a project.
        if fallback['type'] == 'gather' and 'repair' in reason.lower():
            for institution in organizations:
                if actor['id'] not in institution['members']:
                    continue
                project = next((p for p in institution.get('decisions', [])
                                if p['kind'] == 'repair_route' and p['status'] == 'open'
                                and p['created'] < tick < p['expires']), None)
                if project:
                    fallback['params']['purpose'] = dict(kind='voluntary_project',
                                                       institution=institution['id'], proposal=project['id'])
                    choices[0] = (77 + collective * 20, fallback,
                                  'Choose unpaid project preparation to support a proposed public road repair.')
                    break
        _, proposal, self.reason = max(choices, key=lambda item: item[0])
        return deepcopy(proposal)

