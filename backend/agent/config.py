"""Settings of the agent (docs/11 §2, §4.8), from the environment of the backend.

- `SERREIA_AGENT_MODEL`: `claude-sonnet-5-5` by default, `claude-opus-5-5` for long analyses;
- `SERREIA_AGENT_EFFORT`: low | medium | high (default medium: chat with a few tool calls);
- `SERREIA_AGENT_TOKENS_CONVERSATION` / `SERREIA_AGENT_TOKENS_JOUR`: budgets, counted on the
  tokens logged in `agent_journal` (input + output, cache included).
"""

import os
from dataclasses import dataclass, field

DEFAULT_MODEL = "claude-sonnet-5-5"


def _env_int(name: str, default: int) -> int:
    return int(os.environ.get(name, default))


@dataclass(frozen=True)
class AgentConfig:
    modele: str = field(
        default_factory=lambda: os.environ.get("SERREIA_AGENT_MODEL", DEFAULT_MODEL)
    )
    effort: str = field(default_factory=lambda: os.environ.get("SERREIA_AGENT_EFFORT", "medium"))
    max_tokens: int = 16000  # one answer
    max_tours: int = 12  # API calls for one user message (tool loop)
    tokens_conversation: int = field(
        default_factory=lambda: _env_int("SERREIA_AGENT_TOKENS_CONVERSATION", 400_000)
    )
    tokens_jour: int = field(
        default_factory=lambda: _env_int("SERREIA_AGENT_TOKENS_JOUR", 3_000_000)
    )
    expiration_s: float = 7200.0  # a proposal not validated expires (docs/11 §4.5)
    # Actuators without `duree_max_s` (ventilation, LED, heating): longest proposal.
    duree_max_defaut_s: float = 4 * 3600.0
    max_points: int = 500  # get_mesures: series downsampled to this many points
    # Server-side fallback when a safety classifier declines (Claude API only).
    fallbacks: bool = True
