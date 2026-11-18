"""Unit tests for the role skill scout's pure helpers (no network, no repo writes)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from role_skill_scout import GENERIC_NAMES, plan_import, score_candidate, slugify  # noqa: E402


class ScoutScoringTests(unittest.TestCase):
    def test_score_prefers_name_hits(self):
        keywords = ["ielts", "speaking", "band"]
        in_name, hits = score_candidate({"name": "IELTS Speaking Coach", "description": "band scores"}, keywords)
        in_body, _ = score_candidate({"name": "Generic Tutor", "description": "helps with ielts speaking"}, keywords)
        self.assertGreater(in_name, in_body)
        self.assertIn("ielts", hits)

    def test_unrelated_candidate_scores_zero(self):
        score, hits = score_candidate({"name": "Minecraft Server", "description": "mods and plugins"},
                                      ["ielts", "speaking"])
        self.assertEqual(score, 0)
        self.assertEqual(hits, [])

    def test_slugify_is_stable_and_short(self):
        self.assertEqual(slugify("IELTS Speaking Mock Exam!"), "ielts-speaking-mock-exam")
        self.assertLessEqual(len(slugify("x" * 200)), 40)
        self.assertEqual(slugify("!!!"), "skill")

    def test_generic_names_are_blocked(self):
        self.assertIn(slugify("Fitness"), GENERIC_NAMES)
        self.assertNotIn(slugify("Afrexai Fitness Engine"), GENERIC_NAMES)


class ScoutPlanTests(unittest.TestCase):
    def test_github_identifier_maps_to_repo_and_path(self):
        kind, detail = plan_import({"identifier": "openai/skills/skills/.curated/pdf", "source": "github"}, "pdf-guide")
        self.assertEqual(kind, "github")
        self.assertEqual(detail["owner"], "openai")
        self.assertEqual(detail["repo"], "skills")
        self.assertEqual(detail["hints"][0], ["skills", ".curated", "pdf"])

    def test_skills_sh_identifier_strips_registry_prefix(self):
        kind, detail = plan_import({"identifier": "skills-sh/anthropics/skills/pdf", "source": "skills.sh"}, "pdf")
        self.assertEqual(kind, "github")
        self.assertEqual((detail["owner"], detail["repo"]), ("anthropics", "skills"))

    def test_clawhub_identifier_is_a_slug(self):
        kind, detail = plan_import({"identifier": "ielts-speaking-mock-exam", "source": "clawhub"}, "ielts-speaking")
        self.assertEqual(kind, "clawhub")
        self.assertEqual(detail["slug"], "ielts-speaking-mock-exam")

    def test_unusable_identifier_is_reported(self):
        kind, _ = plan_import({"identifier": "owner/repo-without-skill-path", "source": "weird-registry"}, "x")
        self.assertEqual(kind, "unknown")


if __name__ == "__main__":
    unittest.main()
