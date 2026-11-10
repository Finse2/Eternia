"""Individual transport and infrastructure choices from public geography.

The planner can organize an authorized caravan or seek a shared road project;
it does not create a shipment or repair as a side effect of observing a need.
Personal hunger and fatigue retain priority over collective transport work.
"""
from copy import deepcopy
import math

from .logistics_engine import PHYSICAL_KINDS, ROAD_COSTS
from .regional_policy import RegionalPolicy, _get


class LogisticsPolicy(RegionalPolicy):
    name = 'regional interests constrained by physical transport'

    def propose(self, observation):
        actor = observation['actor']
        town = observation['settlement']
        inventory = actor.get('available_inventory', actor.get('inventory', {}))
        if actor.get('journey') and actor['journey'].get('status', 'in_transit') == 'in_transit':
            self.reason = 'Continue the journey; local work and institutional authority require arrival.'
            return {'actor': actor['id'], 'type': 'wait', 'params': {}}

        # Older planners must not accidentally vote against unknown road kinds.
        regional_observation = dict(observation)
        regional_observation['institutions'] = [
            {**institution, 'decisions': [decision for decision in institution.get('decisions', [])
                                         if decision.get('kind') not in PHYSICAL_KINDS]}
            for institution in observation.get('institutions', [])]
        physical = observation.get('physical', {})
        paths = physical.get('paths', {})
        if paths:
            def provisioned(destination):
                path = _get(paths, destination, 'unknown')
                return path == 'unknown' or bool(path and path.get('capacity', 0) >= 1
                    and inventory.get('food', 0) + 1e-9 >= path.get('duration', 0) + 2)

            regional_observation['neighbors'] = [
                {**neighbor, 'permissions': {**neighbor.get('permissions', {}),
                    'migrate': neighbor.get('permissions', {}).get('migrate', True)
                    and provisioned(neighbor['id'])}}
                for neighbor in observation.get('neighbors', [])]
        fallback = super().propose(regional_observation)
        fallback_reason = self.reason
        hunger, energy = actor.get('hunger', 0), actor.get('energy', 100)
        role, tick = actor.get('role', ''), observation.get('tick', 0)
        permissions = town.get('permissions', {})
        if (fallback['type'] == 'eat' or fallback['type'] == 'rest' and energy < 15
                or inventory.get('food', 0) < 1 and hunger >= 35
                or hunger >= 65):
            self.reason = fallback_reason
            return fallback

        score = {'build': 82, 'research': 68, 'accept': 65, 'gather': 53,
                 'offer': 51, 'teach': 18, 'collaborate': 24, 'rest': 12,
                 'migrate': 72, 'wait': 0, 'enact': 87, 'vote': 78,
                 'propose': 70, 'contribute': 64, 'leave_institution': 76,
                 'join_institution': 70, 'form_institution': 67}.get(fallback['type'], 0)
        if fallback['type'] == 'gather' and fallback.get('params', {}).get('resource') == 'food':
            score = 45 + hunger * .5 + (7 if role == 'farmer' else 0)
        if fallback['type'] in ('enact', 'vote', 'propose'):
            mandate = fallback.get('params', {}).get('kind')
            if mandate is None:
                mandate = next((decision.get('kind') for institution in observation.get('institutions', [])
                                for decision in institution.get('decisions', [])
                                if decision['id'] == fallback['params'].get('proposal')), None)
            if mandate == 'distribute_food':
                score = {'enact': 101, 'vote': 96, 'propose': 90}[fallback['type']]
        choices = [(score, fallback, fallback_reason)]

        def consider(kind, params, value, reason, cost=0):
            if permissions.get(kind, True) is False or energy < cost:
                return
            proposal = {'actor': actor['id'], 'type': kind,
                        'location': town['id'], 'params': params}
            signature = self._signature(proposal)
            for memory in actor.get('memory', [])[-16:]:
                if (memory.get('result', {}).get('success') is False
                        and tick - memory.get('tick', -100) <= 2
                        and memory.get('action') and self._signature(memory['action']) == signature):
                    return
            choices.append((value, proposal, reason))

        secure = inventory.get('food', 0) >= 2 and hunger < 56
        institutions = [institution for institution in observation.get('institutions', [])
                        if institution.get('active', True) and institution['settlement_id'] == town['id']
                        and actor['id'] in institution.get('members', [])]
        links = {link['id']: link for link in physical.get('links', [])}
        contracts = {route['id']: route for route in observation.get('regional', {}).get('routes', [])}
        memberships = {institution['id'] for institution in institutions}

        if secure:
            for option in physical.get('dispatch_options', []):
                route = contracts.get(option.get('route'))
                if route is None or route.get('exporter_institution') not in memberships:
                    continue
                amount, risk = option.get('amount', 0), option.get('risk', 1)
                if not all(type(value) in (int, float) and math.isfinite(value) for value in (amount, risk)):
                    continue
                if amount < .1 or not option.get('path') or risk > .45:
                    continue
                consider('dispatch_caravan', {'route': route['id'], 'amount': amount},
                         91 + (4 if role == 'merchant' else 0) - min(8, risk * 10),
                         'Organize a funded, authorized delivery whose public path and supplies are feasible.', 4)

        def local_road(institution, link):
            return (link is not None and town['id'] in (link.get('a'), link.get('b'))
                    and link.get('owner') in (None, institution['id']))

        for institution in institutions:
            identifier, members = institution['id'], institution.get('members', [])
            shared = institution.get('available_inventory', {
                **institution.get('inventory', {}), 'coins': institution.get('treasury', 0)})
            decisions = [decision for decision in institution.get('decisions', [])
                         if decision.get('status', 'open') == 'open'
                         and decision.get('expires', tick + 1) > tick]
            projects = [decision for decision in decisions if decision.get('kind') == 'repair_route']
            for decision in decisions:
                kind, params = decision.get('kind'), decision.get('params', {})
                if kind not in PHYSICAL_KINDS:
                    continue
                link = links.get(params.get('link'))
                if kind == 'repair_route':
                    approve = local_road(institution, link) and link.get('condition', 1) < .9
                    funded = all(shared.get(resource, 0) >= amount for resource, amount in ROAD_COSTS.items())
                else:
                    approve = bool(link and link.get('owner') == identifier
                                   and town['id'] in (link.get('a'), link.get('b')))
                    # Border politics remain distinct from access to one road.
                    other = link.get('b') if link and link.get('a') == town['id'] else link.get('a') if link else None
                    confidence = _get(observation.get('regional', {}).get('diplomacy', {}), other, 0)
                    approve = approve and (confidence < -.4 and actor.get('openness', .5) < .35
                                           if params.get('closed') else confidence > -.35 or actor.get('openness', .5) > .6)
                    funded = True
                if (secure and approve and funded and self._approved(decision, members, tick)):
                    consider('enact', {'institution': identifier, 'proposal': decision['id']}, 98,
                             'Execute the previously approved physical infrastructure mandate with reserved resources.', 2)
                electorate = set(decision.get('electorate', members)) & set(members)
                if actor['id'] in electorate and _get(decision.get('votes', {}), actor['id']) is None:
                    consider('vote', {'institution': identifier, 'proposal': decision['id'], 'approve': bool(approve)},
                             88, 'Judge the local road project from its public condition, ownership and expected access.')

            if not secure or len(members) < 2:
                continue
            candidates = [link for link in links.values() if local_road(institution, link)
                          and link.get('condition', 1) < .6]
            if not projects and candidates:
                road = min(candidates, key=lambda link: (link.get('condition', 1), link['id']))
                consider('propose', {'institution': identifier, 'kind': 'repair_route', 'params': {'link': road['id']}},
                         79 + (3 if institution.get('purpose') == 'council' else 0),
                         'Seek members\' consent to repair a deteriorated local connection before commerce is cut off.', 1)
            if not any(decision.get('kind') == 'route_access' for decision in decisions):
                for link in links.values():
                    if link.get('owner') != identifier or town['id'] not in (link.get('a'), link.get('b')):
                        continue
                    other = link['b'] if link['a'] == town['id'] else link['a']
                    confidence = _get(observation.get('regional', {}).get('diplomacy', {}), other, 0)
                    closed = link.get('closed', False)
                    desired = (confidence < -.45 and actor.get('openness', .5) < .35) if not closed else not (
                        confidence > -.25 or actor.get('openness', .5) > .65)
                    if closed != desired:
                        consider('propose', {'institution': identifier, 'kind': 'route_access',
                                             'params': {'link': link['id'], 'closed': desired}},
                                 80, 'Request control of an owned connection according to expected trade and foreign confidence.', 1)
            # A funded road mandate is followed by explicit personal resource
            # decisions. Shared reserves never appear merely because a road is useful.
            for project in projects:
                if not local_road(institution, links.get(project.get('params', {}).get('link'))):
                    continue
                reserve = {'food': 3, 'wood': 0, 'iron': 0, 'coins': 6}
                if role == 'builder' and actor.get('structures', {}).get('house', 0) < actor.get('goal', {}).get('target', 3):
                    reserve.update(wood=12, iron=2)
                if role == 'researcher' and actor.get('knowledge', 0) < 2:
                    reserve['iron'] = 2
                for resource, target in ROAD_COSTS.items():
                    deficit = max(0, target - shared.get(resource, 0))
                    amount = min(deficit, max(0, inventory.get(resource, 0) - reserve[resource]))
                    if amount >= .1:
                        consider('contribute', {'institution': identifier, 'resource': resource, 'amount': amount},
                                 84, 'Contribute an affordable share of the publicly proposed route repair.', 1)
                    elif resource in ('wood', 'iron') and deficit >= 1 and inventory.get(resource, 0) <= reserve[resource]:
                        skill = 'woodcutting' if resource == 'wood' else 'mining'
                        quantity = min(8, math.ceil(deficit), math.floor(town.get('deposits', {}).get(resource, 0)),
                                       math.floor(energy / 2))
                        if skill in actor.get('skills', []) and quantity >= 1:
                            consider('gather', {'resource': resource, 'amount': quantity}, 77,
                                     'Gather accessible material to help fund a proposed local transport repair.', quantity * 2)
        _, proposal, self.reason = max(choices, key=lambda choice: choice[0])
        return proposal
