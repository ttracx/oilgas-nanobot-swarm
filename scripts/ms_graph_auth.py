#!/usr/bin/env python3
"""
Microsoft Graph Authentication CLI — Interactive device code flow.

Run this script to authenticate Nellie with Microsoft 365:

    python scripts/ms_graph_auth.py

This will:
1. Check for Azure AD app credentials in ~/.nellie/config/microsoft_graph.json
2. If missing, create a template and show setup instructions
3. Initiate device code flow (open a URL, enter a code)
4. Verify authentication by fetching the user profile
5. Test connectivity by fetching inbox and calendar
"""

import asyncio
import json
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from nanobot.integrations.microsoft_graph import (
    ms_graph,
    create_credentials_template,
    CRED_FILE,
    NELLIE_HOME,
)


async def main():
    print("=" * 60)
    print("  Nellie — Microsoft Graph Authentication")
    print("=" * 60)

    # Step 1: Check config
    print(f"\n1. Checking credentials at {CRED_FILE}...")

    if not CRED_FILE.exists():
        create_credentials_template()
        print(f"\n   Template created at {CRED_FILE}")
        print("   Edit the file with your Azure AD app registration details:")
        print("   - client_id: From Azure Portal → App registrations → Application ID")
        print("   - tenant_id: Your tenant ID or 'common' for multi-tenant")
        print("\n   Azure AD App Setup Guide:")
        print("   1. Go to https://portal.azure.com → Azure Active Directory → App registrations")
        print("   2. Click 'New registration'")
        print("   3. Name: 'Nellie Agent'")
        print("   4. Supported account types: 'Personal Microsoft accounts only' or 'Any org + personal'")
        print("   5. Redirect URI: select 'Mobile and desktop' → https://login.microsoftonline.com/common/oauth2/nativeclient")
        print("   6. After creation, copy the Application (client) ID → put in client_id")
        print("   7. Go to 'API permissions' → Add permissions → Microsoft Graph → Delegated:")
        print("      - User.Read, Mail.ReadWrite, Mail.Send")
        print("      - Calendars.ReadWrite, Contacts.Read")
        print("      - Files.Read, Tasks.ReadWrite")
        print("   8. Click 'Grant admin consent' if you're an admin\n")
        return

    # Load and check config
    try:
        data = json.loads(CRED_FILE.read_text(encoding="utf-8"))
        client_id = data.get("client_id", "")
        if not client_id or client_id.startswith("YOUR_"):
            print(f"   Please edit {CRED_FILE} with real Azure AD credentials.")
            return
        print(f"   Client ID: {client_id[:8]}...{client_id[-4:]}")
        print(f"   Tenant ID: {data.get('tenant_id', 'common')}")
    except Exception as e:
        print(f"   Error reading config: {e}")
        return

    # Step 2: Try silent auth first
    print("\n2. Attempting silent authentication...")
    initialized = await ms_graph.initialize()

    if initialized:
        print("   Silent auth succeeded (cached token valid)")
    else:
        # Step 3: Interactive device code flow
        print("   Silent auth failed — starting device code flow...\n")
        success = await ms_graph.authenticate_interactive()
        if not success:
            print("\n   Authentication failed. Please try again.")
            await ms_graph.close()
            return

    # Step 4: Verify by fetching profile
    print("\n3. Verifying Microsoft Graph connectivity...\n")

    me = await ms_graph.get_me()
    if me:
        print(f"   User: {me.get('displayName', 'Unknown')}")
        print(f"   Email: {me.get('mail', me.get('userPrincipalName', 'Unknown'))}")
        print(f"   Job: {me.get('jobTitle', 'N/A')}")
    else:
        print("   Warning: Could not fetch user profile")

    # Step 5: Test API calls
    print("\n4. Testing API endpoints...\n")

    # Test inbox
    try:
        emails = await ms_graph.get_recent_emails(count=5)
        print(f"   Inbox: {len(emails)} recent emails")
        for e in emails[:3]:
            print(f"     - {e.get('subject', 'No subject')[:60]} (from {e.get('from', 'Unknown')})")
    except Exception as e:
        print(f"   Inbox: Error - {e}")

    # Test calendar
    try:
        events = await ms_graph.get_today_events()
        print(f"\n   Calendar: {len(events)} events today")
        for evt in events[:3]:
            start = evt.get("start", "")[:16].replace("T", " ")
            print(f"     - {start} {evt.get('subject', 'No subject')[:50]}")
    except Exception as e:
        print(f"   Calendar: Error - {e}")

    # Test contacts
    try:
        contacts = await ms_graph.get_contacts(count=5)
        print(f"\n   Contacts: {len(contacts)} contacts found")
    except Exception as e:
        print(f"   Contacts: Error - {e}")

    # Test tasks
    try:
        tasks = await ms_graph.get_tasks(status="notStarted", count=5)
        print(f"\n   Tasks: {len(tasks)} pending tasks")
        for t in tasks[:3]:
            print(f"     - [{t.get('importance', 'normal')}] {t.get('title', '')[:50]}")
    except Exception as e:
        print(f"   Tasks: Error - {e}")

    print("\n" + "=" * 60)
    status = await ms_graph.get_status()
    token_mins = status.get("token_expires_in", 0) // 60
    print(f"  Status: {'Authenticated' if status['authenticated'] else 'Not authenticated'}")
    print(f"  Token expires in: {token_mins} minutes")
    print(f"  Credentials: {CRED_FILE}")
    print("=" * 60)
    print("\n  Microsoft Graph is ready for Nellie!")
    print("  The gateway will use these credentials automatically.\n")

    await ms_graph.close()


if __name__ == "__main__":
    asyncio.run(main())
