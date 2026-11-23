"""v0.8 Stage 2: the player's journal, built from the world's own records.

Nothing here is new state: every line is derived from the action audit, the
trade history, work orders, organization decisions and events the world already
keeps, so a journal survives saving, loading and replay unchanged.

The player's view contains what the player did, what happened to them and what
is public (votes, proposals, offers, job notices), plus their own feelings
toward others. The historian's view adds how others regard the player, which
nobody inside the world can read.
"""
from .player import describe_decision, money

GOODS = ('food', 'wood', 'iron')


def household(world):
    """Everyone the player has controlled, in order: the first newcomer and any heirs."""
    people = []
    for entry in world.player_log:
        if entry['event'] in ('joined', 'heir'):
            if people:
                people[-1]['until'] = entry['tick']
            people.append(dict(id=entry['actor'], name=entry['name'], since=entry['tick'], until=None,
                               joined=entry['event'] == 'joined',
                               inventory=dict(entry.get('inventory', {}))))
    return people


def _names(world):
    names = {}
    for snapshot in world.snapshots:  # people who have since died keep their names
        names.update({a['id']: a['name'] for a in snapshot.get('agents', [])})
    names.update({a.id: a.name for a in world.agents})
    for entry in world.player_log:
        if entry['event'] in ('joined', 'heir'):
            names[entry['actor']] = entry['name']
    return names


