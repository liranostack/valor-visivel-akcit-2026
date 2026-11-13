"""Voice guide rules that can be enforced in code (leader's 'Guia de tom de voz', A.06.13).

The guide asks never to use the long dash: rewrite with commas or full stops. The prompts say so;
this is the safety net for what the model still writes. Everything else in the guide (clichés,
"não é X, é Y", ritmo) is judged in context, by the prompts and the conversation judge, never by
word lists.
"""

import re

_LEADING = re.compile(r"^\s*—\s*")
_TRAILING = re.compile(r"\s*—\s*$")
_INNER = re.compile(r"\s*,?\s*—\s*")


def no_em_dash(text: str) -> str:
    """Replace the long dash (—) with a comma; drop it at the start or end of a line. The en dash
    in ranges ("3–4") is a different character and stays."""
    if "—" not in text:
        return text
    lines = []
    for line in text.split("\n"):
        line = _LEADING.sub("", line)
        line = _TRAILING.sub("", line)
        lines.append(_INNER.sub(", ", line))
    return "\n".join(lines)


def one_question(text: str) -> str:
    """vv rule (enforceSingleBoldQuestion): the message asks exactly one thing and ends in "?".

    Keeps the text up to the first question mark, so a second question or a trailing instruction
    ("Me conta a última vez…") is dropped; a question written without "?" gets one.
    """
    text = text.strip()
    if "?" in text:
        return text[: text.index("?") + 1]
    return text.rstrip(".!:; ") + "?"
