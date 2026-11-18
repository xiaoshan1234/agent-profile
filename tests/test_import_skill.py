from __future__ import annotations

import json
import io
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from import_skill import import_skill
from import_skill import _download_github_skill
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
                    "schema": 2,
                    "name": "analyst",
                    "description": "Test role.",
                    "soul": "SOUL.md",
                    "skills": [],
                }
            ),
            encoding="utf-8",
        )
        (self.root / "roles" / "analyst" / "SOUL.md").write_text(
            "# Analyst\n",
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
            skill_id="shared/custom-analysis",
            from_dir=str(source),
            git=None,
            ref="main",
            git_path=None,
            hermes_identifier=None,
            origin_kind=None,
            install_as=None,
            force=False,
            common=False,
            role="analyst",
        )

        copied = self.root / "skills" / "shared" / "custom-analysis" / "SKILL.md"
        self.assertTrue(copied.is_file())
        catalog = json.loads((self.root / "catalog" / "skills.json").read_text(encoding="utf-8"))
        entry = catalog["skills"]["shared/custom-analysis"]
        self.assertEqual(entry["source"], "file")
        self.assertEqual(entry["origin"]["type"], "local")
        role = json.loads(
            (self.root / "roles" / "analyst" / "role.json").read_text(encoding="utf-8")
        )
        self.assertEqual(role["skills"], ["shared/custom-analysis"])
        self.assertEqual(rebuild(self.root, check=False), 0)

    def test_register_hermes_registry_skill_as_common(self) -> None:
        import_skill(
            self.root,
            skill_id="shared/registry-skill",
            from_dir=None,
            git=None,
            ref="main",
            git_path=None,
            hermes_identifier="official/test/registry-skill",
            origin_kind=None,
            install_as="registry-skill",
            force=False,
            common=True,
            role=None,
        )

        catalog = json.loads((self.root / "catalog" / "skills.json").read_text(encoding="utf-8"))
        entry = catalog["skills"]["shared/registry-skill"]
        self.assertEqual(entry["source"], "hermes")
        self.assertEqual(entry["identifier"], "official/test/registry-skill")
        common = json.loads((self.root / "catalog" / "common.json").read_text(encoding="utf-8"))
        self.assertEqual(common["skills"], ["shared/registry-skill"])

    def test_downloads_github_archive_and_selects_skill_path(self) -> None:
        payload = io.BytesIO()
        with zipfile.ZipFile(payload, "w") as archive:
            archive.writestr(
                "repo-main/skills/example/SKILL.md",
                "---\nname: example\ndescription: Example skill.\n---\n",
            )
        class Response(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        response = Response(payload.getvalue())

        with tempfile.TemporaryDirectory() as temp_name:
            with mock.patch("import_skill.urllib.request.urlopen", return_value=response):
                source = _download_github_skill(
                    "owner/repo",
                    "main",
                    "skills/example",
                    Path(temp_name),
                )
            self.assertEqual(source.name, "example")
            self.assertTrue((source / "SKILL.md").is_file())


if __name__ == "__main__":
    unittest.main()
