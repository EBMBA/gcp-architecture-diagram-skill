#!/usr/bin/env python3
"""Build, validate and export Google Cloud architecture diagrams for draw.io.

Diagrams are written as plain .drawio XML using three placeholder style keys:

    gcpIcon=<product key | alias | category:<category>>   official Google Cloud icon
    gcpGroup=<kind>                                         boundary / container
    gcpShape=<kind>                                         generic actor or external system

`build` replaces them with full draw.io styles (icons embedded as SVG data URIs, so
the output file is self-contained), then validates the layout. The placeholder
keys are kept in the output, so a built file can be edited and rebuilt.

Subcommands:
    fetch                 download the official icon packs into the cache
    build IN [-o OUT]     resolve placeholders + validate (--mode modern|legacy);
                          x.src.drawio is built to x.drawio, other files in place
    validate IN           layout / structure checks only
    export IN -f png      export through the draw.io CLI (embeds the diagram XML)
    list [QUERY]          search icon keys
    sheet [-o OUT]        contact sheet of every icon, to eyeball rendering
    docs                  regenerate references/icons.md from icon-map.json

Standard library only. Icons cache: $GCP_ICONS_DIR or ~/.cache/gcp-architecture-diagram/icons
"""

import argparse
import base64
import difflib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
ICON_MAP = SKILL_DIR / "references" / "icon-map.json"
GENERIC_DIR = SKILL_DIR / "assets" / "generic"
CACHE_DIR = Path(os.environ.get("GCP_ICONS_DIR", Path.home() / ".cache" / "gcp-architecture-diagram" / "icons"))

ICON_SIZE = 64
CONNECTION_POINTS = (
    "points=[[0,0,0],[0.25,0,0],[0.5,0,0],[0.75,0,0],[1,0,0],[0,1,0],[0.25,1,0],[0.5,1,0],[0.75,1,0],"
    "[1,1,0],[0,0.25,0],[0,0.5,0],[0,0.75,0],[1,0.25,0],[1,0.5,0],[1,0.75,0]]"
)
ICON_BASE = (
    "shape=image;html=1;verticalLabelPosition=bottom;verticalAlign=top;align=center;"
    "labelBackgroundColor=none;aspect=fixed;imageAspect=0;fontSize=12;fontColor=#202124;"
    "fontFamily=Google Sans,Roboto,Arial,sans-serif;" + CONNECTION_POINTS
)

GROUP_BASE = (
    "rounded=1;absoluteArcSize=1;arcSize=12;html=1;whiteSpace=wrap;container=1;dropTarget=1;collapsible=0;"
    "fillColor=none;verticalAlign=top;align=left;spacingLeft=12;spacingTop=6;fontSize=13;fontStyle=1;"
    "fontFamily=Google Sans,Roboto,Arial,sans-serif;strokeWidth={width};strokeColor={color};fontColor={color};{extra}"
)
GROUPS = {
    # kind: (stroke color, stroke width, extra style)
    "google_cloud":  ("#4285F4", 2, ""),
    "organization":  ("#5F6368", 1, "dashed=1;dashPattern=8 4;"),
    "folder":        ("#5F6368", 1, "dashed=1;dashPattern=8 4;"),
    "project":       ("#5F6368", 1.5, ""),
    "region":        ("#4285F4", 1.5, "dashed=1;dashPattern=8 4;"),
    "zone":          ("#80868B", 1, "dashed=1;dashPattern=3 3;"),
    "vpc":           ("#34A853", 1.5, ""),
    "subnet":        ("#34A853", 1, "dashed=1;dashPattern=8 4;"),
    "vpc_sc":        ("#EA4335", 1.5, "dashed=1;dashPattern=8 4;"),
    "cluster":       ("#4285F4", 1, "dashed=1;dashPattern=3 3;"),
    "instance_group":("#FBBC04", 1.5, "dashed=1;dashPattern=8 4;"),
    "logical":       ("#80868B", 1, "dashed=1;dashPattern=3 3;"),
    "on_premises":   ("#5F6368", 1.5, "fillColor=#F1F3F4;"),
    "other_cloud":   ("#5F6368", 1.5, "dashed=1;dashPattern=1 3;"),
    "internet":      ("#80868B", 1, "dashed=1;dashPattern=1 3;"),
}

GENERIC = {
    # kind: Material Symbols file stem
    "user": "person", "users": "group", "browser": "computer", "laptop": "computer",
    "mobile": "smartphone", "server": "dns", "database": "database", "internet": "public",
    "datacenter": "domain", "external_api": "api", "other_cloud": "cloud", "storage": "storage",
}

