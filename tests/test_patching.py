import json
import tomllib
import unittest

from app_forge.analyzer import snapshot_tree
from app_forge.domain.errors import ConflictFailure
from app_forge.domain.models import Patch, parse_manifest
from app_forge.patching import PatchConflict, apply_patch, remove_patch
from tests.helpers import ForgeTestCase

SRC = "def f():\n    x = 1\n    # forge:anchor routers\n    return x\n"


def insert(content="y = 2\n", **kw):
    return Patch(kw.pop("id", "reg"), "a.py", "insert", kw.pop("anchor", "routers"), kw.pop("position", "after"),
                 kw.pop("comment", "#"), content)


class InsertTests(unittest.TestCase):
    def test_inserts_with_anchor_indent_and_markers(self):
        r = apply_patch(SRC, insert("y = 2\nz = 3\n"), "acme.c", "pkg")
        self.assertEqual(r.status, "applied")
        self.assertIn("    # forge:begin acme.c:reg\n    y = 2\n    z = 3\n    # forge:end acme.c:reg\n    return x", r.new_text)
        compile(r.new_text, "x", "exec")

    def test_position_before(self):
        r = apply_patch(SRC, insert(position="before"), "acme.c", "pkg")
        self.assertLess(r.new_text.index("forge:begin"), r.new_text.index("forge:anchor"))

    def test_idempotent(self):
        once = apply_patch(SRC, insert(), "acme.c", "pkg")
        twice = apply_patch(once.new_text, insert(), "acme.c", "pkg")
        self.assertEqual((twice.status, twice.new_text), ("unchanged", once.new_text))

    def test_different_existing_block_conflicts_unless_replacing(self):
        once = apply_patch(SRC, insert("y = 2\n"), "acme.c", "pkg")
        with self.assertRaises(PatchConflict) as cm:
            apply_patch(once.new_text, insert("y = 99\n"), "acme.c", "pkg")
        self.assertEqual(cm.exception.code, "patch-exists-different")
        up = apply_patch(once.new_text, insert("y = 99\n"), "acme.c", "pkg", replace=True, expect_sha=once.sha256)
        self.assertIn("y = 99", up.new_text)
        self.assertNotIn("y = 2", up.new_text)
        self.assertEqual(up.new_text.count("forge:begin"), 1)

    def test_replace_refuses_edited_block(self):
        once = apply_patch(SRC, insert("y = 2\n"), "acme.c", "pkg")
        with self.assertRaises(PatchConflict) as cm:
            apply_patch(once.new_text.replace("y = 2", "y = 3  # mine"), insert("y = 99\n"), "acme.c", "pkg",
                        replace=True, expect_sha=once.sha256)
        self.assertEqual(cm.exception.code, "patch-modified")

    def test_remove_restores_original_bytes(self):
        r = apply_patch(SRC, insert(), "acme.c", "pkg")
        self.assertEqual(remove_patch(r.new_text, "acme.c", "reg", r.sha256), SRC)

    def test_remove_refuses_edited_block_and_reports_missing(self):
        r = apply_patch(SRC, insert(), "acme.c", "pkg")
        with self.assertRaises(PatchConflict) as cm:
            remove_patch(r.new_text.replace("y = 2", "y = 3"), "acme.c", "reg", r.sha256)
        self.assertEqual(cm.exception.code, "patch-modified")
        with self.assertRaises(PatchConflict) as cm:
            remove_patch(SRC, "acme.c", "reg", r.sha256)
        self.assertEqual(cm.exception.code, "patch-block-missing")

    def test_anchor_missing_and_ambiguous(self):
        with self.assertRaises(PatchConflict) as cm:
            apply_patch("x = 1\n", insert(), "acme.c", "pkg")
        self.assertEqual(cm.exception.code, "anchor-missing")
        with self.assertRaises(PatchConflict) as cm:
            apply_patch(SRC + "    # forge:anchor routers\n", insert(), "acme.c", "pkg")
        self.assertEqual(cm.exception.code, "anchor-ambiguous")
        # a different anchor whose name merely starts the same is not a match
        with self.assertRaises(PatchConflict):
            apply_patch(SRC.replace("routers", "routers-extra"), insert(), "acme.c", "pkg")

    def test_crlf_and_missing_trailing_newline_are_preserved(self):
        crlf = SRC.replace("\n", "\r\n")
        r = apply_patch(crlf, insert(), "acme.c", "pkg")
        self.assertNotIn("\n", r.new_text.replace("\r\n", ""))
        self.assertEqual(remove_patch(r.new_text, "acme.c", "reg", r.sha256), crlf)
        no_nl = "a = 1\n# forge:anchor routers"
        r = apply_patch(no_nl, insert(), "acme.c", "pkg")
        self.assertEqual(remove_patch(r.new_text, "acme.c", "reg", r.sha256), no_nl + "\n")

    def test_other_comment_styles(self):
        r = apply_patch("// forge:anchor routers\n", insert("app.use(x);\n", comment="//"), "acme.c", "pkg")
        self.assertIn("// forge:begin acme.c:reg", r.new_text)

    def test_package_placeholder_is_rendered(self):
        r = apply_patch(SRC, insert("from {{package}} import z\n"), "acme.c", "mypkg")
        self.assertIn("from mypkg import z", r.new_text)


