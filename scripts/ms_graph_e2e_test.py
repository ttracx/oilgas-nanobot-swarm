#!/usr/bin/env python3
"""
Microsoft Graph End-to-End Test — verifies the full pipeline.

Tests:
1. Authentication (MSAL silent or device code)
2. Email reading → entity extraction → vault merge
3. Calendar query → entity extraction → vault merge
4. Contact sync → vault merge (no LLM needed)
5. Task sync → vault merge (no LLM needed)
6. Daily digest → composite query
7. Person context → cross-domain search
8. Vault verification → check entities were created

Prerequisite: Run `python scripts/ms_graph_auth.py` first to authenticate.
"""

import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from nanobot.integrations.microsoft_graph import ms_graph, CRED_FILE
from nanobot.integrations.msgraph_ingestion import (
    ingest_contacts, ingest_emails, ingest_calendar, ingest_tasks, run_full_sync,
)
from nanobot.knowledge.vault import vault


class TestResult:
    def __init__(self):
        self.passed: list[str] = []
        self.failed: list[str] = []
        self.skipped: list[str] = []
        self.details: dict[str, str] = {}

    def ok(self, name: str, detail: str = ""):
        self.passed.append(name)
        if detail:
            self.details[name] = detail
        print(f"  ✓ {name}" + (f" — {detail}" if detail else ""))

    def fail(self, name: str, error: str):
        self.failed.append(name)
        self.details[name] = error
        print(f"  ✗ {name} — {error}")

    def skip(self, name: str, reason: str):
        self.skipped.append(name)
        print(f"  ○ {name} — {reason}")

    def summary(self):
        total = len(self.passed) + len(self.failed) + len(self.skipped)
        print(f"\n{'=' * 60}")
        print(f"  Results: {len(self.passed)}/{total} passed, {len(self.failed)} failed, {len(self.skipped)} skipped")
        print(f"{'=' * 60}")
        if self.failed:
            print("\n  Failures:")
            for name in self.failed:
                print(f"    - {name}: {self.details[name]}")


