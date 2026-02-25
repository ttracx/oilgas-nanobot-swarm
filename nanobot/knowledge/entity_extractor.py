"""
LLM-Powered Entity Extraction — uses the swarm's LLM backend to extract
structured entities from raw text (emails, transcripts, documents, swarm output).

Falls back to regex patterns if LLM is unavailable.

Extraction output matches the vault's category schema:
- people, companies, projects, topics, decisions, commitments
"""

import json
import os
import re
import structlog
from dataclasses import dataclass, field
from typing import Any

log = structlog.get_logger()

OLLAMA_URL = os.getenv("OLLAMA_URL", os.getenv("VLLM_URL", "http://localhost:11434/v1"))
EXTRACTION_MODEL = os.getenv("EXTRACTION_MODEL", os.getenv("SWARM_MODEL", "nanobot-reasoner"))


@dataclass
class ExtractedEntity:
    """A structured entity extracted from text."""
    type: str  # people, companies, projects, topics, decisions, commitments
    name: str
    context: str = ""
    relationships: list[str] = field(default_factory=list)
    confidence: float = 0.8
    role: str = ""
    aliases: list[str] = field(default_factory=list)


@dataclass
class ExtractionResult:
    """Full result from entity extraction."""
    entities: list[ExtractedEntity] = field(default_factory=list)
    summary: str = ""
    action_items: list[str] = field(default_factory=list)
    decisions: list[str] = field(default_factory=list)
    topics: list[str] = field(default_factory=list)


EXTRACTION_SYSTEM_PROMPT = """You are a knowledge graph extraction agent.
Given raw text, extract structured entities for a personal knowledge graph.

Output JSON matching this exact schema:
{
  "entities": [
    {
      "type": "people|companies|projects|topics|decisions|commitments",
      "name": "Entity Name",
      "context": "What we learned about this entity",
      "relationships": ["Other Entity Name"],
      "confidence": 0.0-1.0,
      "role": "Optional role/title",
      "aliases": ["Optional", "alternate names"]
    }
  ],
  "summary": "1-2 sentence summary of the text",
  "action_items": ["Action item with owner and deadline if known"],
  "decisions": ["Decision that was made"],
  "topics": ["Key topics discussed"]
}

Rules:
- Use existing entity names when possible (check the provided list)
- Mark confidence < 0.7 for inferred/uncertain relationships
- Include temporal context (dates, deadlines) in the context field
- Prefer specific names over pronouns
- Only extract entities that are clearly meaningful (skip trivial mentions)
- type must be one of: people, companies, projects, topics, decisions, commitments
"""


