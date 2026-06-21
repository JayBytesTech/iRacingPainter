"""Discover inter-panel seams from the stock paint patterns (no 3D model needed).

The insight: every stock pattern is a design laid out *correctly in 3D*, so two UV
pixels that map to the same 3D point carry the same color in every pattern. The set
of recolorable patterns therefore acts like a structured-light code painted on the
car — a per-pixel "fingerprint" (its color across all N patterns). Panel edges that
are adjacent in 3D but split across the UV unwrap share matching fingerprints along
their shared seam.

For each pair of panels we:
  1. sample an inward ring of edge pixels and build their N-pattern fingerprints,
  2. match informative (high-variance) fingerprints across the pair with a Lowe
     ratio test (kills flat-region ambiguity — a real seam point has ONE distinctly
     closest partner),
  3. fit a robust affine transform (RANSAC) between the matched UV points; a true
     seam yields many inliers with a sub-pixel-coherent transform.

Output: seams.json — a list of {a, b, inliers, residual, transform, samples} that a
renderer can use to continue a design across the seam (map a point on panel A's edge
to its partner on panel B). This is the substrate for the projection milestone:
cross-panel stripes/curves that line up at the seams.

Usage:
    python -m iracing_painter.seams templates/porsche_992_gt3
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage
from scipy.spatial import cKDTree

from .patterns import load_manifest, patterns_dir


def _load_pattern_stack(template_dir: Path) -> np.ndarray:
    """Stack the recolorable patterns into an (N, H, W, 3) uint8 array."""
    rec = [m["id"] for m in load_manifest(template_dir) if m.get("recolor")]
    if not rec:
        raise FileNotFoundError(
            f"no recolorable patterns in {template_dir} — run: "
            f"python -m iracing_painter.extract {template_dir}"
        )
    pdir = patterns_dir(template_dir)
    imgs = [np.array(Image.open(pdir / f"pattern_{pid}.png").convert("RGB")) for pid in rec]
    return np.stack(imgs)


def _inward_ring(mask: np.ndarray, lo: int = 3, hi: int = 7) -> np.ndarray:
    """Pixels forming a ring just inside a segment's edge (avoids seam-line AA).

    Returns coords in (x, y) order so transforms/samples are consumer-friendly.
    """
    ring = ndimage.binary_erosion(mask, iterations=lo) & ~ndimage.binary_erosion(mask, iterations=hi)
    ys, xs = np.where(ring)
    return np.stack([xs, ys], axis=1)


def _fingerprints(stack: np.ndarray, coords: np.ndarray) -> np.ndarray:
    """(N,H,W,3) + (M,2) (x,y) coords -> (M, N*3) float32 fingerprints."""
    sampled = stack[:, coords[:, 1], coords[:, 0], :]  # index [y, x]; (N, M, 3)
    return sampled.transpose(1, 0, 2).reshape(len(coords), -1).astype(np.float32)


def _fit_similarity(src: np.ndarray, dst: np.ndarray):
    """Umeyama similarity (rotation + uniform scale + translation, reflection
    allowed) mapping src->dst. Returns (M 3x2 with X=[x,y,1] @ M = dst, residuals).

    iRacing UV islands keep uniform texel density, so adjacent panels are related
    by a similarity (not a general affine) — this avoids shear/anisotropic stretch
    that would distort a design across elongated panels, and supports mirrored seams.
    """
    src = src.astype(float); dst = dst.astype(float)
    mu_s, mu_d = src.mean(0), dst.mean(0)
    sc, dc = src - mu_s, dst - mu_d
    cov = (dc.T @ sc) / len(src)
    U, S, Vt = np.linalg.svd(cov)
    R = U @ Vt  # reflection allowed (no det correction) -> handles mirrored panels
    var_s = (sc ** 2).sum() / len(src)
    scale = S.sum() / var_s if var_s > 1e-9 else 1.0
    A = scale * R                       # 2x2 linear part (dst = A @ src + t)
    t = mu_d - A @ mu_s
    M = np.vstack([A.T, t])             # (3,2): [x,y,1] @ M = dst
    X = np.hstack([src, np.ones((len(src), 1))])
    resid = np.sqrt(((X @ M - dst) ** 2).sum(1))
    return M, resid


def _ransac_affine(src, dst, iters=300, thresh=6.0, rng=None):
    """Robust affine fit. Returns (transform 3x2, inlier_mask) or (None, None)."""
    rng = rng or np.random.default_rng(0)
    n = len(src)
    if n < 6:
        return None, None
    X = np.hstack([src.astype(float), np.ones((n, 1))])
    best_inl = None
    for _ in range(iters):
        idx = rng.choice(n, size=3, replace=False)
        try:
            M, _ = _fit_similarity(src[idx], dst[idx])
        except np.linalg.LinAlgError:
            continue
        inl = np.sqrt(((X @ M - dst) ** 2).sum(1)) < thresh
        if best_inl is None or inl.sum() > best_inl.sum():
            best_inl = inl
    if best_inl is None or best_inl.sum() < 6:
        return None, None
    M, _ = _fit_similarity(src[best_inl], dst[best_inl])  # refit on inliers
    inl = np.sqrt(((X @ M - dst) ** 2).sum(1)) < thresh
    return M, inl


def build_seam_graph(
    template_dir: str | Path,
    min_size: int = 1500,
    match_dist: float = 110.0,
    ratio: float = 0.85,
    min_inliers: int = 12,
    inlier_thresh: float = 8.0,
) -> list[dict]:
    """Discover seams between panels. Returns a list of seam records."""
    template_dir = Path(template_dir)
    seg = np.array(Image.open(template_dir / "zones" / "segments.png"))
    stack = _load_pattern_stack(template_dir)

    # Candidate panels: segments big enough to carry a meaningful edge.
    ids, counts = np.unique(seg, return_counts=True)
    panels = [int(i) for i, c in zip(ids, counts) if i != 0 and c >= min_size]

    # Precompute edge rings, fingerprints, variance, and a KD-tree per panel.
    ring, fp, var, tree = {}, {}, {}, {}
    for p in panels:
        coords = _inward_ring(seg == p)
        if len(coords) < 10:
            continue
        ring[p] = coords
        fp[p] = _fingerprints(stack, coords)
        var[p] = fp[p].var(1)
        tree[p] = cKDTree(fp[p])
    panels = [p for p in panels if p in ring]

    seams = []
    for ia in range(len(panels)):
        a = panels[ia]
        # Match only informative edge pixels of A (those that vary across patterns).
        info = var[a] > np.percentile(var[a], 50)
        Fa, Ca = fp[a][info], ring[a][info]
        for ib in range(ia + 1, len(panels)):
            b = panels[ib]
            d, j = tree[b].query(Fa, k=2)
            keep = (d[:, 0] < match_dist) & (d[:, 0] < ratio * d[:, 1])
            if keep.sum() < min_inliers:
                continue
            src = Ca[keep]
            dst = ring[b][j[keep, 0]]
            M, inl = _ransac_affine(src, dst, thresh=inlier_thresh)
            if M is None or inl.sum() < min_inliers:
                continue
            src_i, dst_i = src[inl], dst[inl]
            resid = float(np.median(_fit_similarity(src_i, dst_i)[1]))
            # store a handful of sample correspondences (x,y order) for sanity/preview
            step = max(1, len(src_i) // 8)
            samples = [
                [int(s[0]), int(s[1]), int(t[0]), int(t[1])]  # (ax, ay, bx, by)
                for s, t in zip(src_i[::step], dst_i[::step])
            ]
            seams.append({
                "a": a, "b": b,
                "inliers": int(inl.sum()),
                "residual_px": round(resid, 2),
                # transform maps [x,y,1] (panel A) -> [x,y] (panel B): row-major 3x2
                "transform": [[round(v, 6) for v in row] for row in M.tolist()],
                "samples": samples,
            })

    seams.sort(key=lambda s: -s["inliers"])
    return seams


def write_seams(template_dir: str | Path) -> Path:
    template_dir = Path(template_dir)
    seams = build_seam_graph(template_dir)
    # Annotate with zone labels where known, for readability.
    labels = {}
    lpath = template_dir / "zones" / "labels.json"
    if lpath.exists():
        zmap = json.loads(lpath.read_text()).get("zones", {})
        for zone, sids in zmap.items():
            for sid in sids:
                labels[sid] = zone
    for s in seams:
        s["a_zone"] = labels.get(s["a"])
        s["b_zone"] = labels.get(s["b"])
    out = template_dir / "zones" / "seams.json"
    out.write_text(json.dumps(seams, indent=2))
    return out


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "templates/porsche_992_gt3"
    out = write_seams(target)
    seams = json.loads(out.read_text())
    print(f"discovered {len(seams)} seams -> {out}")
    for s in seams[:25]:
        an = s.get("a_zone") or f"seg{s['a']}"
        bn = s.get("b_zone") or f"seg{s['b']}"
        print(f"  {s['inliers']:4d} inliers  resid={s['residual_px']:.1f}px   {an} <-> {bn}")
