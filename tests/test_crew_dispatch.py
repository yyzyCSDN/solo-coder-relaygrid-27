import pytest

from relaygrid.crew.routing import RoadEdge, RoadSnapshot, shortest_path, shortest_minutes
from relaygrid.crew.shifts import Shift, Assignment
from relaygrid.crew.dispatch import (
    CrewProfile, DispatchRequest, DispatchOrder, DispatchDecision,
    decide_dispatch, replan_advice,
)


def make_net(version=1, blocked=()):
    edges=[
        RoadEdge('base','a',5),
        RoadEdge('a','job',6),
        RoadEdge('base','job',20),
    ]
    blocked={(x,y) for x,y in blocked}
    edges=[RoadEdge(e.a,e.b,e.minutes,
                    blocked=(e.a,e.b) in blocked or (e.b,e.a) in blocked)
           for e in edges]
    return RoadSnapshot(version,tuple(edges),captured_at_min=0.0)


def make_crew(shift=None, skills=frozenset({'electric'}), base='base'):
    shift=shift or Shift('c1',0.0,480.0,480.0,60.0)
    return CrewProfile('c1',shift,skills,base)


def make_request(**kw):
    vals=dict(job_id='j1',job_node='job',required_skill='electric',
              departure_min=60.0,duration_min=60.0)
    vals.update(kw)
    return DispatchRequest(**vals)


def test_snapshot_plans_path_with_version():
    snap=make_net(1)
    path,minutes=shortest_path('base','job',snap.edges)
    assert path==['base','a','job'] and minutes==11
    assert shortest_minutes('base','job',snap.edges)==11


def test_snapshot_is_immutable():
    snap=make_net(1)
    with pytest.raises(AttributeError):
        snap.version=2


def test_decide_accepts_and_freezes_order():
    decision=decide_dispatch(make_request(),make_crew(),make_net(1))
    assert decision.accepted and bool(decision)
    order=decision.order
    assert order.snapshot_version==1
    assert order.source=='road_snapshot'
    assert order.route_path==('base','a','job')
    assert order.travel_min==11.0
    assert order.departure_min==60.0
    assert order.eta_min==71.0


def test_decide_rejects_missing_skill():
    decision=decide_dispatch(make_request(),make_crew(skills=frozenset()),make_net(1))
    assert not decision.accepted and decision.order is None
    assert 'skill_missing' in decision.reasons


def test_decide_rejects_when_all_routes_blocked():
    snap=make_net(1,blocked={('base','a'),('a','job'),('base','job')})
    decision=decide_dispatch(make_request(),make_crew(),snap)
    assert not decision.accepted
    assert 'no_route' in decision.reasons


def test_decide_rejects_outside_shift():
    decision=decide_dispatch(make_request(departure_min=470.0,duration_min=30.0),make_crew(),make_net(1))
    assert not decision.accepted
    assert 'beyond_shift_end' in decision.reasons


def test_decide_rejects_rest_violation():
    previous=Assignment('c1','j0',0.0,50.0)
    decision=decide_dispatch(make_request(departure_min=100.0),make_crew(),make_net(1),[previous])
    assert not decision.accepted
    assert 'rest_violation' in decision.reasons


def test_single_decision_collects_skill_route_and_rest():
    snap=make_net(1,blocked={('base','a'),('a','job'),('base','job')})
    previous=Assignment('c1','j0',0.0,50.0)
    decision=decide_dispatch(make_request(departure_min=100.0),
                             make_crew(skills=frozenset()),snap,[previous])
    assert not decision.accepted
    assert {'skill_missing','no_route','rest_violation'} <= set(decision.reasons)


def test_accepted_order_eta_is_frozen():
    order=decide_dispatch(make_request(),make_crew(),make_net(1)).order
    with pytest.raises(AttributeError):
        order.eta_min=999.0


def test_replan_advice_suggests_without_mutating_order():
    order=decide_dispatch(make_request(),make_crew(),make_net(1)).order
    snap2=make_net(2,blocked={('a','job')})  # new closure on the old route
    advice=replan_advice(order,snap2)
    # accepted order keeps the confirmed snapshot/route/ETA
    assert order.snapshot_version==1
    assert order.route_path==('base','a','job')
    assert order.eta_min==71.0
    # advice is advisory only
    assert advice.snapshot_version==2
    assert advice.reachable
    assert advice.suggested_path==('base','job')
    assert advice.suggested_eta_min==80.0
    assert advice.eta_delta_min==9.0
    assert advice.route_changed
    assert len(advice.closures_on_route)==1
    assert advice.note=='new_closures_on_route'


def test_replan_advice_unreachable_keeps_accepted_eta():
    order=decide_dispatch(make_request(),make_crew(),make_net(1)).order
    snap2=make_net(2,blocked={('base','a'),('a','job'),('base','job')})
    advice=replan_advice(order,snap2)
    assert not advice.reachable
    assert advice.suggested_eta_min is None
    assert order.eta_min==71.0
    assert order.snapshot_version==1


def test_replan_advice_unchanged_route():
    order=decide_dispatch(make_request(),make_crew(),make_net(1)).order
    advice=replan_advice(order,make_net(2))
    assert advice.note=='route_unchanged'
    assert not advice.route_changed
    assert advice.eta_delta_min==0.0