class TomlAndJsonTests(unittest.TestCase):
    BASE = '[project]\nname = "x"\n'
    P = Patch("cfg", "pyproject.toml", "toml-table", content='[tool.ruff]\nline-length = 100\n\n[tool.ruff.lint]\nselect = ["F"]\n')

    def test_append_tables_keeps_file_valid_and_removal_is_exact(self):
        r = apply_patch(self.BASE, self.P, "acme.c", "pkg")
        d = tomllib.loads(r.new_text)
        self.assertEqual(d["tool"]["ruff"]["line-length"], 100)
        self.assertEqual(d["project"]["name"], "x")
        self.assertEqual(remove_patch(r.new_text, "acme.c", "cfg", r.sha256), self.BASE)

    def test_existing_identical_tables_are_left_alone(self):
        text = self.BASE + '\n[tool.ruff]\nline-length = 100\n\n[tool.ruff.lint]\nselect = ["F"]\n'
        self.assertEqual(apply_patch(text, self.P, "acme.c", "pkg").status, "unchanged")

    def test_differing_or_partial_tables_conflict(self):
        for existing in ('[tool.ruff]\nline-length = 88\n', '[tool.ruff]\nline-length = 100\n'):
            with self.assertRaises(PatchConflict) as cm:
                apply_patch(self.BASE + existing, self.P, "acme.c", "pkg")
            self.assertEqual(cm.exception.code, "config-key-conflict", existing)

    def test_invalid_inputs(self):
        for text, patch, code in (
                ("not = [valid", self.P, "target-unparseable"),
                (self.BASE, Patch("c", "p.toml", "toml-table", content="a = 1\n"), "patch-invalid"),
                (self.BASE, Patch("c", "p.toml", "toml-table", content="[a\n"), "patch-invalid"),
                (self.BASE, Patch("c", "p.toml", "toml-table", content="[[a]]\nx = 1\n"), "patch-invalid")):
            with self.assertRaises(PatchConflict) as cm:
                apply_patch(text, patch, "acme.c", "pkg")
            self.assertEqual(cm.exception.code, code)

    def test_json_merge(self):
        p = Patch("cfg", "c.json", "json-merge", data={"a": {"b": 1}, "list": [1, 2], "pkg": "{{package}}"})
        base = json.dumps({"a": {"c": 2}, "list": [2, 3]})
        r = apply_patch(base, p, "acme.c", "mypkg")
        self.assertEqual(json.loads(r.new_text), {"a": {"c": 2, "b": 1}, "list": [2, 3, 1], "pkg": "mypkg"})
        self.assertEqual(apply_patch(r.new_text, p, "acme.c", "mypkg").status, "unchanged")
        with self.assertRaises(PatchConflict) as cm:
            apply_patch(json.dumps({"a": {"b": 99}}), p, "acme.c", "mypkg")
        self.assertEqual(cm.exception.code, "config-key-conflict")