USER_AGENT = "gcp-architecture-diagram-skill/1.0"


# ---------------------------------------------------------------- icon map / cache

def load_map():
    with open(ICON_MAP, encoding="utf-8") as f:
        data = json.load(f)
    aliases = {}
    for key, p in data["products"].items():
        for a in p.get("aliases", []):
            aliases[a] = key
    data["_aliases"] = aliases
    return data


def fetch(args):
    data = load_map()
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    for pack, url in data["sources"]["packs"].items():
        dest = CACHE_DIR / pack
        if dest.exists() and any(dest.rglob("*.svg")) and not args.force:
            print(f"{pack}: cached ({dest})")
            continue
        print(f"{pack}: downloading {url}")
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=60) as r, tempfile.TemporaryFile() as tmp:
            shutil.copyfileobj(r, tmp)
            tmp.seek(0)
            if dest.exists():
                shutil.rmtree(dest)
            dest.mkdir(parents=True)
            with zipfile.ZipFile(tmp) as z:
                for info in z.infolist():
                    name = info.filename
                    if info.is_dir() or "__MACOSX" in name or not name.lower().endswith(".svg"):
                        continue
                    # flatten: only the basename matters for lookup
                    target = dest / Path(name).name
                    target.write_bytes(z.read(info))
        print(f"{pack}: {len(list(dest.glob('*.svg')))} SVG files")
    missing = check_map(data)
    if missing:
        print("\nWARNING: icon-map.json references files that are not in the packs:")
        for m in missing:
            print("  -", m)
        return 1
    print("\nAll icons referenced by icon-map.json are present.")
    return 0


class IconResolver:
    def __init__(self, data, mode):
        self.data, self.mode = data, mode
        self._cache = {}
        if not (CACHE_DIR / "category").exists():
            raise SystemExit(f"Icon packs not found in {CACHE_DIR}. Run: python3 {Path(__file__).name} fetch")

    def _file(self, pack, stem):
        d = CACHE_DIR / pack
        if pack == "legacy":
            p = d / f"{stem}.svg"
            return p if p.exists() else None
        hits = sorted(d.glob(f"{stem}-512-color*.svg"))
        return hits[0] if hits else None

    def canonical(self, key):
        """Return ('product'|'category', key) or None."""
        k = key.strip().lower().replace("-", "_").replace(" ", "_")
        if k.startswith("category:"):
            c = k.split(":", 1)[1]
            return ("category", c) if c in self.data["categories"] else None
        if k in self.data["products"]:
            return ("product", k)
        if k in self.data["_aliases"]:
            return ("product", self.data["_aliases"][k])
        if k in self.data["core"]:
            return ("product", k)
        return None

    def suggest(self, key):
        pool = list(self.data["products"]) + list(self.data["_aliases"]) + [f"category:{c}" for c in self.data["categories"]]
        return difflib.get_close_matches(key.lower(), pool, n=3, cutoff=0.5)

    def path(self, key, mode=None):
        mode = mode or self.mode
        kind, k = self.canonical(key)
        if kind == "category":
            return self._file("category", self.data["categories"][k]["stem"])
        p = self.data["products"][k]
        if mode == "legacy" and p.get("legacy"):
            f = self._file("legacy", p["legacy"])
            if f:
                return f
        if p.get("core"):
            return self._file("core", self.data["core"][k])
        return self._file("category", self.data["categories"][p["category"]]["stem"])

    def data_uri(self, path):
        if path not in self._cache:
            svg = path.read_bytes()
            # draw.io convention: base64 without ';base64' (';' is the style separator)
            self._cache[path] = "data:image/svg+xml," + base64.b64encode(svg).decode()
        return self._cache[path]


def check_map(data):
    missing = []
    r = IconResolver.__new__(IconResolver)
    r.data, r.mode, r._cache = data, "modern", {}
    for c, v in data["categories"].items():
        if not r._file("category", v["stem"]):
            missing.append(f"category {c}: {v['stem']}")
    for k, stem in data["core"].items():
        if not r._file("core", stem):
            missing.append(f"core {k}: {stem}")
        if k not in data["products"]:
            missing.append(f"core {k}: no product entry")
    for k, p in data["products"].items():
        if p["category"] not in data["categories"]:
            missing.append(f"product {k}: unknown category {p['category']}")
        if p.get("core") and k not in data["core"]:
            missing.append(f"product {k}: marked core but no core icon")
        if p.get("legacy") and not r._file("legacy", p["legacy"]):
            missing.append(f"product {k}: legacy {p['legacy']}")
    for g in GENERIC.values():
        if not (GENERIC_DIR / f"{g}.svg").exists():
            missing.append(f"generic {g}")
    return missing


