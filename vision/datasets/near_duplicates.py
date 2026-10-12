"""Near-duplicate grouping on 64-bit perceptual hashes (docs/02-donnees.md §3)."""

import numpy as np

HASH_BITS = 64
_BLOCK = 2048  # rows per distance block, bounds memory on large buckets


class UnionFind:
    def __init__(self, n: int):
        self.parent = np.arange(n)

    def find(self, i: int) -> int:
        parent = self.parent
        root = i
        while parent[root] != root:
            root = parent[root]
        while parent[i] != root:
            parent[i], i = root, parent[i]
        return root

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[max(ra, rb)] = min(ra, rb)


def _chunks(max_dist: int) -> list[tuple[int, int]]:
    """Split the hash into max_dist + 1 bit ranges (pigeonhole: one range must match exactly)."""
    n = max_dist + 1
    bounds = np.linspace(0, HASH_BITS, n + 1).astype(int)
    return [(int(bounds[i]), int(bounds[i + 1])) for i in range(n)]


def group_near_duplicates(
    hashes: np.ndarray,
    max_dist: int = 6,
    confirm: np.ndarray | None = None,
    max_confirm_dist: int = 8,
) -> np.ndarray:
    """Return a group id per image; near-duplicates share a group.

    Two images are linked when their `hashes` (pHash) are within Hamming distance max_dist and,
    if `confirm` (a second, independent hash such as dHash) is given, when those are within
    max_confirm_dist too. On plain-background PlantVillage leaves the 64-bit pHash alone links
    unrelated images, and union-find chaining then builds one giant group.

    Grouping is transitive (union-find). Group ids are 0..n_groups-1, ordered by first item.
    """
    hashes = np.asarray(hashes, dtype=np.uint64)
    if confirm is not None:
        confirm = np.asarray(confirm, dtype=np.uint64)
    n = len(hashes)
    uf = UnionFind(n)
    for lo, hi in _chunks(max_dist):
        mask = np.uint64((1 << (hi - lo)) - 1)
        keys = (hashes >> np.uint64(lo)) & mask
        order = np.argsort(keys, kind="stable")
        sorted_keys = keys[order]
        starts = np.flatnonzero(np.r_[True, sorted_keys[1:] != sorted_keys[:-1]])
        ends = np.r_[starts[1:], n]
        for s, e in zip(starts, ends, strict=True):
            if e - s < 2:
                continue
            idx = order[s:e]
            h = hashes[idx]
            for b in range(0, len(h), _BLOCK):
                # Row block b..b+_BLOCK against later columns only (upper triangle).
                close = np.bitwise_count(h[b : b + _BLOCK, None] ^ h[None, b:]) <= max_dist
                ii, jj = np.nonzero(np.triu(close, k=1))
                i_glob, j_glob = idx[b + ii], idx[b + jj]
                if confirm is not None:
                    ok = np.bitwise_count(confirm[i_glob] ^ confirm[j_glob]) <= max_confirm_dist
                    i_glob, j_glob = i_glob[ok], j_glob[ok]
                for i, j in zip(i_glob, j_glob, strict=True):
                    uf.union(int(i), int(j))
    roots = np.array([uf.find(i) for i in range(n)])
    _, groups = np.unique(roots, return_inverse=True)
    return groups
