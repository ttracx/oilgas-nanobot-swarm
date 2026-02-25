"""
Knowledge Vault — Markdown-based knowledge graph with backlinks.

All knowledge lives as plain Markdown files at the configured VAULT_ROOT.
Default: ~/.nellie/vault/
Relationships are expressed via [[wikilinks]] (Obsidian-compatible).
The vault is fully inspectable and editable by the user.

Entity categories:
- people/         — contacts, collaborators, stakeholders
- companies/      — organizations, teams, groups
- projects/       — active and past projects
- topics/         — concepts, technologies, domains
- decisions/      — architectural decisions, commitments
- commitments/    — tracked promises, follow-ups
- meetings/       — meeting notes and transcripts
- daily/          — auto-generated daily notes
"""

import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import structlog

log = structlog.get_logger()

# Configurable vault root — defaults to ~/.nellie/vault/
VAULT_ROOT = Path(os.getenv(
    "NELLIE_VAULT_PATH",
    str(Path.home() / ".nellie" / "vault"),
))

CATEGORIES = [
    "people", "companies", "projects", "topics",
    "decisions", "commitments", "meetings", "daily",
]

# Regex for [[wikilinks]] including optional display text: [[target|display]]
BACKLINK_RE = re.compile(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]")

# Regex for YAML frontmatter
FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)


def _ensure_vault() -> None:
    """Create vault directory structure if it doesn't exist."""
    VAULT_ROOT.mkdir(parents=True, exist_ok=True)
    for cat in CATEGORIES:
        (VAULT_ROOT / cat).mkdir(exist_ok=True)
    # Create _index.md if missing
    index_path = VAULT_ROOT / "_index.md"
    if not index_path.exists():
        index_path.write_text(
            "# Nellie Knowledge Graph\n\n"
            "This vault contains Nellie's accumulated knowledge.\n"
            "Notes are plain Markdown with [[backlinks]].\n\n"
            "## Categories\n"
            + "".join(f"- [[{c}]]\n" for c in CATEGORIES),
            encoding="utf-8",
        )


def _slugify(name: str) -> str:
    """Convert a name to a safe filename slug."""
    slug = re.sub(r"[^\w\s-]", "", name.strip())
    slug = re.sub(r"[\s]+", "-", slug).lower()
    return slug[:80]


def _note_path(category: str, name: str) -> Path:
    """Get the filesystem path for a note."""
    return VAULT_ROOT / category / f"{_slugify(name)}.md"


def _parse_frontmatter(content: str) -> tuple[dict, str]:
    """Extract YAML-like frontmatter from a markdown file.

    Handles multiline values (lists, nested dicts) via simple parsing.
    For production with complex YAML, swap to PyYAML.
    """
    match = FRONTMATTER_RE.match(content)
    if not match:
        return {}, content

    fm_text = match.group(1)
    body = content[match.end():]
    metadata = {}
    current_key = None
    current_list: list[str] | None = None

    for line in fm_text.strip().split("\n"):
        stripped = line.strip()
        # List item under a key
        if stripped.startswith("- ") and current_key:
            if current_list is None:
                current_list = []
            current_list.append(stripped[2:].strip())
            metadata[current_key] = current_list
            continue
        # New key: value
        if ":" in line and not line.startswith(" ") and not line.startswith("-"):
            # Save previous list if any
            current_list = None
            key, _, val = line.partition(":")
            current_key = key.strip()
            val = val.strip()
            if val.startswith("[") and val.endswith("]"):
                # Inline list: [a, b, c]
                items = [v.strip().strip("\"'") for v in val[1:-1].split(",") if v.strip()]
                metadata[current_key] = items
            elif val:
                metadata[current_key] = val
            # else: could be a list starting next line

    return metadata, body


