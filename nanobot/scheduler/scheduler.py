"""
Background Agent Scheduler — runs agent teams on cron schedules.

Inspired by Rowboat's agent-schedule pattern:
- Three schedule types: cron, interval, once
- Persistent state tracking
- Immediate trigger capability
- 60-second poll interval

Schedule config lives at ~/.nellienano/workspace/schedules.json
Schedule state persists at ~/.nellienano/workspace/.scheduler_state.json
"""

import asyncio
import json
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import structlog

from nanobot.scheduler.agent_teams import get_team, TEAM_REGISTRY, AgentTeam
from nanobot.knowledge.vault import vault
from nanobot.knowledge.graph_builder import graph_builder
from nanobot.integrations.nellie_memory_bridge import memory_bridge

log = structlog.get_logger()

WORKSPACE = Path.home() / ".nellienano" / "workspace"
SCHEDULE_FILE = WORKSPACE / "schedules.json"
STATE_FILE = WORKSPACE / ".scheduler_state.json"
OUTPUT_DIR = WORKSPACE / "scheduler_output"

POLL_INTERVAL = 60  # seconds


def _parse_cron_simple(expression: str, now: datetime) -> datetime | None:
    """
    Simple cron parser for common patterns.
    Supports: "HH:MM" (daily at time), "*/N" (every N minutes), "weekday HH:MM".
    For production, use croniter library.
    """
    expr = expression.strip()

    # "*/N" — every N minutes
    if expr.startswith("*/"):
        try:
            minutes = int(expr[2:])
            next_run = now + timedelta(minutes=minutes)
            return next_run
        except ValueError:
            pass

    # "HH:MM" — daily at specific time
    if ":" in expr and len(expr) <= 5:
        try:
            hour, minute = map(int, expr.split(":"))
            today_at = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if today_at <= now:
                today_at += timedelta(days=1)
            return today_at
        except ValueError:
            pass

    # "weekday HH:MM" — specific day of week
    weekdays = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
                "friday": 4, "saturday": 5, "sunday": 6}
    parts = expr.lower().split()
    if len(parts) == 2 and parts[0] in weekdays:
        try:
            target_day = weekdays[parts[0]]
            hour, minute = map(int, parts[1].split(":"))
            days_ahead = target_day - now.weekday()
            if days_ahead <= 0:
                days_ahead += 7
            next_run = (now + timedelta(days=days_ahead)).replace(
                hour=hour, minute=minute, second=0, microsecond=0
            )
            return next_run
        except ValueError:
            pass

    log.warning("cron_parse_failed", expression=expr)
    return None


class ScheduleEntry:
    """A single scheduled agent team run."""

    def __init__(self, data: dict):
        self.name: str = data["name"]
        self.team: str = data["team"]
        self.schedule_type: str = data.get("schedule_type", "cron")  # cron, interval, once
        self.expression: str = data.get("expression", "08:00")
        self.starting_message: str = data.get("starting_message", "")
        self.enabled: bool = data.get("enabled", True)
        self.context: dict = data.get("context", {})

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "team": self.team,
            "schedule_type": self.schedule_type,
            "expression": self.expression,
            "starting_message": self.starting_message,
            "enabled": self.enabled,
            "context": self.context,
        }


class SchedulerState:
    """Persistent scheduler state — tracks when each schedule last ran."""

    def __init__(self):
        self.states: dict[str, dict] = {}

    def load(self) -> None:
        if STATE_FILE.exists():
            self.states = json.loads(STATE_FILE.read_text(encoding="utf-8"))

    def save(self) -> None:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps(self.states, indent=2), encoding="utf-8")

    def get(self, name: str) -> dict:
        return self.states.get(name, {
            "status": "idle",
            "last_run_at": None,
            "next_run_at": None,
            "run_count": 0,
            "last_result": None,
        })

    def update(self, name: str, **kwargs) -> None:
        if name not in self.states:
            self.states[name] = {
                "status": "idle",
                "last_run_at": None,
                "next_run_at": None,
                "run_count": 0,
                "last_result": None,
            }
        self.states[name].update(kwargs)
        self.save()


