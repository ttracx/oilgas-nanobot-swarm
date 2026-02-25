"""
Graph Builder — Incrementally builds knowledge graph from swarm outputs and ingestion sources.

Architecture (modeled after Rowboat's async graph builder):
1. Scans source folders for new/changed files
2. Extracts entities via LLM (falls back to regex)
3. Creates/updates Markdown notes with backlinks in the vault
4. Tracks processing state to avoid re-processing
5. Supports event-based triggers (not just polling)

Source folders:
- ~/.nellie/vault/             — the knowledge vault itself
- ~/.nellie/inbox/             — user-dropped files (notes, emails, docs)
- ~/.nellienano/workspace/swarm_output/  — completed swarm session artifacts
- ~/.nellienano/workspace/memory/HISTORY.md — swarm session history

The builder runs as an async background task, polling every POLL_INTERVAL seconds.
Events (new_file, swarm_complete) can trigger immediate processing.
"""

import asyncio
import hashlib
import json
import os
from datetime import datetime
from pathlib import Path

import structlog

from nanobot.knowledge.vault import vault, VAULT_ROOT, CATEGORIES
from nanobot.knowledge.entity_extractor import (
    extract_entities_llm, _extract_entities_regex, ExtractionResult,
)

log = structlog.get_logger()

NELLIE_HOME = Path(os.getenv("NELLIE_HOME", str(Path.home() / ".nellie")))
INBOX_DIR = NELLIE_HOME / "inbox"
SWARM_OUTPUT_DIR = Path.home() / ".nellienano" / "workspace" / "swarm_output"
HISTORY_FILE = Path.home() / ".nellienano" / "workspace" / "memory" / "HISTORY.md"
STATE_FILE = NELLIE_HOME / ".graph_builder_state.json"

POLL_INTERVAL = int(os.getenv("GRAPH_BUILDER_POLL_INTERVAL", "60"))
BATCH_SIZE = 10
USE_LLM_EXTRACTION = os.getenv("GRAPH_BUILDER_LLM", "true").lower() in ("true", "1", "yes")


class GraphBuilderState:
    """Persistent state for incremental processing."""

    def __init__(self):
        self.file_hashes: dict[str, str] = {}
        self.last_build: str = ""
        self.files_processed: int = 0
        self.entities_created: int = 0

    def load(self) -> None:
        if STATE_FILE.exists():
            data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            self.file_hashes = data.get("file_hashes", {})
            self.last_build = data.get("last_build", "")
            self.files_processed = data.get("files_processed", 0)
            self.entities_created = data.get("entities_created", 0)

    def save(self) -> None:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps({
            "file_hashes": self.file_hashes,
            "last_build": self.last_build,
            "files_processed": self.files_processed,
            "entities_created": self.entities_created,
        }, indent=2), encoding="utf-8")

    def is_changed(self, filepath: str, content: str) -> bool:
        h = hashlib.md5(content.encode()).hexdigest()
        old_hash = self.file_hashes.get(filepath)
        if old_hash == h:
            return False
        self.file_hashes[filepath] = h
        return True


class EventBus:
    """Simple async event bus for triggering graph builds on events."""

    def __init__(self):
        self._handlers: dict[str, list] = {}

    def on(self, event: str, handler) -> None:
        self._handlers.setdefault(event, []).append(handler)

    async def emit(self, event: str, data: dict | None = None) -> None:
        for handler in self._handlers.get(event, []):
            try:
                await handler(data or {})
            except Exception as e:
                log.error("event_handler_error", event=event, error=str(e))


