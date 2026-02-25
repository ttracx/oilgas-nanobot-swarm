"""
VaultFileWatcher — watches the knowledge vault for manual edits.

On Markdown file changes:
1. Incremental vector index update (add/update/remove)
2. Knowledge graph cache invalidation (forces rebuild)
3. Event callbacks for swarm triggers

Uses watchdog for cross-platform file watching with debounced batching.
Ported from the TypeScript nellie-agent scaffold's file-watcher.ts.
"""

import asyncio
import threading
import time
import structlog
from pathlib import Path
from typing import Callable

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileSystemEvent

log = structlog.get_logger()

DEBOUNCE_SECONDS = 2.0


class _VaultHandler(FileSystemEventHandler):
    """Internal watchdog handler that collects Markdown file changes."""

    def __init__(self, vault_path: Path, callback: Callable[[list[dict]], None]):
        super().__init__()
        self.vault_path = vault_path
        self.callback = callback
        self.pending: dict[str, dict] = {}
        self._lock = threading.Lock()
        self._timer: threading.Timer | None = None

    def _is_relevant(self, path: str) -> bool:
        """Only watch .md files, skip hidden dirs."""
        if not path.endswith(".md"):
            return False
        try:
            rel = Path(path).relative_to(self.vault_path)
            return not any(p.startswith(".") for p in rel.parts)
        except ValueError:
            return False

    def on_created(self, event: FileSystemEvent) -> None:
        if not event.is_directory and self._is_relevant(event.src_path):
            self._queue_change("add", event.src_path)

    def on_modified(self, event: FileSystemEvent) -> None:
        if not event.is_directory and self._is_relevant(event.src_path):
            self._queue_change("change", event.src_path)

    def on_deleted(self, event: FileSystemEvent) -> None:
        if not event.is_directory and self._is_relevant(event.src_path):
            self._queue_change("unlink", event.src_path)

    def _queue_change(self, change_type: str, path: str) -> None:
        """Queue a change and reset the debounce timer."""
        rel = str(Path(path).relative_to(self.vault_path))
        with self._lock:
            self.pending[path] = {
                "type": change_type,
                "path": path,
                "relative_path": rel,
            }
            if self._timer:
                self._timer.cancel()
            self._timer = threading.Timer(DEBOUNCE_SECONDS, self._flush)
            self._timer.daemon = True
            self._timer.start()

    def _flush(self) -> None:
        """Process all pending changes."""
        with self._lock:
            changes = list(self.pending.values())
            self.pending.clear()
        if changes:
            self.callback(changes)


class VaultFileWatcher:
    """
    Watches the vault directory for Markdown file changes.

    On change:
    - Updates vector index incrementally
    - Invalidates knowledge graph cache
    - Calls optional on_change callbacks
    """

    def __init__(
        self,
        vault_path: str | Path,
        vector_store=None,
        graph_invalidator: Callable | None = None,
        on_change: Callable[[list[dict]], None] | None = None,
    ):
        self.vault_path = Path(vault_path)
        self.vector_store = vector_store
        self.graph_invalidator = graph_invalidator
        self.on_change = on_change
        self._observer: Observer | None = None
        self._running = False

    def start(self) -> None:
        """Start watching the vault directory."""
        if self._running:
            log.warning("file_watcher_already_running")
            return

        handler = _VaultHandler(self.vault_path, self._process_changes)
        self._observer = Observer()
        self._observer.schedule(handler, str(self.vault_path), recursive=True)
        self._observer.daemon = True
        self._observer.start()
        self._running = True
        log.info("file_watcher_started", vault=str(self.vault_path))

    def stop(self) -> None:
        """Stop watching."""
        if self._observer:
            self._observer.stop()
            self._observer.join(timeout=5)
            self._observer = None
        self._running = False
        log.info("file_watcher_stopped")

    @property
    def is_running(self) -> bool:
        return self._running

    def _process_changes(self, changes: list[dict]) -> None:
        """Process a batch of debounced file changes."""
        adds = [c for c in changes if c["type"] == "add"]
        updates = [c for c in changes if c["type"] == "change"]
        deletes = [c for c in changes if c["type"] == "unlink"]

        log.info(
            "vault_changes_detected",
            adds=len(adds),
            updates=len(updates),
            deletes=len(deletes),
        )

        # Update vector index
        if self.vector_store:
            for change in changes:
                try:
                    if change["type"] == "unlink":
                        self.vector_store.remove_note(change["path"])
                    else:
                        self.vector_store.index_note(change["path"])
                except Exception as e:
                    log.error(
                        "vector_index_update_failed",
                        file=change["relative_path"],
                        error=str(e),
                    )

        # Invalidate graph cache
        if self.graph_invalidator:
            try:
                self.graph_invalidator()
            except Exception as e:
                log.error("graph_invalidation_failed", error=str(e))

        # Custom callback
        if self.on_change:
            try:
                self.on_change(changes)
            except Exception as e:
                log.error("on_change_callback_failed", error=str(e))
