"""Build/check the two-hop, file-owned Company Brain memory map (stdlib only)."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

SECTIONS = ("Projects", "State", "Skills", "Memory", "Routines", "Not here")
ENTRY = re.compile(r"^- \[([^\]]+)\]\((.+)\):\s*(.*)$")
MAX_ITEMS = 67  # Six headings + six blanks + 67 entries = 79 lines, strictly below 80.
DEFAULT_ROOT = Path(__file__).resolve().parents[1]


def read_json(path: Path, default=None):
    return json.loads(path.read_text(encoding="utf-8-sig")) if path.is_file() else default


def key(path: Path | str) -> str:
    return str(Path(path).resolve()).replace("\\", "/").casefold()


def absolute(path: Path | str) -> str:
    return Path(path).resolve().as_posix()


def entry(line: str):
    match = ENTRY.fullmatch(line)
    if not match:
        return None
    label, target, note = match.groups()
    return label, target.strip("<>"), note


def configured(root: Path) -> dict:
    return read_json(root / "memory-map/config.json", {})


def project_folders(root: Path, config: dict) -> list[Path]:
    result = {key(root): root}
    # Only owner-registered project paths are included, never their whole drive.
    for record in read_json(root / "records/index.json", []):
        if record.get("kind") != "project" or record.get("archived"):
            continue
        record_path = root / "records/project" / record["id"] / f"v{record['version']:04d}.json"
        current = read_json(record_path, {})
        raw = current.get("data", {}).get("path")
        if raw:
            path = Path(raw)
            if not path.is_absolute():
                raise ValueError(f"Project {record['id']} has a non-absolute root: {raw}")
            result[key(path)] = path
    for raw in config.get("known_project_roots", []):
        path = Path(raw)
        result[key(path)] = path
    for raw in config.get("project_discovery_roots", [absolute(root / "company")]):
        parent = Path(raw)
        if parent.is_dir():
            result[key(parent)] = parent
            # Only these explicitly declared project containers are walked.
            for path in parent.rglob("*"):
                if path.is_dir() and not any(p in {".git", "__pycache__", "node_modules"} for p in path.parts):
                    result[key(path)] = path
    return sorted(result.values(), key=key)


def catalog(root: Path, config: dict) -> list[dict]:
    items: dict[str, dict] = {}

    def add(path, area, section, label=None, authority="project_source", canonical=None):
        path = Path(path).resolve()
        history_root = (root / "store/history").resolve()
        # Private message shards and their per-message index are served only by
        # dedicated history recall, never promoted into the document graph.
        if path.is_relative_to(history_root) and path not in {history_root, history_root / "coverage.json"}:
            return
        ident = key(path)
        if ident in items:
            return
        items[ident] = dict(path=path.as_posix(), area=area, section=section,
                            label=(label or path.stem).replace("[", "(").replace("]", ")"),
                            authority=authority, canonical_path=canonical)

    # Registered project locations are not facts duplicated into the map.
    for path in project_folders(root, config):
        add(path, "project-locations", "Projects", path.name, "project_location")

    for path in sorted(root.glob("*")):
        if path.is_file() and (path.suffix.lower() in {".md", ".ps1"} or path.name == ".gitignore"):
            if path.name != "BRAIN.md":  # Entry router is not a fact/document hop.
                add(path, "workspace", "State", path.name)
    for folder, pattern, area, section, authority in [
        ("docs", "**/*", "workspace-guides", "State", "project_source"),
        ("app", "*", "application-source", "State", "project_source"),
        ("evaluations", "*", "verification", "State", "project_source"),
        ("company", "**/*", "team-workspaces", "State", "generated_projection"),
        ("skills", "**/*", "active-playbooks", "Skills", "generated_projection"),
        ("routines", "**/*", "routines", "Routines", "routine_definition"),
        ("journals", "**/*", "technical-journals", "Memory", "project_source"),
        ("state", "**/*", "owned-state", "State", "project_source"),
        ("store", "*", "append-only-store", "State", "append_only_store"),
        ("store/routines", "**/*", "routine-history", "State", "append_only_store"),
    ]:
        for path in sorted((root / folder).glob(pattern)):
            if path.is_file() and path.suffix.lower() in {".md", ".json", ".jsonl", ".ndjson", ".py", ".html", ".ps1", ".csv"} and "__pycache__" not in path.parts:
                label = path.relative_to(root / folder).as_posix()
                add(path, area, section, label, authority)

    if (root / "store/history").is_dir():
        add(root / "store/history", "history-collection", "Memory", "Private history collection — use dedicated history recall", "private_archive_collection")
    if (root / "store/history/coverage.json").is_file():
        add(root / "store/history/coverage.json", "history-collection", "State", "History intake coverage and source availability", "archive_coverage")

    inventory = read_json(root / "docs/SKILL-INVENTORY.json", {})
    for skill in inventory.get("skills", []):
        if not skill.get("migrate", True):
            continue
        if skill.get("source_path"):
            add(skill["source_path"], "original-skill-sources", "Skills", skill["name"], "original_source")
        for link in skill.get("source_links", []):
            if link.get("path"):
                add(link["path"], "original-skill-sources", "Skills", link.get("label"), "original_source")
        for link in skill.get("validation", {}).get("relative_links", []):
            if link.get("path"):
                add(link["path"], "skill-reference-guides", "Skills", Path(link["path"]).parent.name + " / " + Path(link["path"]).name, "original_source")
    for role in inventory.get("organization", []):
        for field, area, section in [("source_refs", "company-methodology", "Memory"),
                                     ("journal_refs", "original-technical-journals", "Memory"),
                                     ("paper_refs", "thesis-and-research", "Memory")]:
            for raw in role.get(field, []):
                add(raw, area, section, authority="original_source")

    # These exact source files were explicitly selected for library reconciliation.
    # A transcript remains an original document, not copied into every chat context.
    video_inventory = read_json(root / "docs/VIDEO-RESEARCH-INVENTORY.json", {})
    for video in video_inventory.get("videos", []):
        for source in video.get("notes", []):
            add(source["path"], "youtube-research-notes", "Memory", source.get("title"), "original_source")
        for transcript in video.get("transcripts", []):
            add(transcript["path"], "youtube-research-transcripts", "Memory", video.get("title"), "original_source")
    for citation in video_inventory.get("current_research_citations", []):
        for source in citation.get("document_sources", []):
            add(source["path"], "thesis-and-research", "Memory", authority="original_source")

    # Current record versions and previous versions are distinguishable projections.
    current = {(v["kind"], v["id"]): v for v in read_json(root / "records/index.json", [])}
    for (kind, ident), record in current.items():
        current_path = root / "records" / kind / ident / f"v{record['version']:04d}.json"
        if not current_path.is_file():
            raise ValueError(f"Current record index points to a missing version: {current_path}")
    add(root / "records/index.json", "record-projections", "State", "Current version index", "generated_projection")
    for path in sorted((root / "records").glob("*/*/v*.json")):
        data = read_json(path, {})
        kind, ident = path.parent.parent.name, path.parent.name
        version = int(path.stem[1:])
        current_version = current.get((kind, ident), {}).get("version")
        active = version == current_version
        source = data.get("data", {}).get("source", "")
        canonical = source.split("; SHA256", 1)[0].strip() if isinstance(source, str) else ""
        supplied_source = data.get("data", {}).get("capture", {}).get("provenance", {}).get("source_file")
        if supplied_source:
            canonical = supplied_source
        canonical = canonical if canonical and Path(canonical).is_absolute() else None
        if canonical:
            # The source owns the fact; this JSON is an attributable historical copy.
            add(canonical, "recovered-source-documents", "Memory", authority="original_source")
        area = ("current-" + kind + "-records") if active else "record-history"
        section = "Skills" if kind == "skill" else "Routines" if kind == "loop" else "Memory" if kind == "memory" else "State"
        add(path, area, section, f"{kind}:{ident} v{version}" + (" (snapshot)" if canonical else ""),
            "source_snapshot" if canonical else "runtime_definition_projection", canonical)
    # Run artifacts are files owned by the runner, not dashboard-owned facts.
    for path in sorted((root / "deliverables").glob("*/*.md")):
        add(path, "run-artifacts", "State", path.parent.name[:12] + " / " + path.name, "run_artifact")
    if (root / "runtime/brain.sqlite").is_file():
        add(root / "runtime/brain.sqlite", "operational-state", "State", "Private recoverable SQLite projection", "generated_projection")
    for raw in config.get("extra_documents", []):
        add(raw["path"], raw.get("area", "owner-added"), raw.get("section", "Memory"), raw.get("label"), raw.get("authority", "owner_declared_source"))
    return sorted(items.values(), key=lambda v: (v["area"], SECTIONS.index(v["section"]), v["label"].casefold(), key(v["path"])))


def write_preserving(path: Path, content: str, map_root: Path):
    if path.is_file() and path.read_text(encoding="utf-8") == content:
        return
    if path.is_file():
        old = path.read_bytes()
        digest = hashlib.sha256(old).hexdigest()[:16]
        archive = map_root / "history" / (path.stem + "-" + digest + path.suffix)
        archive.parent.mkdir(parents=True, exist_ok=True)
        if not archive.exists():
            archive.write_bytes(old)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")


def rebuild(root: Path) -> dict:
    map_root = root / "memory-map"
    map_root.mkdir(parents=True, exist_ok=True)
    config_path = map_root / "config.json"
    config = configured(root)
    if not config:
        config = {"schema_version": 1, "master": "MASTER.md", "area_directory": "areas",
                  "archive_list": "ARCHIVE.md", "project_discovery_roots": [absolute(root / "company")],
                  "known_project_roots": [], "extra_documents": []}
        config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    notes, manual = {}, []
    previous = read_json(map_root / "catalog.json", {"documents": []})
    generated_before = {key(x["path"]) for x in previous["documents"]}
    for path in (map_root / config["area_directory"]).glob("*.md"):
        section = "Memory"
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("## ") and line[3:] in SECTIONS:
                section = line[3:]
            parsed = entry(line)
            if parsed:
                label, target, note = parsed
                notes[key(target)] = note
                if key(target) not in generated_before:
                    manual.append(dict(path=target, label=label, section=section, area="owner-added"))
    configured_paths = {key(v["path"]) for v in config.get("extra_documents", [])}
    for value in manual:
        if key(value["path"]) not in configured_paths:
            config.setdefault("extra_documents", []).append(value)
            configured_paths.add(key(value["path"]))
    write_preserving(config_path, json.dumps(config, ensure_ascii=False, indent=2) + "\n", map_root)
    documents = catalog(root, config)
    groups = {}
    for document in documents:
        groups.setdefault(document["area"], []).append(document)
    master_lines, expected_areas = [], set()
    for area, group in sorted(groups.items()):
        pages = [group[i:i + MAX_ITEMS] for i in range(0, len(group), MAX_ITEMS)]
        for number, values in enumerate(pages, 1):
            suffix = f"-{number:02d}" if len(pages) > 1 else ""
            path = map_root / config["area_directory"] / (area + suffix + ".md")
            expected_areas.add(key(path))
            lines = []
            for section in SECTIONS:
                lines.append("## " + section)
                for value in values:
                    if value["section"] == section:
                        note = notes.get(key(value["path"]), "")
                        lines.append(f"- [{value['label']}](<{value['path']}>):" + (" " + note if note else ""))
                lines.append("")
            write_preserving(path, "\n".join(lines), map_root)
            display_name = area.replace('-', ' ').title() + ((' ' + str(number)) if suffix else '')
            master_lines.append(f"- [{display_name}](<{absolute(path)}>):")
    # Preserve superseded signposts in history, rather than deleting them.
    for path in (map_root / config["area_directory"]).glob("*.md"):
        if key(path) not in expected_areas:
            if not path.resolve().is_relative_to(map_root.resolve()):
                raise ValueError("Refusing to relocate a signpost outside memory-map")
            digest = hashlib.sha256(path.read_bytes()).hexdigest()[:16]
            target = map_root / "history" / (path.stem + "-retired-" + digest + ".md")
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                target = target.with_name(target.stem + "-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f") + ".md")
            path.rename(target)
    write_preserving(map_root / config["master"], "\n".join(master_lines) + "\n", map_root)
    archive = map_root / config["archive_list"]
    if not archive.exists():
        archive.write_text("", encoding="utf-8")
    payload = {"schema_version": 1, "root": absolute(root), "documents": documents,
               "area_count": len(master_lines), "ownership": "Original sources own knowledge; store/ledger.jsonl owns app state; SQLite, exported records, source snapshots and dashboard JSON are projections, not second fact authorities."}
    write_preserving(map_root / "catalog.json", json.dumps(payload, ensure_ascii=False, indent=2) + "\n", map_root)
    return payload


def check(root: Path) -> dict:
    map_root, errors = root / "memory-map", []
    config = configured(root)
    if not config:
        return {"ok": False, "errors": ["Missing memory-map/config.json; run --rebuild first."]}
    master = map_root / config["master"]
    if not master.is_file():
        return {"ok": False, "errors": [f"Missing master: {master}"]}
    lines = master.read_text(encoding="utf-8").splitlines()
    if len(lines) >= 60:
        errors.append(f"Master has {len(lines)} lines; it must be under 60.")
    areas, listed, project_entries = [], {}, set()

    def validate_target(target, where):
        path = Path(target)
        if not path.is_absolute():
            errors.append(f"Non-absolute path in {where}: {target}")
        if not path.exists():
            errors.append(f"Missing path in {where}: {target}")
        return path

    for number, line in enumerate(lines, 1):
        parsed = entry(line)
        if not parsed:
            errors.append(f"Master line {number} is not an area path entry.")
            continue
        label, target, note = parsed
        if note:
            errors.append(f"Master line {number} contains a note/fact; master only routes to areas.")
        path = validate_target(target, "master")
        if key(path) in {key(x) for x in areas}:
            errors.append(f"Duplicate master area: {target}")
        if path.parent.resolve() != (map_root / config["area_directory"]).resolve():
            errors.append(f"Master target is not a direct area signpost: {target}")
        if path.is_file():
            areas.append(path)
    for path in areas:
        area_lines = path.read_text(encoding="utf-8").splitlines()
        if len(area_lines) >= 80:
            errors.append(f"{path.name} has {len(area_lines)} lines; it must be under 80.")
        headings = [line[3:] for line in area_lines if line.startswith("## ")]
        if headings != list(SECTIONS):
            errors.append(f"{path.name}: sections must appear exactly once in order {list(SECTIONS)}; found {headings}.")
        section = None
        for number, line in enumerate(area_lines, 1):
            if not line:
                continue
            if line.startswith("## "):
                section = line[3:]
                continue
            parsed = entry(line)
            if not parsed or section not in SECTIONS:
                errors.append(f"{path.name}:{number}: invalid entry or section.")
                continue
            _, target, _ = parsed
            target_path = validate_target(target, path.name)
            ident = key(target_path)
            if ident in listed:
                errors.append(f"Duplicate document home: {target} in {listed[ident]} and {path.name}.")
            listed[ident] = path.name
            if section == "Projects":
                project_entries.add(ident)
            if target_path.parent.resolve() == (map_root / config["area_directory"]).resolve():
                errors.append(f"Third-hop signpost in {path.name}: {target}")
    for path in (map_root / config["area_directory"]).glob("*.md"):
        if key(path) not in {key(x) for x in areas}:
            errors.append(f"Orphan area signpost, absent from master: {path.name}")
    archived_projects = set()
    archive = map_root / config["archive_list"]
    if not archive.is_file():
        errors.append("Archive list is missing.")
    else:
        for number, line in enumerate(archive.read_text(encoding="utf-8").splitlines(), 1):
            if not line:
                continue
            parsed = entry(line)
            if not parsed:
                errors.append(f"Archive line {number}: invalid entry.")
                continue
            _, target, _ = parsed
            archived_projects.add(key(validate_target(target, "archive list")))
    for path in project_folders(root, config):
        if not path.is_dir():
            errors.append(f"Declared project root is not an existing directory: {absolute(path)}")
        if key(path) not in project_entries | archived_projects:
            errors.append(f"Orphan project folder: {absolute(path)}")
    unmapped = []
    for document in catalog(root, config):
        if document["authority"] != "project_location" and key(document["path"]) not in listed:
            unmapped.append(document["path"])
    return {"ok": not errors, "root": absolute(master), "areas": len(areas),
            "documents": len(listed), "project_folders": len(project_folders(root, config)),
            "unmapped_documents": unmapped, "errors": errors}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT, help="Project root (default: parent of app/)")
    parser.add_argument("--rebuild", action="store_true", help="Refresh signposts, preserving owner notes and prior versions, then check")
    args = parser.parse_args()
    try:
        if args.rebuild:
            rebuild(args.root.resolve())
        result = check(args.root.resolve())
    except (OSError, ValueError, KeyError, TypeError) as exc:
        result = {"ok": False, "errors": [f"Map check failed: {exc}"]}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
