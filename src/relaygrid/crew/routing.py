from __future__ import annotations
from dataclasses import dataclass
import heapq

@dataclass(frozen=True)
class RoadEdge:
    a: str
    b: str
    minutes: float
    blocked: bool=False

def route(start: str, goal: str, edges: list[RoadEdge]) -> tuple[float, tuple[str, ...]]:
    if start==goal: return 0.0,(start,)
    adj: dict[str,list[tuple[str,float]]]={}
    for e in edges:
        if e.blocked: continue
        if e.minutes < 0: raise ValueError("negative travel time")
        adj.setdefault(e.a,[]).append((e.b,e.minutes)); adj.setdefault(e.b,[]).append((e.a,e.minutes))
    pq=[(0.0,start)]; best={start:0.0}; prev={}
    while pq:
        d,u=heapq.heappop(pq)
        if d!=best.get(u): continue
        if u==goal:
            path=[goal]; n=goal
            while n!=start: n=prev[n]; path.append(n)
            path.reverse()
            return d,tuple(path)
        for v,w in adj.get(u,[]):
            nd=d+w
            if nd < best.get(v,float('inf')):
                best[v]=nd; prev[v]=u; heapq.heappush(pq,(nd,v))
    return float('inf'),()

def shortest_minutes(start: str, goal: str, edges: list[RoadEdge]) -> float:
    return route(start,goal,edges)[0]

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
