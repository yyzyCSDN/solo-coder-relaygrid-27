from __future__ import annotations
from dataclasses import dataclass
import heapq

@dataclass(frozen=True)
class RoadEdge:
    a: str
    b: str
    minutes: float
    blocked: bool=False

@dataclass(frozen=True)
class RoadSnapshot:
    """Immutable view of the road network at a given closure version.

    A dispatch is planned against one snapshot; the accepted order keeps
    that version so later closure updates cannot silently change the route.
    """
    version: int
    edges: tuple[RoadEdge, ...]
    captured_at_min: float=0.0

@dataclass(frozen=True)
class RoutePlan:
    """A route planned against a specific road snapshot."""
    snapshot_version: int
    source: str
    path: tuple[str, ...]
    travel_min: float

    @property
    def reachable(self) -> bool:
        return bool(self.path)


def shortest_path(start: str, goal: str, edges: list[RoadEdge]) -> tuple[list[str] | None, float]:
    """Dijkstra shortest path.

    Returns (path_nodes, minutes); (None, inf) when no unblocked route exists.
    """
    if start==goal: return [start], 0.0
    adj: dict[str,list[tuple[str,float]]]={}
    for e in edges:
        if e.blocked: continue
        if e.minutes < 0: raise ValueError("negative travel time")
        adj.setdefault(e.a,[]).append((e.b,e.minutes)); adj.setdefault(e.b,[]).append((e.a,e.minutes))
    pq=[(0.0,start)]; best={start:0.0}; prev={start:None}
    while pq:
        d,u=heapq.heappop(pq)
        if d!=best.get(u): continue
        if u==goal:
            path=[]; node=u
            while node is not None:
                path.append(node); node=prev[node]
            path.reverse()
            return path,d
        for v,w in adj.get(u,[]):
            nd=d+w
            if nd < best.get(v,float('inf')):
                best[v]=nd; prev[v]=u; heapq.heappush(pq,(nd,v))
    return None,float('inf')


def shortest_minutes(start: str, goal: str, edges: list[RoadEdge]) -> float:
    _, minutes = shortest_path(start, goal, edges)
    return minutes


def plan_route(snapshot: RoadSnapshot, start: str, goal: str, source: str="road_snapshot") -> RoutePlan | None:
    """Plan a route against a snapshot, recording the closure version and source."""
    path, minutes = shortest_path(start, goal, snapshot.edges)
    if path is None: return None
    return RoutePlan(snapshot.version, source, tuple(path), minutes)


def choose_crew(job_node: str, crews: list[tuple[str,str,float]], edges: list[RoadEdge], required_skill: str, skills: dict[str,set[str]]):
    candidates=[]
    for crew_id,node,available_at in crews:
        if required_skill not in skills.get(crew_id,set()): continue
        travel=shortest_minutes(node,job_node,edges)
        if travel==float('inf'): continue
        candidates.append((available_at+travel,travel,crew_id))
    if not candidates: return None
    eta,travel,crew_id=min(candidates)
    return {"crew_id":crew_id,"eta_min":eta,"travel_min":travel}