# ---------------------------------------------------------------- style helpers

def parse_style(style):
    out = {}
    for part in (style or "").split(";"):
        if not part:
            continue
        if "=" in part:
            k, v = part.split("=", 1)
            out[k] = v
        else:
            out[part] = None  # named style, e.g. "text"
    return out


def join_style(*parts):
    merged = {}
    for p in parts:
        merged.update(parse_style(p) if isinstance(p, str) else p)
    return ";".join(k if v is None else f"{k}={v}" for k, v in merged.items()) + ";"


MANAGED = {"shape", "image"}


def user_overrides(style, base):
    """Keys the author set that are not part of a previous build output."""
    s = parse_style(style)
    b = parse_style(base)
    return {k: v for k, v in s.items() if k not in MANAGED and not (k in b and b[k] == v)}


# ---------------------------------------------------------------- build

def build(args):
    data = load_map()
    tree = ET.parse(args.input)
    resolver = IconResolver(data, args.mode)
    errors = []
    for cell in tree.iter("mxCell"):
        style = cell.get("style")
        if not style:
            continue
        s = parse_style(style)
        cid = cell.get("id")
        if "gcpIcon" in s:
            key = s["gcpIcon"]
            if not resolver.canonical(key):
                sug = resolver.suggest(key)
                errors.append(f"cell {cid}: unknown gcpIcon '{key}'" + (f" (did you mean: {', '.join(sug)}?)" if sug else ""))
                continue
            mode = s.get("gcpIconMode", args.mode)
            path = resolver.path(key, mode)
            if not path:
                errors.append(f"cell {cid}: icon file for '{key}' not found in cache; run fetch")
                continue
            new = join_style(ICON_BASE, user_overrides(style, ICON_BASE), {"image": resolver.data_uri(path)})
            cell.set("style", new)
            ensure_geometry(cell, ICON_SIZE, ICON_SIZE)
        elif "gcpShape" in s:
            kind = s["gcpShape"]
            if kind not in GENERIC:
                errors.append(f"cell {cid}: unknown gcpShape '{kind}' (one of: {', '.join(GENERIC)})")
                continue
            path = GENERIC_DIR / f"{GENERIC[kind]}.svg"
            new = join_style(ICON_BASE, user_overrides(style, ICON_BASE), {"image": resolver.data_uri(path)})
            cell.set("style", new)
            ensure_geometry(cell, 48, 48)
        elif "gcpGroup" in s:
            kind = s["gcpGroup"]
            if kind not in GROUPS:
                errors.append(f"cell {cid}: unknown gcpGroup '{kind}' (one of: {', '.join(GROUPS)})")
                continue
            color, width, extra = GROUPS[kind]
            base = GROUP_BASE.format(color=color, width=width, extra=extra)
            cell.set("style", join_style(base, user_overrides(style, base)))
    if errors:
        print("BUILD FAILED:")
        for e in errors:
            print("  ERROR", e)
        return 1
    out = args.output or default_output(args.input)
    tree.write(out, encoding="utf-8", xml_declaration=False)
    print(f"built {out} (mode={args.mode})")
    return report(validate_tree(tree))


def default_output(src):
    """diagram.src.drawio -> diagram.drawio; anything else is rebuilt in place."""
    return src[: -len(".src.drawio")] + ".drawio" if src.endswith(".src.drawio") else src


def ensure_geometry(cell, w, h):
    g = cell.find("mxGeometry")
    if g is None:
        g = ET.SubElement(cell, "mxGeometry", {"as": "geometry"})
    g.set("width", g.get("width") or str(w))
    g.set("height", g.get("height") or str(h))


# ---------------------------------------------------------------- validate