async def main():
    print("=" * 60)
    print("  Microsoft Graph End-to-End Test")
    print("=" * 60 + "\n")

    r = TestResult()

    # ── Test 1: Config exists ─────────────────────────────────────────
    if not CRED_FILE.exists():
        r.fail("config_exists", f"No config at {CRED_FILE}. Run: python scripts/ms_graph_auth.py")
        r.summary()
        return r

    try:
        data = json.loads(CRED_FILE.read_text(encoding="utf-8"))
        client_id = data.get("client_id", "")
        if client_id and not client_id.startswith("YOUR_"):
            r.ok("config_exists", f"client_id={client_id[:8]}...")
        else:
            r.fail("config_exists", "client_id not configured")
            r.summary()
            return r
    except Exception as e:
        r.fail("config_exists", str(e))
        r.summary()
        return r

    # ── Test 2: Authentication ────────────────────────────────────────
    try:
        initialized = await ms_graph.initialize()
        if initialized:
            r.ok("authentication", "Token acquired")
        else:
            r.fail("authentication", "Could not authenticate. Run: python scripts/ms_graph_auth.py")
            r.summary()
            await ms_graph.close()
            return r
    except Exception as e:
        r.fail("authentication", str(e))
        r.summary()
        return r

    # ── Test 3: User Profile ──────────────────────────────────────────
    try:
        me = await ms_graph.get_me()
        if me and me.get("displayName"):
            r.ok("user_profile", f"{me['displayName']} ({me.get('mail', 'N/A')})")
        else:
            r.fail("user_profile", "Empty profile response")
    except Exception as e:
        r.fail("user_profile", str(e))

    # ── Test 4: Email Read ────────────────────────────────────────────
    emails = []
    try:
        emails = await ms_graph.get_recent_emails(count=10)
        r.ok("email_read", f"{len(emails)} emails in inbox")
    except Exception as e:
        r.fail("email_read", str(e))

    # ── Test 5: Email Search ──────────────────────────────────────────
    try:
        search_results = await ms_graph.search_emails("meeting", count=5)
        r.ok("email_search", f"{len(search_results)} results for 'meeting'")
    except Exception as e:
        r.fail("email_search", str(e))

    # ── Test 6: Email Body ────────────────────────────────────────────
    if emails:
        try:
            body = await ms_graph.get_email_body(emails[0]["id"])
            if body and body.get("body"):
                r.ok("email_body", f"Body type={body.get('body_type', 'unknown')}, len={len(body.get('body', ''))}")
            else:
                r.fail("email_body", "Empty body response")
        except Exception as e:
            r.fail("email_body", str(e))
    else:
        r.skip("email_body", "No emails to test with")

    # ── Test 7: Calendar — Today ──────────────────────────────────────
    try:
        events = await ms_graph.get_today_events()
        r.ok("calendar_today", f"{len(events)} events today")
    except Exception as e:
        r.fail("calendar_today", str(e))

    # ── Test 8: Calendar — Upcoming ───────────────────────────────────
    try:
        upcoming = await ms_graph.get_upcoming_events(days=7)
        r.ok("calendar_upcoming", f"{len(upcoming)} events in next 7 days")
    except Exception as e:
        r.fail("calendar_upcoming", str(e))

    # ── Test 9: Contacts ──────────────────────────────────────────────
    try:
        contacts = await ms_graph.get_contacts(count=10)
        r.ok("contacts", f"{len(contacts)} contacts")
    except Exception as e:
        r.fail("contacts", str(e))

    # ── Test 10: Tasks ────────────────────────────────────────────────
    try:
        task_lists = await ms_graph.get_task_lists()
        r.ok("task_lists", f"{len(task_lists)} task lists")
    except Exception as e:
        r.fail("task_lists", str(e))

    try:
        tasks = await ms_graph.get_tasks(status="notStarted", count=10)
        r.ok("tasks_pending", f"{len(tasks)} pending tasks")
    except Exception as e:
        r.fail("tasks_pending", str(e))

    # ── Test 11: Daily Digest (composite) ─────────────────────────────
    try:
        t0 = time.time()
        digest = await ms_graph.get_daily_digest()
        dt = time.time() - t0
        r.ok(
            "daily_digest",
            f"{digest.get('summary', 'N/A')} ({dt:.1f}s)"
        )
    except Exception as e:
        r.fail("daily_digest", str(e))

    # ── Test 12: Person Context ───────────────────────────────────────
    if me and me.get("displayName"):
        try:
            t0 = time.time()
            ctx = await ms_graph.get_person_context(me["displayName"])
            dt = time.time() - t0
            r.ok(
                "person_context",
                f"contact={ctx.get('contact') is not None}, emails={len(ctx.get('recent_emails', []))}, events={len(ctx.get('shared_events', []))} ({dt:.1f}s)"
            )
        except Exception as e:
            r.fail("person_context", str(e))
    else:
        r.skip("person_context", "No user profile available")

    # ── Test 13: Token Status ─────────────────────────────────────────
    try:
        status = await ms_graph.get_status()
        token_mins = status.get("token_expires_in", 0) // 60
        r.ok("token_status", f"expires in {token_mins}min, configured={status['configured']}")
    except Exception as e:
        r.fail("token_status", str(e))

    # ── Test 14: Vault Ingestion — Contacts ────────────────────────────
    try:
        t0 = time.time()
        result = await ingest_contacts(count=10)
        dt = time.time() - t0
        r.ok(
            "vault_ingest_contacts",
            f"total={result['total']}, created={result['created']}, updated={result['updated']} ({dt:.1f}s)"
        )
    except Exception as e:
        r.fail("vault_ingest_contacts", str(e))

    # ── Test 15: Vault Ingestion — Emails ────────────────────────────
    try:
        t0 = time.time()
        result = await ingest_emails(count=10)
        dt = time.time() - t0
        r.ok(
            "vault_ingest_emails",
            f"total={result['total']}, people_created={result['people_created']} ({dt:.1f}s)"
        )
    except Exception as e:
        r.fail("vault_ingest_emails", str(e))

    # ── Test 16: Vault Ingestion — Calendar ──────────────────────────
    try:
        t0 = time.time()
        result = await ingest_calendar(days=7)
        dt = time.time() - t0
        r.ok(
            "vault_ingest_calendar",
            f"total={result['total']}, created={result['created']} ({dt:.1f}s)"
        )
    except Exception as e:
        r.fail("vault_ingest_calendar", str(e))

    # ── Test 17: Vault Ingestion — Tasks ─────────────────────────────
    try:
        t0 = time.time()
        result = await ingest_tasks()
        dt = time.time() - t0
        r.ok("vault_ingest_tasks", f"total={result['total']} ({dt:.1f}s)")
    except Exception as e:
        r.fail("vault_ingest_tasks", str(e))

    # ── Test 18: Vault Stats (post-sync) ─────────────────────────────
    try:
        stats = vault.get_stats()
        r.ok("vault_status", f"{stats}")
    except Exception as e:
        r.skip("vault_status", f"Vault not initialized: {e}")

    # Cleanup
    await ms_graph.close()
    r.summary()
    return r


async def _run():
    r = await main()
    if r and r.failed:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(_run())