class PatchManifestValidationTests(unittest.TestCase):
    def manifest(self, patches):
        import pathlib
        from app_forge.catalog.registry import BUILTIN_COMPONENTS
        d = tomllib.loads((BUILTIN_COMPONENTS / "forge.themes/1.0.0/component.toml").read_text())
        d["integration"]["patches"] = patches
        return d

    def test_valid_and_invalid_patches(self):
        ok = {"id": "p-one", "file": "a.py", "kind": "insert", "anchor": "x", "content": "y\n"}
        self.assertEqual(parse_manifest(self.manifest([ok])).patches[0].anchor, "x")
        bad = [{"id": "P", "file": "../a.py", "kind": "weird"},
               {"id": "p-two", "file": "a.py", "kind": "insert", "content": ""},
               {"id": "p-three", "file": "a.py", "kind": "json-merge"},
               {"id": "p-one", "file": "a.py", "kind": "toml-table", "content": "[a]\n"},
               {"id": "p-one", "file": "a.py", "kind": "insert", "anchor": "Bad Anchor", "content": "x", "comment": "!!"}]
        from app_forge.domain.errors import ValidationFailure
        with self.assertRaises(ValidationFailure) as cm:
            parse_manifest(self.manifest(bad))
        self.assertGreaterEqual(len(cm.exception.details), 8)


