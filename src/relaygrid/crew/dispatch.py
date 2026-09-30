from __future__ import annotations
from dataclasses import dataclass
from relaygrid.crew.routing import route
from relaygrid.crew.roads import RoadAtlas, RoadSnapshot
from relaygrid.crew.shifts import Shift, Assignment, worked_minutes, rest_violation

@dataclass(frozen=True)
class CrewState:
    crew_id: str
    node: str
    skills: frozenset[str]
    shift: Shift

@dataclass(frozen=True)
class DispatchDecision:
    """A dispatch plan validated in a single decision: skill, route, shift
    window, work limit and rest were all checked before it was produced."""
    job_id: str
    job_node: str
    crew_id: str
    closure_version: int
    route: tuple[str, ...]
    travel_min: float
    depart_min: float
    eta_min: float
    work_end_min: float
    duration_min: float
    ready_min: float

@dataclass(frozen=True)
class AcceptedDispatch:
    """Persisted record of a confirmed dispatch. Frozen once accepted: a new
    closure version can only supersede it through an explicit accept_replan."""
    decision: DispatchDecision
    seq: int
    supersedes: int | None = None
    @property
    def job_id(self): return self.decision.job_id
    @property
    def crew_id(self): return self.decision.crew_id
    @property
    def closure_version(self): return self.decision.closure_version
    @property
    def route(self): return self.decision.route
    @property
    def depart_min(self): return self.decision.depart_min
    @property
    def eta_min(self): return self.decision.eta_min

@dataclass(frozen=True)
class ReplanProposal:
    """Re-planning suggestion under a newer closure version. Carrying it
    changes nothing; only accept_replan rewrites the accepted record."""
    job_id: str
    crew_id: str
    current: AcceptedDispatch
    closure_version: int
    candidate: DispatchDecision | None
    note: str

def _slot_violation(shift: Shift, assignments: list[Assignment], start: float, end: float) -> str | None:
    if start<shift.start_min or end>shift.end_min: return "shift_window"
    for a in assignments:
        if a.crew_id!=shift.crew_id: continue
        if not (end<=a.start_min or start>=a.end_min): return "overlap"
    projected=worked_minutes(assignments,shift.crew_id,shift.start_min,shift.end_min)+(end-start)
    if projected>shift.max_work_min: return "max_work"
    probe=Assignment(shift.crew_id,"",start,end)
    for a in assignments:
        if a.crew_id!=shift.crew_id: continue
        prev,nxt=(probe,a) if end<=a.start_min else (a,probe)
        if rest_violation(prev,nxt,shift.min_rest_min): return "rest"
    return None

