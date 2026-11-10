"""Accounted transport actions and collectively funded physical infrastructure.

Regional diplomatic mandates remain independent of transport. An agreement
permits a member to organize a caravan; geography, reserved cargo and road
capacity still decide whether it can depart. Shared infrastructure requires
the same frozen electorate and prior-tick approval as other public projects.
"""
from copy import deepcopy

from .actions import _number, _require
from .institutions import approved
from .regional_engine import RegionalEngine


ROAD_COSTS = {'wood': 6., 'iron': 1., 'coins': 3.}
PHYSICAL_KINDS = {'repair_route', 'route_access'}


class LogisticsEngine(RegionalEngine):
    parameters = {**RegionalEngine.parameters,
                  'dispatch_caravan': {'route', 'amount'}}

    def _metric(self, name):
        super()._metric(name)
        physical = getattr(self.world, 'physical_metrics', {})
        if name in physical:
            physical[name] += 1

    def _prepare(self, proposal):
        prepared = super()._prepare(proposal)
        action, actor, _, _ = prepared
        _require(not self.world.is_traveling(actor.id) or action.type == 'wait',
                 'in_transit', 'Travelers cannot work or exercise local authority during a journey.')
        return prepared

    def _peer(self, actor, settlement, params):
        target = super()._peer(actor, settlement, params)
        _require(not self.world.is_traveling(target.id), 'remote_action',
                 'A traveling person is unavailable for local cooperation or teaching.')
        return target

    def _check_accept(self, actor, settlement, params):
        details = super()._check_accept(actor, settlement, params)
        _require(not any(self.world.is_traveling(details[party].id) for party in ('seller', 'buyer')),
                 'remote_action', 'A traveling person cannot fulfill a local market offer.')
        return details

    def _link(self, reference, settlement):
        _require(type(reference) is int and reference >= 0, 'unknown_route',
                 'A physical route requires a stable integer ID.')
        link = next((link for link in self.world.links if link['id'] == reference), None)
        _require(link is not None, 'unknown_route', 'That physical route does not exist.')
        _require(settlement.id in (link['a'], link['b']), 'remote_action',
                 'Infrastructure decisions require a local endpoint.')
        return link

    def _link_frame(self, link):
        capture = getattr(self.world, 'link_frame', None)
        frame = capture(link['id']) if capture is not None else deepcopy(link)
        _require(frame is not None, 'route_unavailable', 'The route was not visible at tick start.')
        return frame

    def _check_dispatch_caravan(self, actor, settlement, params):
        reference = params.get('route')
        _require(type(reference) is int and reference >= 0, 'unknown_route',
                 'A caravan requires an approved contract integer ID.')
        route = next((route for route in self.world.routes if route['id'] == reference), None)
        _require(route is not None, 'unknown_route', 'The trade contract does not exist.')
        _require(route['exporter'] == settlement.id, 'remote_action',
                 'A caravan must be organized at its exporting settlement.')
        institution, _ = self._institution(actor, settlement,
                                           {'institution': route['exporter_institution']})
        amount = _number(params.get('amount'), 'amount', minimum=.1, maximum=40)
        details = self.world.caravan_quote(actor, reference, amount)
        return {**details, 'institution': institution, 'energy': details.get('energy', 4)}

    def _check_migrate(self, actor, settlement, params):
        details = super()._check_migrate(actor, settlement, params)
        details['journey'] = self.world.migration_quote(actor, details['destination'].id)
        return details

    def _proposal_params(self, kind, params, settlement):
        if type(kind) is not str or kind not in PHYSICAL_KINDS:
            return super()._proposal_params(kind, params, settlement)
        _require(type(params) is dict and all(type(key) is str for key in params),
                 'invalid_action', 'Infrastructure parameters must be an object with string keys.')
        expected = {'link'} | ({'closed'} if kind == 'route_access' else set())
        _require(set(params) == expected, 'invalid_action',
                 'Repair requires link; access requires link and a boolean closed.')
        link = self._link(params.get('link'), settlement)
        if kind == 'repair_route':
            return {'link': link['id']}
        _require(type(params.get('closed')) is bool, 'invalid_action',
                 'Route access requires a boolean closed.')
        return {'link': link['id'], 'closed': params['closed']}

    def _check_propose(self, actor, settlement, params):
        details = super()._check_propose(actor, settlement, params)
        if details['kind'] in PHYSICAL_KINDS:
            link = self._link(details['params']['link'], settlement)
            frame = self._link_frame(link)
            owner = details['institution'].id
            if details['kind'] == 'repair_route':
                _require(link.get('owner') in (None, owner)
                         and frame.get('owner') in (None, owner),
                         'insufficient_authority', 'An institution cannot claim or repair another owner\'s route.')
            else:
                _require(link.get('owner') == owner and frame.get('owner') == owner,
                         'insufficient_authority', 'Only the owner at tick start and now can propose route access.')
        return details

    def _check_enact(self, actor, settlement, params):
        institution, frame = self._institution(actor, settlement, params)
        proposal = self._proposal(institution, params)
        if proposal['kind'] not in PHYSICAL_KINDS:
            return super()._check_enact(actor, settlement, params)
        _require(approved(self.world, institution, proposal, frame), 'not_approved',
                 'Infrastructure execution requires a prior-tick majority and two consenting members.')
        normalized = self._proposal_params(proposal['kind'], proposal['params'], settlement)
        link = self._link(normalized['link'], settlement)
        original = self._link_frame(link)
        if proposal['kind'] == 'repair_route':
            _require(link.get('owner') in (None, institution.id)
                     and original.get('owner') in (None, institution.id),
                     'insufficient_authority', 'A route belonging to another institution cannot be repaired or claimed.')
            _require(link['condition'] < .9 and original['condition'] < .9,
                     'already_repaired', 'The route does not need another funded repair.')
            available = self.world.available_institution_inventory(institution)
            _require(all(available.get(resource, 0) >= amount for resource, amount in ROAD_COSTS.items()),
                     'insufficient_resources', 'Shared tick-start reserves cannot fund this road repair.')
            costs = dict(ROAD_COSTS)
        else:
            _require(link.get('owner') == institution.id and original.get('owner') == institution.id,
                     'insufficient_authority', 'Only the owner at tick start and now can set route access.')
            costs = {}
        return {'institution': institution, 'proposal': proposal, 'params': normalized,
                'link': link, 'costs': costs, 'energy': 2}

    def _apply(self, action, actor, settlement, details):
        if action.type == 'dispatch_caravan':
            return self.world.launch_caravan(actor, details)
        if action.type == 'migrate':
            return self.world.launch_migration(actor, details['journey'])
        if action.type != 'enact' or details['proposal']['kind'] not in PHYSICAL_KINDS:
            return super()._apply(action, actor, settlement, details)
        institution, proposal, link = details['institution'], details['proposal'], details['link']
        self.world.spend_institution(institution, details['costs'])
        kind = proposal['kind']
        if kind == 'repair_route':
            link['condition'] = min(1., link['condition'] + .45)
            if link.get('owner') is None:
                link['owner'] = institution.id
            self._metric('road_repairs')
            message = f'{actor.name} used {institution.name}\'s approved reserves to repair physical route {link["id"]}.'
        else:
            link['closed'] = details['params']['closed']
            self._metric('route_access_mandates')
            message = f'{actor.name} {"closed" if link["closed"] else "opened"} institution-owned route {link["id"]}.'
        proposal.update(status='enacted', enacted=self.world.tick, executed_by=actor.id)
        self._metric('institution_enactments')
        self._announcement(institution, actor, message)
        return {'institution_id': institution.id, 'proposal_id': proposal['id'],
                'project': kind, 'link': link['id'], 'costs': details['costs'], 'message': message}
