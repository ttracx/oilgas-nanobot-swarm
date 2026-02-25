"""
Microsoft Graph → Vault Ingestion Pipeline.

Pulls data from Microsoft Graph (emails, contacts, calendar, tasks) and
persists it as structured vault notes. This is the "end-to-end" bridge
from Microsoft 365 into Nellie's knowledge graph.

Usage:
  - Called by the scheduler (msgraph-sync agent team)
  - Called by the E2E test to verify the full pipeline
  - Can be run standalone via `python -m nanobot.integrations.msgraph_ingestion`
"""

import asyncio
import re
from datetime import datetime

import structlog

from nanobot.integrations.microsoft_graph import ms_graph
from nanobot.knowledge.vault import vault

log = structlog.get_logger()


def _strip_html(html: str) -> str:
    """Remove HTML tags and collapse whitespace."""
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:2000]  # cap for vault notes


def _safe_name(name: str) -> str:
    """Sanitize a name for use as a vault note title."""
    return re.sub(r"[^\w\s\-.]", "", name).strip()[:80] or "Unknown"


async def ingest_contacts(count: int = 200) -> dict:
    """Sync Outlook contacts into vault/people/ notes.

    Contacts are structured data — no LLM needed.
    Creates or updates a person note for each contact with email, company, title.
    """
    contacts = await ms_graph.get_contacts(count=count)
    created = 0
    updated = 0

    for c in contacts:
        name = _safe_name(c.get("name", ""))
        if not name or name == "Unknown":
            continue

        email = c.get("email", "")
        company = c.get("company", "")
        title = c.get("title", "")
        department = c.get("department", "")
        phone = c.get("phone", "")

        # Build content
        lines = []
        if email:
            lines.append(f"**Email:** {email}")
        if title:
            lines.append(f"**Title:** {title}")
        if company:
            lines.append(f"**Company:** [[{company}]]")
        if department:
            lines.append(f"**Department:** {department}")
        if phone:
            lines.append(f"**Phone:** {phone}")

        content = "\n".join(lines) if lines else "Contact synced from Outlook."

        backlinks = []
        if company:
            backlinks.append(company)

        metadata = {
            "source": "microsoft_graph",
            "ms_graph_id": c.get("id", ""),
        }
        if email:
            metadata["email"] = email

        # Check if note exists — update if so, create if not
        from nanobot.knowledge.vault import _note_path
        path = _note_path("people", name)
        if path.exists():
            vault.update_note(
                "people", name,
                update_metadata=metadata,
                add_source={"type": "outlook_contact", "synced": datetime.now().isoformat()},
            )
            updated += 1
        else:
            vault.create_note(
                "people", name,
                content=content,
                metadata=metadata,
                backlinks=backlinks,
                sources=[{"type": "outlook_contact", "synced": datetime.now().isoformat()}],
                confidence=0.95,
            )
            created += 1

    log.info("contacts_ingested", total=len(contacts), created=created, updated=updated)
    return {"total": len(contacts), "created": created, "updated": updated}


async def ingest_emails(count: int = 20) -> dict:
    """Ingest recent emails into vault/daily/ notes.

    Appends email summaries to today's daily note and creates person
    notes for new senders.
    """
    emails = await ms_graph.get_recent_emails(count=count)
    today = datetime.now().strftime("%Y-%m-%d")
    daily_name = f"Daily - {today}"

    people_seen = set()
    email_summaries = []

    for e in emails:
        sender = e.get("from", "Unknown")
        subject = e.get("subject", "(no subject)")
        received = e.get("received", "")[:16].replace("T", " ")
        preview = e.get("preview", "")[:200]

        email_summaries.append(
            f"- **{received}** — [{subject}] from [[{sender}]]\n  {preview}"
        )

        # Track senders for people notes
        if sender and sender != "Unknown":
            people_seen.add(sender)

    # Append to daily note
    if email_summaries:
        email_section = "\n## Email Summary\n\n" + "\n".join(email_summaries[:15])

        from nanobot.knowledge.vault import _note_path
        daily_path = _note_path("daily", daily_name)
        if daily_path.exists():
            vault.update_note("daily", daily_name, append_content=email_section)
        else:
            vault.create_note(
                "daily", daily_name,
                content=email_section,
                metadata={"source": "microsoft_graph", "date": today},
                sources=[{"type": "outlook_email", "synced": datetime.now().isoformat()}],
            )

    # Create person notes for new senders
    people_created = 0
    for sender in people_seen:
        safe = _safe_name(sender)
        path = _note_path("people", safe)
        if not path.exists():
            vault.create_note(
                "people", safe,
                content=f"First seen in email on {today}.",
                metadata={"source": "microsoft_graph"},
                sources=[{"type": "outlook_email", "first_seen": today}],
                confidence=0.6,
            )
            people_created += 1

    log.info("emails_ingested", total=len(emails), people_created=people_created)
    return {"total": len(emails), "people_created": people_created}