class PatchFlowTests(ForgeTestCase):
    def setUp(self):
        super().setUp()
        self.s = self.services()

    def apply(self, proj, ids, **kw):
        p = self.s.plan_add(proj, {i: "*" for i in ids})
        self.assertEqual(p["conflicts"], [], p["conflicts"])
        self.s.approve_plan(p["plan_id"], "t")
        r = self.s.apply_plan(p["plan_id"], **kw)
        return p, r

    def test_greenfield_components_with_patches(self):
        for arch, comp, needle in (("web", "forge.health-endpoint", '@app.get("/healthz")'),
                                   ("cli", "forge.cli-version-command", "def version()"),
                                   ("desktop", "forge.ruff-config", "[tool.ruff]")):
            out = self.tmp / arch
            r = self.s.create_project(arch, {"name": "Patched App"}, out, components=[comp])
            self.assertTrue(r["patches"], arch)
            self.assertIn(needle, "".join((out / f).read_text() for f in ("src/patched_app/api.py", "src/patched_app/cli.py",
                                                                         "pyproject.toml") if (out / f).exists()))
            rep = self.s.verify_project(out)
            self.assertEqual(rep["overall"], "passed", (arch, [e for e in rep["evidence"] if e["status"] != "passed"]))
        api = (self.tmp / "web" / "src/patched_app/api.py").read_text()
        self.assertIn("    # forge:begin forge.health-endpoint:register-healthz\n    @app.get", api)  # inside create_app

    def test_add_to_existing_project_then_recover_is_byte_exact(self):
        proj = self.make_project(self.s, "web", "Web Flow")
        before = snapshot_tree(proj)
        plan = self.s.plan_add(proj, {"forge.health-endpoint": "*"})
        self.assertEqual({(c["action"], c["path"]) for c in plan["changes"]},
                         {("create", "src/web_flow/health.py"), ("create", "tests/test_health.py"),
                          ("modify", "src/web_flow/api.py"), ("create", ".forge/components.toml")})
        self.assertEqual(snapshot_tree(proj), before)  # planning wrote nothing
        content = self.s.preview_plan(plan["plan_id"], with_content=True)
        self.assertIn("healthz", next(c["content"] for c in content["changes"] if c["path"].endswith("api.py")))
        self.s.approve_plan(plan["plan_id"], "t")
        r = self.s.apply_plan(plan["plan_id"])
        self.assertEqual((r["status"], r["verification"]["overall"]), ("applied", "passed"))
        self.assertEqual(self.s.plan_add(proj, {"forge.health-endpoint": "*"})["changes"], [])  # already installed
        self.assertEqual(self.s.recover_plan(plan["plan_id"])["status"], "rolled_back")
        self.assertEqual(snapshot_tree(proj), before)

    def test_remove_unpatches_exactly_and_protects_user_edits(self):
        proj = self.make_project(self.s, "web", "Web Rm")
        original = (proj / "src/web_rm/api.py").read_text()
        self.apply(proj, ["forge.health-endpoint"])
        api = proj / "src/web_rm/api.py"
        api.write_bytes(api.read_text().replace("    app = FastAPI", "    # my note\n    app = FastAPI").encode())  # edit outside block
        rp = self.s.plan_remove(proj, ["forge.health-endpoint"])
        self.assertEqual(rp["conflicts"], [])
        self.s.approve_plan(rp["plan_id"], "t")
        self.assertEqual(self.s.apply_plan(rp["plan_id"])["status"], "applied")
        self.assertEqual(api.read_text(), original.replace("    app = FastAPI", "    # my note\n    app = FastAPI"))
        self.assertEqual(self.s.analyze_project(proj)["installed_components"], [])

    def test_remove_blocked_when_block_was_edited(self):
        proj = self.make_project(self.s, "web", "Web Ed")
        self.apply(proj, ["forge.health-endpoint"])
        api = proj / "src/web_ed/api.py"
        api.write_text(api.read_text().replace("return health_payload()", "return health_payload({'x': True})"))
        rp = self.s.plan_remove(proj, ["forge.health-endpoint"])
        self.assertEqual([c["code"] for c in rp["conflicts"]], ["patch-modified"])

    def test_missing_anchor_or_target_blocks_the_plan(self):
        proj = self.make_project(self.s, "web", "Web No")
        api = proj / "src/web_no/api.py"
        api.write_text(api.read_text().replace("    # forge:anchor routers\n", ""))
        p = self.s.plan_add(proj, {"forge.health-endpoint": "*"})
        self.assertEqual([c["code"] for c in p["conflicts"]], ["anchor-missing"])
        with self.assertRaises(ConflictFailure):
            self.s.approve_plan(p["plan_id"], "t")
        api.unlink()
        p = self.s.plan_add(proj, {"forge.health-endpoint": "*"})
        self.assertIn("patch-target-missing", {c["code"] for c in p["conflicts"]})

    def test_greenfield_with_missing_patch_target_is_refused(self):
        self.custom_component("acme.nowhere", patches=['[[integration.patches]]\nid = "p-x"\nfile = "nope.py"\n'
                                                       'kind = "insert"\nanchor = "a"\ncontent = "x"\n'])
        with self.assertRaises(ConflictFailure):
            self.services().create_project("cli", {"name": "No Where"}, self.tmp / "nw", components=["acme.nowhere"])

    def test_patch_and_dependency_edit_share_one_pyproject_change(self):
        self.custom_component("acme.both", python_packages=("attrs>=23",), patches=[
            '[[integration.patches]]\nid = "cfg-tables"\nfile = "pyproject.toml"\nkind = "toml-table"\n'
            "content = '''\n[tool.acme]\nenabled = true\n'''\n"])
        s = self.services()
        proj = self.make_project(s, "cli", "Both App")
        p = s.plan_add(proj, {"acme.both": "*"})
        self.assertEqual(sum(1 for c in p["changes"] if c["path"] == "pyproject.toml"), 1)
        s.approve_plan(p["plan_id"], "t")
        self.assertEqual(s.apply_plan(p["plan_id"])["status"], "applied")
        d = tomllib.loads((proj / "pyproject.toml").read_text())
        self.assertTrue(d["tool"]["acme"]["enabled"])
        self.assertIn("attrs>=23", d["project"]["dependencies"])

    def test_upgrade_replaces_managed_block_and_protects_edits(self):
        def comp(version, body):
            self.custom_component("acme.up", version, files={"src/up_mod.py": f"V = '{version}'\n"}, patches=[
                '[[integration.patches]]\nid = "hook"\nfile = "src/{{package}}/cli.py"\nkind = "insert"\n'
                f'anchor = "commands"\ncontent = "{body}"\n'])
        comp("1.0.0", "HOOK = 1")
        comp("2.0.0", "HOOK = 2")
        s = self.services()
        proj = self.make_project(s, "cli", "Up Patch")
        p = s.plan_add(proj, {"acme.up": "==1.0.0"})
        s.approve_plan(p["plan_id"], "t")
        s.apply_plan(p["plan_id"])
        cli = proj / "src/up_patch/cli.py"
        snap = cli.read_text()
        up = s.plan_upgrade(proj, ["acme.up"])
        self.assertEqual(up["conflicts"], [])
        s.approve_plan(up["plan_id"], "t")
        self.assertEqual(s.apply_plan(up["plan_id"])["status"], "applied")
        text = cli.read_text()
        self.assertIn("HOOK = 2", text)
        self.assertNotIn("HOOK = 1", text)
        self.assertEqual(text.count("forge:begin"), 1)
        self.assertEqual(s.recover_plan(up["plan_id"])["status"], "rolled_back")
        self.assertEqual(cli.read_text(), snap)
        cli.write_text(cli.read_text().replace("HOOK = 1", "HOOK = 1  # tuned"))
        self.assertEqual([c["code"] for c in s.plan_upgrade(proj, ["acme.up"])["conflicts"]], ["patch-modified"])

    def test_json_merge_component_warns_and_conflicts_properly(self):
        self.custom_component("acme.json", patches=['[[integration.patches]]\nid = "cfg-json"\nfile = "settings.json"\n'
                                                    'kind = "json-merge"\n[integration.patches.data]\nfeature = true\n'])
        s = self.services()
        proj = self.make_project(s, "cli", "Json App")
        (proj / "settings.json").write_text('{"name": "x"}\n')
        p = s.plan_add(proj, {"acme.json": "*"})
        self.assertTrue(any("re-serialised" in w for w in p["warnings"]))
        s.approve_plan(p["plan_id"], "t")
        s.apply_plan(p["plan_id"])
        self.assertEqual(json.loads((proj / "settings.json").read_text()), {"name": "x", "feature": True})
        rp = s.plan_remove(proj, ["acme.json"])
        self.assertTrue(any("remove them manually" in w for w in rp["warnings"]))
        (proj / "settings.json").write_text('{"feature": false}\n')
        s2 = self.services()
        proj2 = self.make_project(s2, "cli", "Json Two", where=self.tmp / "two")
        (proj2 / "settings.json").write_text('{"feature": false}\n')
        self.assertEqual([c["code"] for c in s2.plan_add(proj2, {"acme.json": "*"})["conflicts"]], ["config-key-conflict"])

    def test_flat_layout_third_party_project_with_manual_anchor(self):
        self.custom_component("acme.flat", files={"src/flat_new.py": "N = 1\n"}, patches=[
            '[[integration.patches]]\nid = "hook"\nfile = "src/{{package}}/mod.py"\nkind = "insert"\n'
            'anchor = "hooks"\ncontent = "import flat_new"\n'])
        root = self.tmp / "legacy"
        (root / "legacy").mkdir(parents=True)
        (root / "legacy" / "__init__.py").write_text("")
        (root / "legacy" / "mod.py").write_text("# forge:anchor hooks\n")
        (root / "pyproject.toml").write_text('[project]\nname="legacy"\nversion="1"\n')
        s = self.services()
        p = s.plan_add(root, {"acme.flat": "*"})
        self.assertEqual(p["conflicts"], [])
        self.assertIn(("modify", "legacy/mod.py"), {(c["action"], c["path"]) for c in p["changes"]})


if __name__ == "__main__":
    unittest.main()
