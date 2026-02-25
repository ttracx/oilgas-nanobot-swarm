"""
Artifact Writer — extracts structured output from agent responses.

Agents can emit two types of structured output in their text:
1. <artifact type="brief|draft|report" path="filename.md">content</artifact>
   → Written to ~/.nellie/vault/artifacts/{type}/{path}
2. <graph_update path="people/person-name.md">content</graph_update>
   → Written directly into the knowledge vault

This lets agents produce actionable files (morning briefs, email drafts,
status reports) and simultaneously update the knowledge graph — all from
a single execution pass.
"""

import re
import structlog
from pathlib import Path
from dataclasses import dataclass, field

from nanobot.knowledge.vault import vault

log = structlog.get_logger()

ARTIFACT_RE = re.compile(
    r'<artifact\s+type="([^"]+)"\s+path="([^"]+)">([\s\S]*?)</artifact>',
    re.MULTILINE,
)
GRAPH_UPDATE_RE = re.compile(
    r'<graph_update\s+path="([^"]+)">([\s\S]*?)</graph_update>',
    re.MULTILINE,
)

VALID_ARTIFACT_TYPES = {"brief", "draft", "report", "voice_note", "update", "digest"}


@dataclass
class Artifact:
    artifact_type: str
    path: str
    content: str


@dataclass
class GraphUpdate:
    path: str
    content: str


@dataclass
class ExtractionResult:
    artifacts: list[Artifact] = field(default_factory=list)
    graph_updates: list[GraphUpdate] = field(default_factory=list)
    artifacts_written: int = 0
    graph_updates_applied: int = 0


def extract_artifacts(text: str) -> list[Artifact]:
    """Extract <artifact> tags from agent output text."""
    results = []
    for match in ARTIFACT_RE.finditer(text):
        atype, path, content = match.group(1), match.group(2), match.group(3).strip()
        if atype not in VALID_ARTIFACT_TYPES:
            log.warning("artifact_invalid_type", type=atype, path=path)
            continue
        results.append(Artifact(artifact_type=atype, path=path, content=content))
    return results


def extract_graph_updates(text: str) -> list[GraphUpdate]:
    """Extract <graph_update> tags from agent output text."""
    results = []
    for match in GRAPH_UPDATE_RE.finditer(text):
        path, content = match.group(1), match.group(2).strip()
        results.append(GraphUpdate(path=path, content=content))
    return results


def write_artifacts(artifacts: list[Artifact]) -> int:
    """Write extracted artifacts to the vault's artifacts directory."""
    written = 0
    for art in artifacts:
        try:
            artifact_dir = vault.vault_path / "artifacts" / art.artifact_type
            artifact_dir.mkdir(parents=True, exist_ok=True)

            # Sanitize path
            safe_path = Path(art.path).name
            if not safe_path.endswith(".md"):
                safe_path += ".md"

            output_path = artifact_dir / safe_path
            output_path.write_text(art.content, encoding="utf-8")
            written += 1
            log.info("artifact_written", type=art.artifact_type, path=str(output_path))
        except Exception as e:
            log.error("artifact_write_failed", type=art.artifact_type, path=art.path, error=str(e))
    return written


def apply_graph_updates(updates: list[GraphUpdate]) -> int:
    """Apply <graph_update> content directly to the knowledge vault."""
    applied = 0
    for update in updates:
        try:
            # Parse path like "people/person-name.md" → category=people, name=person-name
            parts = update.path.strip("/").split("/", 1)
            if len(parts) != 2:
                log.warning("graph_update_invalid_path", path=update.path)
                continue

            category = parts[0]
            name = parts[1].removesuffix(".md")

            # Check if note exists → update, else create
            existing = vault.read_note(category, name)
            if existing:
                vault.update_note(category, name, append_content=update.content)
            else:
                vault.create_note(category, name, content=update.content,
                                  metadata={"source": "agent_graph_update"})
            applied += 1
            log.info("graph_update_applied", category=category, name=name)
        except Exception as e:
            log.error("graph_update_failed", path=update.path, error=str(e))
    return applied


def append_daily_summary(
    agent_id: str,
    duration_ms: int = 0,
    tokens_used: int = 0,
    artifacts_written: int = 0,
    graph_updates_applied: int = 0,
) -> None:
    """Append an execution summary to today's daily note.

    Ported from the TypeScript scaffold's appendExecutionSummary.
    Creates the daily note if it doesn't exist.
    """
    from datetime import datetime

    today = datetime.now().strftime("%Y-%m-%d")
    ts = datetime.now().strftime("%H:%M")
    duration_s = round(duration_ms / 1000, 1) if duration_ms else 0

    summary_line = (
        f"- **{ts}** `{agent_id}` — "
        f"Artifacts: {artifacts_written}, Graph updates: {graph_updates_applied}, "
        f"Tokens: {tokens_used}, Duration: {duration_s}s"
    )

    try:
        existing = vault.read_note("daily", today)
        if existing:
            vault.update_note("daily", today, append_content=summary_line)
        else:
            vault.create_daily_note()
            vault.update_note("daily", today, append_content=f"\n## Agent Activity\n{summary_line}")
        log.info("daily_summary_appended", agent=agent_id, date=today)
    except Exception as e:
        log.error("daily_summary_failed", agent=agent_id, error=str(e))


def process_agent_output(
    text: str,
    agent_id: str = "unknown",
    duration_ms: int = 0,
    tokens_used: int = 0,
) -> ExtractionResult:
    """
    Full pipeline: extract artifacts + graph updates from agent text,
    write artifacts to disk, apply graph updates to vault,
    and append a summary to today's daily note.

    Returns an ExtractionResult with counts and extracted data.
    """
    result = ExtractionResult()
    result.artifacts = extract_artifacts(text)
    result.graph_updates = extract_graph_updates(text)

    if result.artifacts:
        result.artifacts_written = write_artifacts(result.artifacts)
        log.info("artifacts_processed", found=len(result.artifacts), written=result.artifacts_written)

    if result.graph_updates:
        result.graph_updates_applied = apply_graph_updates(result.graph_updates)
        log.info("graph_updates_processed", found=len(result.graph_updates), applied=result.graph_updates_applied)

    # Append execution summary to daily note (only if there was actual output)
    if result.artifacts_written > 0 or result.graph_updates_applied > 0:
        append_daily_summary(
            agent_id=agent_id,
            duration_ms=duration_ms,
            tokens_used=tokens_used,
            artifacts_written=result.artifacts_written,
            graph_updates_applied=result.graph_updates_applied,
        )

    return result
