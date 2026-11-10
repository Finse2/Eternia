"""Voluntary collective action driven by public conditions and personal costs.

This planner knows its own resources and a member's shared accounts. Other
people's holdings, knowledge, private preferences and future votes are unknown.
"""
import math

from .society_policy import CommunityPolicy


class InstitutionalPolicy(CommunityPolicy):
    name = 'individual utility with voluntary institutions'

    def propose(self, observation):
        fallback = super().propose(observation)
        fallback_reason = self.reason
        actor, town = observation['actor'], observation['settlement']
        inventory = actor.get('available_inventory', actor['inventory'])
        hunger, energy = actor.get('hunger', 0), actor.get('energy', 100)
        tick = observation.get('tick', 0)
        role = actor.get('role', '')
        skills = set(actor.get('skills', []))
        permissions = town.get('permissions', {})
        peers = observation.get('peers', [])
        institutions = sorted(observation.get('institutions', []), key=lambda i: i['id'])
        local = [i for i in institutions if i.get('active', True) and i['settlement_id'] == town['id']]
        memberships = [i for i in local if actor['id'] in i.get('members', [])]
        population = max(1, town.get('population', 1))
        food_pressure = max(0, 1 - town.get('food', 0) / population)
        crowded = town.get('deposits', {}).get('food', 0) < max(4, 4 * len(peers))
        recent_rejections = sum(m.get('result', {}).get('success') is False
                                for m in actor.get('memory', [])[-12:])
        choices = []

        def consider(kind, params, score, reason, cost=0):
            if energy < cost or permissions.get(kind, True) is False:
                return
            proposal = {'actor': actor['id'], 'type': kind,
                        'location': town['id'], 'params': params}
            signature = self._signature(proposal)
            for memory in actor.get('memory', [])[-12:]:
                if (memory.get('result', {}).get('success') is False
                        and tick - memory.get('tick', -100) <= 2
                        and memory.get('action')
                        and self._signature(memory['action']) == signature):
                    return
            choices.append((score, proposal, reason))

        # Food and acute fatigue outrank collective projects. A stocked person
        # can spend this cycle on institutions without knowing a peer's stock.
        fallback_score = {'eat': 150 + hunger, 'build': 82, 'research': 68,
                          'accept': 65, 'gather': 53, 'offer': 51,
                          'teach': 18, 'collaborate': 24, 'rest': 12,
                          'migrate': 72, 'wait': 0}.get(fallback['type'], 0)
        if fallback['type'] == 'gather' and fallback['params'].get('resource') == 'food':
            fallback_score = 45 + hunger * .5 + (7 if role == 'farmer' else 0)
        if fallback['type'] == 'accept':
            offer_id = fallback['params'].get('offer_id')
            offer = next((o for o in observation.get('market', []) if o['id'] == offer_id), {})
            if offer.get('resource') == 'food':
                fallback_score = 53 + hunger * .65
        if fallback['type'] == 'rest' and energy < 15:
            fallback_score = 110
        if (inventory.get('food', 0) < 1 and hunger >= 35
                and (fallback['type'] in ('accept', 'migrate')
                     or fallback['type'] == 'gather' and fallback['params'].get('resource') == 'food')):
            fallback_score = max(fallback_score, 110 + hunger)
        choices.append((fallback_score, fallback, fallback_reason))

        secure_food = inventory.get('food', 0) >= 2 and hunger < 56
        if secure_food and not memberships:
            for institution in local:
                if institution.get('rules', {}).get('tax_rate', 0) > 0 and inventory.get('coins', 0) < 4:
                    continue
                trust = actor.get('trust', {})
                members = institution.get('members', [])
                confidence = sum(trust.get(i, trust.get(str(i), 0)) for i in members) / max(1, len(members))
                if confidence > -.3:
                    consider('join_institution', {'institution': institution['id']},
                             60 + max(0, confidence) * 4,
                             'Join a local cooperative to share the cost of food security and public projects.', 1)
            if (not local and len(peers) >= 2 and inventory.get('coins', 0) >= 4
                    and (food_pressure > .1 or crowded or recent_rejections >= 2)):
                base_name = town['name'] + ' Cooperative'
                existing_names = {i['name'] for i in institutions}
                name, number = base_name, 2
                while name in existing_names:
                    name = f'{base_name} {number}'
                    number += 1
                consider('form_institution', {'name': name},
                         61 + min(4, recent_rejections),
                         'Repeated pressure on shared supplies makes a voluntary cooperative worth its founding cost.', 2)

        reserves = {'food': 3, 'wood': 0, 'iron': 0, 'coins': 4}
        if role == 'builder' and actor.get('structures', {}).get('house', 0) < actor.get('goal', {}).get('target', 3):
            reserves.update(wood=12, iron=2, coins=8)
        if role in ('researcher', 'scholar') and actor.get('knowledge', 0) < 2:
            reserves.update(wood=2, iron=2)

        for institution in memberships:
            identifier = institution['id']
            members = institution.get('members', [])
            rules = institution.get('rules', {})
            decisions = [d for d in institution.get('decisions', [])
                         if d.get('status', 'open') == 'open' and d.get('expires', tick + 1) > tick]
            shared = {**institution.get('inventory', {}), 'coins': institution.get('treasury', 0)}
            available_shared = institution.get('available_inventory', shared)
            shared_food = available_shared.get('food', 0)
            food_deficit = max(0, population - town.get('food', 0))
            granary = town.get('buildings', {}).get('granary', 0)
            costs = {'wood': 10, 'iron': 2, 'coins': 6}
            funded = all(shared.get(r, 0) >= quantity for r, quantity in costs.items())
            trust = actor.get('trust', {})
            partners = [person for person in members if person != actor['id']]
            confidence = sum(trust.get(person, trust.get(str(person), 0)) for person in partners) / max(1, len(partners))
            solo_burden = (len(members) < 2 and rules.get('tax_rate', 0) > 0
                           and inventory.get('coins', 0) < 8 and shared['coins'] >= 12
                           and tick - institution.get('founded', tick) >= 12)
            if confidence < -.45 or solo_burden:
                consider('leave_institution', {'institution': identifier},
                         88 if confidence < -.45 else 74,
                         'Leave an organization whose partners are distrusted or whose levy no longer buys meaningful collective authority.')

            def old_majority(decision, current_members):
                electorate = set(decision.get('electorate', current_members)) & set(current_members)
                votes = decision.get('votes', {})
                yes = sum(votes.get(person, votes.get(str(person), {})).get('approve') is True
                          and votes.get(person, votes.get(str(person), {})).get('tick', tick) < tick
                          for person in electorate)
                return (decision.get('status', 'open') == 'open'
                        and decision.get('created', tick) < tick < decision.get('expires', tick + 1)
                        and len(electorate) >= 2 and yes >= 2 and yes > len(electorate) / 2)

            def food_mandate(params, electorate):
                amount = params.get('amount', 0)
                valid_amount = (type(amount) in (int, float) and 0 < amount <= 1000
                                and (type(amount) is int or math.isfinite(amount)))
                destination = params.get('destination')
                member = params.get('member')
                eligible = (destination == 'settlement' or destination == 'member'
                            and type(member) is int and member in members and member in electorate)
                return valid_amount and eligible and amount <= shared_food

            for decision in decisions:
                electorate = set(decision.get('electorate', members)) & set(members)
                votes = {int(voter): vote for voter, vote in decision.get('votes', {}).items()
                         if int(voter) in electorate}
                reciprocal = decision.get('kind') != 'trade_agreement' or any(
                    other.get('active', True)
                    and other['settlement_id'] == decision.get('params', {}).get('destination')
                    and any(d.get('kind') == 'trade_agreement'
                            and d.get('params', {}).get('destination') == town['id']
                            and old_majority(d, other.get('members', []))
                            for d in other.get('decisions', []))
                    for other in institutions)
                food_ready = (decision.get('kind') != 'distribute_food'
                              or food_mandate(decision.get('params', {}), electorate))
                if old_majority(decision, members) and reciprocal and food_ready:
                    consider('enact', {'institution': identifier, 'proposal': decision['id']},
                             90 if decision.get('kind') == 'distribute_food' else 79,
                             'Release existing communal food under a previously approved mandate.'
                             if decision.get('kind') == 'distribute_food' else
                             'Carry out a previously approved collective decision through the world rules.', 2)
                if actor['id'] not in electorate or actor['id'] in votes:
                    continue
                kind, params = decision.get('kind'), decision.get('params', {})
                if kind == 'granary':
                    approve = funded and not granary
                elif kind == 'tax_rate':
                    approve = params.get('value', 0) == 0 or params.get('value', 0) <= .08 and inventory.get('coins', 0) > 6
                elif kind == 'communal_labor':
                    approve = params.get('value', 0) <= .25 and (food_pressure > 0 or crowded)
                elif kind == 'trade_agreement':
                    destination = params.get('destination')
                    neighbor = next((n for n in observation.get('neighbors', []) if n['id'] == destination), None)
                    reciprocal_request = any(other['settlement_id'] == destination
                                             and any(d.get('kind') == 'trade_agreement'
                                                     and d.get('params', {}).get('destination') == town['id']
                                                     and d.get('status', 'open') == 'open'
                                                     for d in other.get('decisions', []))
                                             for other in institutions)
                    approve = bool(neighbor) and (reciprocal_request or role in ('merchant', 'farmer', 'miner'))
                elif kind == 'distribute_food':
                    target = params.get('member')
                    amount = params.get('amount', 0)
                    if params.get('destination') == 'settlement':
                        useful = 0 < amount <= food_deficit
                    else:
                        target_trust = trust.get(target, trust.get(str(target), 0))
                        useful = (inventory.get('food', 0) < 3 if target == actor['id']
                                  else amount <= 3 and target_trust > -.3)
                    approve = food_mandate(params, electorate) and useful
                else:
                    approve = False
                consider('vote', {'institution': identifier, 'proposal': decision['id'], 'approve': approve},
                         83 if kind == 'distribute_food' else 73,
                         'Vote on a funded food release from the public shortage or a bounded member request.'
                         if kind == 'distribute_food' else
                         'Vote from personal affordability and the expected local benefit of this proposal.', 1)

            open_kinds = {d.get('kind') for d in decisions}
            if len(members) >= 2 and shared_food >= .1 and 'distribute_food' not in open_kinds:
                if inventory.get('food', 0) < 2 and shared_food >= 1:
                    amount = min(3 - inventory.get('food', 0), math.floor(shared_food))
                    consider('propose', {'institution': identifier, 'kind': 'distribute_food',
                                         'params': {'destination': 'member', 'member': actor['id'],
                                                    'amount': amount}},
                             85, 'Request a bounded share of communal food before personal reserves run out.', 1)
                elif food_deficit >= .1:
                    amount = min(1000, food_deficit, shared_food)
                    consider('propose', {'institution': identifier, 'kind': 'distribute_food',
                                         'params': {'destination': 'settlement', 'amount': amount}},
                             81 + min(6, food_pressure * 6),
                             'Ask members to release existing pooled food into the settlement food supply.', 1)

            if not secure_food:
                continue
            # Pool only a bounded surplus above the personal food goal. Keeping
            # the pool near its next useful release avoids deposit/withdraw loops.
            personal_food_reserve = max(reserves['food'], actor.get('goal', {}).get('target', 12)
                                        if role == 'farmer' else reserves['food'])
            relief_target = min(4, food_deficit)
            relief_missing = max(0, relief_target - shared_food)
            food_surplus = max(0, inventory.get('food', 0) - personal_food_reserve)
            food_contribution = min(4, relief_missing, food_surplus)
            if food_contribution >= .1:
                consider('contribute', {'institution': identifier, 'resource': 'food',
                                       'amount': food_contribution},
                         65, 'Pool a personal food surplus for an observed settlement shortage.', 1)
            if not granary:
                for resource, quantity in costs.items():
                    missing = max(0, quantity - shared.get(resource, 0))
                    surplus = max(0, inventory.get(resource, 0) - reserves.get(resource, 0))
                    amount = min(4 if resource == 'wood' else 2, missing, math.floor(surplus))
                    if amount >= 1:
                        consider('contribute', {'institution': identifier, 'resource': resource, 'amount': amount},
                                 64, 'Contribute a bounded personal surplus toward a communal granary.', 1)
                    if resource in ('wood', 'iron') and missing > 0:
                        skill = 'woodcutting' if resource == 'wood' else 'mining'
                        gatherable = min(4, math.ceil(missing), math.floor(town.get('deposits', {}).get(resource, 0)), math.floor(energy / 2))
                        if skill in skills and gatherable > 0 and surplus < missing:
                            consider('gather', {'resource': resource, 'amount': gatherable},
                                     57, 'Gather a finite material needed for the cooperative project.', gatherable * 2)
                        for offer in observation.get('market', []):
                            if offer.get('resource') != resource or offer.get('direction') != 'sell' or offer['actor'] == actor['id']:
                                continue
                            price = offer.get('unit_price', 0)
                            affordable = math.floor(max(0, inventory.get('coins', 0) - reserves['coins']) / price) if price > 0 else 0
                            amount = min(2, math.ceil(missing), offer.get('amount', 0), affordable)
                            if amount >= 1 and surplus < missing:
                                consider('accept', {'offer_id': offer['id'], 'amount': amount},
                                         58, 'Purchase a project input from a public offer before contributing it.', 1)

            if len(members) >= 2:
                if rules.get('tax_rate', 0) > 0 and shared['coins'] >= 12 and 'tax_rate' not in open_kinds:
                    consider('propose', {'institution': identifier, 'kind': 'tax_rate', 'params': {'value': 0}},
                             74, 'Propose ending the membership levy now that the project coin cost and a reserve are funded.', 1)
                if funded and not granary and 'granary' not in open_kinds:
                    consider('propose', {'institution': identifier, 'kind': 'granary', 'params': {}},
                             72, 'Ask fellow members to authorize a funded communal granary.', 2)
                if (food_pressure > 0 or crowded) and rules.get('communal_labor', 0) < .15 and 'communal_labor' not in open_kinds:
                    consider('propose', {'institution': identifier, 'kind': 'communal_labor', 'params': {'value': .2}},
                             67, 'Ask members to reallocate a limited share of communal labor toward food.', 2)
                if not granary and shared['coins'] < 6 and rules.get('tax_rate', 0) == 0 and inventory.get('coins', 0) > 8 and 'tax_rate' not in open_kinds:
                    consider('propose', {'institution': identifier, 'kind': 'tax_rate', 'params': {'value': .04}},
                             62, 'Propose a small membership levy to fund projects with existing member coins.', 2)
                if 'trade_agreement' not in open_kinds:
                    for neighbor in sorted(observation.get('neighbors', []), key=lambda n: n['id']):
                        counterpart = [other for other in institutions
                                       if other.get('active', True) and other['settlement_id'] == neighbor['id']
                                       and len(other.get('members', [])) >= 2]
                        if not counterpart or town.get('relations', {}).get(neighbor['id'], town.get('relations', {}).get(str(neighbor['id']))) == 'trade':
                            continue
                        request = any(d.get('kind') == 'trade_agreement'
                                      and d.get('params', {}).get('destination') == town['id']
                                      and d.get('status', 'open') == 'open'
                                      for other in counterpart for d in other.get('decisions', []))
                        complementary = (town.get('food', 0) / population < 1.12
                                         and neighbor.get('food', 0) > neighbor.get('population', 0) * 1.12)
                        if request or complementary or role in ('merchant', 'farmer'):
                            consider('propose', {'institution': identifier, 'kind': 'trade_agreement',
                                                 'params': {'destination': neighbor['id']}},
                                     66 + int(request) * 3,
                                     'Propose reciprocal market access with a reachable organization offering useful trade opportunities.', 1)

        _, proposal, self.reason = max(choices, key=lambda choice: choice[0])
        return proposal
