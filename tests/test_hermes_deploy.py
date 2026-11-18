from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import deploy_hermes
from rebuild_catalog import rebuild


class HermesDeployTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "repo"
        self.root.mkdir()
        self.hermes_home = Path(self.temp.name) / "hermes"
        self.hermes_home.mkdir()
        self.fake_hermes = Path(self.temp.name) / "hermes-bin"
        self.fake_hermes.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        self.fake_hermes.chmod(0o755)
        self._make_repo()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _write_skill(self, bucket: str, skill_id: str, description: str) -> None:
        skill = self.root / "skills" / bucket / skill_id
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text(
            "---\n"
            f"name: {skill_id}\n"
            f"description: {description}\n"
            "---\n\n"
            f"# {skill_id}\n",
            encoding="utf-8",
        )

    def _make_repo(self) -> None:
        (self.root / "catalog").mkdir()
        (self.root / "catalog" / "common.json").write_text(
            json.dumps({"schema": 1, "skills": ["kanban"]}),
            encoding="utf-8",
        )
        (self.root / "catalog" / "skills.json").write_text(
            json.dumps({"schema": 1, "skills": {}}),
            encoding="utf-8",
        )
        self._write_skill("vendor", "kanban", "Shared task tracking.")
        self._write_skill("local", "domain-skill", "Role-specific workflow.")
        role = self.root / "roles" / "coach"
        role.mkdir(parents=True)
        (role / "SOUL.md").write_text(
            "# Coach\n\nPersona.\n\n---\n\n# Coach usage\n\nUsage.\n",
            encoding="utf-8",
        )
        (role / "role.json").write_text(
            json.dumps(
                {
                    "schema": 2,
                    "name": "coach",
                    "description": "Test coach role.",
                    "soul": "SOUL.md",
                    "skills": ["domain-skill"],
                }
            ),
            encoding="utf-8",
        )
        rebuild(self.root, check=False)

    def _options(self, **kwargs):
        values = {
            "role": "coach",
            "profile": None,
            "description": None,
            "soul": "role",
            "no_alias": True,
            "update_skills": False,
            "dry_run": False,
        }
        values.update(kwargs)
        return deploy_hermes.DeployOptions(**values)

    def _fake_create(self, command, *, cwd, check):
        profile = self.hermes_home / "profiles" / command[3]
        (profile / "skills").mkdir(parents=True)
        (profile / "SOUL.md").write_text("Hermes default\n", encoding="utf-8")

    @mock.patch.object(deploy_hermes.subprocess, "run")
    def test_missing_profile_is_created_and_second_run_is_idempotent(self, run) -> None:
        run.side_effect = self._fake_create
        with mock.patch.dict(
            os.environ,
            {
                "HERMES_HOME": str(self.hermes_home),
                "HERMES_BIN": str(self.fake_hermes),
            },
        ):
            self.assertEqual(deploy_hermes.deploy(self.root, self._options()), 0)
            profile = self.hermes_home / "profiles" / "coach"
            self.assertTrue((profile / "skills" / "kanban" / "SKILL.md").is_file())
            self.assertTrue((profile / "skills" / "domain-skill" / "SKILL.md").is_file())
            soul = (profile / "SOUL.md").read_text(encoding="utf-8")
            self.assertIn("Persona.", soul)
            self.assertIn("Usage.", soul)
            self.assertEqual(run.call_count, 1)
            self.assertEqual(run.call_args.args[0][1:3], ["profile", "create"])

            self.assertEqual(deploy_hermes.deploy(self.root, self._options()), 0)
            self.assertEqual(run.call_count, 1)

    @mock.patch.object(deploy_hermes.subprocess, "run")
    def test_existing_profile_is_not_created_and_soul_none_preserves_soul(self, run) -> None:
        profile = self.hermes_home / "profiles" / "coach"
        custom = profile / "skills" / "kanban" / "SKILL.md"
        custom.parent.mkdir(parents=True)
        custom.write_text("local modification\n", encoding="utf-8")
        (profile / "SOUL.md").write_text("Keep this SOUL\n", encoding="utf-8")

        with mock.patch.dict(
            os.environ,
            {
                "HERMES_HOME": str(self.hermes_home),
                "HERMES_BIN": str(self.fake_hermes),
            },
        ):
            deploy_hermes.deploy(self.root, self._options(soul="none"))

        run.assert_not_called()
        self.assertEqual(custom.read_text(encoding="utf-8"), "local modification\n")
        self.assertEqual((profile / "SOUL.md").read_text(encoding="utf-8"), "Keep this SOUL\n")
        self.assertTrue((profile / "skills" / "domain-skill" / "SKILL.md").is_file())

    @mock.patch.object(deploy_hermes.subprocess, "run")
    def test_update_skills_replaces_after_backup(self, run) -> None:
        profile = self.hermes_home / "profiles" / "coach"
        custom = profile / "skills" / "kanban" / "SKILL.md"
        custom.parent.mkdir(parents=True)
        custom.write_text("local modification\n", encoding="utf-8")

        with mock.patch.dict(
            os.environ,
            {
                "HERMES_HOME": str(self.hermes_home),
                "HERMES_BIN": str(self.fake_hermes),
            },
        ):
            deploy_hermes.deploy(
                self.root,
                self._options(soul="none", update_skills=True),
            )

        run.assert_not_called()
        installed = (profile / "skills" / "kanban" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("Shared task tracking.", installed)
        backups = list((profile / ".role-deploy" / "backups").rglob("SKILL.md"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_text(encoding="utf-8"), "local modification\n")

    @mock.patch.object(deploy_hermes.subprocess, "run")
    def test_parts_skills_only_preserves_existing_soul(self, run) -> None:
        profile = self.hermes_home / "profiles" / "coach"
        (profile / "skills").mkdir(parents=True)
        (profile / "SOUL.md").write_text("Existing SOUL\n", encoding="utf-8")

        with mock.patch.dict(
            os.environ,
            {
                "HERMES_HOME": str(self.hermes_home),
                "HERMES_BIN": str(self.fake_hermes),
            },
        ):
            deploy_hermes.deploy(
                self.root,
                self._options(parts="skills", existing_only=True),
            )

        run.assert_not_called()
        self.assertEqual((profile / "SOUL.md").read_text(encoding="utf-8"), "Existing SOUL\n")
        self.assertTrue((profile / "skills" / "domain-skill" / "SKILL.md").is_file())

    @mock.patch.object(deploy_hermes.subprocess, "run")
    def test_existing_only_rejects_missing_profile(self, run) -> None:
        with mock.patch.dict(
            os.environ,
            {
                "HERMES_HOME": str(self.hermes_home),
                "HERMES_BIN": str(self.fake_hermes),
            },
        ):
            with self.assertRaisesRegex(deploy_hermes.RepoError, "Profile does not exist"):
                deploy_hermes.deploy(
                    self.root,
                    self._options(parts="skills", existing_only=True),
                )
        run.assert_not_called()

    @mock.patch.object(deploy_hermes.subprocess, "run")
    def test_parts_soul_only_does_not_install_role_skills(self, run) -> None:
        profile = self.hermes_home / "profiles" / "coach"
        profile.mkdir(parents=True)

        with mock.patch.dict(
            os.environ,
            {
                "HERMES_HOME": str(self.hermes_home),
                "HERMES_BIN": str(self.fake_hermes),
            },
        ):
            deploy_hermes.deploy(
                self.root,
                self._options(parts="soul", existing_only=True),
            )

        run.assert_not_called()
        self.assertIn("Persona.", (profile / "SOUL.md").read_text(encoding="utf-8"))
        self.assertFalse((profile / "skills" / "domain-skill").exists())


if __name__ == "__main__":
    unittest.main()
