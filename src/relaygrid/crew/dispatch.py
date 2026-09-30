"""Crew dispatch: one decision, one immutable accepted order.

A dispatch decision checks shift window, skill, road distance (route), and
rest limits together in a single decision. Once a task is confirmed the
closure version, route, departure time and ETA are frozen on the order; a
new road closure can only produce replanning advice, never a silent rewrite
of the accepted ETA.
"""
from __future__ import annotations
from dataclasses import dataclass

from .shifts import Assignment, Shift, worked_minutes
from .routing import RoadEdge, RoadSnapshot, plan_route


@dataclass(frozen=True)
class CrewProfile:
    crew_id: str
    shift: Shift
    skills: frozenset[str]
    base_node: str


@dataclass(frozen=True)
class DispatchRequest:
    job_id: str
    job_node: str
    required_skill: str
    departure_min: float
    duration_min: float=0.0


@dataclass(frozen=True)
class DispatchOrder:
    """Confirmed dispatch task. Frozen so the accepted ETA cannot drift."""
    job_id: str
    crew_id: str
    origin_node: str
    job_node: str
    snapshot_version: int
    source: str
    route_path: tuple[str, ...]
    travel_min: float
    departure_min: float
    eta_min: float


@dataclass(frozen=True)
class ReplanAdvice:
    """Advisory replan against a newer road snapshot. Never auto-applied."""
    order: DispatchOrder
    snapshot_version: int
    reachable: bool
    suggested_path: tuple[str, ...] | None
    suggested_travel_min: float | None
    suggested_eta_min: float | None
    eta_delta_min: float | None
    route_changed: bool
    closures_on_route: tuple[RoadEdge, ...]
    note: str


@dataclass(frozen=True)
class DispatchDecision:
    accepted: bool
    reasons: tuple[str, ...]
    order: DispatchOrder | None

    def __bool__(self) -> bool:
        return self.accepted


def _last_assignment(assignments, crew_id: str):
    latest=None
    for a in assignments:
        if a.crew_id!=crew_id: continue
        if latest is None or a.end_min>latest.end_min: latest=a
    return latest


def _blocked_on_path(snapshot: RoadSnapshot, path: tuple[str, ...]) -> tuple[RoadEdge, ...]:
    by_pair: dict[tuple[str,str],RoadEdge]={}
    for e in snapshot.edges:
        by_pair[(e.a,e.b)]=e; by_pair[(e.b,e.a)]=e
    found=[]
    for i in range(len(path)-1):
        e=by_pair.get((path[i],path[i+1]))
        if e is not None and e.blocked: found.append(e)
    return tuple(found)


def decide_dispatch(request: DispatchRequest, crew: CrewProfile, snapshot: RoadSnapshot, assignments=()) -> DispatchDecision:
    """Validate skill, shift, road distance and rest in a single decision.

    All four checks run before a verdict is returned; the decision is
    accepted only when every check passes, and the confirmed order then
    freezes the snapshot version, route, departure time and ETA.
    """
    reasons: list[str]=[]

    # 1. skill
    if request.required_skill not in crew.skills:
        reasons.append("skill_missing")

    # 2. road distance / route against the supplied snapshot
    route=plan_route(snapshot, crew.base_node, request.job_node)
    travel=route.travel_min if route is not None else None
    if route is None:
        reasons.append("no_route")

    # 3. shift window and work limits (travel + on-site duration)
    shift=crew.shift
    if request.departure_min < shift.start_min:
        reasons.append("before_shift_start")
    if route is not None:
        end_min=request.departure_min+travel+request.duration_min
        if end_min>shift.end_min:
            reasons.append("beyond_shift_end")
        for a in assignments:
            if a.crew_id!=crew.crew_id: continue
            if not (end_min<=a.start_min or request.departure_min>=a.end_min):
                reasons.append("assignment_overlap")
                break
        projected=worked_minutes(list(assignments),crew.crew_id,shift.start_min,shift.end_min)+request.duration_min
        if projected>shift.max_work_min:
            reasons.append("max_work_exceeded")

    # 4. rest limit since the previous assignment
    previous=_last_assignment(assignments,crew.crew_id)
    if previous is not None and request.departure_min-previous.end_min<shift.min_rest_min:
        reasons.append("rest_violation")

    if reasons:
        return DispatchDecision(False,tuple(reasons),None)

    eta=request.departure_min+travel
    order=DispatchOrder(
        request.job_id,crew.crew_id,crew.base_node,request.job_node,
        snapshot.version,route.source,tuple(route.path),travel,
        request.departure_min,eta)
    return DispatchDecision(True,(),order)


def replan_advice(order: DispatchOrder, new_snapshot: RoadSnapshot) -> ReplanAdvice:
    """Replan an accepted order against a newer closure snapshot.

    The accepted order is never modified; only advisory fields are returned
    so a new closure can never silently rewrite the accepted ETA.
    """
    route=plan_route(new_snapshot, order.origin_node, order.job_node)
    blocked=_blocked_on_path(new_snapshot, order.route_path)
    if route is None:
        note="unreachable_under_new_closures" if blocked else "no_route"
        return ReplanAdvice(order,new_snapshot.version,False,None,None,None,None,True,blocked,note)
    changed=route.path!=order.route_path or route.travel_min!=order.travel_min
    eta=order.departure_min+route.travel_min
    delta=eta-order.eta_min
    if blocked:
        note="new_closures_on_route"
    elif changed:
        note="route_changed"
    else:
        note="route_unchanged"
    return ReplanAdvice(order,new_snapshot.version,True,tuple(route.path),route.travel_min,eta,delta,changed,blocked,note)
