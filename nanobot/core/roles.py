"""
Complete role taxonomy for the hierarchical swarm.
L0 = Queen Orchestrator
L1 = Primary domain agents (spawned by queen)
L2 = Sub-agents (spawned by L1 agents)
"""

from enum import Enum


class L0Role(str, Enum):
    QUEEN = "queen"


class L1Role(str, Enum):
    CODER = "coder"
    RESEARCHER = "researcher"
    ANALYST = "analyst"
    VALIDATOR = "validator"
    EXECUTOR = "executor"
    ARCHITECT = "architect"


class L2Role(str, Enum):
    # Coder sub-swarm
    CODE_PLANNER = "code_planner"
    CODE_WRITER = "code_writer"
    CODE_TESTER = "code_tester"
    CODE_REVIEWER = "code_reviewer"
    # Researcher sub-swarm
    WEB_SEARCHER = "web_searcher"
    SYNTHESIZER = "synthesizer"
    FACT_VERIFIER = "fact_verifier"
    # Analyst sub-swarm
    REASONER = "reasoner"
    CRITIQUER = "critiquer"
    SUMMARIZER = "summarizer"
    # Validator sub-swarm
    CORRECTNESS = "correctness"
    COMPLETENESS = "completeness"
    SCORER = "scorer"
    # Executor sub-swarm
    ACTION_PLANNER = "action_planner"
    ACTION_RUNNER = "action_runner"
