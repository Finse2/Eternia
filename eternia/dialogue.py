"""v0.8 Stage 3: conversations grounded in what each person actually knows.

Every answer is a pure function of the speaker's own observation (the same
detached view their policy decides from, including their memories, motives,
trust and the claims they have heard) and the listener's public identity.
Nothing else is passed in, so a speaker cannot reveal another person's
holdings, buried reserves or anything else they have no way to know.

Answers depend on who is speaking: their skills and role, what they want, how
fairly they feel treated, their temperament and how much they trust the
listener. They can be unsure, decline, or explain how they would vote and why,
using the same criteria their own policy votes by. Structured text, no
language model: the same question in the same world always gets the same answer.
"""
from .economic_policy import EconomicPolicy, WARY_OF_EMPLOYER, WARY_OF_GROUP, confidence, market_view
from .goal_engine import describe_goal
from .institution_policy import levy_vote
from .market import BID_SHARE, bid_price
from .social_memory import describe, provenance

GOODS = ('food', 'wood', 'iron')
SKILL_FOR = {'food': 'foraging', 'wood': 'woodcutting', 'iron': 'mining'}
TOPICS = ('work', 'news', 'trade', 'politics', 'themselves', 'person', 'proposal',
          'work_for_you', 'join', 'teach', 'tell')
NOTABLE = ('arrival', 'famine', 'caravan_loss', 'delivery', 'death', 'agreement', 'player')
DECISION_WORDS = {'tax_rate': 'a levy', 'work_order': 'public work', 'commission': 'a paid commission',
                  'distribute_food': 'a food release', 'granary': 'a communal granary',
                  'trade_terms': 'a trade contract', 'communal_labor': 'communal labor',
                  'specialization': 'a specialization', 'migration_policy': 'a migration rule',
                  'embargo': 'an embargo', 'repair_route': 'a road repair', 'route_access': 'a road closure'}


def money(value):
    return f'{round(value, 2):g}'


def _get(mapping, key, default=None):
    return mapping.get(key, mapping.get(str(key), default))


class _Speaker:
    """What one person knows about themselves and the listener, from their observation alone."""

    def __init__(self, observation, listener):
        self.o, self.me = observation, observation['actor']
        self.listener = listener
        self.town = observation['settlement']
        self.mind = self.me.get('mind') or {}
        self.motives = self.mind.get('motivations', {})
        self.trust = _get(self.me.get('trust', {}), listener['id'], 0.)
        self.openness = self.me.get('openness', .5)
        self.claims = self.me.get('claims', [])
        self.now = observation.get('tick', 0)
        self.people = {p['id']: p['name'] for p in observation.get('peers', [])}
        self.people[listener['id']] = listener['name']
        self.towns = {self.town['id']: self.town['name'], **{n['id']: n['name'] for n in observation.get('neighbors', [])}}
        prices = observation.get('prices', {})
        self.local = prices.get('posted', {}).get(self.town['id'], {})
        self.share = prices.get('bid_share', BID_SHARE)

    @property
    def wary(self):
        return self.trust <= WARY_OF_EMPLOYER

    def confides(self):
        """Talking about oneself depends on temperament and how well one knows the listener."""
        return self.trust >= .15 - .3 * self.openness

    def bid(self, good):
        return bid_price(self.local[good]) if good in self.local else 0.

    def about(self, claim):
        return f'{describe(claim, speaker=self.me["id"])} ({provenance(claim, self.now)})'

    def heard(self, kinds=None, subject=None, *, exclude_listener=True):
        out = [c for c in self.claims if (kinds is None or c['kind'] in kinds)
               and (subject is None or c.get('subject') == subject)
               and not (exclude_listener and c.get('subject') == self.listener['id'] and subject is None)]
        return sorted(out, key=lambda c: (-c['observed'], -c['confidence'], str(c['key'])))

    def opening(self):
        if self.trust <= -.2:
            return f'{self.me["name"]} looks wary of you.'
        if self.trust >= .2:
            return f'{self.me["name"]} greets you warmly.'
        return None


