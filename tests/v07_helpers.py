from eternia.regional_engine import RegionalInstitution


def add_council(world, town=0, *, purpose='council', members=None):
    people = [a.id for a in world.agents if a.home == town]
    institution = RegionalInstitution(world.next_institution_id, 'Test assembly ' + str(town),
                                      town, members=set(people if members is None else members),
                                      purpose=purpose)
    world.next_institution_id += 1
    world.institutions.append(institution)
    return institution


def proposal(world, council, kind, params, *, approved=True):
    identity = world.next_proposal_id
    world.next_proposal_id += 1
    decision = dict(id=identity, kind=kind, params=params, proposer=min(council.members),
                    electorate=sorted(council.members),
                    votes={a: {'approve': True, 'tick': world.tick - 1} for a in council.members}
                    if approved else {},
                    created=world.tick - 2, expires=world.tick + 12, status='open')
    council.decisions.append(decision)
    return decision


def funded_order(world, town=0, resource='iron', quantity=8, wage=2):
    council = add_council(world, town)
    world.advance_time()
    world.advance_time()
    decision = proposal(world, council, 'work_order',
                        dict(resource=resource, quantity=quantity, unit_wage=wage))
    actor = min(council.members)
    result = world.submit_action(dict(actor=actor, type='enact',
                                     institution=council.id, proposal=decision['id']))
    assert result.success, result.message
    world.advance_time()
    return council, world.work_orders[-1]


def chartered_route(world):
    left, right = add_council(world, 0), add_council(world, 1)
    world.settlements[0].food += world.settlements[1].food
    world.settlements[1].food = 0.
    route = dict(id=world.next_route_id, exporter=0, importer=1,
                 exporter_institution=left.id, importer_institution=right.id,
                 resource='food', unit_price=.2, quota=20, created=-1, expires=100,
                 active=True, status='active', volume=0., shipments=0, proposals=[])
    world.next_route_id += 1
    world.routes.append(route)
    return left, right, route