def _build_frontmatter(metadata: dict) -> str:
    """Build a YAML frontmatter block from a dict."""
    lines = ["---"]
    for k, v in metadata.items():
        if isinstance(v, list):
            lines.append(f"{k}: [{', '.join(str(i) for i in v)}]")
        elif isinstance(v, dict):
            lines.append(f"{k}:")
            for dk, dv in v.items():
                lines.append(f"  {dk}: {dv}")
        else:
            lines.append(f"{k}: {v}")
    lines.append("---\n")
    return "\n".join(lines)


def extract_backlinks(content: str) -> list[str]:
    """Extract all [[wikilink]] targets from content."""
    return BACKLINK_RE.findall(content)


class KnowledgeVault:
    """
    Markdown-based knowledge graph.

    Notes are plain Markdown with YAML frontmatter.
    Relationships are expressed via [[wikilinks]].
    Everything is on disk and user-editable.
    """

    def __init__(self, root: Path | None = None):
        self.root = root or VAULT_ROOT
        _ensure_vault()

    def create_note(
        self,
        category: str,
        name: str,
        content: str,
        metadata: dict | None = None,
        backlinks: list[str] | None = None,
        sources: list[dict] | None = None,
        confidence: float = 0.9,
        aliases: list[str] | None = None,
    ) -> Path:
        """Create or overwrite a knowledge note with rich frontmatter."""
        if category not in CATEGORIES:
            raise ValueError(f"Unknown category: {category}. Use one of {CATEGORIES}")

        now = datetime.now().isoformat(timespec="seconds")
        fm: dict[str, Any] = {
            "id": f"{category}/{_slugify(name)}",
            "type": category.rstrip("s"),  # people -> person, etc.
            "title": name,
            "created": now,
            "updated": now,
            "confidence": confidence,
            "tags": [category],
        }
        if aliases:
            fm["aliases"] = aliases
        if sources:
            fm["sources"] = sources
        if metadata:
            fm.update(metadata)

        body = f"# {name}\n\n{content}"

        if backlinks:
            body += "\n\n## Relationships\n"
            for link in backlinks:
                body += f"- [[{link}]]\n"

        full_content = _build_frontmatter(fm) + body

        path = _note_path(category, name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(full_content, encoding="utf-8")
        log.info("note_created", category=category, name=name, path=str(path))
        return path

    def update_note(
        self,
        category: str,
        name: str,
        append_content: str | None = None,
        new_backlinks: list[str] | None = None,
        update_metadata: dict | None = None,
        add_source: dict | None = None,
        new_confidence: float | None = None,
    ) -> Path | None:
        """Update an existing note — append content, add backlinks, update metadata.

        Confidence uses weighted blending: old*0.7 + new*0.3 to preserve
        established knowledge while allowing gradual updates.
        """
        path = _note_path(category, name)
        if not path.exists():
            return None

        content = path.read_text(encoding="utf-8")
        metadata, body = _parse_frontmatter(content)

        metadata["updated"] = datetime.now().isoformat(timespec="seconds")

        # Weighted confidence blending (old*0.7 + new*0.3)
        if new_confidence is not None:
            old_conf = float(metadata.get("confidence", 0.8))
            blended = round(old_conf * 0.7 + new_confidence * 0.3, 3)
            metadata["confidence"] = str(blended)

        if update_metadata:
            metadata.update(update_metadata)

        # Append source to sources list (with dedup)
        if add_source:
            sources = metadata.get("sources", [])
            if isinstance(sources, str):
                sources = []
            # Deduplicate: skip if same ref+date already exists
            already = any(
                isinstance(s, dict) and s.get("ref") == add_source.get("ref")
                and s.get("date") == add_source.get("date")
                for s in sources
            )
            if not already:
                sources.append(add_source)
            metadata["sources"] = sources

        if append_content:
            # Try to append under ## History, or at end of body
            if "## History" in body:
                body = body.replace(
                    "## History\n",
                    f"## History\n- **{datetime.now().strftime('%Y-%m-%d')}**: {append_content}\n",
                )
            else:
                body = body.rstrip() + f"\n\n{append_content}\n"

        if new_backlinks:
            existing_links = set(extract_backlinks(body))
            links_to_add = [l for l in new_backlinks if l not in existing_links]
            if links_to_add:
                if "## Relationships" not in body:
                    body += "\n\n## Relationships\n"
                for link in links_to_add:
                    body += f"- [[{link}]]\n"

        full_content = _build_frontmatter(metadata) + body
        path.write_text(full_content, encoding="utf-8")
        log.info("note_updated", category=category, name=name)
        return path

    def read_note(self, category: str, name: str) -> dict | None:
        """Read a note and return structured data."""
        path = _note_path(category, name)
        if not path.exists():
            return None

        content = path.read_text(encoding="utf-8")
        metadata, body = _parse_frontmatter(content)
        backlinks = extract_backlinks(body)
        reverse = self.find_backlinks_to(name)

        return {
            "category": category,
            "name": name,
            "path": str(path),
            "metadata": metadata,
            "content": body,
            "outgoing_links": backlinks,
            "incoming_links": [
                {"from": r["name"], "category": r["category"]}
                for r in reverse
            ],
        }

    def delete_note(self, category: str, name: str) -> bool:
        """Delete a note from the vault."""
        path = _note_path(category, name)
        if path.exists():
            path.unlink()
            log.info("note_deleted", category=category, name=name)
            return True
        return False

    def search(
        self,
        query: str,
        category: str | None = None,
        max_results: int = 20,
    ) -> list[dict]:
        """Search notes with weighted scoring.

        Scoring weights (ported from TypeScript backlink-resolver):
        - Exact title match: 100
        - Alias exact match: 80
        - Title contains query: 50
        - Alias contains query: 30
        - Tag match: 20
        - Body occurrences: 5 each (capped at 25)
        - Backlink boost: 2 per incoming link (capped at 20)
        - Confidence boost: +10 for confidence >= 0.9
        """
        results = []
        query_lower = query.lower()

        dirs = [self.root / category] if category else [self.root / c for c in CATEGORIES]

        for dir_path in dirs:
            if not dir_path.exists():
                continue
            for md_file in dir_path.glob("*.md"):
                content = md_file.read_text(encoding="utf-8")
                name = md_file.stem.replace("-", " ")
                cat = dir_path.name
                metadata, body = _parse_frontmatter(content)

                score = 0

                # Title scoring
                name_lower = name.lower()
                if query_lower == name_lower:
                    score += 100  # exact title match
                elif query_lower in name_lower:
                    score += 50  # title contains query

                # Alias scoring
                aliases = metadata.get("aliases", [])
                if isinstance(aliases, list):
                    for alias in aliases:
                        alias_lower = str(alias).lower()
                        if query_lower == alias_lower:
                            score += 80  # exact alias match
                        elif query_lower in alias_lower:
                            score += 30  # alias contains query

                # Tag scoring
                tags = metadata.get("tags", [])
                if isinstance(tags, list):
                    for tag in tags:
                        if query_lower in str(tag).lower():
                            score += 20

                # Body scoring (capped at 25)
                body_lower = body.lower()
                body_hits = body_lower.count(query_lower)
                if body_hits > 0:
                    score += min(body_hits * 5, 25)

                # Backlink boost (capped at 20)
                backlinks = extract_backlinks(body)
                if backlinks:
                    score += min(len(backlinks) * 2, 20)

                # Confidence boost
                try:
                    conf = float(metadata.get("confidence", 0))
                    if conf >= 0.9:
                        score += 10
                except (ValueError, TypeError):
                    pass

                if score > 0:
                    results.append({
                        "category": cat,
                        "name": name,
                        "path": str(md_file),
                        "score": score,
                        "metadata": metadata,
                        "preview": body[:300].strip(),
                        "backlinks": backlinks,
                    })

        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:max_results]

    def find_backlinks_to(self, target_name: str) -> list[dict]:
        """Find all notes that link TO a given entity (reverse backlinks)."""
        results = []
        target_lower = target_name.lower()

        for cat_dir in [self.root / c for c in CATEGORIES]:
            if not cat_dir.exists():
                continue
            for md_file in cat_dir.glob("*.md"):
                content = md_file.read_text(encoding="utf-8")
                links = extract_backlinks(content)
                if any(target_lower in l.lower() for l in links):
                    metadata, body = _parse_frontmatter(content)
                    # Extract the context around the backlink
                    context = ""
                    for line in body.split("\n"):
                        if f"[[{target_name}" in line or target_lower in line.lower():
                            context = line.strip()[:200]
                            break
                    results.append({
                        "category": cat_dir.name,
                        "name": md_file.stem.replace("-", " "),
                        "path": str(md_file),
                        "metadata": metadata,
                        "context": context,
                        "all_links": links,
                    })

        return results

    def list_notes(self, category: str | None = None) -> list[dict]:
        """List all notes, optionally filtered by category."""
        results = []
        dirs = [self.root / category] if category else [self.root / c for c in CATEGORIES]

        for dir_path in dirs:
            if not dir_path.exists():
                continue
            for md_file in sorted(dir_path.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True):
                metadata, body = _parse_frontmatter(md_file.read_text(encoding="utf-8"))
                results.append({
                    "category": dir_path.name,
                    "name": md_file.stem.replace("-", " "),
                    "path": str(md_file),
                    "metadata": metadata,
                    "updated": metadata.get("updated", ""),
                })

        return results

    def create_daily_note(self, date: datetime | None = None) -> Path:
        """Create or update today's daily note."""
        d = date or datetime.now()
        date_str = d.strftime("%Y-%m-%d")
        path = self.root / "daily" / f"{date_str}.md"

        if path.exists():
            return path

        content = (
            f"# {date_str}\n\n"
            f"## Agenda\n\n_Auto-populated by morning briefing agent._\n\n"
            f"## Notes\n\n\n"
            f"## Activity Log\n\n"
        )
        fm = {
            "id": f"daily/{date_str}",
            "type": "daily",
            "title": date_str,
            "created": d.isoformat(timespec="seconds"),
            "updated": d.isoformat(timespec="seconds"),
            "tags": ["daily"],
        }
        full = _build_frontmatter(fm) + content
        path.write_text(full, encoding="utf-8")
        log.info("daily_note_created", date=date_str)
        return path

    def build_index(self) -> dict:
        """
        Build a complete knowledge index — used by agents and graph builder.
        Returns {category: [{name, path, metadata, backlinks}]}.
        """
        index: dict[str, Any] = {}
        for cat in CATEGORIES:
            cat_dir = self.root / cat
            if not cat_dir.exists():
                continue
            entries = []
            for md_file in cat_dir.glob("*.md"):
                content = md_file.read_text(encoding="utf-8")
                metadata, body = _parse_frontmatter(content)
                entries.append({
                    "name": md_file.stem.replace("-", " "),
                    "path": str(md_file),
                    "metadata": metadata,
                    "backlinks": extract_backlinks(body),
                })
            if entries:
                index[cat] = entries

        index["_build_time"] = datetime.now().isoformat()
        index["_total_notes"] = sum(
            len(v) for k, v in index.items()
            if isinstance(v, list)
        )
        return index

    def get_stats(self) -> dict:
        """Get vault statistics."""
        stats: dict[str, Any] = {"categories": {}}
        total = 0
        for cat in CATEGORIES:
            cat_dir = self.root / cat
            count = len(list(cat_dir.glob("*.md"))) if cat_dir.exists() else 0
            stats["categories"][cat] = count
            total += count
        stats["total_notes"] = total
        stats["vault_path"] = str(self.root)
        return stats

    def get_entity_names(self) -> list[str]:
        """Get all entity names in the vault — used for dedup during extraction."""
        names = []
        for cat in CATEGORIES:
            cat_dir = self.root / cat
            if not cat_dir.exists():
                continue
            for md_file in cat_dir.glob("*.md"):
                names.append(md_file.stem.replace("-", " ").title())
        return names


# Singleton
vault = KnowledgeVault()