def respond(observation, topic, args, listener):
    """The speaker's answer: lines of speech, any claims passed to the listener, and a stance if asked."""
    if topic not in TOPICS:
        raise ValueError(f'Ask about one of: {", ".join(TOPICS)}.')
    speaker = _Speaker(observation, listener)
    reply = dict(speaker=speaker.me['id'], speaker_name=speaker.me['name'], topic=topic, args=dict(args),
                 lines=[], tells=[], stance=None, declined=False)
    if speaker.opening():
        reply['lines'].append(speaker.opening())
    if speaker.trust <= -.5 and topic not in ('tell',):
        reply['lines'].append('"I have nothing to say to you."')
        reply['declined'] = True
        return reply
    HANDLERS[topic](speaker, args, reply)
    return reply


def say(reply, text):
    reply['lines'].append(f'"{text}"')


# ----- Topics ---------------------------------------------------------------

def _work(s, args, reply):
    skills, me = set(s.me.get('skills', [])), s.me['id']
    orders = s.o.get('municipality', {}).get('work_orders', [])
    names = {i['id']: i['name'] for i in s.o.get('institutions', [])}
    mine = [o for o in orders if o['employer'] == {'kind': 'person', 'id': me}]
    for order in mine:
        say(reply, f'I\'m paying {money(order["unit_wage"])} a unit for {order["remaining"]} more '
                   f'{order["resource"]}, if you can gather it.')
    others = [o for o in orders if o not in mine]
    for order in others[:3]:
        employer = order['employer']
        who = (f'the {s.town["name"]} council' if employer['kind'] == 'municipal'
               else names.get(employer['id'], 'an organization') if employer['kind'] == 'institution'
               else s.people.get(employer['id'], 'someone'))
        line = f'{who} pays {money(order["unit_wage"])} a unit for {order["remaining"]} {order["resource"]}'
        if SKILL_FOR[order['resource']] not in skills:
            line += ', but I can\'t do that work.'
        elif _worth(s, order['resource'], order['unit_wage'], min(8, order['remaining'])):
            line += '. Worth it to me: it beats gathering and selling.'
        else:
            line += f'. Not worth it to me: the market pays {money(s.bid(order["resource"]))} for the same.'
        say(reply, line)
    if not orders:
        say(reply, 'Nobody here is paying for work right now, as far as I can see.')
    board = [o for o in s.o.get('municipality', {}).get('job_board', []) if o['settlement'] != s.town['id']]
    for order in sorted(board, key=lambda o: -o['unit_wage'])[:2]:
        say(reply, f'There\'s a notice from {s.towns.get(order["settlement"], "a neighbor")}: '
                   f'{order["remaining"]} {order["resource"]} at {money(order["unit_wage"])} a unit.')
    for claim in s.heard(('conduct',))[:2]:
        if claim['facts'].get('act') in ('underpaid', 'paid_fairly'):
            say(reply, s.about(claim)[0].upper() + s.about(claim)[1:] + '.')
            reply['tells'].append(claim)


