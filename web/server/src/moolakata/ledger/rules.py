"""Categorisation and payee rules (requirements S2.7): which rule a transaction matches, first
match wins, and what checking a rule's pattern refuses. No tables here: the rules and the
transactions come in as plain objects."""

import re
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

import re2

MAX_PATTERN = 200
MAX_TAGS = 10
# RE2 matches in time linear in the payee, whatever the pattern: no pattern a user saves can
# hold the server (CR3-25). It has no back-references or look-arounds, which need backtracking.
_OPTIONS = re2.Options()
_OPTIONS.case_sensitive = False
_OPTIONS.log_errors = False
# RE2's refusals of what Python's syntax has and RE2's hasn't: a look-around, a back-reference.
_BACKTRACKING = re.compile(r"invalid perl operator: \(\?<?[=!]|invalid escape sequence: \\[1-9]")


class Invalid(ValueError):
    """A rule that can't be kept; the message says why, for its field."""


@dataclass(frozen=True)
class Matcher:
    payeeMatch: str
    amountMin: Decimal | None = None
    amountMax: Decimal | None = None
    direction: str = "any"  # any, in, out
    accountId: str | None = None
    _regex: Any = field(default=None, compare=False)  # an RE2 pattern


def compile_pattern(text: str) -> Any:
    """A rule's payee pattern: None for plain text, else its regular expression in RE2's
    syntax. Refused when it is empty, too long or doesn't compile."""
    t = text.strip()
    if not t or len(t) > MAX_PATTERN:
        raise Invalid(f"Some text of the payee, at most {MAX_PATTERN} characters.")
    if not t.lower().startswith("re:"):
        return None
    body = t[3:].strip()
    if not body:
        raise Invalid("A regular expression after re:, such as re:^AMZN.")
    try:
        return re2.compile(body, _OPTIONS)
    except re2.error as e:
        raise Invalid(_refusal(e)) from None


def _refusal(e: Exception) -> str:
    why = e.args[0] if e.args else ""
    why = why.decode(errors="replace") if isinstance(why, bytes) else str(why)
    if _BACKTRACKING.search(why):
        return "RE2 has no look-arounds or back-references."
    return f"Not a regular expression: {why}."


def matcher(rule) -> Matcher:
    return Matcher(
        rule.payeeMatch,
        rule.amountMin,
        rule.amountMax,
        rule.direction,
        rule.accountId,
        compile_pattern(rule.payeeMatch),
    )


def matches(m: Matcher, payee: str | None, amount: Decimal, account_id: str) -> bool:
    if m.accountId and m.accountId != account_id:
        return False
    if (m.direction == "in" and amount <= 0) or (m.direction == "out" and amount >= 0):
        return False
    size = abs(amount)
    if m.amountMin is not None and size < m.amountMin:
        return False
    if m.amountMax is not None and size > m.amountMax:
        return False
    text = (payee or "")[:500]
    if m._regex is not None:
        return m._regex.search(text) is not None
    return m.payeeMatch.strip().lower() in text.lower()


def first_match(rules: list, matchers: list[Matcher], payee, amount, account_id):
    """The first rule, in order, that the transaction matches; None when none does."""
    for rule, m in zip(rules, matchers, strict=True):
        if matches(m, payee, amount, account_id):
            return rule
    return None
