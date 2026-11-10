"""Purpose-specific organizations and independently negotiated regional mandates.

An organization can offer commercial terms but cannot bind its counterpart.
Opening a route requires two compatible mandates with prior-tick approval.
Embargoes govern the sponsor's routes; councils need broad local support to
control settlement-wide migration. Older experiment engines are unchanged.
"""
from dataclasses import dataclass

from .actions import _number, _require
from .institutions import Institution, InstitutionEngine, approved


PURPOSES = {'cooperative', 'guild', 'council'}
REGIONAL_KINDS = {'trade_terms', 'embargo', 'specialization', 'migration_policy'}
MAX_REGIONAL_INSTITUTIONS = 12


@dataclass
class RegionalInstitution(Institution):
    purpose: str = 'cooperative'


class RegionalEngine(InstitutionEngine):
    parameters = {**InstitutionEngine.parameters,
                  'form_institution': {'name', 'purpose'}}

    def _charter(self, actor, purpose):
        _require(type(purpose) is str and purpose in PURPOSES,
                 'unknown_purpose', 'Choose a cooperative, guild or council.')
        if purpose == 'guild':
            self._skill(actor, 'trading')
        elif purpose == 'cooperative':
            self._skill(actor, 'foraging')

    def _check_form_institution(self, actor, settlement, params):
        name = params.get('name')
        _require(type(name) is str and 0 < len(name.strip()) <= 64,
                 'invalid_action', 'An organization needs a name of 1 to 64 characters.')
        name = name.strip()
        _require(not any(i.name == name for i in self.world.institutions),
                 'already_exists', 'An institution with that name is already in the history.')
        _require(sum(i.active for i in self.world.institutions) < MAX_REGIONAL_INSTITUTIONS,
                 'institution_limit', 'At most twelve active regional institutions are supported.')
        purpose = params.get('purpose', 'cooperative')
        self._charter(actor, purpose)
        self._inventory(actor, {'coins': 2})
        return {'name': name, 'purpose': purpose, 'energy': 2}

    def _check_join_institution(self, actor, settlement, params):
        details = super()._check_join_institution(actor, settlement, params)
        self._charter(actor, getattr(details['institution'], 'purpose', 'cooperative'))
        return details

    def _check_migrate(self, actor, settlement, params):
        details = super()._check_migrate(actor, settlement, params)
        incoming_policy = getattr(self.world, 'regional_migration_open', None)
        if incoming_policy is not None:
            _require(incoming_policy(details['destination'].id), 'permission_denied',
                     'The destination council has closed incoming migration.')
        original_policy = getattr(self.world, 'regional_migration_open_at_start', None)
        if original_policy is not None:
            _require(original_policy(details['destination'].id), 'permission_denied',
                     'The destination was closed to incoming migration at tick start.')
        return details

    def _destination(self, reference, settlement):
        _require(type(reference) is int and reference >= 0, 'unknown_location',
                 'A destination requires a settlement integer ID.')
        target = next((s for s in self.world.settlements if s.id == reference), None)
        _require(target is not None and target.id != settlement.id,
                 'unknown_location', 'A regional mandate needs a different settlement.')
        _require(self._distance(settlement, target) <= 38, 'out_of_range',
                 'The destination lies beyond the supported range of 38.')
        return target

    def _proposal_params(self, kind, params, settlement):
        _require(kind != 'trade_agreement', 'unknown_proposal',
                 'Regional agreements require explicit reciprocal trade_terms.')
        if type(kind) is not str or kind not in REGIONAL_KINDS:
            return super()._proposal_params(kind, params, settlement)
        _require(type(params) is dict and all(type(k) is str for k in params),
                 'invalid_action', 'Proposal parameters must be an object with string keys.')
        if kind == 'specialization':
            _require(set(params) == {'resource'}, 'invalid_action',
                     'Specialization requires only resource.')
            resource = params['resource']
            _require(type(resource) is str and resource in ('food', 'wood', 'iron'),
                     'invalid_resource', 'Specialize in food, wood or iron.')
            return {'resource': resource}
        if kind == 'migration_policy':
            _require(set(params) == {'open'} and type(params.get('open')) is bool,
                     'invalid_action', 'A migration policy requires only a boolean open.')
            return {'open': params['open']}
        if kind == 'embargo':
            _require(set(params) == {'destination', 'enabled'}
                     and type(params.get('enabled')) is bool, 'invalid_action',
                     'An embargo requires destination and a boolean enabled.')
            target = self._destination(params['destination'], settlement)
            return {'destination': target.id, 'enabled': params['enabled']}
        _require(set(params) == {'destination', 'resource', 'direction', 'unit_price', 'quota'},
                 'invalid_action', 'Trade terms require destination, resource, direction, unit_price and quota.')
        target = self._destination(params['destination'], settlement)
        resource, direction = params['resource'], params['direction']
        _require(type(resource) is str and resource in ('food', 'wood', 'iron'),
                 'invalid_resource', 'Trade food, wood or iron between settlements.')
        _require(type(direction) is str and direction in ('export', 'import'),
                 'invalid_action', 'Trade direction must be export or import.')
        price = _number(params['unit_price'], 'unit_price', minimum=.1, maximum=20)
        quota = _number(params['quota'], 'quota', minimum=1, maximum=40, integral=True)
        return {'destination': target.id, 'resource': resource, 'direction': direction,
                'unit_price': price, 'quota': quota}

    def _check_propose(self, actor, settlement, params):
        details = super()._check_propose(actor, settlement, params)
        if details['kind'] == 'migration_policy':
            _require(getattr(details['institution'], 'purpose', None) == 'council',
                     'insufficient_authority', 'Only a council can propose settlement migration rules.')
        return details

    @staticmethod
    def _embargoed(institution, frame, destination):
        def closed(rules):
            embargoes = rules.get('embargoes', {})
            return embargoes.get(destination, embargoes.get(str(destination), False)) is True
        return closed(institution.rules) or bool(frame and closed(frame.get('rules', {})))

    def _check_enact(self, actor, settlement, params):
        institution, frame = self._institution(actor, settlement, params)
        proposal = self._proposal(institution, params)
        if proposal['kind'] not in REGIONAL_KINDS:
            return super()._check_enact(actor, settlement, params)
        _require(approved(self.world, institution, proposal, frame), 'not_approved',
                 'Execution requires a prior-tick majority and at least two consenting members.')
        normalized = self._proposal_params(proposal['kind'], proposal['params'], settlement)
        reciprocal = None
        if proposal['kind'] == 'migration_policy':
            _require(getattr(institution, 'purpose', None) == 'council',
                     'insufficient_authority', 'Only a council can set settlement migration rules.')
            local = {a.id for a in self.world.agents if a.home == settlement.id}
            supporters = len(institution.members & set(frame['members']) & local)
            current_count = self.world.local_named_count(settlement.id)
            original_count = frame.get('local_named_count', current_count)
            _require(supporters * 2 > current_count and supporters * 2 > original_count,
                     'insufficient_authority',
                     'A border mandate requires a council representing a majority of local people at tick start and now.')
        elif proposal['kind'] == 'trade_terms':
            destination = normalized['destination']
            _require(not self._embargoed(institution, frame, destination),
                     'embargoed', 'The sponsor has closed its trade with that settlement.')
            for other in sorted(self.world.institutions, key=lambda i: i.id):
                if not other.active or other.settlement_id != destination:
                    continue
                other_frame = self.world.institution_frame(other)
                if self._embargoed(other, other_frame, settlement.id):
                    continue
                for candidate in other.decisions:
                    terms = candidate.get('params', {})
                    if (candidate.get('kind') == 'trade_terms'
                            and terms.get('destination') == settlement.id
                            and terms.get('resource') == normalized['resource']
                            and terms.get('direction') == ('import' if normalized['direction'] == 'export' else 'export')
                            and terms.get('unit_price') == normalized['unit_price']
                            and terms.get('quota') == normalized['quota']
                            and approved(self.world, other, candidate, other_frame)):
                        reciprocal = (other, candidate)
                        break
                if reciprocal:
                    break
            _require(reciprocal is not None, 'no_matching_terms',
                     'The destination needs independently approved matching price, quota and resource terms.')
            other, _ = reciprocal
            exporter, importer = ((institution, other) if normalized['direction'] == 'export'
                                  else (other, institution))
            _require(not any(
                route.get('exporter_institution') == exporter.id
                and route.get('importer_institution') == importer.id
                and route.get('resource') == normalized['resource']
                and route.get('status') in ('active', 'suspended')
                and route.get('expires', self.world.tick) > self.world.tick
                for route in getattr(self.world, 'routes', ())),
                'active_route', 'These sponsors already have an unexpired contract for that resource.')
        return {'institution': institution, 'proposal': proposal, 'params': normalized,
                'reciprocal': reciprocal, 'energy': 2, 'costs': {}}

    def _apply(self, action, actor, settlement, details):
        if action.type == 'form_institution':
            institution = RegionalInstitution(self.world.next_institution_id,
                                              details['name'], settlement.id,
                                              members={actor.id}, founded=self.world.tick,
                                              purpose=details['purpose'])
            self.world.next_institution_id += 1
            self.world.institutions.append(institution)
            actor.inventory['coins'] -= 2
            self._metric('institutions_formed')
            message = f'{actor.name} founded {institution.name}, a {institution.purpose}.'
            self._announcement(institution, actor, message)
            return {'institution_id': institution.id, 'purpose': institution.purpose,
                    'costs': {'coins': 2.}, 'message': message}
        if action.type != 'enact' or details['proposal']['kind'] not in REGIONAL_KINDS:
            result = super()._apply(action, actor, settlement, details)
            if action.type == 'propose' and details['kind'] == 'trade_terms':
                self._metric('negotiation_attempts')
            return result
        institution, proposal = details['institution'], details['proposal']
        kind, params = proposal['kind'], details['params']
        effects = {'institution_id': institution.id, 'proposal_id': proposal['id'],
                   'project': kind, 'costs': {}}
        if kind == 'trade_terms':
            other, reciprocal = details['reciprocal']
            route = self.world.open_route(institution, other, proposal, reciprocal)
            if isinstance(route, dict):
                effects['route_id'] = route['id']
            reciprocal.update(status='enacted', enacted=self.world.tick, executed_by=actor.id)
            message = (f'{actor.name} opened a negotiated {params["resource"]} route '
                       f'with {self.world.settlements[other.settlement_id].name} '
                       f'at {params["unit_price"]:g} coins per unit, quota {params["quota"]}.')
        elif kind == 'embargo':
            institution.rules.setdefault('embargoes', {})[params['destination']] = params['enabled']
            self._metric('embargo_mandates')
            message = (f'{actor.name} {"closed" if params["enabled"] else "reopened"} '
                       f'{institution.name}\'s trade with {self.world.settlements[params["destination"]].name}.')
        elif kind == 'specialization':
            institution.rules['specialization'] = params['resource']
            self._metric('specialization_mandates')
            message = f'{actor.name} enacted {institution.name}\'s {params["resource"]} specialization mandate.'
        else:
            institution.rules['migration_open'] = params['open']
            self._metric('border_mandates')
            message = f'{actor.name} {"opened" if params["open"] else "closed"} the settlement to migration under a council mandate.'
        proposal.update(status='enacted', enacted=self.world.tick, executed_by=actor.id)
        self._metric('institution_enactments')
        self._announcement(institution, actor, message)
        return {**effects, 'message': message}
