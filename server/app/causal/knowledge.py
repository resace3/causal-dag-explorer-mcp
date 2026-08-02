"""Candidate causal edges among the phenotypes this app tracks.

This is a **prior**, not a finding. Every edge here comes from published
physiology and behaviour, not from the user's data — the app has never
estimated any of it. The DAG view exists to make assumptions explicit *before*
an analysis, which is what a DAG is for.

Three things keep it honest:

* Every edge carries a `rationale` and a `strength` label, so a speculative
  arrow is never displayed like an established one.
* Unmeasured variables (stress, alcohol, illness, work schedule) are first-class
  nodes. Leaving them out is how a DAG quietly lies about confounding.
* Nothing here is fitted, tested or scored against observed data.

Editing this file changes the hypotheses the app proposes. It is meant to be
edited — a personal causal model should be personal.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Strength = Literal["established", "plausible", "speculative"]


@dataclass(frozen=True)
class Variable:
    """A node in the causal graph."""

    id: str
    label: str
    description: str
    #: Lane this variable is observed through, when it is observed at all.
    lane: str | None = None
    measured: bool = True
    unit: str | None = None

    @property
    def kind(self) -> str:
        return "measured" if self.measured else "unmeasured"


@dataclass(frozen=True)
class CausalEdge:
    """A hypothesised direct cause. Never an estimate."""

    source: str
    target: str
    rationale: str
    strength: Strength = "plausible"
    lag: str | None = None
    """Roughly how long the effect is expected to take, when known."""

    origin: Literal["knowledge_base", "user"] = "knowledge_base"
    """Who proposed this arrow. The published priors and the user's own
    additions are both hypotheses, but conflating them would hide which is
    which — so the distinction is carried all the way to the drawing."""


VARIABLES: dict[str, Variable] = {
    variable.id: variable
    for variable in [
        # --- measured, and drawn on the timeline -------------------------
        Variable(
            "exercise",
            "Exercise",
            "Recorded workout sessions and sustained activity.",
            lane="activity",
            unit="min",
        ),
        Variable(
            "step_count",
            "Step count",
            "Daily accumulated steps and their rate.",
            lane="activity",
            unit="steps",
        ),
        Variable(
            "sleep_duration",
            "Sleep duration",
            "Time asleep in the main sleep period.",
            lane="sleep",
            unit="min",
        ),
        # Both were observed through the sleep lane until that row became a
        # duration row. They stay in the model as unmeasured: the arrows into
        # them are still the assumptions an analysis of sleep would rest on,
        # and deleting them would quietly turn "we do not measure this" into
        # "this does not matter". Restoring either means grounding it again in
        # a row that actually reports it.
        Variable(
            "sleep_onset",
            "Sleep onset time",
            "The clock time sleep began. Not measured: the sleep row reports how "
            "long each period lasted, not when it started.",
            measured=False,
        ),
        Variable(
            "sleep_efficiency",
            "Sleep efficiency",
            "Proportion of time in bed spent asleep. Not measured: the sleep row "
            "reports duration only.",
            measured=False,
            unit="%",
        ),
        Variable(
            "resting_heart_rate",
            "Resting heart rate",
            "Heart rate at rest, typically overnight.",
            lane="heart_rate",
            unit="bpm",
        ),
        Variable(
            "hrv",
            "Heart rate variability",
            "Beat-to-beat variation, usually an overnight average.",
            lane="hrv",
            unit="ms",
        ),
        Variable(
            "readiness",
            "Physiological readiness",
            "The provider's composite recovery score.",
            lane="readiness",
        ),
        Variable(
            "light_evening",
            "Evening light exposure",
            "Measured illuminance in the hours before sleep.",
            lane="environment",
            unit="lx",
        ),
        Variable(
            "light_morning",
            "Morning light exposure",
            "Measured illuminance after waking.",
            lane="environment",
            unit="lx",
        ),
        Variable(
            "room_temperature",
            "Room temperature",
            "Ambient temperature where the user sleeps.",
            lane="environment",
            unit="°F",
        ),
        Variable(
            "skin_temperature",
            "Skin temperature",
            "Wrist skin temperature from the wearable.",
            lane="temperature",
            unit="°F",
        ),
        Variable(
            "device_use",
            "Phone use",
            "Screen-on sessions reported by the phone.",
            lane="phone_use",
            unit="min",
        ),
        Variable(
            "tiktok",
            "TikTok",
            "Time in one named app, from the phone's last-used-app sensor. A "
            "subset of phone use rather than a quantity independent of it: "
            "conditioning on both asks the data a question it cannot answer.",
            lane="tiktok",
            unit="min",
        ),
        Variable(
            "computer_use",
            "Computer use",
            "Stretches at this machine, from the idle and focus watchers.",
            lane="computer_use",
            unit="min",
        ),
        Variable(
            "time_away",
            "Time away from home",
            "Periods the presence sensor reported not-home.",
            lane="presence",
            unit="min",
        ),
        Variable(
            "location",
            "Location",
            "Which place the day was spent in.",
            lane="location",
        ),
        # --- unmeasured, but causally important --------------------------
        Variable(
            "circadian_phase",
            "Circadian phase",
            "Internal clock timing. Not measured directly by any connected source.",
            measured=False,
        ),
        Variable(
            "stress",
            "Psychological stress",
            "Not measured. No connected source reports it, and heart rate is not "
            "a substitute for it.",
            measured=False,
        ),
        Variable(
            "alcohol",
            "Alcohol intake",
            "Not measured by any connected source.",
            measured=False,
        ),
        Variable(
            "caffeine",
            "Caffeine intake",
            "Not measured by any connected source.",
            measured=False,
        ),
        Variable(
            "illness",
            "Acute illness",
            "Not measured. Affects several signals at once, so ignoring it can "
            "manufacture associations between them.",
            measured=False,
        ),
        Variable(
            "work_schedule",
            "Work schedule",
            "Not measured. Drives both when the day starts and what is done in it.",
            measured=False,
        ),
        Variable(
            "day_of_week",
            "Day of week",
            "Known from the calendar; a common cause of routine.",
            measured=True,
        ),
    ]
}


EDGES: list[CausalEdge] = [
    # Circadian and light
    CausalEdge(
        "light_evening",
        "circadian_phase",
        "Evening light suppresses melatonin and delays circadian phase.",
        "established",
        lag="same evening",
    ),
    CausalEdge(
        "light_morning",
        "circadian_phase",
        "Morning light advances circadian phase.",
        "established",
        lag="same morning",
    ),
    CausalEdge(
        "circadian_phase",
        "sleep_onset",
        "Circadian phase sets when sleep pressure and the clock permit sleep.",
        "established",
    ),
    CausalEdge(
        "device_use",
        "light_evening",
        "A lit screen contributes to evening light exposure.",
        "plausible",
    ),
    CausalEdge(
        "device_use",
        "sleep_onset",
        "Engagement with a device delays going to bed, beyond its light.",
        "plausible",
    ),
    # The same two claims as the phone above. Asserting that a lit phone delays
    # sleep while a lit monitor does not would be an asymmetry the evidence does
    # not support; both are here at the same strength, and either can be removed
    # from the ledger under the graph.
    CausalEdge(
        "computer_use",
        "light_evening",
        "A lit monitor contributes to evening light exposure.",
        "plausible",
    ),
    CausalEdge(
        "computer_use",
        "sleep_onset",
        "Working or reading at a computer delays going to bed, beyond its light.",
        "plausible",
    ),
    # The tracked app is a *part* of phone use, so no arrow runs between the
    # two: an arrow would claim one causes the other when one simply contains
    # the other. What it gets is its own version of the phone's two claims, on
    # the reasoning that an endless feed and a phone call are not the same
    # fifteen minutes. Both are hypotheses; neither has been tested here.
    CausalEdge(
        "tiktok",
        "sleep_onset",
        "A feed with no end delays putting the phone down, beyond screen time "
        "in general.",
        "speculative",
    ),
    CausalEdge(
        "tiktok",
        "light_evening",
        "A lit screen held close contributes to evening light exposure.",
        "plausible",
    ),
    # Sleep structure
    CausalEdge(
        "sleep_onset",
        "sleep_duration",
        "A later start compresses sleep against a fixed wake time.",
        "established",
    ),
    CausalEdge(
        "room_temperature",
        "sleep_efficiency",
        "Thermal comfort affects awakenings and time to fall asleep.",
        "established",
    ),
    CausalEdge(
        "sleep_efficiency",
        "sleep_duration",
        "Fragmented sleep yields less total sleep for the same time in bed.",
        "established",
    ),
    CausalEdge(
        "alcohol",
        "sleep_efficiency",
        "Alcohol shortens sleep latency but fragments the second half of the night.",
        "established",
    ),
    CausalEdge("caffeine", "sleep_onset", "Adenosine antagonism delays sleep onset.", "established"),
    CausalEdge("stress", "sleep_onset", "Arousal at bedtime delays sleep onset.", "plausible"),
    # Autonomic
    CausalEdge(
        "sleep_duration",
        "hrv",
        "Short sleep is associated with lower overnight parasympathetic tone.",
        "plausible",
        lag="same night",
    ),
    CausalEdge(
        "sleep_duration",
        "resting_heart_rate",
        "Short or fragmented sleep raises overnight heart rate.",
        "plausible",
        lag="same night",
    ),
    CausalEdge("alcohol", "hrv", "Alcohol lowers overnight HRV.", "established", lag="same night"),
    CausalEdge(
        "alcohol",
        "resting_heart_rate",
        "Alcohol raises overnight heart rate.",
        "established",
        lag="same night",
    ),
    CausalEdge("stress", "hrv", "Sympathetic activation lowers HRV.", "established"),
    CausalEdge("stress", "resting_heart_rate", "Sympathetic activation raises heart rate.", "established"),
    CausalEdge(
        "illness",
        "resting_heart_rate",
        "Infection raises resting heart rate, often before symptoms.",
        "established",
    ),
    CausalEdge("illness", "hrv", "Immune activation lowers HRV.", "established"),
    CausalEdge("illness", "skin_temperature", "Fever raises skin temperature.", "established"),
    CausalEdge("illness", "exercise", "Feeling unwell reduces training.", "plausible"),
    # Exercise
    CausalEdge(
        "exercise",
        "resting_heart_rate",
        "Acutely raises heart rate; chronically lowers resting heart rate.",
        "established",
        lag="hours acutely, weeks chronically",
    ),
    CausalEdge(
        "exercise",
        "hrv",
        "Hard sessions suppress HRV that night; training raises it over weeks.",
        "plausible",
        lag="same night",
    ),
    CausalEdge(
        "exercise",
        "sleep_duration",
        "Exercise increases sleep pressure, though evidence in adults is mixed.",
        "speculative",
        lag="same night",
    ),
    CausalEdge("exercise", "skin_temperature", "Exertion raises skin temperature.", "established"),
    CausalEdge("exercise", "step_count", "Most exercise adds steps.", "established"),
    CausalEdge(
        "time_away",
        "step_count",
        "Being out of the house usually means walking.",
        "plausible",
    ),
    CausalEdge(
        "time_away",
        "light_morning",
        "Outdoor light is orders of magnitude brighter than indoor light.",
        "established",
    ),
    CausalEdge("location", "time_away", "Where the day is spent determines time out of the house.", "plausible"),
    # Readiness is a vendor composite of the autonomic signals
    CausalEdge(
        "hrv",
        "readiness",
        "HRV is an explicit input to vendor readiness scores.",
        "established",
    ),
    CausalEdge(
        "resting_heart_rate",
        "readiness",
        "Resting heart rate is an explicit input to vendor readiness scores.",
        "established",
    ),
    CausalEdge(
        "sleep_duration",
        "readiness",
        "Prior sleep is an explicit input to vendor readiness scores.",
        "established",
    ),
    # Routine
    CausalEdge("day_of_week", "work_schedule", "Weekdays and weekends differ.", "established"),
    CausalEdge("work_schedule", "sleep_onset", "Work timing sets bedtime and wake time.", "plausible"),
    CausalEdge("work_schedule", "exercise", "Available time shapes whether training happens.", "plausible"),
    CausalEdge("work_schedule", "time_away", "Commuting and work location drive time away.", "plausible"),
    CausalEdge("room_temperature", "skin_temperature", "Ambient temperature affects skin temperature.", "established"),
]


@dataclass
class Graph:
    """Adjacency helpers over the knowledge base."""

    edges: list[CausalEdge] = field(default_factory=lambda: list(EDGES))

    def parents(self, node: str) -> list[str]:
        return [edge.source for edge in self.edges if edge.target == node]

    def children(self, node: str) -> list[str]:
        return [edge.target for edge in self.edges if edge.source == node]

    def ancestors(self, node: str, depth: int = 6) -> set[str]:
        seen: set[str] = set()
        frontier = [(node, 0)]
        while frontier:
            current, level = frontier.pop()
            if level >= depth:
                continue
            for parent in self.parents(current):
                if parent not in seen:
                    seen.add(parent)
                    frontier.append((parent, level + 1))
        return seen

    def descendants(self, node: str, depth: int = 6) -> set[str]:
        seen: set[str] = set()
        frontier = [(node, 0)]
        while frontier:
            current, level = frontier.pop()
            if level >= depth:
                continue
            for child in self.children(current):
                if child not in seen:
                    seen.add(child)
                    frontier.append((child, level + 1))
        return seen

    def directed_paths(self, start: str, end: str, limit: int = 200) -> list[list[str]]:
        """Every directed path from `start` to `end` (the graph is small)."""
        paths: list[list[str]] = []

        def walk(node: str, trail: list[str]) -> None:
            if len(paths) >= limit:
                return
            if node == end:
                paths.append(list(trail))
                return
            for child in self.children(node):
                if child in trail:
                    continue  # the knowledge base is acyclic; guard anyway
                walk(child, [*trail, child])

        walk(start, [start])
        return paths


def variable(node_id: str) -> Variable:
    return VARIABLES.get(
        node_id,
        Variable(node_id, node_id.replace("_", " ").title(), "Unknown variable."),
    )
