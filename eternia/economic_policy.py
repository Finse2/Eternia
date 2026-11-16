"""Observation-only v0.7 choices, including the price of collective work."""
from copy import deepcopy
import math

from .logistics_policy import LogisticsPolicy
from .regional_policy import _get
from .society_policy import CommunityPolicy

STYLES = ('balanced', 'personal', 'collective')


class EconomicPolicy(LogisticsPolicy):
    name = 'economic agency under a municipal charter'

    def __init__(self, style='balanced'):
        super().__init__()
        if style not in STYLES:
            raise ValueError('Unknown economic policy style')
        self.style = style

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
            skill = {'food': 'foraging', 'wood': 'woodcutting', 'iron': 'mining'}[resource]
            amount = min(8, order['remaining'], math.floor(town.get('deposits', {}).get(resource, 0)),
                         math.floor(energy / 2))
            if skill in skills and amount >= 1:
                private_need = max(0., actor.get('goal', {}).get('target', 60) - actor['inventory']['coins'])
                paid_score = 98 - collective * 32 + min(6, amount * order['unit_wage'] * .3)
                if actor.get('goal', {}).get('kind') in ('wealth', 'profit') and private_need > 0:
                    paid_score += 9
                consider('work', {'order': order['id'], 'amount': amount}, paid_score,
                         f'Earn {amount * order["unit_wage"]:g} funded coins by delivering {resource}; '
                         'compare this pay with voluntary collective work.', amount * 2)

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
                if any(o['resource'] == resource for o in orders):
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

