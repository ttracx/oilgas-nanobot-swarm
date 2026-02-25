"""
VaultVectorStore — semantic search layer for the knowledge vault.

Two embedding strategies:
1. **Local** (default) — FNV1a feature hashing, free, zero-latency, no API needed
2. **OpenAI API** — text-embedding-3-small (1536 dims), highest quality, costs per token

Index persisted at: <vault>/.vectra/index.jsonl  (one JSON object per line)

Search modes:
- Pure vector: cosine similarity over embeddings
- Hybrid (default): 60% vector + 40% keyword overlap — best for mixed entity/NL queries

Ported from the TypeScript nellie-agent scaffold's vector-store.ts.
"""

import json
import math
import os
import re
import time
import structlog
from pathlib import Path
from dataclasses import dataclass, field
from typing import Any

log = structlog.get_logger()


# ── Types ───────────────────────────────────────────────────────────────────


@dataclass
class VectorEntry:
    id: str  # relative path from vault root
    vector: list[float]
    path: str
    title: str
    entity_type: str
    tags: list[str]
    snippet: str
    last_modified: str


@dataclass
class SearchResult:
    score: float
    path: str
    title: str
    entity_type: str
    tags: list[str]
    snippet: str


# ── Embedding Providers ─────────────────────────────────────────────────────


def _tokenize(text: str) -> list[str]:
    """Lowercase, strip non-alnum, split, filter short tokens."""
    cleaned = re.sub(r"[^a-z0-9\s]", " ", text.lower())
    return [t for t in cleaned.split() if len(t) > 2]


def _fnv1a(s: str) -> int:
    """FNV-1a 32-bit hash."""
    h = 0x811C9DC5
    for c in s:
        h ^= ord(c)
        h = (h * 0x01000193) & 0xFFFFFFFF
    return h


def _hash_embed(text: str, dimensions: int = 384) -> list[float]:
    """
    Feature hashing (hashing trick): tokenize → hash each token into
    a fixed-size vector → L2 normalize. Free, zero-latency.
    """
    vec = [0.0] * dimensions
    tokens = _tokenize(text)
    norm = max(1.0, math.sqrt(len(tokens)))

    for token in tokens:
        h = _fnv1a(token)
        idx = h % dimensions
        sign = 1.0 if (h & 1) else -1.0
        vec[idx] += sign / norm

    # L2 normalize
    mag = math.sqrt(sum(v * v for v in vec))
    if mag > 0:
        vec = [v / mag for v in vec]
    return vec


