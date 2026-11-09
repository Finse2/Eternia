"""Voluntary organizations and voted mandates, resolved by the action engine.

Membership is personal; shared property belongs to the organization. Decisions
freeze an electorate when proposed, and only votes recorded before the current
tick can authorize execution. Current membership and location are rechecked.
"""
from copy import deepcopy
from dataclasses import asdict, dataclass, field

from .actions import _number, _require
from .community import CommunityEngine


GRANARY_COSTS = {'wood': 10., 'iron': 2., 'coins': 6.}
PROPOSAL_LIFETIME = 12
MAX_ACTIVE_INSTITUTIONS = 8
PROPOSAL_KINDS = {'granary', 'tax_rate', 'communal_labor', 'trade_agreement'}


@dataclass
class Institution:
    id: int
    name: str
    settlement_id: int
    members: set[int] = field(default_factory=set)
    treasury: float = 0.
    inventory: dict[str, float] = field(default_factory=lambda: {
        'food': 0., 'wood': 0., 'iron': 0.})
    rules: dict = field(default_factory=lambda: {'tax_rate': 0., 'communal_labor': 0.})
    decisions: list[dict] = field(default_factory=list)
    active: bool = True
    founded: int = 0
    empty_since: int | None = None

    def public_state(self):
        state = asdict(self)
        state['members'] = sorted(self.members)
        return state


def eligible_electorate(world, institution, proposal, frame=None):
    """Original voters who remain living, local members at tick start and now."""
    if frame is None:
        frame = world.institution_frame(institution)
    if not frame or not frame.get('active', False) or not institution.active:
        return set()
    local = {a.id for a in world.agents if a.home == institution.settlement_id}
    return (set(proposal.get('electorate', ())) & set(frame.get('members', ()))
            & institution.members & local)


def vote_counts(world, institution, proposal, frame=None):
    """Count the votes demonstrably available before this tick, without mutation."""
    if frame is None:
        frame = world.institution_frame(institution)
    if not frame:
        return 0, 0, 0
    old = next((d for d in frame.get('decisions', ()) if d['id'] == proposal['id']), None)
    if old is None:
        return 0, 0, 0
    electorate = eligible_electorate(world, institution, old, frame)
    yes = no = 0
    for person_id in electorate:
        vote = old.get('votes', {}).get(person_id, old.get('votes', {}).get(str(person_id)))
        if not isinstance(vote, dict) or vote.get('tick', world.tick) >= world.tick:
            continue
        if vote.get('approve') is True:
            yes += 1
        elif vote.get('approve') is False:
            no += 1
    return yes, no, len(electorate)


def approved(world, institution, proposal, frame=None):
    """Authority requires two consenting people and a strict eligible majority."""
    if proposal.get('status') != 'open' or not proposal.get('created', world.tick) < world.tick < proposal.get('expires', 0):
        return False
    yes, _, count = vote_counts(world, institution, proposal, frame)
    return yes >= 2 and yes * 2 > count


