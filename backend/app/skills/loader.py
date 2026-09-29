from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class LoadedSkill:
    name: str
    path: Path
    content: str
    metadata: dict[str, Any]
    references: dict[str, str]

    def as_prompt_context(self, *, max_chars: int = 16000) -> str:
        parts = [
            f"# Skill: {self.name}",
            self.content.strip(),
        ]
        if self.references:
            parts.append("# Skill References")
            for path, content in self.references.items():
                parts.append(f"## {path}\n{content.strip()}")
        text = "\n\n".join(part for part in parts if part)
        return text[:max_chars]


class SkillLoader:
    def __init__(self, skills_root: Path | None = None) -> None:
        self.skills_root = skills_root or _default_skills_root()

    def load(self, name: str, *, include_references: bool = True, max_reference_chars: int = 6000) -> LoadedSkill | None:
        skill_dir = self.skills_root / name
        skill_path = skill_dir / "SKILL.md"
        if not skill_path.exists():
            return None
        content = skill_path.read_text(encoding="utf-8")
        references: dict[str, str] = {}
        if include_references:
            references_dir = skill_dir / "references"
            if references_dir.exists():
                for reference_path in sorted(references_dir.glob("*.md")):
                    references[str(reference_path.relative_to(skill_dir))] = reference_path.read_text(
                        encoding="utf-8"
                    )[:max_reference_chars]
        return LoadedSkill(
            name=name,
            path=skill_path,
            content=content,
            metadata=_parse_frontmatter(content),
            references=references,
        )

    def load_from_manifest_agent(self, agent_module_suffix: str) -> LoadedSkill | None:
        manifest_path = self.skills_root / "skills_manifest.json"
        if not manifest_path.exists():
            return None
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for item in manifest.get("skills", []):
            if str(item.get("agent_module", "")).endswith(agent_module_suffix):
                path = Path(str(item.get("path", "")))
                return self.load(path.parent.name)
        return None


def _default_skills_root() -> Path:
    return Path(__file__).resolve().parents[3] / "skills"


def _parse_frontmatter(content: str) -> dict[str, Any]:
    if not content.startswith("---"):
        return {}
    parts = content.split("---", 2)
    if len(parts) < 3:
        return {}
    metadata: dict[str, Any] = {}
    for line in parts[1].splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        metadata[key.strip()] = value.strip().strip('"').strip("'")
    return metadata
