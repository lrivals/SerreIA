"""Near-duplicate grouping on pHash (docs/02-donnees.md §3)."""

import numpy as np

from vision.datasets.near_duplicates import group_near_duplicates


def flip(h: int, bits: list[int]) -> int:
    for b in bits:
        h ^= 1 << b
    return h


def test_threshold():
    base = 0x0123_4567_89AB_CDEF
    hashes = np.array(
        [base, flip(base, [0, 9, 18, 27, 36, 45]), flip(base, list(range(7)))], dtype=np.uint64
    )
    g = group_near_duplicates(hashes, max_dist=6)
    assert g[0] == g[1]  # distance 6, spread over every chunk
    assert g[2] != g[0]  # distance 7


def test_transitive():
    a = 0
    b = flip(a, [0, 1, 2, 3, 4, 5])
    c = flip(b, [10, 11, 12, 13, 14, 15])  # 12 bits from a
    g = group_near_duplicates(np.array([a, b, c, 0xFFFF_0000_0000_0000], dtype=np.uint64))
    assert g[0] == g[1] == g[2]
    assert g[3] != g[0]


def test_high_bits_and_ids():
    h = np.array([2**64 - 1, 2**64 - 2, 0], dtype=np.uint64)
    g = group_near_duplicates(h)
    assert list(g) == [1, 1, 0] or list(g) == [0, 0, 1]


def test_matches_brute_force():
    rng = np.random.default_rng(0)
    base = rng.integers(0, 2**63, size=40, dtype=np.uint64)
    noisy = base ^ (np.uint64(1) << rng.integers(0, 64, size=40).astype(np.uint64))
    h = np.concatenate([base, noisy, base[:10]])
    g = group_near_duplicates(h)
    d = np.bitwise_count(h[:, None] ^ h[None, :]) <= 6
    # brute-force connected components
    n = len(h)
    comp = list(range(n))
    changed = True
    while changed:
        changed = False
        for i in range(n):
            for j in np.flatnonzero(d[i]):
                m = min(comp[i], comp[j])
                if comp[i] != m or comp[j] != m:
                    comp[i] = comp[j] = m
                    changed = True
    for i in range(n):
        for j in range(n):
            assert (g[i] == g[j]) == (comp[i] == comp[j])


def test_confirm_hash_breaks_false_links():
    a, b = 0, flip(0, [0, 1, 2])  # close pHash
    ph = np.array([a, b], dtype=np.uint64)
    same = np.array([5, 5], dtype=np.uint64)
    far = np.array([0, 0xFFFF], dtype=np.uint64)  # dHash 16 bits apart
    assert group_near_duplicates(ph, confirm=same)[0] == group_near_duplicates(ph, confirm=same)[1]
    g = group_near_duplicates(ph, confirm=far, max_confirm_dist=8)
    assert g[0] != g[1]