class DispatchBoard:
    def __init__(self, atlas: RoadAtlas, crews: list[CrewState], assignments=()):
        self._atlas=atlas
        self._crews={c.crew_id:c for c in crews}
        self._assignments=list(assignments)
        self._accepted: dict[str,AcceptedDispatch]={}
        self._history: list[AcceptedDispatch]=[]
        self._seq=0

    @property
    def assignments(self) -> tuple[Assignment, ...]: return tuple(self._assignments)

    def accepted(self, job_id: str) -> AcceptedDispatch | None:
        return self._accepted.get(job_id)

    def history(self, job_id: str) -> list[AcceptedDispatch]:
        return [r for r in self._history if r.job_id==job_id]

    def _evaluate_crew(self, crew: CrewState, job_id: str, job_node: str, duration_min: float,
                       now_min: float, ready_min: float, snap: RoadSnapshot, assignments):
        travel,path=route(crew.node,job_node,snap.open_edges())
        if travel==float('inf'): return None,"unreachable"
        depart=max(now_min,crew.shift.start_min,ready_min-travel)
        eta=depart+travel; work_end=eta+duration_min
        reason=_slot_violation(crew.shift,assignments,depart,work_end)
        if reason: return None,reason
        return DispatchDecision(job_id,job_node,crew.crew_id,snap.version,path,travel,
                                depart,eta,work_end,duration_min,ready_min),None

    def evaluate(self, job_id: str, job_node: str, required_skill: str, duration_min: float,
                 now_min: float, ready_min: float=0.0):
        if duration_min<0: raise ValueError("negative duration")
        snap=self._atlas.snapshot()
        best=None; rejections={}
        for crew_id in sorted(self._crews):
            crew=self._crews[crew_id]
            if required_skill not in crew.skills:
                rejections[crew_id]="skill"; continue
            cand,reason=self._evaluate_crew(crew,job_id,job_node,duration_min,now_min,ready_min,snap,self._assignments)
            if cand is None: rejections[crew_id]=reason; continue
            if best is None or (cand.eta_min,cand.crew_id)<(best.eta_min,best.crew_id): best=cand
        return best,rejections

    def plan(self, job_id: str, job_node: str, required_skill: str, duration_min: float,
             now_min: float, ready_min: float=0.0) -> DispatchDecision | None:
        return self.evaluate(job_id,job_node,required_skill,duration_min,now_min,ready_min)[0]

    def confirm(self, decision: DispatchDecision) -> AcceptedDispatch:
        if decision.job_id in self._accepted:
            raise ValueError("job already accepted; use propose_replan/accept_replan")
        crew=self._crews.get(decision.crew_id)
        if crew is None: raise ValueError("unknown crew")
        reason=_slot_violation(crew.shift,self._assignments,decision.depart_min,decision.work_end_min)
        if reason: raise ValueError(f"decision no longer valid: {reason}")
        self._assignments.append(Assignment(decision.crew_id,decision.job_id,decision.depart_min,decision.work_end_min))
        self._seq+=1
        rec=AcceptedDispatch(decision,self._seq)
        self._accepted[decision.job_id]=rec; self._history.append(rec)
        return rec

    def propose_replan(self, job_id: str, now_min: float) -> ReplanProposal | None:
        cur=self._accepted.get(job_id)
        if cur is None: raise ValueError("no accepted dispatch for job")
        snap=self._atlas.snapshot()
        if snap.version==cur.closure_version: return None
        d=cur.decision
        crew=self._crews.get(d.crew_id)
        if crew is None: raise ValueError("unknown crew")
        others=[a for a in self._assignments if not (a.crew_id==d.crew_id and a.job_id==job_id)]
        cand,reason=self._evaluate_crew(crew,job_id,d.job_node,d.duration_min,now_min,d.ready_min,snap,others)
        if cand is None: return ReplanProposal(job_id,d.crew_id,cur,snap.version,None,reason)
        note="unaffected" if (cand.route,cand.depart_min,cand.eta_min)==(d.route,d.depart_min,d.eta_min) else "route_changed"
        return ReplanProposal(job_id,d.crew_id,cur,snap.version,cand,note)

    def accept_replan(self, proposal: ReplanProposal) -> AcceptedDispatch:
        if proposal.candidate is None: raise ValueError("proposal has no feasible candidate")
        cur=self._accepted.get(proposal.job_id)
        if cur!=proposal.current: raise ValueError("stale proposal")
        cand=proposal.candidate
        crew=self._crews.get(cand.crew_id)
        if crew is None: raise ValueError("unknown crew")
        others=[a for a in self._assignments if not (a.crew_id==cand.crew_id and a.job_id==cand.job_id)]
        reason=_slot_violation(crew.shift,others,cand.depart_min,cand.work_end_min)
        if reason: raise ValueError(f"candidate no longer valid: {reason}")
        self._assignments=others+[Assignment(cand.crew_id,cand.job_id,cand.depart_min,cand.work_end_min)]
        self._seq+=1
        rec=AcceptedDispatch(cand,self._seq,cur.seq)
        self._accepted[cand.job_id]=rec; self._history.append(rec)
        return rec
