"""Independent, observation-only utility planning for the v0.3 community.

There are no named partners or scheduled decisions. Every person evaluates the
same action vocabulary against their profession, needs, goals and remembered
outcomes. Offers visible in this observation were posted on earlier ticks;
the world, rather than the policy, reserves stock and resolves competing claims.
"""
import json
import math


class CommunityPolicy:
    """Choose one proposal without retaining or mutating a world reference."""

    name = 'independent community utility policy'

    def __init__(self):
        self.reason = ''

    @staticmethod
    def _signature(proposal):
        return json.dumps(proposal, sort_keys=True, separators=(',', ':'))

    def propose(self, observation):
        actor = observation['actor']
        town = observation['settlement']
        inventory = actor['inventory']
        # Reservations are still owned inventory, but cannot be spent twice.
        available = actor.get('available_inventory', inventory)
        peers = sorted(observation.get('peers', []), key=lambda person: person['id'])
        market = sorted(observation.get('market', []), key=lambda offer: offer['id'])
        rules = observation.get('rules', {})
        prices = rules.get('prices', {'food': 1, 'wood': 2, 'iron': 4})
        recipe = rules.get('recipes', {}).get('house', {'wood': 12, 'iron': 2, 'coins': 8})
        gather_limit = rules.get('gather_limit', 8)
        gather_cost = rules.get('gather_energy_per_unit', 2)
        skills = set(actor.get('skills', []))
        permissions = town.get('permissions', {})
        deposits = town.get('deposits', {})
        energy = actor.get('energy', 100)
        hunger = actor.get('hunger', 0)
        role = actor.get('role', '')
        goal = actor.get('goal', {})
        tick = observation.get('tick', observation.get('year', 0))
        coins = available.get('coins', 0)
        total_coins = inventory.get('coins', 0)
        wealth_target = goal.get('target', actor.get('wealth_goal', 60))
        house_target = goal.get('target', 3) if role == 'builder' else 0
        building = role == 'builder' and actor.get('structures', {}).get('house', 0) < house_target
        investigating = role in ('researcher', 'scholar') and actor.get('knowledge', 0) < 2
        has_carpentry = 'carpentry' in skills
        food_target = goal.get('target', 12) if role == 'farmer' else 3
        reserves = {'food': 4 if role == 'farmer' else 2, 'wood': 0, 'iron': 0}
        if building:
            reserves.update(wood=recipe['wood'] + int(not has_carpentry),
                            iron=recipe['iron'] + int(not has_carpentry))
        if investigating:
            reserves['wood'] = max(reserves['wood'], 2)
            reserves['iron'] = max(reserves['iron'], 2)

        def trust(person_id):
            values = actor.get('trust', {})
            return values.get(person_id, values.get(str(person_id), 0))

        people = {person['id']: person for person in peers}
        own_offers = [offer for offer in market if offer['actor'] == actor['id']]
        failed = set()
        for memory in actor.get('memory', [])[-16:]:
            proposal = memory.get('action', memory.get('proposal'))
            result = memory.get('result', {})
            remembered_tick = memory.get('tick', memory.get('year', -100))
            if proposal and result.get('success') is False and tick - remembered_tick <= 2:
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

        consider('wait', {}, 0, 'Preserve supplies while waiting for a useful opportunity.')
        if energy < 100:
            consider('rest', {}, 2 + max(0, 32 - energy) * 3,
                     'Recover energy for gathering, construction or helping another person.')
        if available.get('food', 0) >= 1 and hunger >= 21:
            consider('eat', {}, 90 + hunger,
                     f'Hunger is {hunger:g}; consume one unit of personal food.')

        if building and has_carpentry and all(available.get(resource, 0) >= amount
                                             for resource, amount in recipe.items()):
            labor = min(15, actor.get('labor_credit', 0))
            consider('build', {'structure': 'house'}, 82,
                     f'Use saved materials to advance the goal of {house_target:g} houses.',
                     max(0, 15 - labor))
        topic = 'carpentry' if building and not has_carpentry else 'aether'
        if (investigating or building and not has_carpentry) and all(
                available.get(resource, 0) >= 1 for resource in ('wood', 'iron')):
            consider('research', {'topic': topic}, 68,
                     'Test unusual minerals using personally acquired materials.'
                     if topic == 'aether' else 'Learn the skill required to construct houses.', 10)

        # Accepting a posted price is an independent decision by the other party.
        # Partial fills allow several buyers to compete over a finite offer.
        for offer in market:
            if offer['actor'] == actor['id'] or offer['actor'] not in people:
                continue
            resource = offer.get('resource')
            if resource not in prices:
                continue
            unit_price = offer.get('unit_price', 0)
            remaining = offer.get('amount', 0)
            if unit_price <= 0 or remaining < 1:
                continue
            counterparty = people[offer['actor']]
            confidence = trust(counterparty['id'])
            reputation = counterparty.get('reputation', .5)
            relation_bonus = confidence * 5 + (reputation - .5) * 3
            fair = prices[resource]
            if offer.get('direction') == 'sell':
                missing = max(0, reserves[resource] - available.get(resource, 0))
                if resource == 'food':
                    missing = max(0, (4 if role != 'farmer' else food_target) - available.get('food', 0))
                # Merchants only buy inventory at a discount to a plausible resale
                # price, and only when another visible person could use the good.
                demand = any(
                    person['inventory'].get(resource, 0) <
                    (3 if resource == 'food' else 2 if resource == 'iron' else 12)
                    for person in peers if person['id'] != counterparty['id'])
                speculate = role == 'merchant' and unit_price < fair * .97 and demand
                willingness = fair * (1.4 if resource == 'food' and hunger >= 56 else 1.2)
                willingness *= 1 + max(-.3, confidence * .08)
                if missing <= 0 and not speculate or unit_price > willingness:
                    continue
                coin_reserve = recipe['coins'] if building and resource != 'food' else 0
                budget = max(0, coins - coin_reserve)
                wanted = math.ceil(missing) if missing > 0 else 3
                amount = min(remaining, wanted, math.floor((budget + 1e-8) / unit_price))
                if amount < 1:
                    continue
                if resource == 'food' and missing > 0:
                    score = 53 + hunger * .65 + relation_bonus
                    reason = 'Buy food from a neighbor, preserving time for the personal profession.'
                elif missing > 0:
                    score = 65 + relation_bonus
                    reason = f'Buy missing {resource} from a willing neighbor for the current goal.'
                else:
                    score = 30 + (fair - unit_price) * amount * 5 + relation_bonus
                    reason = f'Buy discounted {resource} where visible demand offers a possible margin.'
                consider('accept', {'offer_id': offer['id'], 'amount': int(amount)}, score, reason, 1)
            elif offer.get('direction') == 'buy':
                surplus = math.floor(available.get(resource, 0) - reserves[resource])
                amount = min(remaining, max(0, surplus))
                minimum = fair * (.75 if role != 'merchant' else 1.02)
                if amount >= 1 and unit_price >= minimum:
                    consider('accept', {'offer_id': offer['id'], 'amount': int(amount)},
                             62 + min(12, amount * unit_price * .25) + relation_bonus,
                             f'Sell surplus {resource} at a posted price without spending reserved supplies.', 1)

        gather_skills = {'food': 'foraging', 'wood': 'woodcutting', 'iron': 'mining'}
        demand = {resource: 0 for resource in prices}
        for person in peers:
            if person['id'] == actor['id']:
                continue
            demand['food'] += max(0, 3 - person['inventory'].get('food', 0))
            if person.get('role') == 'builder' and person.get('structures', {}).get('house', 0) < person.get('goal', {}).get('target', 3):
                demand['wood'] += max(0, recipe['wood'] - person['inventory'].get('wood', 0))
                demand['iron'] += max(0, recipe['iron'] - person['inventory'].get('iron', 0))
            if person.get('role') in ('researcher', 'scholar') and person.get('knowledge', 0) < 2:
                for resource in ('wood', 'iron'):
                    demand[resource] += max(0, 2 - person['inventory'].get(resource, 0))

        active_sell = any(offer.get('direction') == 'sell' for offer in own_offers)
        active_buy = any(offer.get('direction') == 'buy' for offer in own_offers)
        for resource in ('food', 'wood', 'iron'):
            stock = available.get(resource, 0)
            target = food_target if resource == 'food' else reserves[resource]
            missing = max(0, target - stock)
            gatherable = (gather_skills[resource] in skills
                          and permissions.get('gather', True) is not False)
            amount = min(gather_limit, math.floor(deposits.get(resource, 0)),
                         math.floor(energy / gather_cost)) if gatherable else 0
            if amount >= 1:
                if missing > 0:
                    amount = min(amount, math.ceil(missing))
                    score = 45 + (hunger * .5 if resource == 'food' else 8)
                    reason = f'Gather {resource} to secure personal needs and goal prerequisites.'
                    if role == 'farmer' and resource == 'food':
                        score += 7
                else:
                    # Produce for observed demand rather than accumulating goods
                    # indefinitely after every other person has met their goal.
                    professional = resource == {'miner': 'iron', 'farmer': 'food'}.get(role)
                    wants_income = total_coins < wealth_target if role in ('miner', 'merchant') else coins < 16
                    if demand[resource] <= 0 or stock >= 12 or not (professional or wants_income):
                        continue
                    score = 27 + min(10, demand[resource]) + (5 if professional else 0)
                    reason = f'Produce finite {resource} for demand observed among local people.'
                consider('gather', {'resource': resource, 'amount': int(amount)},
                         score, reason, amount * gather_cost)

            if 'trading' not in skills:
                continue
            surplus = max(0, math.floor(stock - reserves[resource]))
            if surplus and not active_sell:
                # A merchant asks for a margin. Producers discount their output;
                # scarcity raises prices while plentiful competing stock lowers it.
                competing = sum(offer.get('amount', 0) for offer in market
                                if offer.get('direction') == 'sell' and offer.get('resource') == resource)
                factor = 1.08 if role == 'merchant' else .88
                factor += min(.10, demand[resource] * .005)
                factor -= min(.10, competing * .01)
                average_trust = sum(trust(person['id']) for person in peers) / max(1, len(peers))
                factor -= max(0, average_trust) * .04
                price = round(max(.1, prices[resource] * factor), 2)
                amount = min(4, surplus)
                if demand[resource] > 0:
                    score = 49 + min(8, demand[resource])
                    if role == 'merchant':
                        score += 4
                    consider('offer', {'resource': resource, 'amount': int(amount),
                                       'unit_price': price, 'direction': 'sell'}, score,
                             f'Offer surplus {resource} at {price:g} coins each; local demand and trust affect the price.')

            # A public bid invites a producer to supply otherwise inaccessible
            # inputs. Coins are reserved by the resolver, never by this policy.
            if missing > 0 and not active_buy and (not gatherable or deposits.get(resource, 0) < 1):
                price = round(prices[resource] * .95, 2)
                budget = max(0, coins - (recipe['coins'] if building and resource != 'food' else 0))
                amount = min(4, math.ceil(missing), math.floor((budget + 1e-8) / price))
                if amount >= 1:
                    score = (51 + hunger * .35) if resource == 'food' else 48
                    consider('offer', {'resource': resource, 'amount': int(amount),
                                       'unit_price': price, 'direction': 'buy'}, score,
                             f'Post a funded request for {resource} that this person cannot obtain locally.')

        for person in peers:
            if person['id'] == actor['id']:
                continue
            confidence = trust(person['id'])
            relationship = 1 + max(0, confidence) * 7
            if actor.get('knowledge', 0) > person.get('knowledge', 0):
                consider('teach', {'target': person['id'], 'topic': 'aether'},
                         12 + relationship + actor.get('curiosity', .5) * 4,
                         f'Share tested mineral knowledge with {person["name"]}; trust makes teaching more worthwhile.', 5)
            if has_carpentry and 'carpentry' not in person.get('skills', []):
                consider('teach', {'target': person['id'], 'topic': 'carpentry'},
                         8 + relationship,
                         f'Pass construction knowledge to {person["name"]} through practical teaching.', 5)
            if (person.get('role') == 'builder'
                    and person.get('structures', {}).get('house', 0) < person.get('goal', {}).get('target', 3)
                    and person.get('labor_credit', 0) < 15 and confidence > -.3):
                own_goal_met = (not building and not investigating and
                                (role not in ('miner', 'merchant') or total_coins >= wealth_target))
                consider('collaborate', {'target': person['id']},
                         (22 if own_goal_met else 7) + relationship,
                         f'Help {person["name"]} with construction to strengthen a useful local relationship.', 5)

        # Survival migration is independent of wealth: completed economic goals
        # must never make someone ignore an exhausted local food supply.
        food_offers = {offer['id'] for offer in market
                       if offer.get('resource') == 'food' and offer.get('direction') == 'sell'}
        can_buy_food = any(proposal['type'] == 'accept'
                           and proposal['params'].get('offer_id') in food_offers
                           for _, proposal, _ in choices)
        no_local_food = (available.get('food', 0) < 1 and not can_buy_food
                         and (not permissions.get('gather', True) or deposits.get('food', 0) < 1))
        if town.get('population', 0) > 10:
            for other in sorted(observation.get('neighbors', []), key=lambda place: place['id']):
                other_permissions = other.get('permissions', {})
                if other.get('distance', 0) > 38 or other_permissions.get('migrate', True) is False:
                    continue
                remote_food = other.get('deposits', {}).get('food', 0)
                if no_local_food and remote_food >= 2 and other_permissions.get('gather', True):
                    consider('migrate', {'destination': other['id']},
                             72 + hunger * .45 - other.get('distance', 0) * .05,
                             f'Move to {other["name"]} because accessible food is exhausted here.', 12)
                elif role == 'miner' and total_coins < wealth_target and deposits.get('iron', 0) < 1:
                    if other.get('deposits', {}).get('iron', 0) >= 4:
                        consider('migrate', {'destination': other['id']},
                                 24 - other.get('distance', 0) * .05,
                                 f'Seek accessible mineral deposits in {other["name"]} after local depletion.', 12)

        if not choices:
            self.reason = 'No feasible action is visible under current permissions and resources.'
            return {'actor': actor['id'], 'type': 'wait', 'location': town['id'], 'params': {}}
        _, proposal, self.reason = max(choices, key=lambda choice: choice[0])
        return proposal
