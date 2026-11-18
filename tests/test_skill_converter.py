from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONVERTER = ROOT / "skills" / "shared" / "skill-converter" / "scripts"
sys.path.insert(0, str(CONVERTER))

import convert_skill


class SkillConverterTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "repo"
        (self.root / "skills").mkdir(parents=True)
        self.source = Path(self.temp.name) / "source-skill"
        (self.source / "agents").mkdir(parents=True)
        (self.source / "scripts").mkdir()
        (self.source / "agents" / "openai.yaml").write_text(
            'interface:\n  display_name: "Source skill"\n',
            encoding="utf-8",
        )
        (self.source / "scripts" / "helper.sh").write_text("#!/bin/sh\n", encoding="utf-8")
        (self.source / "SKILL.md").write_text(
            "---\n"
            "name: source-skill\n"
            "description: A deliberately long source description that must be shortened for Hermes compatibility while preserving the original workflow.\n"
            "metadata:\n"
            "  openclaw:\n"
            "    requires:\n"
            "      bins: [systemctl]\n"
            "---\n\n"
            "# Source Skill\n\n"
            "Use the Bash tool and Read tool on Linux.\n"
            "Run `systemctl status demo` after inspection.\n",
            encoding="utf-8",
        )
        self.original_repo = convert_skill.REPO_ROOT
        convert_skill.REPO_ROOT = self.root

    def tearDown(self) -> None:
        convert_skill.REPO_ROOT = self.original_repo
        self.temp.cleanup()

    def test_converts_codex_openclaw_skill_to_hermes(self) -> None:
        destination = convert_skill.convert(
            source_value=str(self.source),
            domain="documents",
            name="converted-skill",
            description=None,
            version="0.1.0",
            author="Original Author, Hermes Agent",
            license_name="MIT",
            platforms_value=None,
            force=False,
            dry_run=False,
        )

        text = (destination / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn('name: "converted-skill"', text)
        self.assertIn("platforms: [linux]", text)
        self.assertIn("Use the Bash tool and Read tool", text)
        self.assertTrue((destination / "scripts" / "helper.sh").is_file())
        self.assertFalse((destination / "agents").exists())
        report = (destination / "references" / "conversion-report.md").read_text(encoding="utf-8")
        self.assertIn("Codex agents/openai.yaml was excluded", report)
        self.assertIn("OpenClaw-style dependency metadata", report)
        self.assertIn("tool-like name", report)

    def test_dry_run_does_not_write_destination(self) -> None:
        destination = convert_skill.convert(
            source_value=str(self.source),
            domain="shared",
            name="preview-skill",
            description="Preview only.",
            version="0.1.0",
            author="Author, Hermes Agent",
            license_name="MIT",
            platforms_value="linux,macos,windows",
            force=False,
            dry_run=True,
        )
        self.assertFalse(destination.exists())


if __name__ == "__main__":
    unittest.main()
