from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from import_skill import import_skill
from rebuild_catalog import rebuild


class ImportSkillTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "repo"
        (self.root / "catalog").mkdir(parents=True)
        (self.root / "roles" / "analyst").mkdir(parents=True)
        (self.root / "catalog" / "common.json").write_text(
            json.dumps({"schema": 1, "skills": []}),
            encoding="utf-8",
        )
        (self.root / "catalog" / "skills.json").write_text(
            json.dumps({"schema": 1, "skills": {}}),
            encoding="utf-8",
        )
        (self.root / "roles" / "analyst" / "role.json").write_text(
            json.dumps(
                {
                    "schema": 1,
                    "name": "analyst",
                    "description": "Test role.",
                    "soul": {"mode": "none"},
                    "skills": [],
                }
            ),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_import_local_skill_and_attach_to_role(self) -> None:
        source = Path(self.temp.name) / "my-skill"
        source.mkdir()
        (source / "SKILL.md").write_text(
            "---\n"
            "name: custom-analysis\n"
            "description: Analyze a test fixture.\n"
            "---\n\n"
            "# Custom analysis\n",
            encoding="utf-8",
        )

        import_skill(
            self.root,
            skill_id="custom-analysis",
            from_dir=str(source),
            git=None,
            ref="main",
            git_path=None,
            hermes_identifier=None,
            kind=None,
            install_as=None,
            force=False,
            common=False,
            role="analyst",
        )

        copied = self.root / "skills" / "local" / "custom-analysis" / "SKILL.md"
        self.assertTrue(copied.is_file())
        catalog = json.loads((self.root / "catalog" / "skills.json").read_text(encoding="utf-8"))
        self.assertEqual(catalog["skills"]["custom-analysis"]["source"], "local")
        role = json.loads(
            (self.root / "roles" / "analyst" / "role.json").read_text(encoding="utf-8")
        )
        self.assertEqual(role["skills"], ["custom-analysis"])
        self.assertEqual(rebuild(self.root, check=False), 0)

    def test_register_hermes_registry_skill_as_common(self) -> None:
        import_skill(
            self.root,
            skill_id="registry-skill",
            from_dir=None,
            git=None,
            ref="main",
            git_path=None,
            hermes_identifier="official/test/registry-skill",
            kind=None,
            install_as="registry-skill",
            force=False,
            common=True,
            role=None,
        )

        catalog = json.loads((self.root / "catalog" / "skills.json").read_text(encoding="utf-8"))
        entry = catalog["skills"]["registry-skill"]
        self.assertEqual(entry["source"], "hermes")
        self.assertEqual(entry["identifier"], "official/test/registry-skill")
        common = json.loads((self.root / "catalog" / "common.json").read_text(encoding="utf-8"))
        self.assertEqual(common["skills"], ["registry-skill"])


if __name__ == "__main__":
    unittest.main()