class InstitutionEngine(CommunityEngine):
    parameters = {**CommunityEngine.parameters,
                  'form_institution': {'name'},
                  'join_institution': {'institution'},
                  'leave_institution': {'institution'},
                  'contribute': {'institution', 'resource', 'amount'},
                  'propose': {'institution', 'kind', 'params'},
                  'vote': {'institution', 'proposal', 'approve'},
                  'enact': {'institution', 'proposal'}}

    def _institution(self, actor, settlement, params, *, member=True):
        reference = params.get('institution')
        _require(type(reference) is int and reference >= 0, 'unknown_institution',
                 'An institution requires a stable integer ID.')
        try:
            institution = self.world._resolve_institution(reference)
        except ValueError:
            institution = None
        _require(institution is not None and institution.active, 'unknown_institution',
                 'The institution is absent or has collapsed.')
        _require(institution.settlement_id == settlement.id, 'remote_action',
                 'Institutional participation requires presence in its settlement.')
        frame = self.world.institution_frame(institution)
        _require(frame is not None and frame.get('active', False), 'authority_unavailable',
                 'The institution was not active at tick start.')
        if member:
            _require(actor.id in institution.members and actor.id in frame['members'],
                     'not_member', 'Authority requires membership at tick start and now.')
        return institution, frame

    def _proposal(self, institution, params):
        reference = params.get('proposal')
        _require(type(reference) is int and reference >= 0, 'unknown_proposal',
                 'A proposal requires an integer ID.')
        proposal = next((p for p in institution.decisions if p['id'] == reference), None)
        _require(proposal is not None, 'unknown_proposal', 'The proposal does not exist.')
        _require(proposal['status'] == 'open', 'proposal_closed', 'The proposal is already closed.')
        _require(proposal['created'] < self.world.tick < proposal['expires'],
                 'proposal_unavailable', 'The proposal must be from an earlier tick and still live.')
        return proposal

    def _check_form_institution(self, actor, settlement, params):
        name = params.get('name')
        _require(type(name) is str and 0 < len(name.strip()) <= 64,
                 'invalid_action', 'An organization needs a name of 1 to 64 characters.')
        name = name.strip()
        _require(not any(i.name == name for i in self.world.institutions),
                 'already_exists', 'An institution with that name is already in the history.')
        _require(sum(i.active for i in self.world.institutions) < MAX_ACTIVE_INSTITUTIONS,
                 'institution_limit', 'At most eight active institutions are supported.')
        self._inventory(actor, {'coins': 2})
        return {'name': name, 'energy': 2}

    def _check_join_institution(self, actor, settlement, params):
        institution, _ = self._institution(actor, settlement, params, member=False)
        _require(actor.id not in institution.members, 'already_member', 'The actor is already a member.')
        return {'institution': institution, 'energy': 1}

    def _check_leave_institution(self, actor, settlement, params):
        institution, _ = self._institution(actor, settlement, params)
        return {'institution': institution, 'energy': 0}

    def _check_contribute(self, actor, settlement, params):
        institution, _ = self._institution(actor, settlement, params)
        resource = params.get('resource')
        _require(type(resource) is str and resource in ('food', 'wood', 'iron', 'coins'),
                 'invalid_resource', 'Contribute food, wood, iron or coins.')
        amount = _number(params.get('amount'), 'amount', minimum=.1, maximum=1000)
        self._inventory(actor, {resource: amount})
        return {'institution': institution, 'resource': resource, 'amount': amount, 'energy': 1}

    def _proposal_params(self, kind, params, settlement):
        _require(type(kind) is str and kind in PROPOSAL_KINDS,
                 'unknown_proposal', 'Known proposals are granary, tax_rate, communal_labor and trade_agreement.')
        _require(type(params) is dict and all(type(k) is str for k in params),
                 'invalid_action', 'Proposal parameters must be an object with string keys.')
        if kind == 'granary':
            _require(not params, 'invalid_action', 'A granary proposal has no parameters.')
            _require(settlement.buildings.get('granary', 0) < 3, 'already_built',
                     'The settlement already has the supported three communal granaries.')
            return {}
        if kind in ('tax_rate', 'communal_labor'):
            _require(set(params) == {'value'}, 'invalid_action', 'This proposal requires only value.')
            limit = .15 if kind == 'tax_rate' else .3
            return {'value': _number(params['value'], 'value', minimum=0, maximum=limit)}
        _require(set(params) == {'destination'}, 'invalid_action', 'A trade agreement requires only destination.')
        reference = params['destination']
        _require(type(reference) is int and reference >= 0, 'unknown_location',
                 'A destination requires a settlement integer ID.')
        target = next((s for s in self.world.settlements if s.id == reference), None)
        _require(target is not None and target.id != settlement.id,
                 'unknown_location', 'A trade agreement needs a different settlement.')
        _require(self._distance(settlement, target) <= 38, 'out_of_range',
                 'The destination lies beyond the supported trade range.')
        return {'destination': target.id}

    def _check_propose(self, actor, settlement, params):
        institution, frame = self._institution(actor, settlement, params)
        kind = params.get('kind')
        normalized = self._proposal_params(kind, params.get('params', {}), settlement)
        _require(not any(p['kind'] == kind and p['status'] == 'open' and p['expires'] > self.world.tick
                         for p in institution.decisions), 'active_proposal',
                 'This institution already has a live proposal of that kind.')
        electorate = sorted(set(frame['members']) & institution.members & {
            a.id for a in self.world.agents if a.home == settlement.id})
        return {'institution': institution, 'kind': kind, 'params': normalized,
                'electorate': electorate, 'energy': 1}

    def _check_vote(self, actor, settlement, params):
        institution, frame = self._institution(actor, settlement, params)
        proposal = self._proposal(institution, params)
        _require(actor.id in proposal['electorate'], 'not_elector',
                 'Joining later does not add a voter to an existing proposal.')
        old = next((p for p in frame['decisions'] if p['id'] == proposal['id']), None)
        _require(old is not None, 'proposal_unavailable', 'The proposal was not visible at tick start.')
        _require(actor.id not in proposal['votes'] and str(actor.id) not in proposal['votes'],
                 'already_voted', 'Each original member can cast one vote per proposal.')
        _require(type(params.get('approve')) is bool, 'invalid_action', 'approve must be a boolean.')
        return {'institution': institution, 'proposal': proposal,
                'approve': params['approve'], 'energy': 0}

    def _check_enact(self, actor, settlement, params):
        institution, frame = self._institution(actor, settlement, params)
        proposal = self._proposal(institution, params)
        _require(approved(self.world, institution, proposal, frame), 'not_approved',
                 'Execution requires a prior-tick majority and at least two consenting members.')
        # A valid mandate cannot override a changed site or exceed collective caps.
        normalized = self._proposal_params(proposal['kind'], proposal['params'], settlement)
        costs = GRANARY_COSTS if proposal['kind'] == 'granary' else {}
        available = self.world.available_institution_inventory(institution)
        _require(all(available.get(r, 0) >= n for r, n in costs.items()),
                 'insufficient_resources', 'Shared tick-start reserves cannot fund the approved project.')
        if proposal['kind'] in ('tax_rate', 'communal_labor'):
            kind = proposal['kind']
            total = normalized['value'] + sum(i.rules.get(kind, 0) for i in self.world.institutions
                                             if i.active and i.id != institution.id
                                             and i.settlement_id == settlement.id)
            _require(total <= (.15 if kind == 'tax_rate' else .3) + 1e-9,
                     'mandate_conflict', 'Combined active mandates would exceed the settlement limit.')
        reciprocal = None
        if proposal['kind'] == 'trade_agreement':
            destination = normalized['destination']
            for other in sorted(self.world.institutions, key=lambda i: i.id):
                if not other.active or other.settlement_id != destination:
                    continue
                for candidate in other.decisions:
                    if (candidate['kind'] == 'trade_agreement'
                            and candidate['params'].get('destination') == settlement.id
                            and approved(self.world, other, candidate)):
                        reciprocal = (other, candidate)
                        break
                if reciprocal:
                    break
            _require(reciprocal is not None, 'no_reciprocal_mandate',
                     'The destination also needs a prior-tick approved reciprocal agreement.')
        return {'institution': institution, 'proposal': proposal,
                'costs': dict(costs), 'reciprocal': reciprocal, 'energy': 2}

    def _metric(self, key):
        self.world.metrics[key] = self.world.metrics.get(key, 0) + 1

    def _announcement(self, institution, actor, message):
        self.world._event('institution', message, self.world.settlements[institution.settlement_id].name,
                          actor.name, institution_id=institution.id, actor_id=actor.id)

    def _apply(self, action, actor, settlement, details):
        kind = action.type
        if kind == 'form_institution':
            institution = Institution(self.world.next_institution_id, details['name'], settlement.id,
                                      members={actor.id}, founded=self.world.tick)
            self.world.next_institution_id += 1
            self.world.institutions.append(institution)
            actor.inventory['coins'] -= 2
            self._metric('institutions_formed')
            message = f'{actor.name} founded {institution.name}.'
            self._announcement(institution, actor, message)
            return {'institution_id': institution.id, 'costs': {'coins': 2.}, 'message': message}
        if kind not in ('join_institution', 'leave_institution', 'contribute', 'propose', 'vote', 'enact'):
            return super()._apply(action, actor, settlement, details)
        institution = details['institution']
        effects = {'institution_id': institution.id}
        if kind == 'join_institution':
            institution.members.add(actor.id)
            institution.empty_since = None
            self._metric('institution_joins')
            message = f'{actor.name} joined {institution.name}.'
        elif kind == 'leave_institution':
            institution.members.remove(actor.id)
            if not institution.members:
                institution.empty_since = self.world.tick
            self._metric('institution_leaves')
            message = f'{actor.name} left {institution.name}; shared assets stayed with the organization.'
        elif kind == 'contribute':
            resource, amount = details['resource'], details['amount']
            actor.inventory[resource] -= amount
            if resource == 'coins':
                institution.treasury += amount
            else:
                institution.inventory[resource] += amount
            self._metric('institution_contributions')
            effects.update(resource=resource, amount=amount)
            message = f'{actor.name} contributed {amount:g} {resource} to {institution.name}.'
        elif kind == 'propose':
            proposal = {'id': self.world.next_proposal_id, 'kind': details['kind'],
                        'params': deepcopy(details['params']), 'proposer': actor.id,
                        'electorate': details['electorate'],
                        'votes': {actor.id: {'approve': True, 'tick': self.world.tick}},
                        'created': self.world.tick, 'expires': self.world.tick + PROPOSAL_LIFETIME,
                        'status': 'open'}
            self.world.next_proposal_id += 1
            institution.decisions.append(proposal)
            self._metric('institution_proposals')
            effects.update(proposal_id=proposal['id'], kind=proposal['kind'])
            message = f'{actor.name} proposed {proposal["kind"]} in {institution.name}.'
        elif kind == 'vote':
            proposal = details['proposal']
            proposal['votes'][actor.id] = {'approve': details['approve'], 'tick': self.world.tick}
            electorate = set(proposal['electorate']) & institution.members & {
                a.id for a in self.world.agents if a.home == settlement.id}
            negatives = sum(proposal['votes'].get(i, {}).get('approve') is False for i in electorate)
            if negatives >= 2 and negatives * 2 > len(electorate):
                proposal['status'] = 'rejected'
                self._metric('institution_rejections')
            self._metric('institution_votes')
            effects.update(proposal_id=proposal['id'], approve=details['approve'])
            message = f'{actor.name} voted {"yes" if details["approve"] else "no"} on {proposal["kind"]} in {institution.name}.'
        else:
            proposal = details['proposal']
            self.world.spend_institution(institution, details['costs'])
            project = proposal['kind']
            if project == 'granary':
                settlement.buildings['granary'] = settlement.buildings.get('granary', 0) + 1
            elif project in ('tax_rate', 'communal_labor'):
                institution.rules[project] = proposal['params']['value']
            else:
                other, reciprocal = details['reciprocal']
                target = next(s for s in self.world.settlements if s.id == other.settlement_id)
                settlement.relations[target.id] = 'trade'
                target.relations[settlement.id] = 'trade'
                reciprocal['status'] = 'enacted'
                reciprocal['enacted'] = self.world.tick
                reciprocal['executed_by'] = actor.id
            proposal['status'] = 'enacted'
            proposal['enacted'] = self.world.tick
            proposal['executed_by'] = actor.id
            self._metric('institution_enactments')
            effects.update(proposal_id=proposal['id'], project=project, costs=details['costs'])
            message = f'{actor.name} executed the approved {project} mandate of {institution.name}.'
        self._announcement(institution, actor, message)
        return {**effects, 'message': message}