class GraphBuilder:
    """
    Asynchronous knowledge graph builder.

    Processes new files and swarm outputs into the Markdown vault.
    Supports both polling and event-driven triggers.
    Uses LLM for entity extraction when available, falls back to regex.
    """

    def __init__(self):
        self.state = GraphBuilderState()
        self._running = False
        self._task: asyncio.Task | None = None
        self.events = EventBus()
        self._wake_event = asyncio.Event()

        # Register event handlers
        self.events.on("new_file", self._on_new_file)
        self.events.on("swarm_complete", self._on_swarm_complete)

    def start(self) -> None:
        """Start the background graph builder."""
        if self._running:
            return
        self._running = True
        self.state.load()

        # Ensure directories exist
        INBOX_DIR.mkdir(parents=True, exist_ok=True)
        SWARM_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

        self._task = asyncio.create_task(self._poll_loop())
        log.info("graph_builder_started",
                 poll_interval=POLL_INTERVAL,
                 llm_extraction=USE_LLM_EXTRACTION)

    def stop(self) -> None:
        """Stop the background graph builder."""
        self._running = False
        self._wake_event.set()
        if self._task:
            self._task.cancel()
            self._task = None
        log.info("graph_builder_stopped")

    def wake(self) -> None:
        """Wake the builder immediately (e.g., after a swarm completes)."""
        self._wake_event.set()

    async def _poll_loop(self) -> None:
        """Main polling loop — runs until stopped."""
        while self._running:
            try:
                # Create today's daily note
                vault.create_daily_note()
                await self._process_batch()
            except Exception as e:
                log.error("graph_builder_error", error=str(e))

            # Wait for poll interval or wake signal
            self._wake_event.clear()
            try:
                await asyncio.wait_for(self._wake_event.wait(), timeout=POLL_INTERVAL)
            except asyncio.TimeoutError:
                pass

    async def _on_new_file(self, data: dict) -> None:
        """Event handler: new file dropped in inbox."""
        filepath = data.get("path")
        if filepath:
            path = Path(filepath)
            if path.exists() and path.suffix in (".md", ".txt", ".json", ".eml"):
                content = path.read_text(encoding="utf-8", errors="replace")
                source_type = data.get("source_type", "document")
                await self._extract_and_store(content, source_type, str(path))
                self.state.file_hashes[str(path)] = hashlib.md5(content.encode()).hexdigest()
                self.state.save()

    async def _on_swarm_complete(self, data: dict) -> None:
        """Event handler: swarm session completed."""
        session_id = data.get("session_id", "")
        final_answer = data.get("final_answer", "")
        goal = data.get("goal", "")

        if final_answer:
            text = f"Swarm Goal: {goal}\n\nResult:\n{final_answer}"
            await self._extract_and_store(text, "swarm_output", f"swarm:{session_id}")
        self.wake()

    async def _extract_and_store(
        self,
        text: str,
        source_type: str,
        source_ref: str,
    ) -> int:
        """Extract entities from text and store in vault. Returns count of entities created."""
        existing_names = vault.get_entity_names()

        # Use LLM extraction if enabled, otherwise fall back to regex
        if USE_LLM_EXTRACTION:
            result = await extract_entities_llm(
                text, source_type=source_type, existing_entities=existing_names
            )
        else:
            result = _extract_entities_regex(text)

        created = 0
        today = datetime.now().strftime("%Y-%m-%d")
        source_info = {"type": source_type, "ref": source_ref, "date": today}

        for entity in result.entities:
            category = entity.type
            if category not in CATEGORIES:
                continue

            existing = vault.read_note(category, entity.name)
            if existing:
                vault.update_note(
                    category, entity.name,
                    append_content=entity.context or f"Referenced in {source_type}",
                    new_backlinks=entity.relationships or None,
                    add_source=source_info,
                    new_confidence=entity.confidence,
                )
            else:
                vault.create_note(
                    category, entity.name,
                    content=entity.context or f"Discovered from {source_type}.\n",
                    metadata={"role": entity.role} if entity.role else None,
                    backlinks=entity.relationships or None,
                    sources=[source_info],
                    confidence=entity.confidence,
                    aliases=entity.aliases or None,
                )
                created += 1

        # Store decisions as separate notes
        for decision in result.decisions:
            vault.create_note(
                "decisions",
                f"{today} {decision[:50]}",
                content=f"{decision}\n\nSource: {source_type} ({source_ref})",
                sources=[source_info],
            )
            created += 1

        # Store commitments/action items
        for item in result.action_items:
            vault.create_note(
                "commitments",
                f"{today} {item[:50]}",
                content=f"{item}\n\nSource: {source_type} ({source_ref})",
                sources=[source_info],
                metadata={"status": "open"},
            )
            created += 1

        # Update today's daily note with summary
        if result.summary:
            daily_path = vault.root / "daily" / f"{today}.md"
            if daily_path.exists():
                vault.update_note("daily", today, append_content=(
                    f"- [{source_type}] {result.summary[:200]}"
                ))

        self.state.entities_created += created
        log.info("entities_extracted",
                 source=source_type,
                 entities=len(result.entities),
                 created=created,
                 decisions=len(result.decisions),
                 actions=len(result.action_items))
        return created

    async def _process_batch(self) -> None:
        """Scan source directories and process new/changed files."""
        files_to_process: list[tuple[str, Path, str]] = []

        # 1. Scan inbox
        for f in INBOX_DIR.glob("**/*"):
            if f.is_file() and f.suffix in (".md", ".txt", ".json", ".eml"):
                content = f.read_text(encoding="utf-8", errors="replace")
                if self.state.is_changed(str(f), content):
                    files_to_process.append(("inbox", f, content))

        # 2. Scan swarm output manifests
        for manifest in SWARM_OUTPUT_DIR.glob("*/manifest.json"):
            content = manifest.read_text(encoding="utf-8")
            if self.state.is_changed(str(manifest), content):
                files_to_process.append(("swarm_output", manifest, content))

        # 3. Check HISTORY.md
        if HISTORY_FILE.exists():
            content = HISTORY_FILE.read_text(encoding="utf-8")
            if self.state.is_changed(str(HISTORY_FILE), content):
                files_to_process.append(("history", HISTORY_FILE, content))

        if not files_to_process:
            return

        log.info("graph_builder_batch", files=len(files_to_process))

        for i in range(0, len(files_to_process), BATCH_SIZE):
            batch = files_to_process[i:i + BATCH_SIZE]
            for source_type, filepath, content in batch:
                try:
                    if source_type == "swarm_output":
                        await self._process_swarm_manifest(filepath, content)
                    else:
                        await self._extract_and_store(content, source_type, str(filepath))
                    self.state.files_processed += 1
                except Exception as e:
                    log.error("graph_builder_file_error", file=str(filepath), error=str(e))

        self.state.last_build = datetime.now().isoformat()
        self.state.save()

    async def _process_swarm_manifest(self, manifest_path: Path, content: str) -> None:
        """Process a swarm output session into knowledge entries."""
        try:
            manifest = json.loads(content)
        except json.JSONDecodeError:
            return

        session_id = manifest.get("session_id", "unknown")
        session_dir = manifest_path.parent

        # Read all output files in the session
        combined_text = ""
        for fname in manifest.get("files", []):
            fpath = session_dir / fname
            if fpath.exists():
                combined_text += fpath.read_text(encoding="utf-8", errors="replace") + "\n"

        if not combined_text:
            return

        await self._extract_and_store(
            combined_text,
            "swarm_output",
            f"swarm:{session_id[:12]}",
        )

    async def force_rebuild(self) -> dict:
        """Force a complete rebuild — clear hashes and re-process everything."""
        self.state.file_hashes.clear()
        await self._process_batch()
        return vault.build_index()

    def load_graph_context(self, token_budget: int = 2000) -> str:
        """Load relevant vault context for agent injection, within a token budget.

        Priority order (from TypeScript orchestrator):
        1. Today's daily note (highest priority)
        2. Recently updated notes (by mtime, most recent first)

        Rough token estimate: 1 token ≈ 4 chars.
        """
        char_budget = token_budget * 4
        parts: list[str] = []
        used = 0

        # 1. Today's daily note
        today = datetime.now().strftime("%Y-%m-%d")
        daily_path = vault.root / "daily" / f"{today}.md"
        if daily_path.exists():
            daily_content = daily_path.read_text(encoding="utf-8")
            if used + len(daily_content) <= char_budget:
                parts.append(f"## Today ({today})\n{daily_content}")
                used += len(daily_content)

        # 2. Recently updated notes (by mtime, skip daily/)
        recent_files: list[tuple[float, Path]] = []
        for cat in CATEGORIES:
            if cat == "daily":
                continue
            cat_dir = vault.root / cat
            if not cat_dir.exists():
                continue
            for md_file in cat_dir.glob("*.md"):
                recent_files.append((md_file.stat().st_mtime, md_file))

        recent_files.sort(key=lambda x: x[0], reverse=True)

        for _mtime, md_file in recent_files:
            if used >= char_budget:
                break
            content = md_file.read_text(encoding="utf-8")
            # Take just the first 500 chars of each note as a summary
            snippet = content[:500]
            if used + len(snippet) <= char_budget:
                name = md_file.stem.replace("-", " ").title()
                cat = md_file.parent.name
                parts.append(f"## {cat}/{name}\n{snippet}")
                used += len(snippet)

        return "\n\n---\n\n".join(parts) if parts else "(empty vault)"

    async def ingest_contacts(self, contacts: list[dict]) -> int:
        """Ingest Microsoft 365 contacts directly into vault (no LLM needed).

        Contacts are structured data — bypass LLM extraction and merge directly.
        """
        created = 0
        today = datetime.now().strftime("%Y-%m-%d")

        for c in contacts:
            name = c.get("name", "").strip()
            if not name or len(name) < 2:
                continue

            category = "people"
            source_info = {"type": "document", "ref": f"outlook-contact:{c.get('id', '')}", "date": today}

            # Build context from structured fields
            ctx_parts = []
            if c.get("title"):
                ctx_parts.append(f"Title: {c['title']}")
            if c.get("company"):
                ctx_parts.append(f"Company: {c['company']}")
            if c.get("email"):
                ctx_parts.append(f"Email: {c['email']}")
            if c.get("department"):
                ctx_parts.append(f"Department: {c['department']}")
            context = ". ".join(ctx_parts) or "Microsoft 365 contact"

            relationships = [c["company"]] if c.get("company") else []

            existing = vault.read_note(category, name)
            if existing:
                vault.update_note(
                    category, name,
                    append_content=context,
                    new_backlinks=relationships or None,
                    add_source=source_info,
                    new_confidence=1.0,
                )
            else:
                vault.create_note(
                    category, name,
                    content=f"{context}\n\n## History\n",
                    metadata={"role": c.get("title", "")} if c.get("title") else None,
                    backlinks=relationships or None,
                    sources=[source_info],
                    confidence=1.0,
                )
                created += 1

        log.info("contacts_ingested", total=len(contacts), created=created)
        return created

    async def ingest_tasks(self, tasks: list[dict]) -> int:
        """Ingest Microsoft To Do tasks directly into vault as commitments (no LLM needed)."""
        created = 0
        today = datetime.now().strftime("%Y-%m-%d")

        for t in tasks:
            title = t.get("title", "").strip()
            if not title:
                continue

            source_info = {"type": "document", "ref": f"todo:{t.get('id', '')}", "date": today}
            ctx_parts = [f"Status: {t.get('status', 'unknown')}"]
            if t.get("importance"):
                ctx_parts.append(f"Importance: {t['importance']}")
            if t.get("due"):
                ctx_parts.append(f"Due: {t['due']}")
            if t.get("list"):
                ctx_parts.append(f"List: {t['list']}")
            context = ". ".join(ctx_parts)

            existing = vault.read_note("commitments", title)
            if existing:
                vault.update_note(
                    "commitments", title,
                    append_content=context,
                    add_source=source_info,
                    update_metadata={"status": t.get("status", "open")},
                )
            else:
                vault.create_note(
                    "commitments", title,
                    content=f"{context}\n\n## History\n",
                    sources=[source_info],
                    metadata={"status": t.get("status", "open")},
                    confidence=1.0,
                )
                created += 1

        log.info("tasks_ingested", total=len(tasks), created=created)
        return created

    def get_status(self) -> dict:
        """Get builder status."""
        return {
            "running": self._running,
            "llm_extraction": USE_LLM_EXTRACTION,
            "files_processed": self.state.files_processed,
            "entities_created": self.state.entities_created,
            "last_build": self.state.last_build,
            "tracked_files": len(self.state.file_hashes),
            "vault_stats": vault.get_stats(),
            "inbox_path": str(INBOX_DIR),
            "swarm_output_path": str(SWARM_OUTPUT_DIR),
        }


# Singleton
graph_builder = GraphBuilder()
