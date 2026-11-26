"""Find near-duplicate pages inside one site.

Large sets of pages that share most of their text (programmatic or templated pages) are a
common reason Google stops indexing a site, so the audit measures how much of each site they
make up. Similarity is estimated from the bottom-k sketches built in ace/page.py.
"""
from __future__ import annotations

import heapq

from .page import SKETCH_SIZE, Page

# Share of 3-word phrases two pages must have in common to count as near-duplicates.
# Calibrated on the 2026-11-26 run: hand-written articles sit near 0.06 to their closest
# sibling, templated pages near 0.7, so 0.5 separates them with a wide margin.
THRESHOLD = 0.5


def similarity(a: list[int], b: list[int]) -> float:
    """Estimated Jaccard similarity of two pages' text, 0.0 to 1.0 (error about +/-0.05)."""
    if not a or not b:
        return 0.0
    sa, sb = set(a), set(b)
    k = min(SKETCH_SIZE, len(sa | sb))
    smallest = heapq.nsmallest(k, sa | sb)
    return sum(1 for h in smallest if h in sa and h in sb) / k


def clusters(pages: list[Page], threshold: float = THRESHOLD) -> dict[str, int]:
    """Return {url: cluster size} for every page that has at least one near-duplicate."""
    cands = [p for p in pages if len(p.sketch) >= SKETCH_SIZE // 2]
    sets = [set(p.sketch) for p in cands]
    parent = list(range(len(cands)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    floor = int(SKETCH_SIZE * threshold * 0.5)  # cheap pre-filter before the exact estimate
    for i in range(len(cands)):
        for j in range(i + 1, len(cands)):
            if len(sets[i] & sets[j]) < floor:
                continue
            if similarity(cands[i].sketch, cands[j].sketch) >= threshold:
                parent[find(i)] = find(j)
    sizes: dict[int, int] = {}
    for i in range(len(cands)):
        sizes[find(i)] = sizes.get(find(i), 0) + 1
    return {p.url: sizes[find(i)] for i, p in enumerate(cands) if sizes[find(i)] > 1}