def _cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two vectors."""
    dot = 0.0
    na = 0.0
    nb = 0.0
    for i in range(len(a)):
        dot += a[i] * b[i]
        na += a[i] * a[i]
        nb += b[i] * b[i]
    denom = math.sqrt(na) * math.sqrt(nb)
    return dot / denom if denom > 0 else 0.0


# ── Markdown Parsing ────────────────────────────────────────────────────────


def _parse_frontmatter(content: str) -> dict[str, Any]:
    """Extract title, type, tags from YAML frontmatter or first heading."""
    result = {"title": "Untitled", "type": "topic", "tags": []}

    fm_match = re.match(r"^---\n(.*?)\n---", content, re.DOTALL)
    if fm_match:
        block = fm_match.group(1)
        title_m = re.search(r'^title:\s*["\']?(.+?)["\']?\s*$', block, re.MULTILINE)
        if title_m:
            result["title"] = title_m.group(1)
        type_m = re.search(r'^type:\s*["\']?(.+?)["\']?\s*$', block, re.MULTILINE)
        if type_m:
            result["type"] = type_m.group(1)
        tags_m = re.search(r"^tags:\s*\[([^\]]*)\]", block, re.MULTILINE)
        if tags_m:
            result["tags"] = [t.strip().strip("\"'") for t in tags_m.group(1).split(",") if t.strip()]
    else:
        h_match = re.search(r"^#\s+(.+)", content, re.MULTILINE)
        if h_match:
            result["title"] = h_match.group(1).strip()

    return result


def _extract_snippet(content: str, max_len: int = 500) -> str:
    """Strip frontmatter and markdown formatting, return plain text snippet."""
    text = re.sub(r"^---\n.*?\n---\n?", "", content, flags=re.DOTALL)
    text = re.sub(r"#{1,6}\s+", "", text)
    text = re.sub(r"\*\*|__", "", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:max_len]


# ── Vector Store ────────────────────────────────────────────────────────────


class VaultVectorStore:
    """
    Semantic search over the Nellie vault using local feature hashing.
    No external API required. Optionally supports OpenAI embeddings.
    """

    def __init__(self, vault_path: str | Path, dimensions: int = 384):
        self.vault_path = Path(vault_path)
        self.index_dir = self.vault_path / ".vectra"
        self.index_file = self.index_dir / "index.jsonl"
        self.meta_file = self.index_dir / "meta.json"
        self.dimensions = dimensions
        self.entries: list[VectorEntry] = []
        self._use_api = False
        self._api_key: str = ""

    def configure_openai(self, api_key: str, dimensions: int = 1536) -> None:
        """Enable OpenAI API embeddings instead of local hash embeddings."""
        self._use_api = True
        self._api_key = api_key
        self.dimensions = dimensions

    def _embed(self, texts: list[str]) -> list[list[float]]:
        """Embed texts using the configured provider."""
        if self._use_api and self._api_key:
            return self._embed_openai(texts)
        return [_hash_embed(text, self.dimensions) for text in texts]

    def _embed_openai(self, texts: list[str]) -> list[list[float]]:
        """Call OpenAI embeddings API (synchronous for simplicity)."""
        import httpx
        resp = httpx.post(
            "https://api.openai.com/v1/embeddings",
            headers={"Authorization": f"Bearer {self._api_key}"},
            json={"model": "text-embedding-3-small", "input": texts},
            timeout=30.0,
        )
        resp.raise_for_status()
        data = resp.json()
        return [d["embedding"] for d in data["data"]]

    # ── Persistence ─────────────────────────────────────────────────────

    def load(self) -> int:
        """Load index from disk. Returns entry count."""
        if not self.index_file.exists():
            self.entries = []
            return 0
        lines = self.index_file.read_text(encoding="utf-8").strip().split("\n")
        self.entries = []
        for line in lines:
            if not line.strip():
                continue
            d = json.loads(line)
            self.entries.append(VectorEntry(
                id=d["id"], vector=d["vector"], path=d["path"],
                title=d["title"], entity_type=d["type"], tags=d["tags"],
                snippet=d["snippet"], last_modified=d["last_modified"],
            ))
        log.info("vector_store_loaded", entries=len(self.entries))
        return len(self.entries)

    def save(self) -> None:
        """Persist index to disk as JSONL."""
        self.index_dir.mkdir(parents=True, exist_ok=True)
        lines = []
        for e in self.entries:
            lines.append(json.dumps({
                "id": e.id, "vector": e.vector, "path": e.path,
                "title": e.title, "type": e.entity_type, "tags": e.tags,
                "snippet": e.snippet, "last_modified": e.last_modified,
            }))
        self.index_file.write_text("\n".join(lines), encoding="utf-8")
        self.meta_file.write_text(json.dumps({
            "dimensions": self.dimensions,
            "entry_count": len(self.entries),
            "last_updated": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }), encoding="utf-8")

    # ── Indexing ────────────────────────────────────────────────────────

    def index_all(self) -> dict[str, int]:
        """Index all .md files in the vault. Skips unchanged files by mtime."""
        files = list(self.vault_path.rglob("*.md"))
        # Skip hidden dirs (.vectra, .obsidian, .git)
        files = [f for f in files if not any(p.startswith(".") for p in f.relative_to(self.vault_path).parts)]

        existing = {e.id: e for e in self.entries}
        indexed = 0
        skipped = 0
        batch_texts = []
        batch_metas = []

        for fpath in files:
            rel = str(fpath.relative_to(self.vault_path))
            mtime = fpath.stat().st_mtime
            mod_str = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(mtime))

            # Skip if unchanged
            if rel in existing and existing[rel].last_modified == mod_str:
                skipped += 1
                continue

            content = fpath.read_text(encoding="utf-8", errors="replace")
            fm = _parse_frontmatter(content)
            snippet = _extract_snippet(content)

            batch_texts.append(f"{fm['title']}\n\n{snippet}")
            batch_metas.append({
                "id": rel, "path": rel, "title": fm["title"],
                "type": fm["type"], "tags": fm["tags"],
                "snippet": snippet, "last_modified": mod_str,
            })

            # Embed in batches of 50
            if len(batch_texts) >= 50:
                indexed += self._embed_and_upsert(batch_texts, batch_metas)
                batch_texts, batch_metas = [], []

        # Final batch
        if batch_texts:
            indexed += self._embed_and_upsert(batch_texts, batch_metas)

        # Remove deleted files
        current_files = {str(f.relative_to(self.vault_path)) for f in files}
        self.entries = [e for e in self.entries if e.id in current_files]

        self.save()
        log.info("vector_index_rebuilt", indexed=indexed, skipped=skipped, total=len(self.entries))
        return {"indexed": indexed, "skipped": skipped, "total": len(self.entries)}

    def index_note(self, file_path: str | Path) -> None:
        """Index a single note (incremental — called by file watcher)."""
        fpath = Path(file_path)
        if not fpath.exists():
            return
        rel = str(fpath.relative_to(self.vault_path))
        content = fpath.read_text(encoding="utf-8", errors="replace")
        mtime = fpath.stat().st_mtime
        mod_str = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(mtime))
        fm = _parse_frontmatter(content)
        snippet = _extract_snippet(content)

        vectors = self._embed([f"{fm['title']}\n\n{snippet}"])
        entry = VectorEntry(
            id=rel, vector=vectors[0], path=rel, title=fm["title"],
            entity_type=fm["type"], tags=fm["tags"],
            snippet=snippet, last_modified=mod_str,
        )
        # Upsert
        idx = next((i for i, e in enumerate(self.entries) if e.id == rel), None)
        if idx is not None:
            self.entries[idx] = entry
        else:
            self.entries.append(entry)
        self.save()
        log.info("vector_note_indexed", path=rel)

    def remove_note(self, file_path: str | Path) -> None:
        """Remove a note from the index."""
        rel = str(Path(file_path).relative_to(self.vault_path))
        self.entries = [e for e in self.entries if e.id != rel]
        self.save()

    def _embed_and_upsert(self, texts: list[str], metas: list[dict]) -> int:
        """Embed a batch and upsert into the index."""
        try:
            vectors = self._embed(texts)
        except Exception as e:
            log.error("embedding_batch_failed", error=str(e))
            return 0

        count = 0
        for vec, meta in zip(vectors, metas):
            entry = VectorEntry(
                id=meta["id"], vector=vec, path=meta["path"],
                title=meta["title"], entity_type=meta["type"],
                tags=meta["tags"], snippet=meta["snippet"],
                last_modified=meta["last_modified"],
            )
            idx = next((i for i, e in enumerate(self.entries) if e.id == entry.id), None)
            if idx is not None:
                self.entries[idx] = entry
            else:
                self.entries.append(entry)
            count += 1
        return count

    # ── Search ──────────────────────────────────────────────────────────

    def search(self, query: str, top_k: int = 5,
               type_filter: str | None = None,
               tag_filter: list[str] | None = None) -> list[SearchResult]:
        """Pure vector similarity search."""
        if not self.entries:
            return []
        qvec = self._embed([query])[0]
        candidates = []
        for e in self.entries:
            score = _cosine(qvec, e.vector)
            candidates.append((score, e))

        candidates = self._apply_filters(candidates, type_filter, tag_filter)
        candidates.sort(key=lambda x: x[0], reverse=True)

        return [
            SearchResult(score=round(s, 4), path=e.path, title=e.title,
                         entity_type=e.entity_type, tags=e.tags, snippet=e.snippet)
            for s, e in candidates[:top_k]
        ]

    def hybrid_search(self, query: str, top_k: int = 5,
                      type_filter: str | None = None,
                      tag_filter: list[str] | None = None) -> list[SearchResult]:
        """
        Hybrid search: 60% vector similarity + 40% keyword overlap.
        Best for mixed entity + natural language queries.
        """
        if not self.entries:
            return []
        qvec = self._embed([query])[0]
        q_tokens = set(_tokenize(query))

        candidates = []
        for e in self.entries:
            # Vector score
            vs = _cosine(qvec, e.vector)
            # Keyword score
            note_tokens = _tokenize(f"{e.title} {e.snippet}")
            overlap = sum(1 for t in note_tokens if t in q_tokens)
            ks = overlap / max(1, len(q_tokens))
            # Combined
            score = vs * 0.6 + ks * 0.4
            candidates.append((score, e))

        candidates = self._apply_filters(candidates, type_filter, tag_filter)
        candidates.sort(key=lambda x: x[0], reverse=True)

        return [
            SearchResult(score=round(s, 4), path=e.path, title=e.title,
                         entity_type=e.entity_type, tags=e.tags, snippet=e.snippet)
            for s, e in candidates[:top_k]
        ]

    def _apply_filters(
        self,
        candidates: list[tuple[float, VectorEntry]],
        type_filter: str | None,
        tag_filter: list[str] | None,
    ) -> list[tuple[float, VectorEntry]]:
        if type_filter:
            candidates = [(s, e) for s, e in candidates if e.entity_type == type_filter]
        if tag_filter:
            ft = {t.lower() for t in tag_filter}
            candidates = [(s, e) for s, e in candidates
                          if any(t.lower() in ft for t in e.tags)]
        return candidates

    # ── Stats ───────────────────────────────────────────────────────────

    def get_stats(self) -> dict:
        return {
            "entry_count": len(self.entries),
            "dimensions": self.dimensions,
            "index_size_kb": round(len(self.entries) * self.dimensions * 8 / 1024),
            "use_api": self._use_api,
        }
