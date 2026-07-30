"""Turn a typed request for a new row into a definition the app can build.

This is a **local, rule-based reader**, not a language model. Nothing is sent
anywhere: the whole point of the app is that a day's sensor data stays on this
machine, and shipping the prompt plus a catalogue of someone's health streams to
an API to save writing a parser would be a poor trade.

What that buys, besides privacy, is that the reader can be honest. It grounds
every match in the streams the day *actually* has, and reports back exactly what
it understood before anything is created — so a misreading is visible in the
preview rather than discovered later as a row full of the wrong data. When it
cannot read a request it says so and lists what it does know.

The connected assistant can create rows too, through the `add_timeline_row` MCP
tool, which is where full natural-language understanding belongs.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from ..models.timeline import DayTimeline, Lane, TimelineSeries

#: Words that mean "greater than", and words that mean "less than".
ABOVE = ("above", "over", "greater than", "more than", "higher than", "exceeds", ">")
BELOW = ("below", "under", "less than", "lower than", "beneath", "<")

#: Extra ways of naming a stream beyond its own label and id.
SYNONYMS: dict[str, tuple[str, ...]] = {
    "heart_rate": ("heart rate", "heartrate", "hr", "pulse", "bpm", "cardiac"),
    "activity": ("steps", "step", "walking", "movement", "exercise", "workout", "activity"),
    "sleep": ("sleep", "asleep", "napping", "nap", "bed"),
    "hrv": ("hrv", "heart rate variability", "variability", "rmssd"),
    "readiness": ("readiness", "recovery", "body battery", "training readiness"),
    "temperature": ("skin temperature", "wrist temperature", "body temperature"),
    "environment": ("light", "illuminance", "brightness", "room temperature", "ambient"),
    "presence": ("presence", "home", "away", "motion", "occupancy", "device use", "phone use"),
    "location": ("location", "place", "where", "zone", "town"),
}


@dataclass
class LaneSpec:
    """A custom row, resolved against real streams."""

    label: str
    prompt: str
    lane_id: str
    """Which lane the data comes from."""
    series_id: str | None = None
    comparator: str | None = None
    threshold: float | None = None
    unit: str | None = None
    accent: str = "indigo"

    @property
    def mode(self) -> str:
        if self.series_id and self.comparator:
            return "intervals"
        if self.series_id:
            return "series"
        return "events"

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "prompt": self.prompt,
            "laneId": self.lane_id,
            "seriesId": self.series_id,
            "comparator": self.comparator,
            "threshold": self.threshold,
            "unit": self.unit,
            "accent": self.accent,
            "mode": self.mode,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LaneSpec:
        return cls(
            label=data["label"],
            prompt=data.get("prompt", ""),
            lane_id=data["laneId"],
            series_id=data.get("seriesId"),
            comparator=data.get("comparator"),
            threshold=data.get("threshold"),
            unit=data.get("unit"),
            accent=data.get("accent", "indigo"),
        )


@dataclass
class Interpretation:
    understood: bool
    summary: str
    """What the reader believes was asked for, in plain words."""
    spec: LaneSpec | None = None
    problem: str | None = None
    known: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "understood": self.understood,
            "summary": self.summary,
            "spec": self.spec.to_dict() if self.spec else None,
            "problem": self.problem,
            "known": self.known,
        }


def _candidates(timeline: DayTimeline) -> list[tuple[str, Lane, TimelineSeries | None]]:
    """Every phrase that could name a stream, including ones with no data today.

    Lanes the day has nothing for are deliberately still candidates. Skipping
    them lets a request for "heart rate variability" fall through to whichever
    *available* stream happens to be a substring of it — "heart rate" — and
    quietly build the wrong row. Better to match it and then say the day has no
    data for it.
    """
    found: list[tuple[str, Lane, TimelineSeries | None]] = []
    for lane in timeline.lanes:
        # The lane's own numeric series, when it has one. Naming a lane resolves
        # to it so "heart rate above 100" has something to threshold against;
        # a lane with no series (sleep, presence) resolves to its events.
        primary = lane.series[0] if lane.series else None

        for series in lane.series:
            for phrase in (series.label, series.id.replace("series_", "").replace("_", " ")):
                if phrase:
                    found.append((phrase.lower(), lane, series))
        for phrase in (lane.label, lane.id.replace("_", " ")):
            if phrase:
                found.append((phrase.lower(), lane, primary))
        for word in SYNONYMS.get(lane.id, ()):
            found.append((word, lane, primary))
    # Longest phrases first: "heart rate variability" must beat "heart rate".
    return sorted(found, key=lambda item: len(item[0]), reverse=True)


def _match_source(
    text: str, timeline: DayTimeline
) -> tuple[Lane, TimelineSeries | None] | None:
    for phrase, lane, series in _candidates(timeline):
        if phrase and phrase in text:
            return lane, series
    return None


def _match_threshold(text: str) -> tuple[str | None, float | None]:
    """A comparator and a number, if the request carries one."""
    for words, name in ((ABOVE, "above"), (BELOW, "below")):
        for word in words:
            pattern = re.escape(word) + r"\s*(-?\d+(?:\.\d+)?)"
            found = re.search(pattern, text)
            if found:
                return name, float(found.group(1))
    return None, None


def _describe(lane: Lane, series: TimelineSeries | None, comparator, threshold) -> str:
    what = series.label if series else lane.label
    if comparator and threshold is not None:
        unit = f" {series.unit}" if series and series.unit else ""
        return f"{what} {comparator} {threshold:g}{unit}"
    if series:
        return f"{what}, as recorded"
    return f"{lane.label} events"


def interpret(prompt: str, timeline: DayTimeline | None) -> Interpretation:
    """Read a request for a new row against the streams a day actually has."""
    text = " ".join(prompt.lower().split())
    if not text:
        return Interpretation(False, "", problem="Describe the row you want.")

    if timeline is None:
        return Interpretation(
            False,
            "",
            problem=(
                "This day has not been reconstructed yet, so there are no streams to "
                "build a row from."
            ),
        )

    known = sorted(
        {
            series.label
            for lane in timeline.lanes
            if lane.available
            for series in lane.series
        }
        | {lane.label for lane in timeline.lanes if lane.available}
    )

    source = _match_source(text, timeline)
    if source is None:
        return Interpretation(
            False,
            "",
            problem=(
                "No stream in this day matches that. Name one of the streams below, "
                "optionally with a threshold — for example “heart rate above 100”."
            ),
            known=known,
        )

    lane, series = source
    if not lane.available:
        return Interpretation(
            False,
            "",
            problem=(
                f"{lane.label} has no data on {timeline.date}, so there is nothing to "
                "build a row from. Pick a day where it recorded something, or name "
                "another stream."
            ),
            known=known,
        )

    comparator, threshold = _match_threshold(text)
    if comparator and series is None:
        return Interpretation(
            False,
            "",
            problem=(
                f"{lane.label} has no numeric series on this day, so it cannot be "
                "compared against a threshold. Ask for its events instead."
            ),
            known=known,
        )

    summary = _describe(lane, series, comparator, threshold)
    # The resolved description makes a better row label than the raw request:
    # it is already capitalised, carries the unit, and shows what was understood.
    label = summary

    return Interpretation(
        understood=True,
        summary=summary,
        spec=LaneSpec(
            label=label,
            prompt=prompt.strip(),
            lane_id=lane.id,
            series_id=series.id if series else None,
            comparator=comparator,
            threshold=threshold,
            unit=series.unit if series else None,
        ),
        known=known,
    )
