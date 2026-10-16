"""LLM behind the agent: Claude through the Anthropic API, or a scripted fake for the tests.

`turn()` is a generator: it yields the text deltas while the answer streams, and returns a
`Turn` (content blocks as dicts, stop reason, usage). `agent_loop` does
`turn = yield from llm.turn(...)`. The content is kept as returned (thinking blocks
included) and sent back unchanged at the next call.

Any failure of the API (no key, network, quota, overload) raises `AgentIndisponible`: the
greenhouse does not depend on it (docs/11 §1), only the Agent tab is degraded.
"""

from collections.abc import Generator, Iterable
from dataclasses import dataclass, field

from .config import AgentConfig


class AgentIndisponible(RuntimeError):
    """The LLM cannot be reached; nothing else is affected."""


@dataclass
class Turn:
    content: list[dict]
    stop_reason: str
    usage: dict = field(default_factory=dict)  # input/output/cache_read/cache_creation
    modele: str = ""

    @property
    def tool_uses(self) -> list[dict]:
        return [b for b in self.content if b.get("type") == "tool_use"]

    @property
    def text(self) -> str:
        return "".join(b.get("text", "") for b in self.content if b.get("type") == "text")


TurnGen = Generator[str, None, Turn]


def _usage(u) -> dict:
    return dict(
        input_tokens=getattr(u, "input_tokens", 0) or 0,
        output_tokens=getattr(u, "output_tokens", 0) or 0,
        cache_read_input_tokens=getattr(u, "cache_read_input_tokens", 0) or 0,
        cache_creation_input_tokens=getattr(u, "cache_creation_input_tokens", 0) or 0,
    )


class ClaudeLLM:
    """Claude with streaming, the prompt cache (system prompt and conversation) and the
    server-side fallback when a safety classifier declines. Thinking stays adaptive (the
    default of the current models), its depth set by `effort`."""

    FALLBACK_BETA = "server-side-fallback-2026-07-01"
    JSON_RETRIES = 2

    def __init__(self, cfg: AgentConfig | None = None, client=None):
        import anthropic  # optional dependency (extra `backend`)

        self.anthropic = anthropic
        self.cfg = cfg or AgentConfig()
        self.client = client or anthropic.Anthropic()

    @property
    def modele(self) -> str:
        return self.cfg.modele

    def turn(self, system: list[dict], tools: list[dict], messages: list[dict]) -> TurnGen:
        a = self.anthropic
        kwargs = dict(
            model=self.cfg.modele,
            max_tokens=self.cfg.max_tokens,
            system=system,
            # Large inputs stream as generated; the arguments are validated by Tools.run.
            tools=[dict(t, eager_input_streaming=True) for t in tools],
            messages=messages,
            output_config={"effort": self.cfg.effort},
            cache_control={"type": "ephemeral"},  # also caches the conversation so far
        )
        if self.cfg.fallbacks:
            kwargs.update(betas=[self.FALLBACK_BETA], fallbacks="default")
        retries = 0
        while True:
            try:
                with self.client.beta.messages.stream(**kwargs) as stream:
                    for event in stream:
                        if event.type == "text":
                            yield event.text
                    final = stream.get_final_message()
                break
            except ValueError:  # tool input that is not JSON at all: re-issue the turn
                retries += 1
                if retries > self.JSON_RETRIES:
                    raise AgentIndisponible("entrée d'outil illisible") from None
            except a.AuthenticationError as e:
                raise AgentIndisponible(f"clé API refusée ({e.status_code})") from e
            except a.RateLimitError as e:
                raise AgentIndisponible("quota de l'API atteint, réessayer plus tard") from e
            except a.APIStatusError as e:
                raise AgentIndisponible(f"erreur de l'API ({e.status_code})") from e
            except a.APIConnectionError as e:
                raise AgentIndisponible("API injoignable (réseau)") from e
            except (a.AnthropicError, TypeError) as e:  # TypeError: no credentials found
                raise AgentIndisponible(str(e).splitlines()[0]) from e
        content = [b.model_dump(mode="json", exclude_none=True) for b in final.content]
        return Turn(content, final.stop_reason or "end_turn", _usage(final.usage), final.model)


class ScriptedLLM:
    """Fake LLM (CI, docs/16 §4 "client LLM factice"): plays scripted turns in order.

    Each step is a list of blocks: `"text"` (a str) or `("tool", name, input)`; a step with
    a tool call ends with `tool_use`, the others with `end_turn`. A step can also be an
    exception instance, raised to simulate an unavailable API. `calls` keeps what the agent
    sent (system, tools, messages) for the assertions.
    """

    modele = "scripted"

    def __init__(self, steps: Iterable):
        self.steps = list(steps)
        self.calls: list[dict] = []

    def turn(self, system: list[dict], tools: list[dict], messages: list[dict]) -> TurnGen:
        import copy

        self.calls.append(dict(system=system, tools=tools, messages=copy.deepcopy(messages)))
        if not self.steps:
            raise AgentIndisponible("script épuisé")
        step = self.steps.pop(0)
        if isinstance(step, BaseException):
            raise step
        content, n = [], len(self.calls)
        for i, block in enumerate(step if isinstance(step, list) else [step]):
            if isinstance(block, str):
                yield block
                content.append({"type": "text", "text": block})
            else:
                _, name, args = block
                content.append({"type": "tool_use", "id": f"toolu_{n:02d}_{i}", "name": name,
                                "input": args})  # fmt: skip
        stop = "tool_use" if any(b["type"] == "tool_use" for b in content) else "end_turn"
        usage = dict(input_tokens=1000, output_tokens=100, cache_read_input_tokens=0,
                     cache_creation_input_tokens=0)  # fmt: skip
        return Turn(content, stop, usage, self.modele)
