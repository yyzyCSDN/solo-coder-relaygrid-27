from __future__ import annotations
from dataclasses import dataclass
from relaygrid.crew.routing import RoadEdge

def _key(a: str, b: str) -> tuple[str, str]:
    return (a,b) if a<=b else (b,a)

@dataclass(frozen=True)
class RoadSnapshot:
    """Immutable, versioned view of the road network.

    A dispatch decision cites the snapshot version it was planned against,
    so an accepted ETA always keeps the provenance of its closures.
    """
    version: int
    edges: tuple[RoadEdge, ...]
    closures: frozenset[tuple[str, str]] = frozenset()

    def open_edges(self) -> list[RoadEdge]:
        return [e for e in self.edges if not e.blocked and _key(e.a,e.b) not in self.closures]

class RoadAtlas:
    """Publishes road snapshots; new closures bump the version and never
    mutate snapshots that dispatches already referenced."""
    def __init__(self, edges):
        self._edges=tuple(edges); self._closures=frozenset(); self._version=0
    @property
    def version(self) -> int: return self._version
    def snapshot(self) -> RoadSnapshot:
        return RoadSnapshot(self._version,self._edges,self._closures)
    def set_closures(self, pairs) -> RoadSnapshot:
        self._closures=frozenset(_key(a,b) for a,b in pairs); self._version+=1
        return self.snapshot()
    def close(self, *pairs) -> RoadSnapshot:
        return self.set_closures(set(self._closures)|{_key(a,b) for a,b in pairs})
    def reopen(self, *pairs) -> RoadSnapshot:
        return self.set_closures(set(self._closures)-{_key(a,b) for a,b in pairs})
