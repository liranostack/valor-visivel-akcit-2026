"""Tracing helpers. Spans are no-ops unless an OpenTelemetry SDK is configured (AgentCore ADOT).

Attributes never contain message text (ERD, 'Observabilidade'); full instrumentation is A.04.04.
"""

from collections.abc import Iterator
from contextlib import contextmanager

from opentelemetry import trace
from opentelemetry.trace import Span

tracer = trace.get_tracer("vv_mcp")


@contextmanager
def tool_span(name: str, session_id: str | None = None) -> Iterator[Span]:
    with tracer.start_as_current_span(f"tool.{name}") as span:
        if session_id:
            span.set_attribute("session_id", session_id)
        yield span
