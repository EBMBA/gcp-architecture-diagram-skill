"""Run: python3 -m unittest discover -s tests   (icon tests are skipped until `fetch` has run)"""

import io
import subprocess
import sys
import unittest
import xml.etree.ElementTree as ET
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import gcp_drawio as g  # noqa: E402

EDGE = ("edgeStyle=orthogonalEdgeStyle;exitX=1;exitY=0.5;exitDx=0;exitDy=0;"
        "entryX=0;entryY=0.5;entryDx=0;entryDy=0;")


def diagram(*cells):
    return ET.ElementTree(ET.fromstring(
        '<mxGraphModel><root><mxCell id="0"/><mxCell id="1" parent="0"/>' + "".join(cells) + "</root></mxGraphModel>"))


def icon(cid, x, y, value="", style="gcpIcon=cloud_run;", parent="1"):
    return (f'<mxCell id="{cid}" value="{value}" style="{style}" vertex="1" parent="{parent}">'
            f'<mxGeometry x="{x}" y="{y}" width="64" height="64" as="geometry"/></mxCell>')


def edge(eid, src, tgt, style=EDGE):
    return (f'<mxCell id="{eid}" style="{style}" edge="1" parent="1" source="{src}" target="{tgt}">'
            f'<mxGeometry relative="1" as="geometry"/></mxCell>')


class MapTest(unittest.TestCase):
    def test_every_core_product_and_category_is_consistent(self):
        data = g.load_map()
        for k, p in data["products"].items():
            self.assertIn(p["category"], data["categories"], k)
            self.assertEqual(bool(p.get("core")), k in data["core"], k)

    def test_aliases_are_unique_and_do_not_shadow_keys(self):
        data = g.load_map()
        seen = {}
        for k, p in data["products"].items():
            for a in p.get("aliases", []):
                self.assertNotIn(a, data["products"], f"alias {a} shadows a product key")
                self.assertNotIn(a, seen, f"alias {a} used by {seen.get(a)} and {k}")
                seen[a] = k


class ValidateTest(unittest.TestCase):
    def check(self, tree):
        return g.validate_tree(tree)

    def test_clean_horizontal_flow(self):
        e, w, _ = self.check(diagram(icon("a", 0, 0), icon("b", 200, 0), edge("e", "a", "b")))
        self.assertEqual((e, w), ([], []))

    def test_floating_edge_is_an_error(self):
        e, _, _ = self.check(diagram(icon("a", 0, 0),
                                     '<mxCell id="e" edge="1" parent="1" source="a"><mxGeometry as="geometry"/></mxCell>'))
        self.assertTrue(any("floating" in x for x in e))

    def test_overlap_is_an_error(self):
        e, _, _ = self.check(diagram(icon("a", 0, 0), icon("b", 30, 30)))
        self.assertTrue(any("overlap" in x for x in e))

    def test_duplicate_id(self):
        e, _, _ = self.check(diagram(icon("a", 0, 0), icon("a", 300, 0)))
        self.assertTrue(any("duplicate" in x for x in e))

    def test_edge_through_icon(self):
        _, w, _ = self.check(diagram(icon("a", 0, 0), icon("mid", 200, 0), icon("b", 400, 0), edge("e", "a", "b")))
        self.assertTrue(any("passes through 'mid'" in x for x in w))

    def test_crooked_edge(self):
        _, w, _ = self.check(diagram(icon("a", 0, 0), icon("b", 200, 6), edge("e", "a", "b")))
        self.assertTrue(any("crooked" in x for x in w))

    def test_edge_crossing_own_label(self):
        down = "edgeStyle=orthogonalEdgeStyle;exitX=0.5;exitY=1;exitDx=0;exitDy=0;entryX=0.5;entryY=0;entryDx=0;entryDy=0;"
        _, w, _ = self.check(diagram(icon("a", 0, 0, value="Cloud Run"), icon("b", 0, 200), edge("e", "a", "b", down)))
        self.assertTrue(any("label of 'a'" in x for x in w))

    def test_bottom_left_label_does_not_cross_horizontal_edge(self):
        side = "gcpIcon=gke;labelPosition=left;verticalLabelPosition=bottom;align=right;verticalAlign=top;"
        _, w, _ = self.check(diagram(icon("a", 0, 0), icon("b", 200, 0, value="backend", style=side),
                                     edge("e", "a", "b")))
        self.assertEqual(w, [])

    def test_edge_label_on_group_border(self):
        group = ('<mxCell id="g" style="gcpGroup=vpc;" vertex="1" parent="1">'
                 '<mxGeometry x="150" y="-100" width="400" height="300" as="geometry"/></mxCell>')
        labeled = (f'<mxCell id="e" value="private IP" style="{EDGE}" edge="1" parent="1" source="a" target="b">'
                   '<mxGeometry relative="1" as="geometry"/></mxCell>')
        # route 64 -> 256, label centered at x=160, on the group border x=150
        _, w, _ = self.check(diagram(icon("a", 0, 0), group, icon("b", 106, 100, parent="g"), labeled))
        self.assertTrue(any("border of group 'g'" in x for x in w), w)

    def test_edge_through_group_title(self):
        # second agent test, first draft: the logs edge ran through the "Operations" title
        src = (ROOT / "examples/gke-hybrid.src.drawio").read_text()
        src = src.replace('<mxGeometry x="220" y="550" width="480" height="170"',
                          '<mxGeometry x="280" y="550" width="380" height="170"')
        src = src.replace('<mxGeometry x="108" y="40"', '<mxGeometry x="48" y="40"')
        src = src.replace('<mxGeometry x="324" y="40"', '<mxGeometry x="264" y="40"')
        _, w, _ = self.check(ET.ElementTree(ET.fromstring(src)))
        self.assertTrue(any("title of group 'ops'" in x for x in w), w)

    def test_label_sticking_out_of_container(self):
        group = ('<mxCell id="g" style="gcpGroup=logical;" vertex="1" parent="1">'
                 '<mxGeometry x="0" y="0" width="120" height="110" as="geometry"/></mxCell>')
        _, w, _ = self.check(diagram(group, icon("a", 28, 30, value="A very long product label", parent="g")))
        self.assertTrue(any("sticks out" in x for x in w), w)

    def test_src_convention(self):
        self.assertEqual(g.default_output("x/web.src.drawio"), "x/web.drawio")
        self.assertEqual(g.default_output("web.drawio"), "web.drawio")

    def test_child_outside_container(self):
        group = ('<mxCell id="g" style="gcpGroup=vpc;" vertex="1" parent="1">'
                 '<mxGeometry x="0" y="0" width="100" height="100" as="geometry"/></mxCell>')
        _, w, _ = self.check(diagram(group, icon("a", 80, 80, parent="g")))
        self.assertTrue(any("outside its container" in x for x in w))


