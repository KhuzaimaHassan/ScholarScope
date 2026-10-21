"""Neutral deadline resolution and display ordering; no checklist or clock access."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Literal
from zoneinfo import ZoneInfo

from scholarscope.schema import Deadline, timezone_info


@dataclass(frozen=True)
class ResolvedDeadline:
    instant_utc: datetime | None
    local_date: date | None
    precision: Literal["datetime", "date", "unresolved"]
    reason: str


def resolve(deadline: Deadline) -> ResolvedDeadline:
    """Resolve stated data, regardless of verification; never infer a time/year/zone.

    IANA gaps and overlaps use fold=0, explicitly recorded in the reason. This
    selects an interpretation, not a claim that a nonexistent local time existed.
    """
    if deadline.rolling:
        return ResolvedDeadline(None, None, "unresolved", "rolling deadline has no fixed date")
    if deadline.status == "ambiguous":
        return ResolvedDeadline(None, None, "unresolved", "ambiguous deadline; no date selected")
    if deadline.date is None:
        return ResolvedDeadline(None, None, "unresolved", "no date stated")
    local_date = date.fromisoformat(deadline.date)
    if deadline.time is None:
        return ResolvedDeadline(None, local_date, "date", "date only; no time invented")
    if deadline.timezone is None or deadline.timezone == "unknown":
        return ResolvedDeadline(None, local_date, "date", "timezone unknown; time not trusted")
    zone = timezone_info(deadline.timezone)
    assert zone is not None
    naive = datetime.fromisoformat(f"{deadline.date}T{deadline.time}")
    local = naive.replace(tzinfo=zone, fold=0)
    instant = local.astimezone(UTC)
    reason = "stated date, time and timezone"
    if (
        isinstance(zone, ZoneInfo)
        and local.utcoffset() != naive.replace(tzinfo=zone, fold=1).utcoffset()
    ):
        round_trip = instant.astimezone(zone).replace(tzinfo=None)
        if round_trip != naive:
            reason = "nonexistent local time (gap); fold=0 uses the pre-transition offset"
        else:
            reason = "ambiguous local time (overlap); fold=0 selects the first occurrence"
    return ResolvedDeadline(instant, local_date, "datetime", reason)


def compare(deadline: Deadline, now: datetime) -> Literal["past", "upcoming", "unknown"]:
    """Date precision stays upcoming throughout its calendar day, never at midnight.

    With a known source zone use that calendar. Otherwise the caller's explicit
    aware `now` supplies the reference calendar, not an inferred source timezone.
    Callers needing a source-local guarantee must provide/confirm that calendar.
    """
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    resolved = resolve(deadline)
    if resolved.precision == "unresolved":
        return "unknown"
    if resolved.instant_utc is not None:
        return "past" if resolved.instant_utc < now else "upcoming"
    assert resolved.local_date is not None
    zone = timezone_info(deadline.timezone) if deadline.timezone is not None else None
    current_date = now.astimezone(zone).date() if zone is not None else now.date()
    return "past" if current_date > resolved.local_date else "upcoming"


class OrderedDeadlines(list[Deadline]):
    """A resolved display list plus a separate, input-ordered unresolved list."""

    def __init__(self, resolved: Iterable[Deadline], unresolved: list[Deadline]) -> None:
        super().__init__(resolved)
        self.unresolved = unresolved


def ordered(deadlines: Iterable[Deadline]) -> OrderedDeadlines:
    """Order UTC instants/date buckets, keeping unresolved deadlines separately.

    Date-only entries precede timed entries in the same nominal date bucket; this
    is display order, NOT an invented midnight or an absolute cross-zone claim.
    Equal sort keys are stable. Resolution never promotes verification/usability.
    """
    resolved: list[tuple[tuple[int, int, int, int], Deadline]] = []
    unresolved: list[Deadline] = []
    for deadline in deadlines:
        result = resolve(deadline)
        if result.precision == "unresolved":
            unresolved.append(deadline)
        elif result.instant_utc is not None:
            instant = result.instant_utc
            resolved.append(
                (
                    (
                        instant.date().toordinal(),
                        1,
                        instant.hour * 3600 + instant.minute * 60 + instant.second,
                        instant.microsecond,
                    ),
                    deadline,
                )
            )
        else:
            assert result.local_date is not None
            resolved.append(((result.local_date.toordinal(), 0, 0, 0), deadline))
    return OrderedDeadlines((d for _, d in sorted(resolved, key=lambda pair: pair[0])), unresolved)
