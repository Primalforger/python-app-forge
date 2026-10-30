import unittest

from app_forge.domain.pydeps import combine, compare, normalize_name, parse_requirement as P, satisfiable
from tests.helpers import ForgeTestCase


class RequirementComparisonTests(unittest.TestCase):
    def verdict(self, existing, wanted):
        return compare(P(existing), P(wanted))["verdict"]

    def test_verdicts(self):
        cases = [("rich>=13", "rich>=14", "compatible"), ("rich>=13", "rich<13", "incompatible"),
                 ("rich>=13", "rich>=12", "satisfied"), ("rich", "rich>=1", "compatible"),
                 ("rich>=13", "rich", "satisfied"), ("x>=1,<3", "x>=1,<2", "compatible"),
                 ("x>=1,<2", "x>=1,<3", "satisfied"), ("x==1.2.3", "x~=1.2", "satisfied"),
                 ("x==2.0.0", "x~=1.2", "incompatible"), ("x==1.4.*", "x>=1.4,<1.5", "satisfied"),
                 ("x>=3", "x<3", "incompatible"), ("x>=3", "x<=3", "compatible"), ("x>3", "x<=3", "incompatible"),
                 ("x==2", "x!=2", "incompatible"), ("x!=2", "x>=1,<3", "compatible")]
        for e, w, expected in cases:
            self.assertEqual(self.verdict(e, w), expected, (e, w))

    def test_unknown_is_never_guessed(self):
        for e, w in (("x>=1; python_version<'3.12'", "x>=1"), ("x===1.0", "x>=1"), ("x>=1.0rc1", "x>=1"),
                     ("x @ https://example.invalid/x.zip", "x>=1")):
            self.assertEqual(self.verdict(e, w), "unknown", (e, w))

    def test_names_and_extras(self):
        self.assertEqual(P("Typing_Extensions[all]>=4").name, "typing-extensions")
        self.assertEqual(normalize_name("A.B_c"), "a-b-c")

    def test_combine_and_satisfiable(self):
        both = combine([P("a>=1"), P("a<3"), P("a>=1")])
        self.assertEqual(both.raw, "a>=1,<3")
        self.assertTrue(satisfiable(both))
        self.assertFalse(satisfiable(combine([P("a>=3"), P("a<2")])))


class DependencyPlanningTests(ForgeTestCase):
    def setUp(self):
        super().setUp()
        self.proj_name = "Dep App"

    def plan_with(self, *comps, archetype="cli", **kw):
        """comps: list of (id, [python packages]). The cli template already requires typer>=0.12 and rich>=13."""
        for cid, pkgs in comps:
            self.custom_component(cid, python_packages=tuple(pkgs))
        s = self.services()
        proj = kw.get("proj") or self.make_project(s, archetype, self.proj_name)
        return s, proj, s.plan_add(proj, {cid: "*" for cid, _ in comps})

    def changes(self, plan):
        return {d["package"]: d for d in plan["dependency_changes"]}

    def test_looser_existing_requirement_is_flagged_not_silently_skipped(self):
        s, proj, p = self.plan_with(("acme.a", ["rich>=14"]))
        d = self.changes(p)["rich"]
        self.assertEqual((d["action"], d["mode"], d["existing"], d["wanted"]), ("needs-review", "manual", "rich>=13", "rich>=14"))
        self.assertEqual(p["conflicts"], [])
        self.assertTrue(any("review dependency rich" in w for w in p["warnings"]))
        self.assertNotIn(("modify", "pyproject.toml"), {(c["action"], c["path"]) for c in p["changes"]})

    def test_incompatible_requirement_blocks_the_plan(self):
        s, proj, p = self.plan_with(("acme.a", ["rich<13"]))
        self.assertEqual([c["code"] for c in p["conflicts"]], ["dependency-incompatible"])
        self.assertIn("no version satisfies both", p["conflicts"][0]["message"])
        from app_forge.domain.errors import ConflictFailure
        with self.assertRaises(ConflictFailure):
            s.approve_plan(p["plan_id"], "t")

    def test_already_satisfied_and_new_packages(self):
        s, proj, p = self.plan_with(("acme.a", ["rich>=12", "attrs>=23"]))
        d = self.changes(p)
        self.assertEqual(d["rich"]["action"], "already-present")
        self.assertEqual((d["attrs"]["action"], d["attrs"]["mode"]), ("add", "auto"))
        s.approve_plan(p["plan_id"], "t")
        s.apply_plan(p["plan_id"])
        text = (proj / "pyproject.toml").read_text()
        self.assertIn('"attrs>=23"', text)
        self.assertEqual(text.count("rich"), 1)  # the existing requirement was never rewritten or duplicated

    def test_two_components_with_conflicting_needs(self):
        s, proj, p = self.plan_with(("acme.a", ["attrs>=23"]), ("acme.b", ["attrs<23"]))
        self.assertIn("dependency-incompatible", {c["code"] for c in p["conflicts"]})

    def test_two_components_with_compatible_needs_are_combined(self):
        s, proj, p = self.plan_with(("acme.a", ["attrs>=23"]), ("acme.b", ["attrs<25"]))
        self.assertEqual(p["conflicts"], [])
        self.assertEqual(self.changes(p)["attrs"]["spec"], "attrs>=23,<25")
        s.approve_plan(p["plan_id"], "t")
        s.apply_plan(p["plan_id"])
        self.assertIn('"attrs>=23,<25"', (proj / "pyproject.toml").read_text())

    def test_requirements_txt_of_third_party_project_is_respected(self):
        root = self.tmp / "legacy"
        (root / "legacy").mkdir(parents=True)
        (root / "legacy" / "__init__.py").write_text("")
        (root / "requirements.txt").write_text("rich==12.0.0\n")
        s, proj, p = self.plan_with(("acme.a", ["rich>=13"]), proj=root)
        self.assertEqual(p["level"], 3)
        self.assertEqual([c["code"] for c in p["conflicts"]], ["dependency-incompatible"])

    def test_unparseable_requirement_goes_to_manual_review(self):
        s, proj, p = self.plan_with(("acme.a", ["rich>=14; python_version>='3.8'"]))
        self.assertEqual(self.changes(p)["rich"]["action"], "needs-review")


if __name__ == "__main__":
    unittest.main()