@unittest.skipUnless((g.CACHE_DIR / "category").exists(), "icon packs not fetched")
class BuildTest(unittest.TestCase):
    def test_all_icons_resolve_in_both_modes(self):
        data = g.load_map()
        self.assertEqual(g.check_map(data), [])
        for mode in ("modern", "legacy"):
            r = g.IconResolver(data, mode)
            for k in data["products"]:
                self.assertIsNotNone(r.path(k), f"{k} ({mode})")

    def test_modern_uses_category_icon_for_non_core(self):
        r = g.IconResolver(g.load_map(), "modern")
        self.assertIn("DataAnalytics", r.path("pubsub").name)
        self.assertIn("CloudRun", r.path("cloud_run").name)
        self.assertEqual(r.path("pubsub", "legacy").name, "pubsub.svg")

    def test_examples_build_clean(self):
        for src in (ROOT / "examples").glob("*.src.drawio"):
            out = Path(self.id().replace(".", "_") + "_" + src.name)
            try:
                buf = io.StringIO()
                with redirect_stdout(buf):
                    rc = g.build(type("A", (), {"input": str(src), "output": str(out), "mode": "modern"}))
                self.assertEqual(rc, 0, buf.getvalue())
                self.assertNotIn("WARN", buf.getvalue(), f"{src.name}:\n{buf.getvalue()}")
                # rebuild of a built file is idempotent
                first = out.read_text()
                with redirect_stdout(io.StringIO()):
                    g.build(type("A", (), {"input": str(out), "output": str(out), "mode": "modern"}))
                self.assertEqual(first, out.read_text())
            finally:
                out.unlink(missing_ok=True)

    def test_unknown_icon_suggests(self):
        p = subprocess.run([sys.executable, str(ROOT / "scripts/gcp_drawio.py"), "list", "pubsub"],
                           capture_output=True, text=True)
        self.assertIn("pubsub", p.stdout)
        r = g.IconResolver(g.load_map(), "modern")
        self.assertIn("pubsub", r.suggest("pubsubb"))


if __name__ == "__main__":
    unittest.main()
