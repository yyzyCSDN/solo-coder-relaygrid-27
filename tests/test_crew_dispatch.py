import pytest
from relaygrid.crew.routing import RoadEdge, route, shortest_minutes
from relaygrid.crew.roads import RoadAtlas
from relaygrid.crew.shifts import Shift, Assignment
from relaygrid.crew.dispatch import CrewState, DispatchBoard

EDGES=[RoadEdge('D','A',10),RoadEdge('A','S',10),RoadEdge('D','B',30),RoadEdge('B','S',30)]

def crew(cid,skills=('line',),node='D',min_rest=30,max_work=400):
    return CrewState(cid,node,frozenset(skills),Shift(cid,0,480,max_work,min_rest))

def board(*crews,assignments=()):
    return DispatchBoard(RoadAtlas(EDGES),list(crews),assignments)

def test_route_returns_path():
    assert route('D','S',EDGES)==(20.0,('D','A','S'))
    assert shortest_minutes('D','S',EDGES)==20.0
    assert route('D','S',[])==(float('inf'),())

def test_confirm_persists_closure_version_route_departure_eta():
    b=board(crew('c1'))
    d=b.plan('j1','S','line',60,now_min=100)
    assert (d.closure_version,d.route,d.depart_min,d.eta_min)==(0,('D','A','S'),100.0,120.0)
    rec=b.confirm(d)
    assert (rec.closure_version,rec.route,rec.depart_min,rec.eta_min)==(0,('D','A','S'),100.0,120.0)

def test_departure_respects_ready_time():
    b=board(crew('c1'))
    d=b.plan('j1','S','line',60,now_min=100,ready_min=200)
    assert (d.depart_min,d.eta_min)==(180.0,200.0)

def test_skill_checked_in_same_decision():
    b=board(crew('c2',skills=('tree',)))
    d,rej=b.evaluate('j1','S','line',60,now_min=100)
    assert d is None and rej=={'c2':'skill'}

def test_rest_checked_in_same_decision():
    b=board(crew('c1'),assignments=[Assignment('c1','prev',60,100)])
    d,rej=b.evaluate('j1','S','line',60,now_min=100)
    assert d is None and rej['c1']=='rest'

def test_shift_window_checked_in_same_decision():
    b=board(crew('c1'))
    d,rej=b.evaluate('j1','S','line',500,now_min=100)
    assert d is None and rej['c1']=='shift_window'

def test_overlap_and_work_limit_checked_in_same_decision():
    b=board(crew('c1'),assignments=[Assignment('c1','prev',100,200)])
    d,rej=b.evaluate('j1','S','line',60,now_min=100)
    assert d is None and rej['c1']=='overlap'
    b2=board(crew('c1',max_work=60),assignments=[Assignment('c1','prev',0,50)])
    d,rej=b2.evaluate('j1','S','line',60,now_min=100)
    assert d is None and rej['c1']=='max_work'

def test_unreachable_road_checked_in_same_decision():
    b=board(crew('c1'))
    b._atlas.close(('A','S'),('B','S'))
    d,rej=b.evaluate('j1','S','line',60,now_min=100)
    assert d is None and rej['c1']=='unreachable'

def test_plan_picks_earliest_eta_among_valid_crews():
    b=board(crew('c1'),crew('c3',node='A'))
    assert b.plan('j1','S','line',60,now_min=100).crew_id=='c3'

def test_double_confirm_rejected():
    b=board(crew('c1'))
    d=b.plan('j1','S','line',60,now_min=100)
    b.confirm(d)
    with pytest.raises(ValueError): b.confirm(d)

def test_new_closure_proposes_but_never_rewrites_accepted_eta():
    b=board(crew('c1'))
    rec=b.confirm(b.plan('j1','S','line',60,now_min=100))
    b._atlas.close(('A','S'))
    assert b.accepted('j1').eta_min==120.0 and b.accepted('j1').closure_version==0
    prop=b.propose_replan('j1',now_min=100)
    assert prop.note=='route_changed' and prop.closure_version==1
    assert prop.candidate.route==('D','B','S') and prop.candidate.eta_min==160.0
    assert b.accepted('j1').eta_min==120.0 and b.accepted('j1').closure_version==0
    new=b.accept_replan(prop)
    assert (new.eta_min,new.closure_version,new.supersedes)==(160.0,1,rec.seq)
    assert b.accepted('j1').eta_min==160.0
    assert [r.seq for r in b.history('j1')]==[rec.seq,new.seq]

def test_unreachable_replan_keeps_accepted_eta():
    b=board(crew('c1'))
    b.confirm(b.plan('j1','S','line',60,now_min=100))
    b._atlas.close(('A','S'),('B','S'))
    prop=b.propose_replan('j1',now_min=100)
    assert prop.candidate is None and prop.note=='unreachable'
    assert b.accepted('j1').eta_min==120.0
    with pytest.raises(ValueError): b.accept_replan(prop)

def test_no_proposal_without_new_closure_version():
    b=board(crew('c1'))
    b.confirm(b.plan('j1','S','line',60,now_min=100))
    assert b.propose_replan('j1',now_min=100) is None

def test_stale_proposal_rejected():
    b=board(crew('c1'))
    b.confirm(b.plan('j1','S','line',60,now_min=100))
    b._atlas.close(('A','S'))
    prop=b.propose_replan('j1',now_min=100)
    b.accept_replan(prop)
    with pytest.raises(ValueError): b.accept_replan(prop)