async def ingest_calendar(days: int = 7) -> dict:
    """Ingest upcoming calendar events into vault/meetings/ notes.

    Creates a meeting note for each event with attendees linked as backlinks.
    """
    events = await ms_graph.get_upcoming_events(days=days)
    created = 0

    for evt in events:
        subject = _safe_name(evt.get("subject", "Untitled Meeting"))
        start = evt.get("start", "")[:16].replace("T", " ")
        end = evt.get("end", "")[:16].replace("T", " ")
        organizer = evt.get("organizer", "")
        attendees = evt.get("attendees", [])

        content_lines = [
            f"**When:** {start} → {end}",
            f"**Organizer:** [[{organizer}]]" if organizer else "",
        ]

        backlinks = []
        if organizer:
            backlinks.append(organizer)
        for a in attendees:
            if a:
                content_lines.append(f"- [[{a}]]")
                backlinks.append(a)

        content = "\n".join(line for line in content_lines if line)

        # Use date + subject as note name to avoid collisions
        note_name = f"{start[:10]} {subject}" if start else subject

        from nanobot.knowledge.vault import _note_path
        path = _note_path("meetings", note_name)
        if not path.exists():
            vault.create_note(
                "meetings", note_name,
                content=content,
                metadata={"source": "microsoft_graph", "ms_event_id": evt.get("id", "")[:20]},
                backlinks=backlinks,
                sources=[{"type": "outlook_calendar", "synced": datetime.now().isoformat()}],
                confidence=0.95,
            )
            created += 1

    log.info("calendar_ingested", total=len(events), created=created)
    return {"total": len(events), "created": created}


async def ingest_tasks() -> dict:
    """Ingest pending tasks into today's daily note.

    Appends a task summary section to the daily note.
    """
    tasks = await ms_graph.get_tasks(status="notStarted", count=50)
    today = datetime.now().strftime("%Y-%m-%d")
    daily_name = f"Daily - {today}"

    if not tasks:
        return {"total": 0}

    task_lines = []
    for t in tasks:
        importance = t.get("importance", "normal")
        title = t.get("title", "")
        due = t.get("due", "")
        marker = "!" if importance == "high" else " "
        due_str = f" (due {due})" if due else ""
        task_lines.append(f"- [{marker}] {title}{due_str}")

    task_section = "\n## Pending Tasks\n\n" + "\n".join(task_lines[:25])

    from nanobot.knowledge.vault import _note_path
    daily_path = _note_path("daily", daily_name)
    if daily_path.exists():
        vault.update_note("daily", daily_name, append_content=task_section)
    else:
        vault.create_note(
            "daily", daily_name,
            content=task_section,
            metadata={"source": "microsoft_graph", "date": today},
        )

    log.info("tasks_ingested", total=len(tasks))
    return {"total": len(tasks)}


async def run_full_sync() -> dict:
    """Run the complete MS Graph → Vault sync pipeline.

    Returns aggregate stats from all ingestion steps.
    """
    if not ms_graph.creds.is_configured:
        initialized = await ms_graph.initialize()
        if not initialized:
            return {"error": "Microsoft Graph not configured or authenticated"}

    if not ms_graph.creds.is_token_valid:
        return {"error": "Microsoft Graph token expired — re-authenticate"}

    results = {}

    try:
        results["contacts"] = await ingest_contacts()
    except Exception as e:
        log.error("contact_ingestion_failed", error=str(e))
        results["contacts"] = {"error": str(e)}

    try:
        results["emails"] = await ingest_emails()
    except Exception as e:
        log.error("email_ingestion_failed", error=str(e))
        results["emails"] = {"error": str(e)}

    try:
        results["calendar"] = await ingest_calendar()
    except Exception as e:
        log.error("calendar_ingestion_failed", error=str(e))
        results["calendar"] = {"error": str(e)}

    try:
        results["tasks"] = await ingest_tasks()
    except Exception as e:
        log.error("task_ingestion_failed", error=str(e))
        results["tasks"] = {"error": str(e)}

    log.info("full_sync_complete", results=results)
    return results


if __name__ == "__main__":
    asyncio.run(run_full_sync())
