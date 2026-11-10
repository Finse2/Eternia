"""Public-information planning for competing regional institutions.

People retain personal needs and goals. Their preferred organization, willingness
to trade and political judgments depend on profession, temperament, public local
conditions, remembered outcomes and other organizations' advertised proposals.
No pair of towns or institutions is assigned a future agreement.
"""
import math

from .institution_policy import InstitutionalPolicy
from .society_policy import CommunityPolicy


REGIONAL_KINDS = {'trade_terms', 'embargo', 'specialization', 'migration_policy'}
PURPOSE_LABELS = {'cooperative': 'Cooperative', 'guild': 'Trading Guild',
                  'council': 'Council'}


def _get(mapping, key, default=None):
    return mapping.get(key, mapping.get(str(key), default))


class RegionalPolicy(InstitutionalPolicy):
    name = 'independent regional interests and negotiated terms'

    @staticmethod
    def _approved(decision, members, tick):
        electorate = set(decision.get('electorate', members)) & set(members)
        votes = decision.get('votes', {})
        yes = sum(_get(votes, voter, {}).get('approve') is True
                  and _get(votes, voter, {}).get('tick', tick) < tick
                  for voter in electorate)
        return (decision.get('status', 'open') == 'open'
                and decision.get('created', tick) < tick < decision.get('expires', tick + 1)
                and yes >= 2 and yes * 2 > len(electorate))

    @staticmethod
    def _resource_target(town, resource):
        population = max(1, town.get('population', 1))
        return population * {'food': 1.12, 'wood': .25, 'iron': .12}[resource]

    @staticmethod
    def _export_reserve(town, resource):
        return max(1, town.get('population', 1)) * {'food': 1.1, 'wood': .10, 'iron': .04}[resource]

    @staticmethod
    def _advantage(town):
        population = max(1, town.get('population', 1))
        values = {'food': town.get('farmland', 0) * town.get('fertility', 0) / population,
                  'wood': town.get('forest', 0) * 1.5,
                  'iron': town.get('ore', 0) * 1.6}
        return max(values, key=values.get)

    def propose(self, observation):
        actor, town = observation['actor'], observation['settlement']
        inventory = actor.get('available_inventory', actor['inventory'])
        role = actor.get('role', '')
        energy, hunger = actor.get('energy', 100), actor.get('hunger', 0)
        tick = observation.get('tick', 0)
        openness = max(0, min(1, actor.get('openness', .5)))
        preferred = actor.get('preferred_purpose', {
            'miner': 'guild', 'merchant': 'guild', 'councillor': 'council'
        }.get(role, 'cooperative'))
        if preferred not in PURPOSE_LABELS:
            preferred = 'cooperative'
        institutions = sorted(observation.get('institutions', []), key=lambda i: i['id'])
        local = [i for i in institutions if i.get('active', True) and i['settlement_id'] == town['id']]
        memberships = [i for i in local if actor['id'] in i.get('members', [])]
        neighbors = {n['id']: n for n in observation.get('neighbors', []) if n.get('distance', 0) <= 38}
        regional = observation.get('regional', {})
        diplomacy = regional.get('diplomacy', {})
        prices = regional.get('prices', {'food': .2, 'wood': .5, 'iron': 1.5})
        local_count = regional.get('local_named_count', len(observation.get('peers', [])) + 1)
        permissions = town.get('permissions', {})
        population = max(1, town.get('population', 1))
        pressure = max(0, 1 - town.get('food', 0) / population)

        # Keep v0.4's food relief and public projects for civic organizations.
        # Regional votes are evaluated below; the old planner must not vote on
        # them as unknown policies or create an implicit, unpriced treaty.
        civic = dict(observation)
        civic['institutions'] = [
            {**i, 'decisions': [d for d in i.get('decisions', [])
                               if d.get('kind') not in REGIONAL_KINDS
                               and d.get('kind') != 'trade_agreement']}
            for i in memberships if i.get('purpose', 'cooperative') != 'guild']
        fallback = super().propose(civic)
        fallback_reason = self.reason
        if (fallback['type'] in ('form_institution', 'join_institution')
                or fallback['type'] == 'propose'
                and fallback.get('params', {}).get('kind') == 'trade_agreement'):
            fallback = CommunityPolicy.propose(self, observation)
            fallback_reason = self.reason

        # Competing groups share a bounded local labor/tax mandate. A proposal
        # can use the remaining public capacity; an older over-cap mandate must
        # wait for changed conditions rather than monopolizing every third turn.
        params = fallback.get('params', {})
        institution = next((i for i in memberships if i['id'] == params.get('institution')), None)
        decision = next((d for d in institution.get('decisions', [])
                         if d['id'] == params.get('proposal')), None) if institution else None
        mandate = params.get('kind') if fallback['type'] == 'propose' else (
            decision.get('kind') if decision else None)
        if institution and mandate in ('tax_rate', 'communal_labor'):
            cap = .15 if mandate == 'tax_rate' else .3
            others = sum(i.get('rules', {}).get(mandate, 0) for i in local if i['id'] != institution['id'])
            remaining = max(0, round(cap - others, 8))
            if fallback['type'] == 'propose':
                proposed = params.get('params', {}).get('value', 0)
                current = institution.get('rules', {}).get(mandate, 0)
                revised = min(proposed, remaining)
                if revised == current:
                    fallback = CommunityPolicy.propose(self, observation)
                    fallback_reason = self.reason
                else:
                    params['params']['value'] = revised
                    fallback_reason = 'Seek only the public mandate capacity remaining after other institutions\' decisions.'
            elif decision['params'].get('value', 0) > remaining + 1e-9:
                if fallback['type'] == 'vote':
                    params['approve'] = False
                    fallback_reason = 'Oppose a policy that exceeds the remaining collective mandate capacity.'
                elif fallback['type'] == 'enact':
                    fallback = CommunityPolicy.propose(self, observation)
                    fallback_reason = self.reason

        choices = []

        def consider(kind, params, score, reason, cost=0):
            if energy < cost or permissions.get(kind, True) is False:
                return
            proposal = {'actor': actor['id'], 'type': kind,
                        'location': town['id'], 'params': params}
            signature = self._signature(proposal)
            for memory in actor.get('memory', [])[-16:]:
                if (memory.get('result', {}).get('success') is False
                        and tick - memory.get('tick', -100) <= 2
                        and memory.get('action')
                        and self._signature(memory['action']) == signature):
                    return
            choices.append((score, proposal, reason))

        score = {'eat': 150 + hunger, 'build': 82, 'research': 68,
                 'accept': 65, 'gather': 53, 'offer': 51, 'teach': 18,
                 'collaborate': 24, 'rest': 12, 'migrate': 72,
                 'wait': 0, 'enact': 84, 'vote': 74, 'propose': 70,
                 'contribute': 64, 'leave_institution': 76}.get(fallback['type'], 0)
        if fallback['type'] == 'gather' and fallback['params'].get('resource') == 'food':
            score = 45 + hunger * .5 + (7 if role == 'farmer' else 0)
        if fallback['type'] == 'rest' and energy < 15:
            score = 110
        mandate = fallback.get('params', {}).get('kind')
        if fallback['type'] in ('enact', 'vote'):
            proposal_id = fallback.get('params', {}).get('proposal')
            mandate = next((d.get('kind') for i in memberships for d in i.get('decisions', [])
                            if d.get('id') == proposal_id), mandate)
        if mandate == 'distribute_food':
            score = {'enact': 94, 'vote': 83, 'propose': 85}.get(fallback['type'], score)
        if inventory.get('food', 0) < 1 and hunger >= 35 and (
                fallback['type'] in ('accept', 'migrate') or fallback['type'] == 'gather'
                and fallback['params'].get('resource') == 'food'):
            score = max(score, 110 + hunger)
        choices.append((score, fallback, fallback_reason))

        secure = inventory.get('food', 0) >= 2 and hunger < 56
        has_preferred = any(i.get('purpose', 'cooperative') == preferred for i in memberships)
        if secure and not has_preferred and len(memberships) < 2:
            candidates = [i for i in local if i.get('purpose', 'cooperative') == preferred]
            for institution in candidates:
                trust = actor.get('trust', {})
                members = institution.get('members', [])
                confidence = sum(_get(trust, person, 0) for person in members) / max(1, len(members))
                if confidence > -.35 and (institution.get('rules', {}).get('tax_rate', 0) == 0
                                           or inventory.get('coins', 0) >= 4):
                    consider('join_institution', {'institution': institution['id']},
                             70 + max(0, confidence) * 4,
                             f'Join a {preferred} whose public purpose serves this person\'s interests.', 1)
            if not candidates and len(observation.get('peers', [])) >= 1 and inventory.get('coins', 0) >= 2:
                base = f'{town["name"]} {PURPOSE_LABELS[preferred]}'
                name, suffix = base, 2
                existing_names = {i['name'] for i in institutions}
                while name in existing_names:
                    name = f'{base} {suffix}'
                    suffix += 1
                consider('form_institution', {'name': name, 'purpose': preferred},
                         65 + (2 if role == 'councillor' else 0),
                         f'Create a {preferred} to pursue local interests with willing members.', 2)

        # A second civic affiliation can build a majority council, but nobody is
        # assigned to it and its public levy may make membership unattractive.
        if secure and memberships and len(memberships) < 2 and preferred != 'council':
            for institution in local:
                if institution.get('purpose') == 'council' and actor['id'] not in institution.get('members', []):
                    if institution.get('rules', {}).get('tax_rate', 0) <= .05:
                        consider('join_institution', {'institution': institution['id']},
                                 59 + openness * 3,
                                 'Seek representation in a council that can influence public policy.', 1)

        def relationship(destination):
            return _get(diplomacy, destination, 0)

        def blocked(institution, destination):
            return _get(institution.get('rules', {}).get('embargoes', {}), destination, False) is True

        def contracted(institution, params):
            for route in regional.get('routes', []):
                if route.get('status') in ('expired', 'cancelled') or route.get('expires', tick) <= tick + 3:
                    continue
                if route.get('resource') != params.get('resource'):
                    continue
                if params.get('direction') == 'import':
                    sponsor, destination = route.get('importer_institution'), route.get('exporter')
                else:
                    sponsor, destination = route.get('exporter_institution'), route.get('importer')
                if sponsor == institution['id'] and destination == params.get('destination'):
                    return True
            return False

        def has_capacity(resource):
            return (town.get(resource, 0) > self._export_reserve(town, resource)
                    or self._advantage(town) == resource)

        def acceptable(institution, params):
            resource, destination = params.get('resource'), params.get('destination')
            if resource not in prices or destination not in neighbors or blocked(institution, destination):
                return False
            price = params.get('unit_price', 0)
            quota = params.get('quota', 0)
            if type(quota) is not int or not 1 <= quota <= 40 or not isinstance(price, (int, float)) or not math.isfinite(price):
                return False
            confidence = relationship(destination)
            if confidence < -.5 and openness < .35:
                return False
            fair = prices[resource]
            if params.get('direction') == 'import':
                useful = town.get(resource, 0) < self._resource_target(town, resource)
                limit = fair * (1.1 + openness * .25 + (pressure * .2 if resource == 'food' else 0)
                                + confidence * .08)
                return useful and .1 <= price <= limit and town.get('treasury', 0) >= min(quota, 2) * price
            if params.get('direction') == 'export':
                minimum = fair * (.9 - openness * .2 - confidence * .08)
                return has_capacity(resource) and price >= max(.1, minimum) and price <= 20
            return False

        def reciprocal_for(institution, decision):
            params = decision.get('params', {})
            for other in institutions:
                if not other.get('active', True) or other['settlement_id'] != params.get('destination'):
                    continue
                for candidate in other.get('decisions', []):
                    terms = candidate.get('params', {})
                    if (candidate.get('kind') == 'trade_terms'
                            and terms.get('destination') == town['id']
                            and terms.get('resource') == params.get('resource')
                            and terms.get('unit_price') == params.get('unit_price')
                            and terms.get('quota') == params.get('quota')
                            and terms.get('direction') != params.get('direction')
                            and not blocked(other, town['id'])
                            and self._approved(candidate, other.get('members', []), tick)):
                        return True
            return False

        for institution in memberships:
            identifier = institution['id']
            purpose = institution.get('purpose', 'cooperative')
            members = institution.get('members', [])
            decisions = [d for d in institution.get('decisions', [])
                         if d.get('status', 'open') == 'open' and d.get('expires', tick + 1) > tick]
            open_kinds = {d.get('kind') for d in decisions}
            political_bonus = 2 if role == 'councillor' else 0
            for decision in decisions:
                kind, params = decision.get('kind'), decision.get('params', {})
                if kind not in REGIONAL_KINDS:
                    continue
                if (self._approved(decision, members, tick)
                        and (kind != 'trade_terms' or reciprocal_for(institution, decision))
                        and (kind != 'trade_terms' or not contracted(institution, params))
                        and (kind != 'migration_policy' or len(members) * 2 > local_count)):
                    consider('enact', {'institution': identifier, 'proposal': decision['id']},
                             87 + political_bonus,
                             'Execute a public mandate whose prior votes and counterpart authority are visible.', 2)
                electorate = set(decision.get('electorate', members)) & set(members)
                if actor['id'] not in electorate or _get(decision.get('votes', {}), actor['id']) is not None:
                    continue
                if kind == 'trade_terms':
                    approve = acceptable(institution, params)
                elif kind == 'embargo':
                    confidence = relationship(params.get('destination'))
                    approve = (confidence < -.35 and openness < .5) if params.get('enabled') else (
                        confidence > -.25 or openness > .65)
                elif kind == 'specialization':
                    resource = params.get('resource')
                    approve = resource == self._advantage(town) or resource == 'food' and pressure > .25
                    if purpose == 'cooperative' and resource != 'food' and pressure > .1:
                        approve = False
                else:
                    approve = (openness > .45 or pressure < .15) if params.get('open') else (
                        openness < .45 and pressure > .2)
                consider('vote', {'institution': identifier, 'proposal': decision['id'], 'approve': approve},
                         78 + political_bonus,
                         'Judge the advertised terms against domestic needs, prices, temperament and foreign relations.')

            if not secure or len(members) < 2:
                continue
            if 'embargo' not in open_kinds:
                for destination in sorted(neighbors):
                    confidence = relationship(destination)
                    embargo = blocked(institution, destination)
                    if not embargo and confidence < -.45 and openness < .4:
                        consider('propose', {'institution': identifier, 'kind': 'embargo',
                                             'params': {'destination': destination, 'enabled': True}},
                                 75, 'Ask members to suspend this organization\'s trade with a distrusted partner.', 1)
                    elif embargo and (confidence > -.15 or openness > .7):
                        consider('propose', {'institution': identifier, 'kind': 'embargo',
                                             'params': {'destination': destination, 'enabled': False}},
                                 73, 'Ask members to reopen institutional trade when its expected benefit improves.', 1)

            if purpose == 'council' and len(members) * 2 > local_count and 'migration_policy' not in open_kinds:
                current = institution.get('rules', {}).get('migration_open', True)
                desired = not (openness < .25 and pressure > .25)
                if desired != current:
                    consider('propose', {'institution': identifier, 'kind': 'migration_policy',
                                         'params': {'open': desired}},
                             74 + political_bonus,
                             'Request a border policy from a council representing a majority of local people.', 1)

            if 'specialization' not in open_kinds:
                resource = 'food' if purpose == 'cooperative' and pressure > .1 else self._advantage(town)
                if institution.get('rules', {}).get('specialization') != resource:
                    consider('propose', {'institution': identifier, 'kind': 'specialization',
                                         'params': {'resource': resource}},
                             67 + political_bonus,
                             'Propose a production emphasis suited to public local endowments and this institution\'s interests.', 1)

            if 'trade_terms' in open_kinds:
                continue
            # A visible foreign request is an offer to negotiate, not consent.
            # This person proposes the matching side only if its terms are useful.
            for other in institutions:
                destination = other['settlement_id']
                if destination not in neighbors or not other.get('active', True):
                    continue
                for decision in other.get('decisions', []):
                    params = decision.get('params', {})
                    if (decision.get('kind') != 'trade_terms' or decision.get('status', 'open') != 'open'
                            or decision.get('expires', tick + 1) <= tick
                            or params.get('destination') != town['id']):
                        continue
                    response = {**params, 'destination': destination,
                                'direction': 'import' if params.get('direction') == 'export' else 'export'}
                    if acceptable(institution, response) and not contracted(institution, response):
                        consider('propose', {'institution': identifier, 'kind': 'trade_terms', 'params': response},
                                 77 + (2 if purpose == 'guild' else 0),
                                 'Offer a matching side to useful public trade terms, subject to an independent local vote.', 1)

            for destination, neighbor in sorted(neighbors.items()):
                if not any(i.get('active', True) and i['settlement_id'] == destination
                           and len(i.get('members', [])) >= 2 for i in institutions):
                    continue
                if blocked(institution, destination) or relationship(destination) < -.5 and openness < .35:
                    continue
                for resource, fair in prices.items():
                    own_need = self._resource_target(town, resource) - town.get(resource, 0)
                    foreign_need = self._resource_target(neighbor, resource) - neighbor.get(resource, 0)
                    if own_need >= 1 and (neighbor.get(resource, 0) > self._export_reserve(neighbor, resource)
                                          or self._advantage(neighbor) == resource):
                        direction, quota = 'import', min(20, max(1, math.ceil(own_need)))
                        scarcity = min(1, own_need / max(1, self._resource_target(town, resource)))
                        price = round(max(.1, fair * (.82 + openness * .2 + scarcity * .18)), 2)
                    elif foreign_need >= 1 and has_capacity(resource):
                        direction, quota = 'export', min(20, max(1, math.ceil(foreign_need)))
                        scarcity = max(0, 1 - town.get(resource, 0) / max(1, self._export_reserve(town, resource)))
                        price = round(max(.1, fair * (1.1 - openness * .2 + scarcity * .1)), 2)
                    else:
                        continue
                    params = {'destination': destination, 'resource': resource,
                              'direction': direction, 'unit_price': price, 'quota': quota}
                    if not acceptable(institution, params) or contracted(institution, params):
                        continue
                    need_bonus = min(4, pressure * 4) if direction == 'import' and resource == 'food' else 0
                    consider('propose', {'institution': identifier, 'kind': 'trade_terms', 'params': params},
                             69 + (3 if purpose == 'guild' else 0) + need_bonus,
                             f'Negotiate {resource} {direction}s from public shortages and independently chosen prices.', 1)

        # Productive migration is an individual decision, not an assignment of
        # workers to a scripted national specialization.
        professional = {'miner': 'iron', 'farmer': 'food', 'builder': 'wood'}.get(role)
        if professional and town.get('population', 0) > 10:
            local_deposit = town.get('deposits', {}).get(professional, 0)
            for destination, neighbor in sorted(neighbors.items()):
                border = _get(regional.get('borders', {}), destination, True)
                if isinstance(border, dict):
                    border = border.get('open', True)
                if border is False or neighbor.get('permissions', {}).get('migrate', True) is False:
                    continue
                deposit = neighbor.get('deposits', {}).get(professional, 0)
                if local_deposit < 1 and deposit >= 4 and inventory.get('food', 0) >= 1:
                    consider('migrate', {'destination': destination},
                             63 + max(0, openness - .5) * 4 - neighbor.get('distance', 0) * .04,
                             f'Move toward accessible {professional} and a better professional opportunity.', 12)

        _, proposal, self.reason = max(choices, key=lambda item: item[0])
        return proposal