def journal(world, view='player'):
    """The player's story so far; ``view='historian'`` adds how others regard them."""
    if view not in ('player', 'historian'):
        raise ValueError('A journal view is player or historian.')
    people = household(world)
    mine = {p['id'] for p in people}
    names = _names(world)
    institutions = {i.id: i for i in world.institutions}
    towns = {s.id: s.name for s in world.settlements}
    income, spending, transactions = {}, {}, []

    def flow(tick, kind, text, coins=0., table=None):
        if coins:
            target = income if coins > 0 else spending
            label = table or kind
            target[label] = round(target.get(label, 0.) + abs(coins), 6)
        transactions.append(dict(tick=tick, kind=kind, text=text, coins=round(coins, 6)))

    worked, refusals, memberships, votes, contests = [], [], {}, [], dict(lost=[], won=[])
    hired = {}
    results_by_tick = {}
    for audit in world.action_log:
        results_by_tick.setdefault(audit['tick'], []).append(audit)
    for audit in world.action_log:
        action, result, tick = audit['action'], audit['result'], audit['tick']
        actor, kind = action.get('actor'), action.get('type')
        effects, params = result.get('effects', {}), action.get('params', {})
        if kind == 'accept' and result['success'] and (effects.get('seller') in mine or effects.get('buyer') in mine):
            price = effects.get('price', 0.)
            selling = effects.get('seller') in mine
            other = effects.get('buyer') if selling else effects.get('seller')
            flow(tick, 'offer', f'{"Sold" if selling else "Bought"} {effects.get("amount")} '
                 f'{params.get("resource", "goods")} {"to" if selling else "from"} {names.get(other, "a neighbor")} '
                 f'for {money(price)} coins', price if selling else -price,
                 'sales to neighbors' if selling else 'purchases from neighbors')
            continue
        if kind == 'work' and result['success'] and effects.get('employer') in [{'kind': 'person', 'id': i} for i in mine]:
            entry = hired.setdefault(effects['order_id'], dict(order=effects['order_id'], workers={}, delivered=0, paid=0.))
            entry['workers'][names.get(actor, 'someone')] = entry['workers'].get(names.get(actor, 'someone'), 0) + effects['amount']
            entry['delivered'] += effects['amount']
            entry['paid'] = round(entry['paid'] + effects.get('coins', 0.), 6)
            transactions.append(dict(tick=tick, kind='delivery', coins=0., text=(
                f'{names.get(actor, "Someone")} delivered {effects["amount"]} {effects["resource"]} under your job '
                f'{effects["order_id"]} and was paid {money(effects.get("coins", 0))} from its escrow')))
        if actor not in mine:
            continue
        if not result['success']:
            refusals.append(dict(tick=tick, type=kind, code=result['code'], message=result['message']))
            if result['code'] == 'conflict':
                subject = world._contested(action)
                rivals = sorted({names.get(r['action'].get('actor'), 'someone') for r in results_by_tick[tick]
                                 if r['result']['success'] and r['action'].get('actor') != actor
                                 and subject is not None and world._contested(r['action']) == subject})
                if rivals:
                    contests['lost'].append(dict(tick=tick, what=_what(action), to=rivals))
            continue
        if kind in ('trade', 'gather', 'work'):
            subject = world._contested(action)
            losers = sorted({names.get(r['action'].get('actor'), 'someone') for r in results_by_tick[tick]
                             if r['result'].get('code') == 'conflict' and subject is not None
                             and world._contested(r['action']) == subject})
            if losers:
                contests['won'].append(dict(tick=tick, what=_what(action), over=losers))
        if kind == 'trade':
            price, buy = effects.get('price', 0.), effects.get('direction') == 'buy'
            flow(tick, 'market', f'{"Bought" if buy else "Sold"} {effects["amount"]} {effects["resource"]} at the '
                 f'{towns.get(action.get("location"), "")} market for {money(price)} coins', -price if buy else price,
                 'market purchases' if buy else 'market sales')
        elif kind == 'work':
            employer = effects.get('employer', {})
            who = (f'the {towns.get(employer.get("id"), "town")} council' if employer.get('kind') == 'municipal'
                   else getattr(institutions.get(employer.get('id')), 'name', 'an organization')
                   if employer.get('kind') == 'institution' else names.get(employer.get('id'), 'an employer'))
            worked.append(dict(tick=tick, order=effects['order_id'], employer=who, resource=effects['resource'],
                               amount=effects['amount'], coins=effects.get('coins', 0.)))
            flow(tick, 'wages', f'Delivered {effects["amount"]} {effects["resource"]} for {who} and earned '
                 f'{money(effects.get("coins", 0))} coins', effects.get('coins', 0.))
        elif kind == 'hire':
            order = next((o for o in world.work_orders if o['id'] == effects['order_id']), {})
            entry = hired.setdefault(effects['order_id'], dict(order=effects['order_id'], workers={}, delivered=0, paid=0.))
            entry.update(tick=tick, resource=order.get('resource'), quantity=order.get('quantity'),
                         unit_wage=order.get('unit_wage'), budget=effects['wage_budget'])
            flow(tick, 'hire', f'Put {money(effects["wage_budget"])} coins in escrow to hire '
                 f'{order.get("quantity")} {order.get("resource")} at {money(order.get("unit_wage", 0))} each '
                 f'(job {effects["order_id"]})', -effects['wage_budget'], 'wages put in escrow')
        elif kind == 'consign':
            transactions.append(dict(tick=tick, kind='shipment', coins=0., text=(
                f'Shipped {effects["amount"]} {effects["resource"]} to {towns.get(effects["destination"], "a neighbor")}; '
                f'{money(effects["coins"])} coins due on delivery')))
        elif kind == 'form_institution':
            identity = effects.get('institution_id')
            memberships[identity] = dict(institution=identity, name=getattr(institutions.get(identity), 'name', '?'),
                                         joined=tick, left=None, founded=True)
            flow(tick, 'organization', f'Founded {memberships[identity]["name"]}', -2., 'organization fees')
        elif kind in ('join_institution', 'leave_institution'):
            identity = effects.get('institution_id')
            name = getattr(institutions.get(identity), 'name', '?')
            if kind == 'join_institution':
                memberships[identity] = dict(institution=identity, name=name, joined=tick, left=None, founded=False)
                transactions.append(dict(tick=tick, kind='organization', coins=0., text=f'Joined {name}'))
            elif identity in memberships:
                memberships[identity]['left'] = tick
                transactions.append(dict(tick=tick, kind='organization', coins=0., text=f'Left {name}'))
        elif kind == 'contribute':
            name = getattr(institutions.get(effects.get('institution_id')), 'name', 'an organization')
            coins = effects['amount'] if effects['resource'] == 'coins' else 0.
            flow(tick, 'gift', f'Gave {money(effects["amount"])} {effects["resource"]} to {name}', -coins, 'gifts')
        elif kind == 'build':
            costs = effects.get('costs', {})
            flow(tick, 'building', f'Built a {effects.get("structure", "structure")}', -costs.get('coins', 0.), 'building')
        elif kind == 'vote':
            institution = institutions.get(params.get('institution'))
            decision = next((d for d in getattr(institution, 'decisions', []) if d['id'] == params.get('proposal')), None)
            votes.append(dict(tick=tick, institution=getattr(institution, 'name', '?'), proposal=params.get('proposal'),
                              approve=params.get('approve'),
                              about=describe_decision(decision, _public(world, institution)) if decision else '',
                              outcome=decision.get('status') if decision else None))
        elif kind == 'enact':
            transactions.append(dict(tick=tick, kind='politics', coins=0., text=result['message']))
    for entry in world.trade_history:
        if entry.get('actor') not in mine:
            continue
        if entry.get('kind') == 'delivery':
            flow(entry['tick'], 'shipment', f'A shipment reached {towns.get(entry["settlement"], "its market")}: '
                 f'paid {money(entry["coins"])} coins (gain {money(entry.get("gain", 0))})', entry['coins'], 'shipments delivered')
        elif entry.get('kind') not in ('purchase', 'sale', 'consignment'):
            transactions.append(dict(tick=entry['tick'], kind='shipment', coins=0., text=(
                f'A shipment of {money(entry.get("amount", 0))} {entry.get("resource") or "goods"} to '
                f'{towns.get(entry.get("settlement"), "its market")} was {"lost" if entry["kind"] == "loss" else entry["kind"]}'
                + (f': {entry["reason"]}' if entry.get('reason') else '')
                + f' (worth {money(-entry.get("gain", 0))} coins at home)')))
    for order in world.work_orders:
        if order['employer'].get('kind') == 'person' and order['employer'].get('id') in mine and order['id'] in hired:
            entry = hired[order['id']]
            entry['status'] = order['status']
            if order['status'] != 'open':
                refund = round(entry.get('budget', 0.) - entry['paid'], 6)
                if refund > 1e-9:
                    flow(order['expires'] if order['status'] == 'expired' else order['created'], 'refund',
                         f'Job {order["id"]} closed ({order["status"]}); {money(refund)} unused coins came back', refund,
                         'unused wages returned')
    levy_names = {p['name'] for p in people}
    for event in world.events:
        if event.get('kind') == 'levy' and event.get('agent') in levy_names:
            flow(event['tick'], 'levy', event['message'], -event.get('amount', 0.), 'levies')
    proposals = []
    for institution in world.institutions:
        for decision in institution.decisions:
            if decision.get('proposer') in mine:
                yes = sum(v.get('approve') is True for v in decision.get('votes', {}).values())
                no = sum(v.get('approve') is False for v in decision.get('votes', {}).values())
                proposals.append(dict(tick=decision['created'], institution=institution.name, proposal=decision['id'],
                                      about=describe_decision(decision, _public(world, institution)),
                                      status=decision['status'], yes=yes, no=no))
    transactions.sort(key=lambda t: t['tick'])
    current = next((a for a in world.agents if a.id in world.active_players()), None)
    start = people[0]['inventory'].get('coins', 0.) if people else 0.
    now = current.inventory['coins'] if current is not None else 0.
    explained = sum(income.values()) - sum(spending.values())
    for entry in memberships.values():
        institution = institutions.get(entry['institution'])
        entry['member_now'] = bool(current is not None and institution is not None and institution.active
                                   and current.id in institution.members)
    out = dict(people=people, coins=dict(start=start, now=round(now, 6), income=income, spending=spending,
                                         unexplained=round(now - start - explained, 6)),
               transactions=transactions, worked=worked, hired=sorted(hired.values(), key=lambda h: h['order']),
               memberships=sorted(memberships.values(), key=lambda m: m['joined']), votes=votes,
               proposals=sorted(proposals, key=lambda p: p['tick']), contests=contests, refusals=refusals,
               relationships=sorted(({'name': names.get(other, f'person {other}'), 'your_trust': round(value, 3)}
                                     for other, value in (current.trust.items() if current is not None else ())
                                     if abs(value) >= .005 and other in names),
                                    key=lambda r: -abs(r['your_trust'])),
               events=[dict(tick=e['tick'], kind=e['kind'], message=e['message']) for e in world.events
                       if e.get('player') or (e.get('kind') == 'death' and e.get('actor_id') in mine)])
    if view == 'historian':
        out['regard'] = sorted(({'name': a.name, 'trust_in_you': round(a.trust.get(current.id, 0.), 3)}
                                for a in world.agents if current is not None and a.id != current.id
                                and abs(a.trust.get(current.id, 0.)) >= .005), key=lambda r: r['trust_in_you'])
    return out