def _worth(s, good, wage, amount):
    """The speaker's own rule for paid work: decline when gathering and selling pays more."""
    bid = s.bid(good)
    if bid <= 0:
        return True
    sellable = min(amount, int((s.town.get('treasury', 0) + 1e-9) // bid))
    return not sellable * bid / 2 > amount * wage + 1e-9


def _trade(s, args, reply):
    if s.local:
        say(reply, 'Here, ' + '; '.join(f'{g} sells for {money(s.local[g])} and the market pays {money(s.bid(g))}'
                                        for g in GOODS) + '.')
    best = None
    for neighbor in s.o.get('neighbors', []):
        there = s.o.get('prices', {}).get('posted', {}).get(neighbor['id'], {})
        for good in GOODS:
            if good in there and good in s.local:
                gap = bid_price(there[good]) - s.local[good]
                if best is None or gap > best[0]:
                    best = (gap, neighbor['name'], good, bid_price(there[good]))
    if best and best[0] > 0:
        say(reply, f'{best[1]} pays {money(best[3])} for {best[2]}, more than it costs here, '
                   'if you can get it there.')
    elif best:
        say(reply, 'Prices are much the same in the towns around here.')
    links = [l for l in s.o.get('physical', {}).get('links', []) if s.town['id'] in (l['a'], l['b'])]
    for link in links:
        other = s.towns.get(link['b'] if link['a'] == s.town['id'] else link['a'], 'a neighbor')
        if link.get('closed'):
            say(reply, f'The road to {other} is closed.')
        elif link.get('condition', 1) < .7:
            say(reply, f'The {link["terrain"]} road to {other} is in poor repair.')
    losses = s.heard(('shipment',))
    for claim in losses[:2]:
        say(reply, s.about(claim)[0].upper() + s.about(claim)[1:] + '.')
        reply['tells'].append(claim)
    if not losses and links:
        say(reply, 'I haven\'t heard of anything lost on the roads lately.')
    inventory, food = s.me['inventory'], s.local.get('food')
    if food is not None:
        dear = food >= 1.25
        if dear and inventory.get('food', 0) >= 6:
            say(reply, 'Food is dear here, which suits anyone with food to sell.')
        elif dear:
            say(reply, 'Food is dear here, and that is hard on people like me.')
        elif inventory.get('food', 0) >= 6:
            say(reply, 'Food is cheap here; selling it barely pays.')
    for memory in reversed(s.me.get('memory', [])):
        if memory.get('kind') == 'consignment':
            gain = memory.get('gain', 0)
            fate = 'arrived' if memory.get('outcome') == 'delivered' else 'was lost'
            say(reply, f'My last shipment {fate}; I {"made" if gain >= 0 else "lost"} {money(abs(gain))} coins on it.')
            break


def _news(s, args, reply):
    def notable(event):
        if event.get('kind') == 'agreement':
            return s.town['name'] in event.get('message', '')
        about_listener = event.get('actor_id') == s.listener['id'] or event.get('agent') == s.listener['name']
        return event.get('kind') in NOTABLE and event.get('settlement') == s.town['name'] and not about_listener

    seen = [e for e in s.o.get('recent_events', []) if notable(e)]
    for event in seen[-3:]:
        say(reply, f'I saw it here: {event["message"]}')
        thought = _interpret(s, event)
        if thought:
            say(reply, thought)
    shared = s.heard()[:3]
    for claim in shared:
        say(reply, s.about(claim)[0].upper() + s.about(claim)[1:] + '.')
        reply['tells'].append(claim)
    if not seen and not shared:
        say(reply, 'Nothing much has happened that I know of.')


def _interpret(s, event):
    """The same event means different things to different people."""
    kind, wealth = event.get('kind'), s.motives.get('wealth', .5)
    belonging = s.motives.get('belonging', .4)
    if kind == 'famine':
        return ('We could be next; I keep food put by.' if s.motives.get('security', .5) >= .5
                else 'Hard times there; it may mean good prices for food.')
    if kind == 'arrival':
        return ('New hands are welcome here.' if s.openness >= .5 else 'Another mouth to feed, if you ask me.')
    if kind == 'caravan_loss':
        return ('The roads are risky; I would not trust much to them.' if s.motives.get('security', .5) >= .5
                else 'A loss, but trade has to go on.')
    if kind == 'death':
        return 'We miss them.' if belonging >= .5 else None
    if kind == 'delivery':
        return 'Trade keeps the stores full.' if wealth >= .5 else None
    return None


def _politics(s, args, reply):
    me = s.me['id']
    mine = [i for i in s.o.get('institutions', []) if me in i.get('members', []) and i.get('active', True)]
    fairness = s.mind.get('fairness', .5)
    if fairness < .4:
        say(reply, 'This town does not treat people like me fairly.')
    elif fairness > .55:
        say(reply, 'On the whole the town treats people like me fairly.')
    if not mine:
        say(reply, 'I\'m not a member of any organization, so I have no say in their decisions.')
    for institution in mine:
        rate = institution.get('rules', {}).get('tax_rate', 0)
        say(reply, f'I belong to {institution["name"]}' + (f', which levies {rate:.0%} of members\' coins.' if rate else '.'))
        for decision in institution.get('decisions', []):
            if decision.get('status') == 'open' and decision.get('expires', 0) > s.now:
                stance = stance_on(s, institution, decision)
                say(reply, stance['text'])
    if not s.confides():
        return
    goal = s.me.get('goal', {})
    if goal.get('kind') == 'influence':
        say(reply, 'I mean to see public decisions carried through.')


def _themselves(s, args, reply):
    me, inventory = s.me, s.me['inventory']
    if me.get('hunger', 0) >= 65:
        say(reply, 'I\'m hungry, to be honest.')
    if not s.confides():
        say(reply, 'I\'d rather keep my own affairs to myself with someone I barely know.')
        reply['declined'] = True
        return
    goal = me.get('goal', {})
    if goal.get('kind'):
        since = s.mind.get('goal_since')
        say(reply, f'I\'m trying to {describe_goal(goal)}' + (f', since {_ago(s.now - since)}.' if since is not None else '.'))
    history = s.mind.get('history', [])
    if history:
        last = history[-1]
        word = 'managed' if last.get('outcome') == 'completed' else 'gave up trying'
        say(reply, f'Before that I {word} to {describe_goal(last.get("goal", {}))}.')
    if s.motives:
        top = max(s.motives, key=s.motives.get)
        say(reply, {'security': 'What matters most to me is being safe from want.',
                    'wealth': 'I want to be well off.', 'belonging': 'My neighbors matter most to me.',
                    'curiosity': 'I want to understand how things work.',
                    'influence': 'I want a say in how this town is run.',
                    'legacy': 'I want to leave something behind.'}[top])
    if inventory.get('food', 0) < 2 and me.get('hunger', 0) < 65:
        say(reply, 'My food is running low.')


def _ago(cycles):
    return 'this season' if cycles <= 0 else 'last season' if cycles == 1 else \
        f'{cycles} seasons ago' if cycles < 8 else f'about {cycles // 4} years ago'


def _person(s, args, reply):
    target = args.get('person')
    if s.wary:
        say(reply, 'I won\'t discuss my neighbors with you.')
        reply['declined'] = True
        return
    you = target == s.listener['id']
    name = 'you' if you else s.people.get(target) or next(
        (c.get('subject_name') for c in s.claims if c.get('subject') == target), None)
    if name is None:
        say(reply, 'I don\'t know them.')
        return
    regard = _get(s.me.get('trust', {}), target, 0.)
    feeling = ('I trust {0}.' if regard >= .2 else 'I don\'t trust {0}.' if regard <= -.2 else
               'I\'ve no strong feelings about {0}.' if abs(regard) >= .03 else 'I don\'t know {0} well.')
    say(reply, feeling.format(name))
    for claim in s.heard(subject=target, exclude_listener=False)[:3]:
        text = s.about(claim)
        say(reply, text[0].upper() + text[1:] + '.')
        if not you:
            reply['tells'].append(claim)


def stance_on(s, institution, decision):
    """How the speaker would vote and why, by the same criteria their policy votes with."""
    me, kind, params = s.me['id'], decision['kind'], decision.get('params', {})
    vote = _get(decision.get('votes', {}), me)
    words = DECISION_WORDS.get(kind, kind.replace('_', ' '))
    label = f'proposal {decision["id"]} ({words})'
    if vote is not None:
        side = 'for' if vote.get('approve') else 'against'
        return dict(side=side, voted=True, reasons=[], text=f'I voted {side} {label}.')
    if me not in decision.get('electorate', []):
        return dict(side=None, voted=False, reasons=['not in the electorate'],
                    text=f'I can\'t vote on {label}; I wasn\'t a member when it was tabled.')
    town, shared = s.town, institution.get('available_inventory', {})
    side, reasons = None, []
    if kind == 'tax_rate':
        market = market_view(s.o)
        standing = EconomicPolicy._standing(s.o, market) if market else None
        if standing and s.mind:
            value, current = params.get('value', 0), institution.get('rules', {}).get('tax_rate', 0)
            approve = levy_vote(coins=standing['coins'], value=value, current=current, fairness=standing['fairness'],
                                solidarity=standing['solidarity'], wealth_motive=standing['motives'].get('wealth', .5))
            side = 'for' if approve else 'against'
            if value > current:
                reasons.append('it would cost me little' if standing['coins'] * value < 3 else
                               'I owe my neighbors that much' if standing['solidarity'] >= .5 else
                               'the town is unfair to people like me' if standing['fairness'] < .35 else
                               'it would cost me more than I get back')
            else:
                reasons.append('the levy costs me real money' if approve else 'the levy does more good than harm')
    elif kind == 'work_order':
        budget = params['quantity'] * params['unit_wage']
        ceiling = s.bid(params['resource']) or 2
        checks = [(town.get('deposits', {}).get(params['resource'], 0) >= 1, 'there is material to gather',
                   'there is nothing left to gather'),
                  (town.get('treasury', 0) >= budget, 'the treasury can pay', 'the treasury cannot pay it'),
                  (params['unit_wage'] <= ceiling + 1e-9, 'the wage is no more than the market pays',
                   f'the wage is more than the market pays ({money(ceiling)})')]
        side = 'for' if all(ok for ok, _, _ in checks) else 'against'
        reasons = [good if ok else bad for ok, good, bad in checks if (ok if side == 'for' else not ok)]
    elif kind == 'commission':
        budget = params['quantity'] * params['unit_wage']
        stores = (institution.get('purpose') == 'cooperative' and params['resource'] == 'food'
                  and shared.get('coins', 0) >= budget and shared.get('food', 0) < 6)
        side = 'for' if stores else None
        reasons = ['it stocks our shared food stores'] if stores else ['it depends on what the organization still needs']
    elif kind == 'distribute_food':
        amount = params.get('amount', 0)
        if amount > shared.get('food', 0):
            side, reasons = 'against', ['we do not have that much food']
        elif params.get('destination') == 'settlement':
            useful = 0 < amount <= max(0, town.get('population', 0) - town.get('food', 0))
            side, reasons = ('for', ['the town is short']) if useful else ('against', ['the town is not short'])
        else:
            target, regard = params.get('member'), _get(s.me.get('trust', {}), params.get('member'), 0.)
            useful = (s.me['inventory'].get('food', 0) < 3 if target == me else amount <= 3 and regard > -.3)
            side = 'for' if useful else 'against'
            reasons = ['a little help for a member I don\'t distrust' if useful else
                       'I don\'t trust the person it would go to' if regard <= -.3 else 'it is more than a member needs']
    elif kind == 'communal_labor':
        population = max(1, town.get('population', 1))
        pressure = max(0, 1 - town.get('food', 0) / population)
        crowded = town.get('deposits', {}).get('food', 0) < max(4, 4 * len(s.o.get('peers', [])))
        approve = params.get('value', 0) <= .25 and (pressure > 0 or crowded)
        side, reasons = ('for', ['food is short']) if approve else ('against', ['we don\'t need it'])
    if side is None:
        text = f'I haven\'t made up my mind about {label}; ' + (reasons[0] if reasons else 'it depends how things look then') + '.'
    else:
        text = f'I\'d vote {side} {label}: ' + ', and '.join(reasons) + '.'
    return dict(side=side, voted=False, reasons=reasons, text=text)


def _proposal(s, args, reply):
    for institution in s.o.get('institutions', []):
        if institution['id'] != args.get('institution'):
            continue
        decision = next((d for d in institution.get('decisions', []) if d['id'] == args.get('proposal')), None)
        if decision is None:
            break
        if decision.get('status') != 'open':
            vote = _get(decision.get('votes', {}), s.me['id'])
            said = f'I voted {"for" if vote.get("approve") else "against"} it.' if vote else 'I had no vote on it.'
            say(reply, f'That proposal was {decision.get("status")}. {said}')
            return
        reply['stance'] = stance_on(s, institution, decision)
        say(reply, reply['stance']['text'])
        return
    say(reply, 'I don\'t know of that proposal.')


def _work_for_you(s, args, reply):
    good, wage = args.get('resource'), args.get('wage', 0)
    if SKILL_FOR.get(good) not in s.me.get('skills', []):
        say(reply, f'I can\'t gather {good}; find someone with the skill.')
        reply['stance'] = 'no'
        return
    if s.wary:
        say(reply, 'I won\'t work for you, not after what I know.')
        reply['stance'] = 'no'
        return
    if not _worth(s, good, wage, 8):
        say(reply, f'Not at {money(wage)}: the market pays {money(s.bid(good))} for {good}, and gathering and '
                   f'selling it myself pays better. I\'d want at least {money(s.bid(good) / 2)} a unit.')
        reply['stance'] = 'no'
        return
    reply['stance'] = 'maybe'
    word = 'I might' if s.trust < .2 else 'I would likely'
    caution = (' I don\'t know you, but the wages would be held in escrow, so the risk is yours.' if abs(s.trust) < .03 else '')
    say(reply, f'{word}, at {money(wage)} a unit, if nothing better comes up. Post the job and I\'ll see.{caution}')


def _join(s, args, reply):
    me = s.me['id']
    institution = next((i for i in s.o.get('institutions', []) if i['id'] == args.get('institution')), None)
    if institution is None or not institution.get('active', True):
        say(reply, 'I don\'t know that organization.')
        return
    if me in institution.get('members', []):
        say(reply, f'I\'m already in {institution["name"]}.')
        reply['stance'] = 'member'
        return
    if institution.get('settlement_id') != s.town['id']:
        say(reply, 'It\'s not in this town.')
        reply['stance'] = 'no'
        return
    regard = confidence(s.me, institution.get('members', []))
    if regard <= WARY_OF_GROUP:
        say(reply, f'I don\'t trust the people in {institution["name"]}.')
        reply['stance'] = 'no'
        return
    purpose = institution.get('purpose', 'cooperative')
    fairness, belonging = s.mind.get('fairness', .5), s.motives.get('belonging', .4)
    market = market_view(s.o)
    standing = EconomicPolicy._standing(s.o, market) if market and s.mind else None
    aggrieved = standing is not None and (fairness < .42 or standing['insecure'] or (standing['poor'] and fairness < .5))
    if purpose == 'cooperative' and aggrieved and belonging >= .3:
        rivals = [i for i in s.o.get('institutions', []) if i.get('purpose') == 'cooperative' and i.get('active', True)
                  and i['settlement_id'] == s.town['id'] and confidence(s.me, i.get('members', [])) > WARY_OF_GROUP]
        largest = max(rivals, key=lambda i: (len(i.get('members', [])), -i['id'])) if rivals else institution
        if largest['id'] != institution['id']:
            say(reply, f'I\'d sooner join {largest["name"]}; more of my neighbors are in it.')
            reply['stance'] = 'no'
        else:
            say(reply, 'Perhaps. Pooling food and work with neighbors looks fairer than facing this economy alone.')
            reply['stance'] = 'maybe'
        return
    if purpose == s.me.get('preferred_purpose'):
        say(reply, f'A {purpose} is the kind of thing I\'d join, when I can spare the time.')
        reply['stance'] = 'maybe'
        return
    say(reply, 'I\'m managing well enough on my own for now.')
    reply['stance'] = 'no'


def _teach(s, args, reply):
    topic = args.get('topic')
    knows = 'carpentry' in s.me.get('skills', []) if topic == 'carpentry' else s.me.get('knowledge', 0) >= 1
    if not knows:
        say(reply, f'I don\'t know enough about {"the Aether" if topic == "aether" else topic} to teach it.')
        reply['stance'] = 'no'
        return
    if s.trust <= -.6:
        say(reply, 'I won\'t teach you.')
        reply['stance'] = 'no'
        return
    say(reply, 'I know it. I teach when I have the time and see someone who can use it; I can\'t promise when.')
    reply['stance'] = 'maybe'


def _tell(s, args, reply):
    claim = args['claim']
    known = any(str(c['key']) == str(claim['key']) for c in s.claims)
    if known:
        say(reply, 'I\'d heard.')
    elif s.trust < 0:
        say(reply, 'Is that so? I\'m not sure I believe you.')
    else:
        say(reply, 'I hadn\'t heard that.')
    reply['stance'] = 'known' if known else 'new'


HANDLERS = {'work': _work, 'news': _news, 'trade': _trade, 'politics': _politics, 'themselves': _themselves,
            'person': _person, 'proposal': _proposal, 'work_for_you': _work_for_you, 'join': _join,
            'teach': _teach, 'tell': _tell}
