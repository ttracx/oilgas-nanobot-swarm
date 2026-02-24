"""Verify all modules import cleanly."""

import pytest


def test_core_agent():
    from nanobot.core.agent import Nanobot, AgentConfig, AgentRole, AgentTask, AgentResult
    assert AgentRole.ORCHESTRATOR.value == "orchestrator"
    assert AgentRole.CODE_PLANNER.value == "code_planner"


def test_tools():
    from nanobot.tools.base import ToolRegistry, BaseTool, ToolResult
    from nanobot.tools.web_search import WebSearchTool
    from nanobot.tools.code_runner import CodeRunnerTool
    from nanobot.tools.file_io import FileIOTool
    from nanobot.tools.http_fetch import HttpFetchTool
    from nanobot.tools.router import ToolRouter

    registry = ToolRegistry()
    registry.register(WebSearchTool())
    registry.register(CodeRunnerTool())
    registry.register(FileIOTool())
    registry.register(HttpFetchTool())

    assert len(registry.all_tools()) == 4
    assert "web_search" in registry
    assert "run_python" in registry
    assert "file_io" in registry
    assert "http_fetch" in registry

    funcs = registry.as_openai_functions()
    assert len(funcs) == 4
    assert all(f["type"] == "function" for f in funcs)


def test_roles():
    from nanobot.core.roles import L0Role, L1Role, L2Role
    assert len(L1Role) == 6
    assert len(L2Role) == 15


def test_sub_prompts():
    from nanobot.core.sub_prompts import SUB_AGENT_PROMPTS
    from nanobot.core.roles import L2Role
    assert len(SUB_AGENT_PROMPTS) == len(L2Role)


def test_agent_v2():
    from nanobot.core.agent_v2 import NanobotV2, build_default_registry
    registry = build_default_registry()
    assert len(registry.all_tools()) == 4


def test_hierarchical_swarm_import():
    from nanobot.core.hierarchical_swarm import HierarchicalSwarm
    from nanobot.core.l1_agent import L1Agent
    from nanobot.core.sub_swarm import SubSwarm


def test_gateway_import():
    from nanobot.api.gateway import app
    assert app.title == "NeuralQuantum Nanobot Swarm Gateway"