def _what(action):
    params = action.get('params', {})
    if action.get('type') == 'work':
        return f'paid work under job {params.get("order")}'
    verb = 'the last' if action.get('type') == 'trade' else 'the accessible'
    return f'{verb} {params.get("resource", "goods")}'


def _public(world, institution):
    """Enough public context to describe a decision in words."""
    if institution is None:
        return {'settlement': {'id': -1, 'name': ''}, 'neighbors': [], 'peers': [], 'actor': {'id': -1}, 'institutions': []}
    town = world.settlements[institution.settlement_id]
    return {'settlement': {'id': town.id, 'name': town.name},
            'neighbors': [{'id': s.id, 'name': s.name} for s in world.settlements if s.id != town.id],
            'peers': [{'id': a.id, 'name': a.name} for a in world.agents],
            'actor': {'id': -1}, 'institutions': []}


def journal_text(entries, limit=12):
    """The journal as terminal lines; the newest transactions last."""
    coins = entries['coins']
    lines = [f'Coins: {money(coins["start"])} on arrival, {money(coins["now"])} now.']
    if coins['income']:
        lines.append('Earned: ' + ', '.join(f'{money(v)} from {k}' for k, v in sorted(coins['income'].items())))
    if coins['spending']:
        lines.append('Spent: ' + ', '.join(f'{money(v)} on {k}' for k, v in sorted(coins['spending'].items())))
    if abs(coins['unexplained']) > .005:
        lines.append(f'Other changes: {money(coins["unexplained"])} coins.')
    if len(entries['people']) > 1:
        lines.append('Your household: ' + ' -> '.join(p['name'] for p in entries['people']))
    for job in entries['hired']:
        workers = ', '.join(f'{name} ({units})' for name, units in sorted(job['workers'].items())) or 'nobody yet'
        lines.append(f'Your job {job["order"]}: {job["delivered"]} of {job.get("quantity", "?")} {job.get("resource", "")} '
                     f'delivered, {money(job["paid"])} coins paid; worked by {workers}; {job.get("status", "open")}.')
    if entries['worked']:
        total = sum(w['coins'] for w in entries['worked'])
        lines.append(f'Paid work: {len(entries["worked"])} deliveries, {money(total)} coins.')
    for member in entries['memberships']:
        state = 'member' if member['member_now'] else 'no longer a member'
        lines.append(f'{"Founded" if member["founded"] else "Joined"} {member["name"]} in cycle {member["joined"]} ({state}).')
    for proposal in entries['proposals']:
        lines.append(f'Your proposal {proposal["proposal"]} in {proposal["institution"]}: {proposal["about"]}, '
                     f'{proposal["status"]} ({proposal["yes"]} for, {proposal["no"]} against).')
    for vote in entries['votes'][-limit:]:
        lines.append(f'You voted {"for" if vote["approve"] else "against"} {vote["about"]} in {vote["institution"]}'
                     f' (now {vote["outcome"]}).')
    for lost in entries['contests']['lost'][-limit:]:
        lines.append(f'Cycle {lost["tick"]}: {", ".join(lost["to"])} got {lost["what"]} before you.')
    for won in entries['contests']['won'][-limit:]:
        lines.append(f'Cycle {won["tick"]}: you got {won["what"]} before {", ".join(won["over"])}.')
    if entries['relationships']:
        lines.append('How you feel about people: ' + ', '.join(
            f'{r["name"]} {r["your_trust"]:+.2f}' for r in entries['relationships'][:8]))
    if entries.get('regard') is not None:
        lines.append('How people regard you (historian\'s view): ' + (', '.join(
            f'{r["name"]} {r["trust_in_you"]:+.2f}' for r in entries['regard']) or 'nobody has formed a view'))
    recent = [t for t in entries['transactions'] if t['coins'] or t['kind'] in ('delivery', 'shipment', 'politics')]
    if recent:
        lines.append('Recently:')
        lines.extend(f'  cycle {t["tick"]}: {t["text"]}' for t in recent[-limit:])
    return lines