class Box:
    __slots__ = ("x", "y", "w", "h")

    def __init__(self, x, y, w, h):
        self.x, self.y, self.w, self.h = x, y, w, h

    @property
    def cx(self):
        return self.x + self.w / 2

    @property
    def cy(self):
        return self.y + self.h / 2

    def intersects(self, o, pad=0):
        return (self.x - pad < o.x + o.w and o.x < self.x + self.w + pad and
                self.y - pad < o.y + o.h and o.y < self.y + self.h + pad)

    def contains(self, o):
        return (o.x >= self.x - 0.5 and o.y >= self.y - 0.5 and
                o.x + o.w <= self.x + self.w + 0.5 and o.y + o.h <= self.y + self.h + 0.5)

    def hits_segment(self, x1, y1, x2, y2, shrink=2):
        """Axis-aligned segment vs box (box shrunk a little so touching edges don't count)."""
        bx1, by1, bx2, by2 = self.x + shrink, self.y + shrink, self.x + self.w - shrink, self.y + self.h - shrink
        if abs(y1 - y2) < 0.5:  # horizontal
            return by1 < y1 < by2 and min(x1, x2) < bx2 and max(x1, x2) > bx1
        if abs(x1 - x2) < 0.5:  # vertical
            return bx1 < x1 < bx2 and min(y1, y2) < by2 and max(y1, y2) > by1
        return False


