"""Load and check the editable pathway guidance file."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

GUIDANCE_PATH = Path(__file__).resolve().parent.parent / "guidance" / "pathway.json"

STAGE_ORDER = ["referral", "review", "initial_appointment", "specialist_assessment", "feedback"]
SECTIONS = ["what_happens", "preparation", "questions", "contacts"]
STATUSES = {"verified", "unverified"}


class GuidanceError(Exception):
    """The guidance file is missing or not in the expected shape."""


def _check_item(item: Any, where: str, sources: dict[str, Any], problems: list[str]) -> None:
    if not isinstance(item, dict) or not str(item.get("text", "")).strip():
        problems.append(f"{where}: each item needs some text.")
        return
    status = item.get("status")
    if status not in STATUSES:
        problems.append(f"{where}: status must be 'verified' or 'unverified'.")
    source = item.get("source")
    if status == "verified":
        if source not in sources:
            problems.append(f"{where}: a verified item must name a known source.")
    elif source is not None and source not in sources:
        problems.append(f"{where}: unknown source '{source}'.")


def validate(data: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    sources = data.get("sources")
    if not isinstance(sources, dict) or not sources:
        return ["The file needs a 'sources' section."]
    for key, source in sources.items():
        if not str(source.get("url", "")).startswith("https://"):
            problems.append(f"Source '{key}' needs an https:// URL.")
        try:
            date.fromisoformat(str(source.get("verified_on", "")))
        except ValueError:
            problems.append(f"Source '{key}' needs a verified_on date (YYYY-MM-DD).")

    for list_name in ("route_notes", "assessment_vs_diagnosis", "benchmarks"):
        for index, item in enumerate(data.get(list_name, [])):
            _check_item(item, f"{list_name}[{index}]", sources, problems)

    stages = data.get("stages", [])
    ids = [stage.get("id") for stage in stages]
    if ids != STAGE_ORDER:
        problems.append(f"Stages must be, in order: {', '.join(STAGE_ORDER)}.")
    for stage in stages:
        for section in SECTIONS:
            for index, item in enumerate(stage.get(section, [])):
                _check_item(item, f"{stage.get('id')}.{section}[{index}]", sources, problems)
    return problems


def load_guidance(path: Path = GUIDANCE_PATH) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise GuidanceError(f"Guidance file not found: {path.name}") from exc
    except json.JSONDecodeError as exc:
        raise GuidanceError(f"Guidance file is not valid JSON (line {exc.lineno}).") from exc
    problems = validate(data)
    if problems:
        raise GuidanceError("Guidance file needs fixing: " + " ".join(problems))
    return data


def stage_by_id(data: dict[str, Any], stage_id: str) -> dict[str, Any]:
    for stage in data["stages"]:
        if stage["id"] == stage_id:
            return stage
    raise KeyError(stage_id)


def unverified_items(data: dict[str, Any]) -> list[tuple[str, str]]:
    """(where, text) for every item still marked unverified."""
    found: list[tuple[str, str]] = []
    for list_name in ("route_notes", "assessment_vs_diagnosis", "benchmarks"):
        for item in data.get(list_name, []):
            if item["status"] == "unverified":
                found.append((list_name, item["text"]))
    for stage in data["stages"]:
        for section in SECTIONS:
            for item in stage.get(section, []):
                if item["status"] == "unverified":
                    found.append((f"{stage['title']} – {section.replace('_', ' ')}", item["text"]))
    return found