class BackgroundScheduler:
    """
    Runs agent teams on cron schedules.

    Each schedule entry maps to an AgentTeam and runs at specified intervals.
    Results are persisted to the knowledge graph and scheduler output directory.
    """

    def __init__(self):
        self.schedules: list[ScheduleEntry] = []
        self.state = SchedulerState()
        self._running = False
        self._task: asyncio.Task | None = None
        self._swarm_runner = None  # Set during startup
        self._wake_event = asyncio.Event()

    def set_swarm_runner(self, runner) -> None:
        """Inject the swarm runner (called during gateway startup)."""
        self._swarm_runner = runner

    def load_schedules(self) -> None:
        """Load schedule configuration from disk."""
        if not SCHEDULE_FILE.exists():
            # Create default schedule file
            self._create_default_schedules()

        data = json.loads(SCHEDULE_FILE.read_text(encoding="utf-8"))
        self.schedules = [ScheduleEntry(s) for s in data.get("schedules", [])]
        self.state.load()

        # Calculate next_run_at for all schedules
        now = datetime.now()
        for entry in self.schedules:
            state = self.state.get(entry.name)
            if not state.get("next_run_at"):
                next_run = _parse_cron_simple(entry.expression, now)
                if next_run:
                    self.state.update(entry.name, next_run_at=next_run.isoformat())

        log.info("schedules_loaded", count=len(self.schedules))

    def _create_default_schedules(self) -> None:
        """Create default schedule configuration."""
        SCHEDULE_FILE.parent.mkdir(parents=True, exist_ok=True)
        default = {
            "schedules": [
                {
                    "name": "morning-briefing",
                    "team": "daily-briefing",
                    "schedule_type": "cron",
                    "expression": "07:30",
                    "starting_message": "Generate today's morning briefing.",
                    "enabled": False,
                },
                {
                    "name": "knowledge-maintenance",
                    "team": "knowledge-curator",
                    "schedule_type": "cron",
                    "expression": "*/120",
                    "starting_message": "Review recent activity and update the knowledge graph.",
                    "enabled": False,
                },
                {
                    "name": "weekly-project-update",
                    "team": "project-updater",
                    "schedule_type": "cron",
                    "expression": "friday 17:00",
                    "starting_message": "Generate weekly project status updates.",
                    "enabled": False,
                },
            ],
        }
        SCHEDULE_FILE.write_text(json.dumps(default, indent=2), encoding="utf-8")
        log.info("default_schedules_created", path=str(SCHEDULE_FILE))

    def start(self) -> None:
        """Start the background scheduler."""
        if self._running:
            return
        self._running = True
        self.load_schedules()
        self._task = asyncio.create_task(self._poll_loop())
        log.info("scheduler_started", schedules=len(self.schedules))

    def stop(self) -> None:
        """Stop the background scheduler."""
        self._running = False
        self._wake_event.set()
        if self._task:
            self._task.cancel()
            self._task = None
        log.info("scheduler_stopped")

    def wake(self) -> None:
        """Immediately wake the scheduler to check for pending runs."""
        self._wake_event.set()

    async def _poll_loop(self) -> None:
        """Main scheduler loop."""
        while self._running:
            try:
                await self._check_schedules()
            except Exception as e:
                log.error("scheduler_error", error=str(e))

            # Wait for poll interval or wake signal
            self._wake_event.clear()
            try:
                await asyncio.wait_for(self._wake_event.wait(), timeout=POLL_INTERVAL)
            except asyncio.TimeoutError:
                pass

    async def _check_schedules(self) -> None:
        """Check all schedules and run any that are due."""
        now = datetime.now()

        for entry in self.schedules:
            if not entry.enabled:
                continue

            state = self.state.get(entry.name)
            if state["status"] == "running":
                continue

            next_run_str = state.get("next_run_at")
            if not next_run_str:
                continue

            try:
                next_run = datetime.fromisoformat(next_run_str)
            except (ValueError, TypeError):
                continue

            if now >= next_run:
                asyncio.create_task(self._execute_schedule(entry))

    async def _execute_schedule(self, entry: ScheduleEntry) -> None:
        """Execute a scheduled agent team run."""
        log.info("schedule_executing", name=entry.name, team=entry.team)
        self.state.update(entry.name, status="running")

        team = get_team(entry.team)
        if not team:
            log.error("schedule_team_not_found", team=entry.team)
            self.state.update(entry.name, status="error", last_result="team not found")
            return

        if not self._swarm_runner:
            log.error("schedule_no_swarm_runner")
            self.state.update(entry.name, status="error", last_result="no swarm runner")
            return

        try:
            # Build the goal with context
            goal_parts = []

            if team.system_prompt:
                goal_parts.append(f"## Agent Instructions\n{team.system_prompt}")

            if team.inject_knowledge:
                index = vault.build_index()
                goal_parts.append(f"## Knowledge Graph Index\n```json\n{json.dumps(index, indent=1, default=str)[:3000]}\n```")

            if team.inject_history:
                try:
                    history = await memory_bridge.get_recent_swarm_history(5)
                    if history:
                        hist_text = "\n".join(
                            f"- [{h.get('goal', '')[:60]}] → {h.get('success_rate', 0)}% success"
                            for h in history
                        )
                        goal_parts.append(f"## Recent Swarm History\n{hist_text}")
                except Exception:
                    pass

            goal_parts.append(f"## Task\n{entry.starting_message}")

            full_goal = "\n\n".join(goal_parts)

            # Execute via swarm (inject team name for backend routing)
            run_context = {**entry.context, "_team_name": entry.team}
            result = await self._swarm_runner(full_goal, team.mode, run_context)

            # Persist result
            session_id = result.get("session_id", "unknown")
            success = result.get("success", False)
            final_answer = result.get("final_answer", "")

            # Save output
            OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
            output_file = OUTPUT_DIR / f"{entry.name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
            output_file.write_text(
                f"# {entry.name}\n"
                f"**Team:** {entry.team}\n"
                f"**Time:** {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
                f"**Session:** {session_id}\n"
                f"**Success:** {success}\n\n"
                f"---\n\n{final_answer}\n",
                encoding="utf-8",
            )

            # Auto-persist to memory bridge
            try:
                await memory_bridge.persist_swarm_result(session_id, result)
            except Exception as e:
                log.warning("schedule_persist_failed", error=str(e))

            # Update knowledge graph if team requests it
            if team.update_knowledge_after and final_answer:
                try:
                    vault.create_note(
                        "Tasks", f"{entry.name} - {datetime.now().strftime('%Y-%m-%d')}",
                        content=f"Automated run by {entry.team} team.\n\n{final_answer[:1000]}",
                        metadata={"source": "scheduler", "team": entry.team, "session": session_id[:12]},
                    )
                except Exception as e:
                    log.warning("schedule_knowledge_update_failed", error=str(e))

            # Calculate next run
            now = datetime.now()
            next_run = _parse_cron_simple(entry.expression, now)

            self.state.update(
                entry.name,
                status="idle",
                last_run_at=now.isoformat(),
                next_run_at=next_run.isoformat() if next_run else None,
                run_count=self.state.get(entry.name).get("run_count", 0) + 1,
                last_result="success" if success else "failed",
            )

            log.info("schedule_complete", name=entry.name, success=success, session=session_id[:8])

        except Exception as e:
            log.error("schedule_execution_failed", name=entry.name, error=str(e))
            now = datetime.now()
            next_run = _parse_cron_simple(entry.expression, now)
            self.state.update(
                entry.name,
                status="idle",
                last_run_at=now.isoformat(),
                next_run_at=next_run.isoformat() if next_run else None,
                last_result=f"error: {str(e)[:100]}",
            )

    async def trigger_now(self, schedule_name: str) -> dict:
        """Manually trigger a schedule to run immediately."""
        entry = next((s for s in self.schedules if s.name == schedule_name), None)
        if not entry:
            return {"error": f"Schedule '{schedule_name}' not found"}

        asyncio.create_task(self._execute_schedule(entry))
        return {"triggered": schedule_name, "team": entry.team}

    async def run_team_now(self, team_name: str, task: str, context: dict | None = None) -> dict:
        """Run an agent team immediately with a custom task (not from schedule)."""
        team = get_team(team_name)
        if not team:
            return {"error": f"Team '{team_name}' not found"}

        if not self._swarm_runner:
            return {"error": "Swarm runner not available"}

        # Build goal
        goal_parts = []
        if team.system_prompt:
            goal_parts.append(f"## Agent Instructions\n{team.system_prompt}")
        if team.inject_knowledge:
            index = vault.build_index()
            goal_parts.append(f"## Knowledge Graph Index\n```json\n{json.dumps(index, indent=1, default=str)[:3000]}\n```")
        goal_parts.append(f"## Task\n{task}")
        full_goal = "\n\n".join(goal_parts)

        run_context = {**(context or {}), "_team_name": team_name}
        result = await self._swarm_runner(full_goal, team.mode, run_context)
        return result

    def add_schedule(self, entry_data: dict) -> None:
        """Add a new schedule entry."""
        entry = ScheduleEntry(entry_data)
        self.schedules.append(entry)

        # Save to disk
        data = {"schedules": [s.to_dict() for s in self.schedules]}
        SCHEDULE_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")

        # Calculate initial next_run
        now = datetime.now()
        next_run = _parse_cron_simple(entry.expression, now)
        if next_run:
            self.state.update(entry.name, next_run_at=next_run.isoformat())

        log.info("schedule_added", name=entry.name, team=entry.team)

    def remove_schedule(self, name: str) -> bool:
        """Remove a schedule by name."""
        self.schedules = [s for s in self.schedules if s.name != name]
        data = {"schedules": [s.to_dict() for s in self.schedules]}
        SCHEDULE_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return True

    def toggle_schedule(self, name: str, enabled: bool) -> bool:
        """Enable or disable a schedule."""
        for s in self.schedules:
            if s.name == name:
                s.enabled = enabled
                data = {"schedules": [s.to_dict() for s in self.schedules]}
                SCHEDULE_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
                return True
        return False

    def get_status(self) -> dict:
        """Get full scheduler status."""
        return {
            "running": self._running,
            "schedules": [
                {
                    **entry.to_dict(),
                    "state": self.state.get(entry.name),
                }
                for entry in self.schedules
            ],
            "teams_available": list(TEAM_REGISTRY.keys()),
        }


# Singleton
scheduler = BackgroundScheduler()
