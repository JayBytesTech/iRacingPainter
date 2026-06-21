"""Chain per-seam transforms into a global design space.

`seams.py` gives pairwise affine transforms between adjacent panels. This module
stitches them into a single coordinate frame ("design space") so a design defined
once flows across many panels and lines up at the seams.

Method: build a graph (panels = nodes, seams = edges weighted by inlier count),
take a maximum-reliability spanning forest, pick the biggest component's most-
connected panel as the root (identity), and compose seam transforms outward so every
panel gets a transform mapping its UV pixels -> design space. Along every spanning-
tree seam the two panels agree exactly in design space (continuity by construction);
non-tree seams (loop closures) may differ slightly — that's the only approximation.

Output: zones/layout.json — {root, transforms: {seg_id: 3x3 UV->design}, components}.

Usage:
    python -m iracing_painter.layout templates/porsche_992_gt3
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np


def _affine_3x3(transform_3x2) -> np.ndarray:
    """seams.json transform (rows give x'=..,y'=..) -> 3x3 matrix on [x,y,1]^T."""
    m = np.array(transform_3x2, float)  # (3,2)
    return np.array([
        [m[0, 0], m[1, 0], m[2, 0]],
        [m[0, 1], m[1, 1], m[2, 1]],
        [0.0, 0.0, 1.0],
    ])


def build_layout(template_dir: str | Path) -> dict:
    template_dir = Path(template_dir)
    seams_path = template_dir / "zones" / "seams.json"
    if not seams_path.exists():
        raise FileNotFoundError(
            f"no seams.json — run: python -m iracing_painter.seams {template_dir}"
        )
    seams = json.loads(seams_path.read_text())

    # Adjacency: for each seam keep the A->B affine (and its inverse for B->A).
    adj: dict[int, list[tuple[int, np.ndarray, int]]] = {}
    edges = []
    for s in seams:
        a, b = s["a"], s["b"]
        A = _affine_3x3(s["transform"])      # maps A-uv -> B-uv
        # Skip degenerate fits (near-singular affine can't be inverted/composed).
        if abs(np.linalg.det(A[:2, :2])) < 1e-3:
            continue
        Ainv = np.linalg.inv(A)
        adj.setdefault(a, []).append((b, A, s["inliers"]))
        adj.setdefault(b, []).append((a, Ainv, s["inliers"]))
        edges.append((s["inliers"], a, b))

    # Maximum-reliability spanning forest (Kruskal on -inliers via union-find).
    parent = {n: n for n in adj}
    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]; x = parent[x]
        return x
    tree: dict[int, list[tuple[int, np.ndarray]]] = {n: [] for n in adj}
    for inl, a, b in sorted(edges, key=lambda e: -e[0]):
        ra, rb = find(a), find(b)
        if ra == rb:
            continue
        parent[ra] = rb
        A = next(M for (nb, M, _) in adj[a] if nb == b)
        tree[a].append((b, A))
        tree[b].append((a, np.linalg.inv(A)))

    # Components, and a root per component = the highest-degree panel.
    comps: dict[int, list[int]] = {}
    for n in adj:
        comps.setdefault(find(n), []).append(n)

    transforms: dict[int, np.ndarray] = {}
    components = []
    for members in comps.values():
        root = max(members, key=lambda n: len(adj[n]))
        transforms[root] = np.eye(3)
        # BFS out from root composing transforms: T_child = T_parent @ (parent->child)
        stack = [root]
        seen = {root}
        while stack:
            u = stack.pop()
            for (v, Muv) in tree[u]:  # Muv maps u-uv -> v-uv
                if v in seen:
                    continue
                # design = T_u(u-uv); u-uv = Muv^{-1}(v-uv); so T_v = T_u @ Muv^{-1}
                transforms[v] = transforms[u] @ np.linalg.inv(Muv)
                seen.add(v); stack.append(v)
        components.append({"root": root, "members": sorted(members)})

    components.sort(key=lambda c: -len(c["members"]))
    return {
        "root": components[0]["root"] if components else None,
        "transforms": {str(k): v.tolist() for k, v in transforms.items()},
        "components": components,
    }


def load_layout(template_dir: str | Path) -> dict[int, np.ndarray]:
    """Return {seg_id: 3x3 UV->design matrix} from layout.json, or {}."""
    p = Path(template_dir) / "zones" / "layout.json"
    if not p.exists():
        return {}
    data = json.loads(p.read_text())
    return {int(k): np.array(v, float) for k, v in data["transforms"].items()}


def write_layout(template_dir: str | Path) -> Path:
    template_dir = Path(template_dir)
    layout = build_layout(template_dir)
    out = template_dir / "zones" / "layout.json"
    out.write_text(json.dumps(layout, indent=2))
    return out


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "templates/porsche_992_gt3"
    out = write_layout(target)
    data = json.loads(out.read_text())
    print(f"layout -> {out}")
    print(f"root panel: {data['root']}   panels placed: {len(data['transforms'])}")
    for c in data["components"]:
        if len(c["members"]) > 1:
            print(f"  component (root {c['root']}): {c['members']}")