async def extract_entities_llm(
    text: str,
    source_type: str = "document",
    existing_entities: list[str] | None = None,
    client=None,
) -> ExtractionResult:
    """
    Extract entities using an LLM call.

    Args:
        text: Raw text to extract from
        source_type: Type of source (email, meeting, voice_memo, document, swarm_output)
        existing_entities: Names of entities already in the vault for dedup
        client: AsyncOpenAI client (optional, creates one if not provided)

    Returns:
        ExtractionResult with entities, summary, action items, decisions
    """
    if client is None:
        from openai import AsyncOpenAI
        client = AsyncOpenAI(
            base_url=OLLAMA_URL,
            api_key=os.getenv("VLLM_API_KEY", "nq-nanobot"),
        )

    existing = existing_entities or []
    existing_text = ", ".join(existing[:100]) if existing else "(empty vault)"

    try:
        response = await client.chat.completions.create(
            model=EXTRACTION_MODEL,
            messages=[
                {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
                {"role": "user", "content": (
                    f"Source type: {source_type}\n\n"
                    f"Existing entities in graph (use these names if they match):\n{existing_text}\n\n"
                    f"Raw text to process:\n---\n{text[:4000]}\n---\n\n"
                    f"Extract entities and relationships as JSON."
                )},
            ],
            temperature=0.1,
            max_tokens=2048,
        )

        content = response.choices[0].message.content or ""

        # Try to parse JSON from the response (handle markdown code blocks)
        json_str = content
        if "```json" in content:
            json_str = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
            json_str = content.split("```")[1].split("```")[0].strip()

        data = json.loads(json_str)

        entities = []
        for e in data.get("entities", []):
            if not e.get("type") or not e.get("name"):
                continue
            if e.get("confidence", 1.0) < 0.4:
                continue
            entities.append(ExtractedEntity(
                type=e["type"],
                name=e["name"],
                context=e.get("context", ""),
                relationships=e.get("relationships", []),
                confidence=e.get("confidence", 0.8),
                role=e.get("role", ""),
                aliases=e.get("aliases", []),
            ))

        return ExtractionResult(
            entities=_deduplicate_entities(entities),
            summary=data.get("summary", ""),
            action_items=data.get("action_items", []),
            decisions=data.get("decisions", []),
            topics=data.get("topics", []),
        )

    except json.JSONDecodeError as e:
        log.warning("llm_extraction_json_error", error=str(e)[:100])
        return _extract_entities_regex(text)
    except Exception as e:
        log.warning("llm_extraction_failed", error=str(e)[:200])
        return _extract_entities_regex(text)


# ── Regex Fallback ───────────────────────────────────────────────────────

PERSON_PATTERNS = [
    re.compile(r"(?:authored by|written by|contact|from|to|cc|assigned to|@)\s+([A-Z][a-z]+ [A-Z][a-z]+)", re.IGNORECASE),
    re.compile(r"([A-Z][a-z]+ [A-Z][a-z]+)\s+(?:said|mentioned|noted|suggested|proposed|reported)"),
]

ORG_PATTERNS = [
    re.compile(r"(?:at|from|for|with)\s+([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)*(?:\s+(?:Inc|LLC|Corp|Ltd|Co|AI|io)\.?))"),
]

PROJECT_PATTERNS = [
    re.compile(r"(?:project|repo|repository|codebase)\s*:?\s*[\"']?(\w[\w\s-]{2,30})[\"']?", re.IGNORECASE),
]

TECH_TOPICS = {
    "authentication", "api", "database", "frontend", "backend", "deployment",
    "testing", "security", "performance", "architecture", "migration",
    "kubernetes", "docker", "react", "python", "typescript", "swift",
    "machine learning", "ai", "quantum", "blockchain", "cloud",
    "mcp", "agent", "swarm", "knowledge graph", "embeddings",
}


def _extract_entities_regex(text: str) -> ExtractionResult:
    """Regex-based fallback when LLM is unavailable."""
    entities: list[ExtractedEntity] = []

    for pattern in PERSON_PATTERNS:
        for match in pattern.findall(text):
            name = match.strip()
            if len(name) > 3:
                entities.append(ExtractedEntity(
                    type="people", name=name, confidence=0.6,
                ))

    for pattern in ORG_PATTERNS:
        for match in pattern.findall(text):
            name = match.strip()
            if len(name) > 2:
                entities.append(ExtractedEntity(
                    type="companies", name=name, confidence=0.6,
                ))

    for pattern in PROJECT_PATTERNS:
        for match in pattern.findall(text):
            name = match.strip()
            if len(name) > 2:
                entities.append(ExtractedEntity(
                    type="projects", name=name, confidence=0.5,
                ))

    text_lower = text.lower()
    for kw in TECH_TOPICS:
        if kw in text_lower:
            entities.append(ExtractedEntity(
                type="topics", name=kw.title(), confidence=0.5,
            ))

    # Dedup by (type, name) with relationship merging
    deduped = _deduplicate_entities(entities)

    return ExtractionResult(entities=deduped)


def _deduplicate_entities(entities: list[ExtractedEntity]) -> list[ExtractedEntity]:
    """Deduplicate entities by (type, name), merging relationships and contexts.

    When duplicates are found:
    - Relationships from all duplicates are merged (union)
    - Contexts are appended
    - Highest confidence wins
    - Aliases are merged
    """
    merged: dict[tuple[str, str], ExtractedEntity] = {}

    for e in entities:
        key = (e.type, e.name.lower())
        if key in merged:
            existing = merged[key]
            # Merge relationships (union)
            existing_rels = set(existing.relationships)
            for rel in e.relationships:
                if rel not in existing_rels:
                    existing.relationships.append(rel)
            # Append context if different
            if e.context and e.context not in existing.context:
                existing.context = (
                    f"{existing.context}; {e.context}" if existing.context else e.context
                )
            # Keep highest confidence
            if e.confidence > existing.confidence:
                existing.confidence = e.confidence
            # Merge aliases
            existing_aliases = set(a.lower() for a in existing.aliases)
            for alias in e.aliases:
                if alias.lower() not in existing_aliases:
                    existing.aliases.append(alias)
            # Keep role if existing is empty
            if not existing.role and e.role:
                existing.role = e.role
        else:
            merged[key] = e

    return list(merged.values())