def label_lines(value):
    text = re.sub(r"<br\s*/?>", "\n", value or "", flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    return [l for l in text.split("\n") if l.strip()]


def validate_tree(tree):
    root = tree.getroot()
    model = root if root.tag == "mxGraphModel" else root.find(".//mxGraphModel")
    errors, warnings, infos = [], [], []
    if model is None:
        return ["no <mxGraphModel> found (compressed diagram? save uncompressed)"], [], []
    cells = {}
    for c in model.iter("mxCell"):
        cid = c.get("id")
        if cid in cells:
            errors.append(f"duplicate cell id '{cid}'")
        cells[cid] = c
    for rid in ("0", "1"):
        if rid not in cells:
            errors.append(f"missing root cell id='{rid}'")

    def is_container(c):
        s = parse_style(c.get("style"))
        return "gcpGroup" in s or s.get("container") == "1" or s.get("swimlane", "x") is None

    def is_text(c):
        s = parse_style(c.get("style"))
        return "text" in s or s.get("shape") == "text"

    abs_cache = {}

    def abs_box(cid):
        if cid in abs_cache:
            return abs_cache[cid]
        c = cells[cid]
        g = c.find("mxGeometry")
        if g is None:
            return None
        x, y = float(g.get("x", 0)), float(g.get("y", 0))
        w, h = float(g.get("width", 0)), float(g.get("height", 0))
        p = c.get("parent")
        if p in cells and p not in ("0", "1") and cells[p].get("vertex") == "1":
            pb = abs_box(p)
            if pb:
                x, y = x + pb.x, y + pb.y
        abs_cache[cid] = Box(x, y, w, h)
        return abs_cache[cid]

    def ancestors(cid):
        out = set()
        p = cells[cid].get("parent")
        while p in cells and p not in ("0", "1"):
            out.add(p)
            p = cells[p].get("parent")
        return out

    vertices, icons, edges = [], [], []
    for cid, c in cells.items():
        p = c.get("parent")
        if cid not in ("0",) and p is not None and p not in cells:
            errors.append(f"cell {cid}: parent '{p}' does not exist")
        if c.get("vertex") == "1":
            vertices.append(cid)
            s = parse_style(c.get("style"))
            if not is_container(c) and not is_text(c) and s.get("fillColor") != "#F5F5F5" and abs_box(cid):
                icons.append(cid)
        elif c.get("edge") == "1":
            edges.append(cid)

    # background rectangle is not an "icon"
    icons = [i for i in icons if not (abs_box(i).w >= 1000 and abs_box(i).h >= 600)]

    # containment
    for cid in vertices:
        p = cells[cid].get("parent")
        if p in cells and p not in ("0", "1"):
            if not is_container(cells[p]):
                warnings.append(f"cell {cid}: parent '{p}' is not a container (add gcpGroup or container=1)")
            elif abs_box(cid) and abs_box(p) and not abs_box(p).contains(abs_box(cid)):
                warnings.append(f"cell {cid}: extends outside its container '{p}' (child coordinates are relative to the container)")

    # overlaps: icon vs icon, label vs icon
    def label_box(cid):
        b = abs_box(cid)
        lines = label_lines(cells[cid].get("value"))
        if not lines:
            return None
        st = parse_style(cells[cid].get("style"))
        w, h = max(len(l) for l in lines) * 6.6, 15 * len(lines)
        x = {"left": b.x - w - 4, "right": b.x + b.w + 4}.get(st.get("labelPosition"), b.cx - w / 2)
        y = {"top": b.y - h - 2, "middle": b.cy - h / 2}.get(st.get("verticalLabelPosition"), b.y + b.h + 2)
        return Box(x, y, w, h)

    for i, a in enumerate(icons):
        for b in icons[i + 1:]:
            if abs_box(a).intersects(abs_box(b)):
                errors.append(f"icons '{a}' and '{b}' overlap")
        la = label_box(a)
        if la:
            for b in icons:
                if b != a and la.intersects(abs_box(b)):
                    warnings.append(f"label of '{a}' overlaps icon '{b}'")

    # edges
    for eid in edges:
        e = cells[eid]
        src, tgt = e.get("source"), e.get("target")
        if not src or not tgt:
            errors.append(f"edge {eid}: missing source/target (floating edge)")
            continue
        if src not in cells or tgt not in cells:
            errors.append(f"edge {eid}: source/target points to a missing cell")
            continue
        sp, tp = ancestors(src) | {src}, ancestors(tgt) | {tgt}
        ep = e.get("parent")
        if (cells[src].get("parent") != cells[tgt].get("parent")) and ep not in ("1",) and ep not in (sp & tp):
            warnings.append(f"edge {eid}: crosses containers; set parent=\"1\"")
        sb, tb = abs_box(src), abs_box(tgt)
        if not sb or not tb:
            continue
        s = parse_style(e.get("style"))
        g = e.find("mxGeometry")
        waypoints = [] if g is None else [(float(p.get("x", 0)), float(p.get("y", 0)))
                                          for arr in g.findall("Array") for p in arr.findall("mxPoint")]
        path = edge_path(sb, tb, s, waypoints)
        if path is None:
            continue
        bends = len(path) - 2
        if bends > 1:
            warnings.append(f"edge {eid} ({src}->{tgt}): {bends} bends; move nodes so it needs at most one")
        # near-miss alignment => small visible dogleg
        if len(path) > 2:
            dx, dy = abs(sb.cx - tb.cx), abs(sb.cy - tb.cy)
            if 0.5 < dy <= 12 and dx > dy:
                warnings.append(f"edge {eid} ({src}->{tgt}): centers {dy:.0f}px apart vertically -> crooked edge; align y")
            elif 0.5 < dx <= 12 and dy > dx:
                warnings.append(f"edge {eid} ({src}->{tgt}): centers {dx:.0f}px apart horizontally -> crooked edge; align x")
        skip = {src, tgt} | ancestors(src) | ancestors(tgt)
        for (x1, y1), (x2, y2) in zip(path, path[1:]):
            for other in icons:
                if other not in skip and abs_box(other).hits_segment(x1, y1, x2, y2):
                    warnings.append(f"edge {eid} ({src}->{tgt}) passes through '{other}'")
                lb = label_box(other)
                if lb and lb.hits_segment(x1, y1, x2, y2, shrink=0):
                    warnings.append(f"edge {eid} ({src}->{tgt}) crosses the label of '{other}' "
                                    f"(move it to a free side, e.g. top: verticalLabelPosition=top;verticalAlign=bottom; "
                                    f"or top-right: labelPosition=right;verticalLabelPosition=top;align=left;verticalAlign=bottom;)")

    # edge labels sit at the middle of the route: they must not land on a group border
    groups = [v for v in vertices if is_container(cells[v]) and abs_box(v)]
    for eid in edges:
        e = cells[eid]
        lines = label_lines(e.get("value"))
        if not lines or e.get("source") not in cells or e.get("target") not in cells:
            continue
        sb, tb = abs_box(e.get("source")), abs_box(e.get("target"))
        if not sb or not tb:
            continue
        g = e.find("mxGeometry")
        if g is not None and g.find("mxPoint[@as='offset']") is not None:
            continue  # label dragged off the edge by the author
        # mxGeometry x on an edge = label position along the route, -1 (source) .. 1 (target)
        frac = (float(g.get("x", 0)) + 1) / 2 if g is not None else 0.5
        wps = [] if g is None else [(float(p.get("x", 0)), float(p.get("y", 0)))
                                   for arr in g.findall("Array") for p in arr.findall("mxPoint")]
        path = edge_path(sb, tb, parse_style(e.get("style")), wps)
        if not path:
            continue
        mx, my = path_point(path, frac)
        w, h = max(len(l) for l in lines) * 6.2 + 6, 14 * len(lines)
        lb = Box(mx - w / 2, my - h / 2, w, h)
        for gid in groups:
            gb = abs_box(gid)
            borders = [(gb.x, gb.y, gb.x + gb.w, gb.y), (gb.x, gb.y + gb.h, gb.x + gb.w, gb.y + gb.h),
                       (gb.x, gb.y, gb.x, gb.y + gb.h), (gb.x + gb.w, gb.y, gb.x + gb.w, gb.y + gb.h)]
            if any(lb.hits_segment(*seg, shrink=0) for seg in borders):
                warnings.append(f"edge {eid}: label '{' '.join(lines)}' sits on the border of group '{gid}' "
                                f"(move it along the edge: <mxGeometry x='-0.5' relative='1'> = 25% from the source; or drop it)")
                break

    # overlapping parallel segments between different edges
    segs = []
    for eid in edges:
        e = cells[eid]
        if e.get("source") in cells and e.get("target") in cells:
            sb, tb = abs_box(e.get("source")), abs_box(e.get("target"))
            if sb and tb:
                g = e.find("mxGeometry")
                wps = [] if g is None else [(float(p.get("x", 0)), float(p.get("y", 0)))
                                           for arr in g.findall("Array") for p in arr.findall("mxPoint")]
                path = edge_path(sb, tb, parse_style(e.get("style")), wps)
                if path:
                    segs += [(eid, a, b) for a, b in zip(path, path[1:])]
    seen = set()
    for i, (e1, a1, b1) in enumerate(segs):
        for e2, a2, b2 in segs[i + 1:]:
            if e1 == e2 or (e1, e2) in seen:
                continue
            if collinear_overlap(a1, b1, a2, b2):
                seen.add((e1, e2))
                warnings.append(f"edges {e1} and {e2} run on top of each other; offset exit/entry points")

    # canvas
    boxes = [abs_box(v) for v in vertices if abs_box(v)]
    if boxes:
        maxx = max(b.x + b.w for b in boxes)
        maxy = max(b.y + b.h for b in boxes)
        infos.append(f"{len(icons)} icons, {len(edges)} edges, content extends to {maxx:.0f}x{maxy:.0f}")
    return errors, warnings, infos


def side_point(box, fx, fy):
    return box.x + box.w * fx, box.y + box.h * fy


def edge_path(sb, tb, s, waypoints):
    """Approximate the orthogonal route draw.io will draw. Returns a list of points."""
    def f(k):
        return float(s[k]) if s.get(k) not in (None, "") else None
    ex, ey, nx, ny = f("exitX"), f("exitY"), f("entryX"), f("entryY")
    if ex is None or ey is None:
        if abs(sb.cy - tb.cy) < 0.5:
            ex, ey = (1, 0.5) if tb.cx > sb.cx else (0, 0.5)
        elif abs(sb.cx - tb.cx) < 0.5:
            ex, ey = (0.5, 1) if tb.cy > sb.cy else (0.5, 0)
        else:
            return None  # auto-routed, can't predict reliably
    if nx is None or ny is None:
        if abs(sb.cy - tb.cy) < 0.5:
            nx, ny = (0, 0.5) if tb.cx > sb.cx else (1, 0.5)
        elif abs(sb.cx - tb.cx) < 0.5:
            nx, ny = (0.5, 0) if tb.cy > sb.cy else (0.5, 1)
        else:
            return None
    start, end = side_point(sb, ex, ey), side_point(tb, nx, ny)
    orient = "h" if ex in (0, 1) else "v"       # leaving through a left/right side => horizontal
    end_orient = "h" if nx in (0, 1) else "v"   # entering through a left/right side => horizontal
    pts = [start]
    targets = waypoints + [end]
    for i, wp in enumerate(targets):
        last = pts[-1]
        same_y, same_x = abs(last[1] - wp[1]) < 0.5, abs(last[0] - wp[0]) < 0.5
        if same_y or same_x:
            pts.append(wp)
            orient = "h" if same_y else "v"
            continue
        is_end = i == len(targets) - 1
        if is_end and orient == end_orient:
            # Z shape: draw.io splits the run in the middle
            if orient == "h":
                mx = (last[0] + wp[0]) / 2
                pts += [(mx, last[1]), (mx, wp[1]), wp]
            else:
                my = (last[1] + wp[1]) / 2
                pts += [(last[0], my), (wp[0], my), wp]
        else:
            pts += [(wp[0], last[1]) if orient == "h" else (last[0], wp[1]), wp]
            orient = "v" if orient == "h" else "h"
    return pts


def path_point(pts, frac=0.5):
    """Point at `frac` of the route length (draw.io places edge labels this way)."""
    seg = [((a, b), abs(a[0] - b[0]) + abs(a[1] - b[1])) for a, b in zip(pts, pts[1:])]
    left = sum(l for _, l in seg) * max(0.0, min(1.0, frac))
    for (a, b), l in seg:
        if left <= l and l > 0:
            t = left / l
            return a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t
        left -= l
    return pts[-1]


def collinear_overlap(a1, b1, a2, b2, tol=3):
    if abs(a1[1] - b1[1]) < 0.5 and abs(a2[1] - b2[1]) < 0.5 and abs(a1[1] - a2[1]) < tol:
        lo, hi = max(min(a1[0], b1[0]), min(a2[0], b2[0])), min(max(a1[0], b1[0]), max(a2[0], b2[0]))
        return hi - lo > 10
    if abs(a1[0] - b1[0]) < 0.5 and abs(a2[0] - b2[0]) < 0.5 and abs(a1[0] - a2[0]) < tol:
        lo, hi = max(min(a1[1], b1[1]), min(a2[1], b2[1])), min(max(a1[1], b1[1]), max(a2[1], b2[1]))
        return hi - lo > 10
    return False


def report(result):
    errors, warnings, infos = result
    for i in infos:
        print("  info   ", i)
    for w in warnings:
        print("  WARN   ", w)
    for e in errors:
        print("  ERROR  ", e)
    if errors:
        print(f"validation: {len(errors)} error(s), {len(warnings)} warning(s)")
        return 1
    print(f"validation: OK ({len(warnings)} warning(s))")
    return 0


def validate(args):
    return report(validate_tree(ET.parse(args.input)))


# ---------------------------------------------------------------- export

def drawio_bin():
    for c in (os.environ.get("DRAWIO_BIN"), shutil.which("drawio"), shutil.which("draw.io"),
              "/Applications/draw.io.app/Contents/MacOS/draw.io",
              str(Path.home() / "Applications/draw.io.app/Contents/MacOS/draw.io")):
        if c and Path(c).exists():
            return c
    raise SystemExit("draw.io CLI not found. Install draw.io desktop (macOS: brew install --cask drawio) or set DRAWIO_BIN.")


def export(args):
    out = args.output or str(Path(args.input).with_suffix(f".{args.format}"))
    cmd = [drawio_bin(), "-x", "-f", args.format, "-b", str(args.border), "-o", out]
    if args.format in ("png", "svg", "pdf"):
        cmd.append("-e")  # embed diagram XML so the export stays editable
    if args.scale:
        cmd += ["-s", str(args.scale)]
    if sys.platform.startswith("linux"):
        cmd.append("--no-sandbox")
    cmd.append(args.input)
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0 or not Path(out).exists():
        print(r.stdout, r.stderr)
        return 1
    print(f"exported {out}")
    return 0


# ---------------------------------------------------------------- list / sheet / docs

def list_icons(args):
    data = load_map()
    q = (args.query or "").lower()
    for k, p in sorted(data["products"].items()):
        hay = " ".join([k, p["label"], p["category"]] + p.get("aliases", [])).lower()
        if q in hay:
            kind = "core" if p.get("core") else f"category:{p['category']}"
            print(f"{k:32} {p['label']:34} {kind}")
    if not q or "category" in q:
        for c, v in data["categories"].items():
            print(f"{'category:' + c:32} {v['label']:34} category icon")
    return 0


def sheet(args):
    data = load_map()
    resolver = IconResolver(data, args.mode)
    keys = sorted(data["products"]) + [f"category:{c}" for c in data["categories"]]
    cols, step_x, step_y = 10, 170, 150
    cells = ['<mxCell id="0"/>', '<mxCell id="1" parent="0"/>']
    for i, k in enumerate(keys):
        x, y = 40 + (i % cols) * step_x, 40 + (i // cols) * step_y
        uri = resolver.data_uri(resolver.path(k))
        style = join_style(ICON_BASE, {"image": uri, "gcpIcon": k})
        cells.append(f'<mxCell id="i{i}" value="{k}" style="{style}" vertex="1" parent="1">'
                     f'<mxGeometry x="{x}" y="{y}" width="{ICON_SIZE}" height="{ICON_SIZE}" as="geometry"/></mxCell>')
    for j, (kind, stem) in enumerate(GENERIC.items()):
        i = len(keys) + j
        x, y = 40 + (i % cols) * step_x, 40 + (i // cols) * step_y
        uri = resolver.data_uri(GENERIC_DIR / f"{stem}.svg")
        style = join_style(ICON_BASE, {"image": uri})
        cells.append(f'<mxCell id="g{j}" value="gcpShape={kind}" style="{style}" vertex="1" parent="1">'
                     f'<mxGeometry x="{x}" y="{y}" width="48" height="48" as="geometry"/></mxCell>')
    xml = ('<mxfile><diagram name="icons"><mxGraphModel><root>' + "".join(cells) +
           "</root></mxGraphModel></diagram></mxfile>")
    out = args.output or f"icon-sheet-{args.mode}.drawio"
    Path(out).write_text(xml, encoding="utf-8")
    print(f"wrote {out} ({len(keys)} icons + {len(GENERIC)} generic shapes)")
    return 0


def docs(args):
    data = load_map()
    lines = [
        "# Icon keys",
        "",
        "Generated by `scripts/gcp_drawio.py docs` from `icon-map.json`. Do not edit by hand.",
        "",
        "Use the key in a cell style: `gcpIcon=<key>`. Aliases are accepted too.",
        "",
        "- **modern** (default): products marked *core* have their own 4-color icon; every other",
        "  product uses its **category** icon, as Google's icon guide requires. The label carries the product name.",
        "- **legacy**: products with a ✓ in the legacy column get their own (pre-2025) icon.",
        "",
        "## Products",
        "",
        "| key | product | modern icon | legacy | aliases |",
        "|---|---|---|---|---|",
    ]
    by_cat = {}
    for k, p in data["products"].items():
        by_cat.setdefault(p["category"], []).append((k, p))
    for c in data["categories"]:
        for k, p in sorted(by_cat.get(c, [])):
            modern = "**core**" if p.get("core") else f"category: {data['categories'][c]['label']}"
            lines.append(f"| `{k}` | {p['label']} | {modern} | {'✓' if p.get('legacy') else ''} | "
                         f"{', '.join(p.get('aliases', []))} |")
    lines += ["", "## Category icons", "", "Use `gcpIcon=category:<key>` to show a category itself.", "",
              "| key | category |", "|---|---|"]
    lines += [f"| `category:{c}` | {v['label']} |" for c, v in data["categories"].items()]
    lines += ["", "## Generic shapes (`gcpShape=<key>`)", "", "| key | use for |", "|---|---|"]
    uses = {"user": "a person", "users": "a group of users", "browser": "web browser / desktop client",
            "laptop": "same as browser", "mobile": "mobile app", "server": "on-premises / third-party server",
            "database": "non-GCP database", "internet": "the public internet", "datacenter": "corporate site / data center",
            "external_api": "third-party API / SaaS", "other_cloud": "another cloud provider", "storage": "non-GCP storage"}
    lines += [f"| `{k}` | {uses[k]} |" for k in GENERIC]
    lines += ["", "## Group kinds (`gcpGroup=<key>`)", "", "| key | stroke | line |", "|---|---|---|"]
    for k, (color, width, extra) in GROUPS.items():
        line = "dashed" if "dashed=1" in extra else "solid"
        if "fillColor" in extra:
            line += ", grey fill"
        lines.append(f"| `{k}` | {color} | {line} |")
    out = SKILL_DIR / "references" / "icons.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {out}")
    return 0


# ---------------------------------------------------------------- cli

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("fetch"); p.add_argument("--force", action="store_true"); p.set_defaults(fn=fetch)
    p = sub.add_parser("build"); p.add_argument("input"); p.add_argument("-o", "--output")
    p.add_argument("--mode", choices=["modern", "legacy"], default="modern"); p.set_defaults(fn=build)
    p = sub.add_parser("validate"); p.add_argument("input"); p.set_defaults(fn=validate)
    p = sub.add_parser("export"); p.add_argument("input"); p.add_argument("-o", "--output")
    p.add_argument("-f", "--format", choices=["png", "svg", "pdf", "jpg"], default="png")
    p.add_argument("-b", "--border", type=int, default=20); p.add_argument("-s", "--scale", type=float)
    p.set_defaults(fn=export)
    p = sub.add_parser("list"); p.add_argument("query", nargs="?"); p.set_defaults(fn=list_icons)
    p = sub.add_parser("sheet"); p.add_argument("-o", "--output")
    p.add_argument("--mode", choices=["modern", "legacy"], default="modern"); p.set_defaults(fn=sheet)
    p = sub.add_parser("docs"); p.set_defaults(fn=docs)
    args = ap.parse_args()
    sys.exit(args.fn(args))


if __name__ == "__main__":
    main()
