# Yesterday Timeline

An MCP server that reconstructs a local calendar day from Home Assistant and
wearable data, and serves it as an hour-by-hour swimlane timeline on localhost.

It opens on today, so far. A calendar in the sidebar picks any earlier day,
which is fetched and processed on demand.

The page answers one question — *what actually happened on this day, and how do
I know?* — and every mark on it is clickable down to the raw sensor records
behind it.

![The Yesterday page with mock data](docs/screenshot-mock.png)

<details>
<summary>More screenshots</summary>

**Live Home Assistant data.** Four lanes have data; the other four hide
themselves and say why. The hatched band is a 450-minute stretch where the step
counter stopped reporting — drawn as missing rather than smoothed over.

![The same page against a live Home Assistant instance](docs/screenshot-home-assistant.png)

**Details panel.** Every mark opens its full provenance: which rule produced it,
at which version, with which thresholds, from which raw records.

![The details panel showing provenance for a sleep interval](docs/screenshot-details.png)

**Collapsed mode.** The major events of the day on one line — and nothing else.
No arrows, no connections, no implied causality.

![Collapsed mode showing major events only](docs/screenshot-collapsed.png)

**DAG mode.** The same day, with the causal structure you would have to assume
to ask whether exercise affected sleep — placed on the day's own clock. The
nodes are real recorded moments; the arrows are assumptions, and the ones the
day could not place are listed rather than dropped.

![The DAG tab showing a time-anchored causal graph](docs/screenshot-dag.png)

</details>

> **This version does not do causal inference.** It visualizes timing and makes
> the day inspectable. It will say "the evening run ended 4.6 hours before the
> recorded sleep onset"; it will never say the run *caused* anything. See
> [No causal claims](#no-causal-claims).

---

## Contents

- [What it does](#what-it-does)
- [Choosing a day](#choosing-a-day)
- [Adding your own row](#adding-your-own-row)
- [The DAG tab](#the-dag-tab)
- [Quick start (mock data)](#quick-start-mock-data)
- [Architecture](#architecture)
- [Connecting Home Assistant](#connecting-home-assistant)
- [Connecting ActivityWatch](#connecting-activitywatch)
- [Wearable providers](#wearable-providers)
- [MCP client configuration](#mcp-client-configuration)
- [MCP tools](#mcp-tools)
- [Environment variables](#environment-variables)
- [Starting it automatically at login](#starting-it-automatically-at-login)
- [Developer commands](#developer-commands)
- [Testing](#testing)
- [Where to change things](#where-to-change-things)
- [Privacy model](#privacy-model)
- [No causal claims](#no-causal-claims)
- [Troubleshooting](#troubleshooting)
- [Known limitations](#known-limitations)
- [Future causal-analysis extension points](#future-causal-analysis-extension-points)

---

## What it does

1. **Collects** the previous local calendar day from Home Assistant's history
   API and a wearable provider.
2. **Normalizes** it — unit cleanup, de-duplication, state intervals, counter
   resets, explicit outages.
3. **Engineers interpretable features** with configurable thresholds, each
   carrying full provenance.
4. **Visualizes** the day as aligned swimlanes on one shared time axis.
5. **Makes every event inspectable**, down to the raw records that produced it.

Nothing is invented. A lane with no data hides itself and says why; a stream
that stopped reporting is drawn as a hatched gap rather than a smooth line.

### Arranging the rows

Each row has a handle on hover: drag it, or use the up/down buttons beside it,
and the order is remembered. Hovering also reveals a **×** on the right of the
row, which hides that lane; it stays restorable from *Visible data streams*,
which is what the title on the control says, because a bare × otherwise reads
as deleting the data. The saved order is a list of lane ids and is
routinely stale in both directions — a lane vanishes on a day with no data for
it, and a new one appears when a source starts reporting — so a lane that
disappears today and returns tomorrow comes back where you left it, and a lane
you have never arranged joins at the bottom rather than jumping to the top.

**Which rows are hidden is remembered too**, along with which tab you were on
and the collapsed view's own switches — all on the same terms as the order: they
are arrangements of your own view rather than anything derived from the data.
They also **follow you between tabs**. This page opens automatically at login
and tends to be left open, so two tabs at once is the normal case — and an older
tab holding a stale arrangement would otherwise write it back over what you just
did in the newer one.

**Hiding a row removes it from all three tabs.** It loses its switch in
Collapsed rather than merely being switched off there, and it loses its row in
the DAG. Removed means removed; offering to bring it back on another tab would
be offering something already declined.

The rows on Expanded are therefore the single answer to "which streams does this
day have?", and the other two tabs read it rather than each deciding for
themselves. One consequence: you cannot draw a DAG arrow to a variable whose
lane you have hidden. Restore the row from *Visible data streams* to reach it
again.

### The lanes

| Lane | What it shows | Source |
| --- | --- | --- |
| Activity | Workout sessions, and step rate derived from a cumulative counter | Wearable records, or a Home Assistant step sensor |
| Heart Rate | Continuous heart rate, or a once-a-day resting value when that is all a source publishes | Wearable |
| Heart Rate Variability | One nightly value, attached to the sleep period it summarises | Wearable |
| Physiological Readiness | The provider's own composite score — never relabelled "energy" | Wearable |
| Sleep Duration | How long each sleep period lasted — main sleep and naps, one bar each | Google Health, or bed-occupancy as a documented fallback |
| Skin / Wrist Temperature | Wearable temperature, labelled with the actual measurement | Wearable |
| Environment | Light-condition blocks derived from measured illuminance, plus a room-temperature sub-line | Home Assistant |
| Presence & Motion | Home/away, arrivals and departures, motion, door openings | Home Assistant |
| Computer Use | Stretches at this machine, which application had focus, and which site a browser tab was on | ActivityWatch |
| Phone Use | Screen-on stretches, and which app was in front during them | Home Assistant |
| TikTok | Spells in one named app, followed on its own row | Home Assistant |
| Phone Location | The zone a device tracker reported, and the town it geocoded to | Home Assistant |

### Data sources are MCP servers

Every row in the **MCPs** panel is an MCP integration you configured — not an
internal abstraction. Each row names the server and states how it is reached, so
the route is never implied:

| Row | MCP server | How it is read |
| --- | --- | --- |
| Home Assistant | `ha-mcp` | Its REST API (faster than proxying history through the MCP server) |
| Garmin | `garmin` | The MCP server itself, read-only `get_*` tools only |
| ActivityWatch | `activitywatch` | The same local REST API that MCP server wraps — see [Connecting ActivityWatch](#connecting-activitywatch) |
| Google Health | `google-health` | The MCP server itself, read-only tools only. Supplies sleep and nothing else |

Leave `command` unset under `mcp.servers` and the timeline reuses the server
definition already in your MCP client's configuration, so credentials live in
one place.

**Reading from** in that panel chooses which of them to use, and in what order.
It is a ranked list rather than a set of checkboxes because the order is the
merge priority: when two sources both offer a metric, the one higher in the list
supplies it. Metrics are never blended, so a heart-rate line always comes from a
single device rather than being stitched together from two.

Two consequences worth knowing:

- **A source switched off is not contacted at all** — not even probed for
  status. The panel says "switched off" rather than reporting a connection that
  was never attempted, and switching Home Assistant off leaves its lanes empty
  with that as the stated reason.
- **The selection is stored, not written back to `config.yaml`.** That file
  stays the declared baseline, so clearing the selection returns the app to
  exactly what the configuration says. A source you later remove from the config
  is dropped from a stored selection rather than lingering in it.

Mock mode ignores the picker entirely — `USE_MOCK_DATA` forces the mock
provider, and a mock row is never reported as switched off by a switch that does
not govern it.

**Only read-only tools are ever called.** The Garmin MCP also exposes tools that
create workouts and delete courses; `app/connectors/mcp_client.py` enforces an
allow-list and refuses anything outside it before the call leaves this process.

---

## Adding your own row

A **+ Add a row** control sits under the expanded timeline. Describe the row in
words and it is built from the streams the day already holds:

| Request | What you get |
| --- | --- |
| `heart rate above 100` | Intervals where the condition held |
| `heart rate below 50` | The same, the other way |
| `step rate over 60` | Intervals from the step-rate series |
| `heart rate` | The series itself, plotted |
| `sleep`, `when I was away from home` | That lane's events |

**The reader is local and rule-based — not a language model.** It matches stream
names, synonyms and thresholds against what the day actually recorded, and
nothing is sent anywhere: shipping the request plus a catalogue of your health
streams to an API to save writing a parser would be a poor trade.

That makes it fallible in one specific way — it can match something *near* what
you asked for — so it never creates anything without first showing what it
understood, and **Add row** stays disabled until there is a reading to agree
with. A request it cannot read is refused with the streams that day does have.

The case this is built around: asking for `heart rate variability` on a day with
no HRV must not quietly resolve to `heart rate`, which is a substring of it and
would produce a plausible-looking row full of the wrong data. It names the
stream and says the day has none, and a test pins that.

Rows are stored, so they appear on every day, and each one says why it is empty
when the condition never held. Everything a row produces carries the same
provenance as a built-in feature — rule id, version, threshold, source records —
because a row invented in a text box is still a derived feature.

The assistant can add rows too, with real language understanding, through the
`add_timeline_row` MCP tool.

---

## Collapsed mode

The **Collapsed** tab reduces the day to its major events on one line. Three
controls shape it:

- **Phenotype toggles** switch individual streams in and out, because a busy day
  puts more on one line than one line can hold. **Every lane visible on the
  Expanded tab has a switch here**, not only the ones whose events are in the
  curated major-event list — and a lane hidden there has none at all.
- **Major events only / Every event** drops that curation, so anything the
  Expanded tab draws can be brought onto this line. Off by default: a view whose
  whole point is being readable at a glance stops being readable with two
  hundred marks on it.
- **The window spans a month either side** of the selected day, scrolling
  horizontally. The view opens centred on that day, with history to its left and
  what followed to its right. The forward end stops at today, since a day that
  has not happened holds no data and cannot be reconstructed.

Two rules decide what a switched-on lane contributes, because "major" is a
curated list of event categories and not every lane has one:

- A lane that **defines major events** contributes those.
- A lane that **defines none** — Computer Use, Phone Use, Environment, HRV —
  contributes everything it recorded. Otherwise switching it on would do
  nothing and look broken.

TikTok is on the curated list; the phone's screen-on stretches and ordinary app
spells are deliberately not. A phone produces dozens of both in a day, which on
one line is a smear rather than a landmark, while a followed app is a handful of
spells and the reason that row exists at all.

Lanes with major events start on; the rest start off, so connecting a new source
does not silently triple the number of marks. Both states are remembered
explicitly, so a lane you switched off stays off even if its default later
changes.

**A lane that is only a continuous line is not offered here.** A heart-rate
trace with no discrete readings has nothing this view can draw: one row of marks
cannot carry a curve, and picking a moment out of one to stand for the whole
would be inventing salience — the same reason the DAG tab gives no node to a
continuously sampled signal. It is left out rather than offered as a switch that
does nothing.

Every mark is clickable, including its caption and the leader line joining the
two: the caption is the most obvious thing to aim at, and a mark is a bar eight
pixels tall with its name floating some way above it. **A mark can belong to any
day in the window**, so the details panel names the day when it is not the one
on screen, rather than showing another day's times under this day's heading.

A period that crosses midnight — a night's sleep, usually — is stored once per
day it touches, each copy cut at the boundary. The two halves are drawn running
to their panel edges so they meet as one unbroken bar, and the night is
announced once, on the day it began, labelled with its real span rather than the
half that ends at midnight.

Each day is drawn as its own panel with its own scale rather than laid on one
continuous ruler. A day is 23 or 25 hours across a daylight-saving change, so a
single linear ruler would either misplace the boundaries or silently stretch one
day; a panel per day keeps every day internally exact and makes the boundary
explicit.

**Panels load as they scroll into view, and only if the day is already
processed.** Sixty-one days is far more than fits on screen, so pulling them all
up front would mean dozens of requests for panels nobody has scrolled to. A day
the server has *never* processed is never fetched automatically at all —
reconstructing one goes out to Home Assistant and the wearable MCP and takes the
better part of a minute, so it shows a **Fetch this day** button and stays a
deliberate choice.

---

## Choosing a day

The page opens on **today**, and the sidebar's single navigation item goes back
to it from wherever the calendar takes you. Today is incomplete by definition —
the header says *In progress* and reads "Your data from today so far", so a
part-day is never presented as a finished one. Just after midnight it is
genuinely almost empty, which is the honest answer rather than a bug.

A day still running is served from cache and never re-fetched by the one-minute
poll, so an open page does not spawn an MCP subprocess every minute. **Refresh**
is how you ask for the hours since the last sync.

The MCP tools still describe yesterday by default (`get_yesterday_timeline`),
since a finished day is the one worth handing to an agent. The sidebar calendar
selects any other day up to and including today.

| Marker | Meaning |
| --- | --- |
| Filled dot | Already processed, and holds events |
| Hollow ring | Already processed, but nothing was recorded |
| Unmarked | Not fetched yet — selectable, and fetched on demand |

The three states are drawn differently on purpose: "nothing happened that day"
and "nobody has looked at that day" are different facts, and a calendar that
showed them the same way would invite the wrong conclusion.

Days are stored once processed, so revisiting one is instant. A first visit to
an unfetched day takes as long as its sources need — tens of seconds when an
MCP-backed source has to sign in. Future days are never selectable, and today is
labelled *In progress*, because a day still happening is incomplete by
definition.

> Note: the first version of this project deliberately had no date selection.
> The calendar was added later at the owner's request; everything else about the
> single-day design is unchanged, and there is still no trends view, no
> multi-day comparison, and no cross-day aggregation.

---

## Quick start (mock data)

No credentials, no Home Assistant, no wearable account.

```bash
make install
```

```bash
make build && make dev-backend
```

Then open **http://127.0.0.1:8000**.

`USE_MOCK_DATA` defaults to `true`, so the page fills with a deterministic
synthetic day: a main sleep period crossing midnight, three activity sessions,
a heart-rate series with an elevated stretch inside each workout, one nightly
HRV value, a temperature curve, light-condition intervals, home/away intervals,
motion events, and a charging gap where the watch recorded nothing.

The same seed always produces the same day:

```bash
MOCK_DATA_SEED=42
```

### Prerequisites

- **Python 3.12+** — `uv` will install it for you (`uv python install 3.12`)
- **Node.js 18+**
- **[uv](https://docs.astral.sh/uv/)** for the Python environment. Prefer plain
  `pip`? `python -m venv server/.venv && server/.venv/bin/pip install -e "server[dev]"`.

### Two ways to run it

| Mode | Command | URL |
| --- | --- | --- |
| **Built** (one process, one port) | `make build` then `make dev-backend` | `http://127.0.0.1:8000` |
| **Dev servers** (hot reload) | `make dev` | `http://127.0.0.1:3000` |

In dev mode Vite proxies `/api` to the backend, so the browser only ever talks
to one origin.

---

## The DAG tab

Next to **Expanded** and **Collapsed** is **DAG**: your causal model, **laid out
on the day's own clock**. There is nothing to configure first — it opens on the
whole model, and arrows are drawn by dragging from the dot on one row to
another.

**The rows are the Expanded tab's rows** — the same rows, with the same names,
icons and descriptions, in the same order, on the same x-axis. Four rows there
is four rows here. Rearranging the timeline rearranges this; hiding a row there
removes it from here. A node appears only at an hour the day actually recorded
that event or state.

A lane can hold more than one quantity — Sleep carries duration, efficiency and
onset — so a row stacks a tier per variable inside itself, named down the right
of the row label, exactly as Presence & Motion stacks home/away, arrivals,
motion and device use inside one row on the timeline. The row is the lane; the
glyph in a node says which quantity.

Three kinds of row therefore never appear, and all three used to:

| Not drawn | Why |
| --- | --- |
| A lane you hid | Hidden is hidden, on every tab |
| A lane with no data today | HRV on a night the watch was not worn is not a row on the timeline, so it is not a row here |
| Variables no lane observes — stress, alcohol, work schedule | Nothing on the timeline carries them |

The last one costs something real: **those arrows can no longer be drawn by
dragging**, because there is no tier to drag to. They remain in the model,
remain in the ledger below the graph, and become rows here the moment a
connected source starts reporting them.

Computer Use earned its row by gaining a variable: the causal model now has
*Computer use*, grounded on the stretches at the machine, carrying the same two
arrows the phone already had — to evening light and to sleep onset. Asserting
that a lit phone delays sleep while a lit monitor does not would be an asymmetry
the evidence does not support. Both are marked *plausible*, and either can be
removed from the ledger.

That ordering has a cost worth stating: the graph used to be laid out
cause-first, so every arrow pointed down the page. Ordered by lane, some point
back up. The arrowhead was always the honest signal for direction, and now it is
the only one.

![The DAG tab showing a time-anchored causal graph](docs/screenshot-dag.png)

Two things are on screen at once, and they have very different standing:

- **The nodes are observations.** Each sits at a real recorded time, with its
  own value and duration.
- **The arrows are assumptions.** They come from published physiology in
  `server/app/causal/knowledge.py`. Nothing is fitted, estimated or tested
  against your data, and the page says so in three places: a banner above the
  graph, the closing note, and an `"estimated": false` field that a test
  asserts.

Anchoring the graph in real times buys one piece of discipline — **an arrow is
only drawn when the order in time permits it**, joining each cause to the first
occurrence of its effect that does not precede it — and costs the ability to
draw anything for a variable the day never recorded.

| Encoding | Meaning |
| --- | --- |
| Glyph inside the node | Which variable it is — sleep duration, onset and efficiency share a row but not an icon |
| Node colour | The timeline lane it belongs to, matching the Expanded tab |
| Tier name beside the row label | Which quantity that tier of the row holds |
| Dashed circle, "no data this day" | A variable of a drawn row that this day did not record |
| Solid navy arrow | Immediate — the effect follows within two hours |
| Dashed green arrow | Delayed — the effect appears hours later |
| Fainter line | Weaker published evidence for that link |
| Violet ring | An arrow you drew, rather than a published prior |
| Full-width band | A state that held all day, so no single hour owns it |

### Drawing and removing arrows

Drag the dot on the trailing edge of any node onto another tier. Tiers are the
drop target rather than nodes, and a variable of a drawn row that this day
recorded nothing for still gets a dashed stand-in to grab. Hovering an arrow
reveals a delete control at its midpoint. A drag that would close a loop is
refused with the reason, since a cyclic "DAG" is not one.

Edits are stored server-side, so `get_expected_dag` reflects them too.

### Asking a specific question

The tab shows the model; it does not ask anything of it. Confounder, mediator
and collider are not properties of a variable — they are properties of a
variable *relative to a named exposure and outcome* — so with no question asked
there are no roles to assign, and claiming otherwise would be describing a
comparison nobody set up.

Naming a pair is still supported, through `POST /api/dag` with an `outcome` (and
optionally an `exposure`), and through the `get_expected_dag` MCP tool. That is
where the adjustment set, the mediator warnings and the collider warnings come
from:

| Role | Meaning | What to do with it |
| --- | --- | --- |
| **Confounder** | A common cause of both exposure and outcome | Adjust for it |
| **Mediator** | Sits on the path from exposure to outcome | Do *not* adjust — it absorbs the effect you want |
| **Collider** | A common *effect* of two variables | Do *not* adjust — it manufactures an association |

### What it refuses to draw

Three cases where an arrow would be a lie. The page stays quiet about them —
the graph is the graph — but every one is in the `/api/dag` response and the
`get_expected_dag` MCP tool, under `rows` and `unplacedEdges`:

- **Unmeasured variables** — stress, alcohol, caffeine, illness, work schedule.
  They have no place on a clock at all, and no lane on the timeline, so the tab
  gives them no row. They remain part of the assumed structure, and the
  response names which ones you cannot adjust away with the sources you have
  connected.
- **Whole-day states** — the town you were in, an all-day away period. True at
  every hour, so there is no single hour for an arrow to attach to. They get a
  band instead.
- **Continuously sampled signals** with no discrete events, such as a raw heart
  rate trace. Picking a moment out of a continuous line would be inventing
  salience. A derived value like resting heart rate *is* a moment, and does get
  a node.

Edit `knowledge.py` to change the hypotheses; `causal/grounding.py` decides how
each variable is recognised on a real day. Both are meant to be edited — a
personal causal model should be personal, which is also why the arrows can be
drawn by hand.

> Like the calendar, this reverses the original spec's "no causal claims"
> constraint, added later at the owner's request. It is scoped so it stays
> defensible: the app proposes *structure* and orders it in time, and still
> estimates nothing. The timeline tabs remain free of causal language, and a
> test asserts that.

---

## Architecture

```
                MCP client (Claude Code, Claude Desktop, ...)
                                  │  stdio
                                  ▼
                        MCP server  (server/app/mcp/)
                                  │  HTTP to localhost
                                  ▼
  ┌───────────────────────── Local API (FastAPI) ─────────────────────────┐
  │                                                                        │
  │  connectors/home_assistant  ──┐                                        │
  │  connectors/wearables       ──┤──▶ normalization ──▶ feature_engineering│
  │                               │         │                    │         │
  │                               ▼         ▼                    ▼         │
  │                        raw records   samples/states     lanes + events  │
  │                               └──────── storage (SQLite) ──────┘        │
  └───────────────────────────────────┬────────────────────────────────────┘
                                      │  GET /api/yesterday
                                      ▼
                        React + TypeScript + SVG interface
```

Layers are strictly separated:

- **Connectors** know about vendors. Nothing else does.
- **Normalization** does unit cleanup and interval closing. No interpretation.
- **Feature engineering** interprets, with thresholds from `config.yaml` and
  provenance on every output.
- **The frontend** draws what it is given. It never decides what is true.

### The shared event schema

`server/app/models/timeline.py` is mirrored by
`frontend/src/types/timeline.ts`. Timestamps are timezone-aware ISO 8601
throughout and are converted to local display time only at render.

```ts
type TimelineEvent = {
  id: string;
  phenotype: string;
  label: string;
  eventType: 'point' | 'interval' | 'continuous';
  startTime: string;
  endTime?: string;
  value?: number | string;
  unit?: string;
  source: string;
  measuredOrDerived: 'measured' | 'derived';
  confidence?: number;
  metadata?: Record<string, unknown>;
  provenance?: {
    rawRecordIds: string[];
    transformationRule?: string;
    ruleVersion?: string;
    thresholds?: Record<string, unknown>;
  };
};
```

### Days are not always 24 hours

Daylight-saving transitions produce 23- and 25-hour days, and in a few zones
local midnight does not exist at all on the spring-forward date.
`server/app/services/day.py` handles both, and the frontend's x-scale divides by
the day's *real* length:

```
x = padLeft + fractionOfDay * drawableWidth
fractionOfDay = elapsedRealTime(dayStart → t) / elapsedRealTime(dayStart → dayEnd)
```

> One trap worth knowing about: subtracting two Python `datetime`s that share a
> `ZoneInfo` uses their *wall-clock* fields, so a 23-hour day silently measures
> as 24. Every duration in this codebase normalizes to UTC first. See
> `services/day.py::elapsed` and `tests/test_day.py`.

---

## Connecting Home Assistant

### 1. Credentials

Create a long-lived access token in Home Assistant (profile → Security → Long-lived
access tokens), then:

```bash
cp .env.example .env
```

```
HOME_ASSISTANT_URL=http://homeassistant.local:8123
HOME_ASSISTANT_TOKEN=<your token>
LOCAL_TIMEZONE=America/New_York
USE_MOCK_DATA=false
```

`.env` is git-ignored. The token is read from the environment only — it is never
written to SQLite, returned by the API, or logged.

### 2. Find your entities

```bash
make discover
```

This lists every entity the timeline can use, grouped by role, and prints a
ready-to-paste `config.yaml` fragment. It never prints your credentials.

### 3. Map them

```bash
cp config.example.yaml config.yaml
```

```yaml
home_assistant:
  entities:
    presence: [person.you]
    motion: [binary_sensor.living_room_motion]
    temperature: [sensor.bedroom_temperature]
    illuminance: [sensor.living_room_illuminance]
    humidity: [sensor.living_room_humidity]
    door: [binary_sensor.front_door]
    device_use: [binary_sensor.phone_interactive]
    app_usage: [sensor.phone_last_used_app]
    steps: [sensor.you_steps]
    resting_heart_rate: [sensor.you_resting_heart_rate]
    sleep: [binary_sensor.bed_occupied]
```

Entity IDs are never hardcoded. Malformed configuration produces a specific
validation error naming the offending key.

### Two things about Home Assistant history that matter

Both were found against a live instance and are handled:

1. **Only the first row of each entity's history carries `entity_id` and
   `attributes`.** Every later row is minimal (`state` + `last_changed`). A
   parser that filters on `entity_id` keeps one sample per entity and silently
   drops the rest.

2. **Home Assistant records state *changes*, not samples.** A sensor that has
   not changed in an hour is steady, not missing. Numeric streams are therefore
   held until `feature_engineering.data_gap.stale_after_minutes` elapses. An
   explicit `unavailable` state is different — that is *known* missing data and
   is always drawn as a gap, however brief.

### Failure handling

The app stays usable when Home Assistant does not. Missing entities, unknown and
unavailable states, duplicate records, sensor gaps, timezone conversion, DST,
histories crossing midnight, authentication failure, an offline instance, rate
limits and partial availability are all handled, and each produces a specific
message rather than a generic error.

### Phone use, and the TikTok row

Two rows come from the Home Assistant companion app on an Android phone.

**Phone Use** has two tiers, the same shape Computer Use has:

* **Screen-on stretches**, from `entities.device_use` — the companion app's
  *Interactive* sensor. Locks shorter than
  `feature_engineering.device_use.merge_within_minutes` do not end a session,
  so putting the phone down for a moment is not a new pickup.
* **Which app was in front**, from `entities.app_usage` — the companion app's
  *Last used app* sensor, which reports an Android package name.

**TikTok** follows one app on its own row, so a quarter of an hour that
disappears inside "phone use" can be lined up against sleep onset and evening
light. Everything it draws also appears as an application spell one row up:
that is one stretch of time at two grains, not two measurements, and the
details panel says so.

#### Why the screen sensor is required, not optional

`sensor.<phone>_last_used_app` reports a change and then **holds that value
indefinitely**, screen on or off. The app open when the phone is put down at
eleven is still the reported app at eight the next morning. Drawn unclipped,
one glance at TikTok before bed becomes a nine-hour block.

So every run is intersected with the screen-on windows before anything is
drawn, and the unbridged windows are used for that — bridging a five-minute
pocket gap into a session is fine for a session bar, but it would silently
become five minutes in an app. With `device_use` configured and `app_usage`
missing, the top tier still draws. The other way round, the application tier is
**withheld** and both the lane and a warning say why, because there is no
honest version of that row.

Two smaller decisions follow the same rule:

* Runs are built from every package and filtered to the tracked ones
  *afterwards*. Filtering first would let two TikTok spells either side of a
  glance at the home screen merge across it, relabelling that glance — on the
  one row whose entire job is to say how long was spent in the app.
* Package names get readable labels (`com.zhiliaoapp.musically` → TikTok) from
  a lookup in `rules/phone_use.py`, and anything unlisted falls back to its
  last segment. The raw package is kept in the event metadata and provenance,
  so the label can never hide what was recorded.

#### Following a different app

TikTok ships under two package names depending on where the phone was set up,
which is why the config takes a list:

```yaml
feature_engineering:
  tiktok:
    packages:
      - com.zhiliaoapp.musically
      - com.ss.android.ugc.trill
```

Point those at another package to follow a different app. The row's *name*
lives in `server/app/feature_engineering/rules/tiktok.py` alongside the causal
variable of the same id — change both together, or the row will draw Instagram
under a TikTok heading.

No application is labelled social, productive or a distraction anywhere in
this app. The row says how long, and when.

### The TV row

**TV** is the third screen, and it has the same two tiers for the same reasons:

* **On-stretches**, from `entities.tv_use` — a sensor that is on while the set
  is. Off-stretches shorter than `feature_engineering.tv.merge_within_minutes`
  do not end a sitting, so switching off to answer the door is not two evenings.
* **What was playing**, from `entities.tv_title`, with `entities.tv_app`
  naming the service it streamed from.

The two tiers make **different claims**, and the row is built so one cannot
pass for the other. The pale band underneath says the television was *powered
on* — a paused episode, an idle menu and a set left running in an empty room
all satisfy it equally. Only the solid bars on top say something was reported
playing. The band carries no caption for this reason, the summary line reads
"with the TV on" rather than "watching", and the causal variable is called
`tv_use` and describes itself as opportunity to watch rather than attention
paid. If the stricter claim is what you want, narrow the sensor rather than the
wording: point `tv_use` at a template that is on only when the media player is
`playing`.

A media-title sensor holds its last value after playback stops, exactly like
the phone's last-used-app sensor, so `tv_title` is clipped to the on-windows
and is **withheld entirely** without a `tv_use` sensor. That clipping lives in
`rules/spells.py` and is shared by all three rows — the phone, TikTok and the
television — rather than copied per row, since it is precisely the kind of
subtlety that rots when it exists in three places.

#### Recording it, on a Home Assistant instance that has none of this

Media players are usually *not* worth putting on the recorder allowlist: they
write a row every time the playback position ticks. The cheaper shape is to
derive small entities from the media player and record those instead — a
template `binary_sensor` for on/off, and template sensors for the title and the
app. That is what the example config assumes.

---

## Connecting ActivityWatch

[ActivityWatch](https://activitywatch.net) records which application had focus
and whether the keyboard and mouse were idle. If it is running, there is nothing
to configure — it listens on `http://localhost:5600` and the timeline finds it.

```yaml
activitywatch:
  enabled: true
  mcp_server: activitywatch
  detail: domain
```

### Why this one is read over REST, not over its MCP server

The other MCP-backed source, Garmin, is read through its MCP server because that
server returns JSON. The `activitywatch` MCP server returns *formatted text* —
ranked tables meant for a reader — so consuming it would mean parsing its
column layout back into numbers, and every change to its output would break the
timeline. It is a thin wrapper over ActivityWatch's own local REST API, which is
what this app reads instead. Same server, same data, one less thing to break.
The row still names the MCP integration, so the panel matches what you
configured in your MCP client.

Set `ACTIVITYWATCH_URL` if it does not listen on the default port. There is no
credential: the server is unauthenticated and reachable only from this machine,
which is also why the timeline never addresses it off-machine.

### How much detail is kept

`detail` decides what is read at all. It is the same treatment
`include_street_address` gets for phone location — reduced but useful by
default, with the revealing level a deliberate choice:

| Level | What each event carries |
| --- | --- |
| `app` | The application name only. The browser extension is not read at all. |
| `domain` *(default)* | Plus the site a tab was on, reduced to its domain — `github.com`, never `github.com/you/private-repo` |
| `full` | Plus window titles and complete URLs |

**Reduction happens in the connector, before a record exists.** A title the
level does not permit is not stored, not cached in SQLite, not returned by the
API and not sent to the browser — the same rule that keeps GPS coordinates out
of the Phone Location lane. Choosing `full` is choosing to store window titles,
which quote document names, message subjects and search queries. Each event
records the level that produced it.

### What the lane shows

Three tiers on one row, coarsest first:

- **At the computer** — merged stretches of keyboard and mouse activity. An idle
  spell shorter than `merge_within_minutes` does not end a stretch, because
  pausing to read a page is not leaving the desk.
- **Applications** — which program had focus, for runs past `min_app_minutes`.
- **Browsing** — which site a tab was on, when the level permits it and the
  browser extension is reporting.

Two deliberate omissions. Applications are never categorised as work, leisure or
distraction: that judgement is not in the data, and nothing else in this
application passes judgement either. And **a computer that is off is not missing
data** — the lane produces no continuous series, so a day spent away from the
desk lowers no coverage figure and draws no hatched gap.

Stretches below `min_session_minutes` are still drawn, marked `brief`, and left
out of the session count. Discarding them was the first version of this rule and
it was wrong: real idle data fragments into four-minute stretches split by
six-minute breaks, so a whole evening of recorded activity disappeared from a
lane that had the events for it.

Without `aw-watcher-afk` the lane still works, from focus events alone — but a
window left open then counts as use, so those sessions are marked medium quality
and the reconstruction warns that they were inferred.

---

## Wearable providers

The core application is not coupled to any vendor. These providers ship today:

| Provider | Use for | Capabilities |
| --- | --- | --- |
| `mock` | Exploring the interface with no credentials | All six metrics |
| `json_file` | Any export you can write to a JSON schema | Whatever the file declares |
| `home_assistant` | A wearable whose data already reaches Home Assistant (Fitbit, Withings, Google Fit) | Sleep only — see below |
| `garmin_mcp` | A Garmin watch, through the Garmin MCP server | Sleep, HRV, continuous heart rate, activity, Body Battery |
| `google_health_mcp` | Fitbit and Pixel data that reaches the Google Health API | Sleep only, deliberately |
| `auto` | Several routes at once, tried in order per metric | The union of its routes |

### `auto`: several routes at once

Most people have more than one source, and each covers what the other misses.

```yaml
wearable:
  provider: auto
  routes:
    - garmin_mcp       # continuous HR when the watch was worn
    - home_assistant   # the Fitbit daily summary for the nights it was not
```

The merge is per-metric and first-non-empty: for each metric the routes are
asked in order and the first with data supplies it. Metrics are never blended,
so a heart-rate line always comes from one device rather than being stitched
together, and every event keeps its own source and device in the details panel.

#### Pinning a metric to one source

Falling through to the next route is a convenience. For a metric two sources
both claim and *disagree* about, it is a hazard: a week's row can end up being
two different measurements wearing one label, with nothing on screen saying
which night came from which device.

```yaml
wearable:
  metric_routes:
    sleep: [google_health_mcp]
```

A metric named here uses exactly those routes and nothing else. A night Google
Health has no record for is reported missing rather than answered by the watch,
which is the whole point. Routes named only under `metric_routes` are built
even when they are absent from `routes`, so a pin is never silently inert.

Set it in `config.yaml`:

```yaml
wearable:
  provider: json_file
  json_file:
    path: ./data/wearable.json
```

### The `home_assistant` provider

Fitbit-style integrations publish the night's sleep as a handful of once-a-day
sensors rather than a stage-by-stage record:

```yaml
wearable:
  provider: home_assistant
  home_assistant:
    device_name: Fitbit Inspire 3
    sleep:
      start_time: sensor.you_sleep_start_time        # "02:11"
      time_in_bed_minutes: sensor.you_sleep_time_in_bed
      minutes_asleep: sensor.you_sleep_minutes_asleep
      efficiency: sensor.you_sleep_efficiency
```

The provider reconstructs one interval from the clock string plus the duration,
choosing the date that makes the night end at or before the moment the
integration published it — so a 23:30 bedtime reported at 08:00 is correctly
attributed to the previous evening.

It declares **only** `sleep`, because that is all it can honestly serve: a daily
resting heart rate is not a heart-rate curve, so it is handled as its own Home
Assistant stream and drawn as a single labelled point.

### The `garmin_mcp` provider

```yaml
mcp:
  servers:
    garmin:
      discover_from_client: true    # reuse your MCP client's definition
      # or launch it explicitly:
      # command: uvx
      # args: ["--from", "git+https://github.com/Taxuspt/garmin_mcp", "garmin-mcp"]

wearable:
  provider: garmin_mcp
  garmin_mcp:
    mcp_server: garmin
```

This is the richest route: a stage-by-stage hypnogram, two-minute heart rate,
Body Battery as the readiness line, and real activity records. Garmin returns a
`null`-filled envelope for a day it has nothing for — that is a real answer
("the watch wasn't worn"), so the lanes hide themselves rather than erroring.

### Adding a vendor

`server/app/connectors/wearables/registry.py` documents the four steps:

1. Create `server/app/connectors/wearables/<vendor>.py` implementing
   `WearableProvider` — subclass `BaseWearableProvider` and override only the
   metrics the vendor really exposes.
2. Register the factory in `_FACTORIES`.
3. Add the name to the `Literal` in `config/schema.py::WearableConfig`.
4. Document any new environment variables in `.env.example`.

Nothing else changes: capability metadata flows to the frontend automatically,
and lanes without a supporting capability hide themselves.

---

## MCP client configuration

### Claude Code

```bash
claude mcp add yesterday-timeline -- /absolute/path/to/yesterday-timeline/server/.venv/bin/python -m app.mcp.server
```

Or add it to `.mcp.json` in your project:

```json
{
  "mcpServers": {
    "yesterday-timeline": {
      "command": "/absolute/path/to/yesterday-timeline/server/.venv/bin/python",
      "args": ["-m", "app.mcp.server"],
      "cwd": "/absolute/path/to/yesterday-timeline/server"
    }
  }
}
```

### Claude Desktop

`~/Library/Application Support/Claude/claude_desktop_config.json` on macOS, or
`%APPDATA%\Claude\claude_desktop_config.json` on Windows:

```json
{
  "mcpServers": {
    "yesterday-timeline": {
      "command": "C:\\path\\to\\yesterday-timeline\\server\\.venv\\Scripts\\python.exe",
      "args": ["-m", "app.mcp.server"],
      "cwd": "C:\\path\\to\\yesterday-timeline\\server"
    }
  }
}
```

Credentials come from `.env`, so they do not need to appear in the MCP client
configuration. If you prefer to pass them explicitly, add an `env` block.

---

## MCP tools

| Tool | Purpose |
| --- | --- |
| `launch_yesterday_timeline` | Start the backend and frontend if they are not running; return the URL. Idempotent. |
| `sync_yesterday_data` | Fetch and process the previous local calendar day. Returns counts, coverage, warnings, errors. |
| `get_yesterday_timeline` | Return the normalized timeline. Supports lane filtering, downsampling, and toggling metadata/provenance. |
| `get_day_timeline` | Return the timeline for one specific day (`YYYY-MM-DD`). |
| `list_days` | List the days the calendar can offer, and which already hold data. |
| `get_expected_dag` | Build the causal graph. No arguments gives the whole model, as the DAG tab shows it; an outcome (and optional exposure) narrows it and adds roles. A hypothesis, never an estimate. |
| `list_causal_variables` | List variables usable as an exposure or outcome, and whether each was observed. |
| `add_timeline_row` | Add a row to the expanded timeline, described in words. |
| `list_timeline_rows` | List the custom rows, with the request behind each. |
| `remove_timeline_row` | Remove a custom row. |

| `get_data_sources` | Status and capabilities of every configured source. |
| `get_event_details` | Complete metadata and provenance for one event id. |
| `refresh_timeline` | Re-run synchronization and feature engineering. |
| `open_timeline` | Open the URL in the default browser, or return it if that is not possible. |

```json
{ "status": "running", "url": "http://127.0.0.1:8000", "backend_url": "http://127.0.0.1:8000" }
```

The tools deliberately do not stream the whole dataset through the model:
`get_yesterday_timeline` returns a lane summary by default, and the localhost
frontend fetches processed data straight from the local API.

### Local API

FastAPI serves OpenAPI documentation at `http://127.0.0.1:8000/docs`.

```
GET    /api/health              GET    /api/yesterday
GET    /api/config              POST   /api/yesterday/sync
GET    /api/data-sources        GET    /api/day/{date}
GET    /api/days                POST   /api/day/{date}/sync
GET    /api/lane-config         GET    /api/events/{event_id}
PATCH  /api/lane-config         GET    /api/raw-records/{record_id}
GET    /api/dag/variables       DELETE /api/cache
POST   /api/dag
```

`/api/yesterday` is an alias for `/api/day/{yesterday}`; both return the same
payload. A future date is refused with a `future_date` error rather than an
empty day.

---

## Environment variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `LOCAL_TIMEZONE` | `America/New_York` | IANA zone used to decide which day "yesterday" was |
| `USE_MOCK_DATA` | `true` | `false` reads real sources |
| `MOCK_DATA_SEED` | `42` | Makes the mock day reproducible |
| `WEARABLE_PROVIDER` | *(config.yaml)* | Overrides the configured provider |
| `HOME_ASSISTANT_URL` | — | e.g. `http://homeassistant.local:8123` |
| `HOME_ASSISTANT_TOKEN` | — | Long-lived access token |
| `HOME_ASSISTANT_TIMEOUT_SECONDS` | `15` | Request timeout |
| `HOME_ASSISTANT_VERIFY_SSL` | `true` | Only disable for a self-signed cert on your own network |
| `ACTIVITYWATCH_URL` | `http://localhost:5600` | Where the ActivityWatch server listens |
| `ACTIVITYWATCH_TIMEOUT_SECONDS` | `20` | Request timeout |
| `API_HOST` / `API_PORT` | `127.0.0.1` / `8000` | Backend bind address |
| `FRONTEND_PORT` | `3000` | Vite dev server port |
| `DATA_DIR` | `./data` | Where the SQLite file lives |
| `CONFIG_PATH` | *(auto)* | `config.yaml`, falling back to `config.example.yaml` |

---

## Starting it automatically at login

One command registers a Windows Scheduled Task that starts the server, pulls
yesterday, and opens the page every time you sign in:

```powershell
.\scripts\install_autostart.ps1
```

```powershell
.\scripts\install_autostart.ps1 -Status
```

```powershell
.\scripts\install_autostart.ps1 -Uninstall
```

It runs as your user at your login, 30 seconds after sign-in
(`-DelaySeconds` changes that), with no elevation and no console window. The
task waits for a network connection first, because Home Assistant is reached
over one — a machine that signs in before Wi-Fi associates would otherwise
record a failed fetch.

| Script | What it does |
| --- | --- |
| `scripts/install_autostart.ps1` | Registers, inspects or removes the login task |
| `scripts/start_on_login.ps1` | What the task runs: start, pre-fetch, open. Safe to run by hand |
| `scripts/stop.ps1` | Stops the server |

`start_on_login.ps1` is idempotent — if something already answers on port 8000
it reuses it rather than starting a second server. A failed fetch is logged and
the page still opens; a source that was down is not a reason to show nothing.

Progress goes to `logs/startup.log`, one block per login:

```
2026-07-30 10:22:26  --- login trigger ---
2026-07-30 10:22:39  Server is up.
2026-07-30 10:22:40  Ready: 2026-07-29 - 18 events, 85% coverage, 1225 raw records.
```

`scripts/stop.ps1` finds the server by **who owns the port**, not by process
name. A `uv`-created virtualenv has a trampoline `python.exe` that re-execs the
real interpreter, so the process actually holding port 8000 is a child of the
one the launcher started — stopping the parent alone would leave the server
running.

### Days synced while they were still running

Opening the page on a day still in progress caches a partial snapshot of it.
Once that day ends, the snapshot is no longer a valid answer, so `get_or_sync`
compares each cached day's generation time against the day's own end and
re-fetches anything captured early.

The check deliberately fires only *after* a day is over. Today always looks
partial by that definition, and the page polls every minute — re-fetching on
each poll would spawn and authenticate a Garmin MCP subprocess every time.
Today stays cached; **Refresh** is how you ask for its latest hours.

---

## Developer commands

```bash
make help
```

| Command | What it does |
| --- | --- |
| `make install` | Install backend and frontend dependencies |
| `make dev` | Start the backend API and the frontend dev server together |
| `make build` | Build the frontend so the backend serves it on one port |
| `make sync` | Fetch and process yesterday from the configured sources |
| `make open` | Open the timeline in the default browser |
| `make discover` | List Home Assistant entities and print a config fragment |
| `make test` | Backend and frontend unit tests |
| `make test-e2e` | Playwright end-to-end suite (needs a running app) |
| `make clean-data` | Delete every locally cached record |

Direct equivalents, if you would rather not use `make`:

```bash
cd server && .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

```bash
cd frontend && npm run dev
```

### Docker (optional, not required)

```bash
docker compose up --build
```

Builds the frontend, serves it from the backend, and publishes only to
`127.0.0.1:8000`.

---

## Testing

```bash
make test
```

**Backend** (pytest) covers previous-day calculation, timezone handling and DST
transitions, event normalization, sleep crossing midnight, missing values, Home
Assistant API parsing, feature-engineering provenance, mock provider determinism,
MCP tool responses, partial-source failure, and the real-world Home Assistant
regressions described above.

**Frontend** (vitest) covers timeline rendering, lane alignment, lane visibility,
the collapsed/expanded toggle, event selection, the details panel, missing-data
gaps, source-error states, and zoom.

**End-to-end** (Playwright) drives the whole workflow: load the Yesterday page,
confirm lanes render on a shared axis, click an event, confirm the details panel,
inspect raw data, switch to collapsed mode and back, hide and restore a lane,
refresh, and check that no causal or judgemental language appears anywhere.

```bash
cd frontend && npm run test:e2e:install   # once
```

---

## The icon

`frontend/public/favicon.svg` is the source of truth — three staggered lanes on
a shared axis, in the app's own accents. It was designed at 16px first, because
that is the size a bookmarks bar actually renders: no fine detail, no lettering,
just a few thick shapes and strong colour. The stagger is the part that does the
work, since three left-aligned bars would read as a generic list icon.

Everything else is generated from it, so the two can never drift:

```bash
cd frontend && npm run icons
```

That writes `favicon.ico` (16/32/48), `icon-16/32/48/192/512.png` and
`apple-touch-icon.png`. Rendering goes through the Chromium that Playwright
already installs, so there is no new image dependency.

> The `.ico` matters more than it looks. Chrome's bookmarks bar is fed from its
> favicon *database*, not from the live page, and that database falls back to
> `/favicon.ico`. Before this existed the SPA route answered that request with
> `200 OK` and a page of HTML — no error anywhere, and no icon.

---

## Where to change things

| To change... | Edit |
| --- | --- |
| Any threshold | `config.yaml` → `feature_engineering:` |
| Light categories | `config.yaml` → `feature_engineering.light_category.thresholds` |
| **Workout detection** | `server/app/feature_engineering/rules/activity.py` |
| **Sleep intervals** | `server/app/feature_engineering/rules/sleep.py` |
| **Where sleep comes from** | `config.yaml` → `wearable.metric_routes.sleep` |
| Google Health sleep parsing | `server/app/connectors/wearables/google_health_mcp.py` |
| **Elevated heart rate / baselines** | `server/app/feature_engineering/rules/heart_rate.py` |
| **HRV handling** | `server/app/feature_engineering/rules/hrv.py` |
| **Readiness** | `server/app/feature_engineering/rules/readiness.py` |
| **Temperature deviation** | `server/app/feature_engineering/rules/temperature.py` |
| **Light categories / environment** | `server/app/feature_engineering/rules/light.py` |
| **Presence, motion, doors** | `server/app/feature_engineering/rules/presence.py` |
| **Computer use sessions and applications** | `server/app/feature_engineering/rules/computer_use.py` |
| **Phone screen sessions and app spells** | `server/app/feature_engineering/rules/phone_use.py` |
| What a package name is called on screen | `server/app/feature_engineering/rules/phone_use.py::APP_NAMES` |
| **Which app the TikTok row follows** | `config.yaml` → `feature_engineering.tiktok.packages` (and the row's name in `rules/tiktok.py`) |
| **TV sittings and programmes** | `server/app/feature_engineering/rules/tv.py` |
| What counts as the TV being "on" | `config.yaml` → `home_assistant.entities.tv_use` (narrow the sensor, not the label) |
| Clipping a held-over sensor to an on-signal | `server/app/feature_engineering/rules/spells.py` — shared by the phone, TikTok and TV rows |
| How much of a window or tab is kept | `config.yaml` → `activitywatch.detail` |
| Lane order and failure handling | `server/app/feature_engineering/pipeline.py` |
| Config schema for a new rule | `server/app/config/schema.py` |
| **Add a wearable provider** | `server/app/connectors/wearables/registry.py` + a new module beside it |
| Home Assistant entity groups | `server/app/config/schema.py::HomeAssistantEntities` and `connectors/home_assistant/connector.py::STREAM_BY_DOMAIN` |
| The calendar and its markers | `frontend/src/components/Calendar.tsx` |
| Which events count as "major" in collapsed mode | `frontend/src/utilities/lanes.ts::MAJOR_CATEGORIES` |
| Which days are offered | `server/app/services/sync.py::available_days` |
| Lane colours, heights, major events | `frontend/src/utilities/lanes.ts` |
| The x-axis scale | `frontend/src/timeline/scale.ts` |

---

## Privacy model

- **All processing is local.** No personal sensor data is transmitted anywhere.
- The server binds to `127.0.0.1` by default, and CORS is restricted to the
  local frontend origin.
- Secrets live in environment variables only. The token is never stored in
  SQLite, returned by the API, or written to logs.
- **No geographic coordinates** are read or emitted, including in the Phone
  Location lane. Home Assistant puts `latitude`, `longitude` and `gps_accuracy`
  in device-tracker attributes; the connector keeps only the state string, so
  they never enter the data model at all. A test walks the serialised lane and
  fails if any field carries one.
- **Sleep stages are discarded at the connector.** Google Health returns a
  full hypnogram — every deep/REM/light/awake stretch of the night. The Sleep
  Duration row reports how long, so the stages are dropped where they arrive
  rather than ignored at render time, and never reach SQLite, the API or the
  browser. What is stored is the period, how much of it was asleep, and whether
  the provider called it main sleep or a nap.
- **Computer use is reduced before it is stored.** `activitywatch.detail`
  decides what the connector keeps, and anything above that level is dropped
  where the events arrive rather than hidden at render time — so it never
  reaches SQLite, the API or the browser. The default keeps application names
  and browsing domains; window titles and full URLs require `detail: full`.
- **Phone app names are package names, and nothing finer.** The Phone Use and
  TikTok rows read one sensor whose state is a package (`com.whatsapp`). No
  notification text, message content, in-app screen or URL is available to this
  app or stored by it, and the sensor is only read in combination with the
  screen-state sensor — an app spell is never drawn for a phone that was
  asleep. The friendly label is presentation only; the package it came from
  stays in the event.
- **Location is shown at town level by default.** The lane draws the tracker's
  zone (`Home`, `Away`, or a named zone) and the town from a geocoded sensor.
  The full street address is off unless you deliberately set
  `feature_engineering.phone_location.include_street_address: true`, and each
  event records that the choice was made.
- **MCP calls are read-only.** The client enforces a per-server allow-list of
  `get_*` tools and refuses anything else before it leaves the process.
- Locally cached data lives in one SQLite file at `$DATA_DIR/yesterday.sqlite3`.
  Raw records are retained for 90 days so that personal baselines can span more
  than one day.

```bash
make clean-data          # or: curl -X DELETE http://127.0.0.1:8000/api/cache
```

---

## No causal claims

This version is a temporal visualization and feature-engineering application. It
lays the foundation for later N-of-1 causal analysis by making the observed day
understandable, without claiming causality now.

The DAG tab proposes causal *structure* — which arrows you would have to
assume — and is labelled as a hypothesis throughout. No effect is estimated
anywhere in this app.

On the timeline itself, it **will** say:

> Evening run ended 4.6 hours before the recorded sleep onset.
> Mean heart rate was 120 bpm during recorded activity and 63 bpm outside it.
> Measured illuminance in the hour before sleep onset was 28 lux, lower than the
> 41 lux recorded in the two hours before that.

It will **not** say that exercise improved sleep, that bright light increased
energy, or that heart rate represented stress. There are no causal arrows, no
delayed-effect edges, and no recommendations.

It is equally careful about labels. Elevated heart rate is reported relative to
your own observed baseline — "1.8 standard deviations above the 30-day personal
baseline" — never as an anxiety, stress or panic event, and never as clinically
abnormal. A wrist sensor reports skin temperature, not core body temperature. A
vendor readiness score is called physiological readiness, not energy. And the
status card reports coverage and counts; it never tells you that you had a good
day.

Automated tests assert that no causal or judgemental language appears on the
timeline tabs, and that the DAG payload always reports `estimated: false` and
never carries a p-value, effect size or coefficient.

---

## Troubleshooting

**The page says the local backend is not running.**
Start it with `make dev-backend`, or call the `launch_yesterday_timeline` MCP
tool. Check `http://127.0.0.1:8000/api/health`.

**"Home Assistant could not be reached at the configured URL."**
Check `HOME_ASSISTANT_URL` in `.env` and that the instance is up. Wearable lanes
still render — the app degrades per-source, not globally.

**"Home Assistant rejected the access token."**
Long-lived tokens are revoked when the issuing user's password changes. Create a
new one and update `HOME_ASSISTANT_TOKEN`.

**"Home Assistant returned no history for: sensor.x"**
The entity does not exist, or `recorder` is not enabled for it. Check the ID with
`make discover`, and confirm it is not excluded in your recorder configuration.

**A lane I expected is hidden.**
Open *Visible data streams* — unavailable lanes are listed there with the exact
reason. Most often the provider does not publish that metric, or nothing was
recorded during the day.

**The step or environment line has a hatched gap.**
The source genuinely stopped reporting for longer than
`feature_engineering.data_gap.stale_after_minutes`. Raise that value for sensors
that legitimately report rarely.

**The Computer Use lane says ActivityWatch recorded nothing.**
It only holds days since it was installed, and it records nothing while the
machine is off. Check the ActivityWatch dashboard at `http://localhost:5600` for
the day in question; if the app is not running, the MCPs panel says so instead.

**Computer use shows applications but no browsing.**
The ActivityWatch browser extension is not installed or not reporting, or
`activitywatch.detail` is set to `app`. Browser time still appears under the
browser's own application name.

**A whole day shows as "Away".**
Home Assistant's `person` entity was `not_home` for the day. Set
`feature_engineering.home_presence.entity_priority` to prefer a tracker that
actually updates.

**The wrong day is shown.**
`LOCAL_TIMEZONE` overrides `config.yaml`. Confirm with
`http://127.0.0.1:8000/api/config`.

**Port 8000 or 3000 is in use.**
Set `API_PORT` / `FRONTEND_PORT` in `.env`.

---

## Known limitations

- **One day at a time.** The calendar picks *which* day; it never compares two.
  There is no trends view and no cross-day aggregation.
- **The DAG is a prior, not a finding.** Its arrows encode published
  physiology, not anything learned from your data. Placing them on the clock
  checks only that an assumed effect is *ordered* correctly in time — it does
  not test whether the effect occurred. Estimating the effects it proposes
  would need many days, which this version does not do.
- **A first visit to an unfetched day is slow.** It has to sign in to the
  sources and read the whole day — tens of seconds when Garmin is involved.
  Processed days are stored, so returning to one is instant.
- **How far back you can go depends on the sources**, not on this app: Home
  Assistant's `recorder` retention (10 days by default), whatever history your
  wearable account holds, and — for computer use — the day ActivityWatch was
  installed, since it keeps everything from then and nothing from before.
- **Computer use is one machine's.** ActivityWatch records the computer it runs
  on. A second machine needs its own watcher, and if one server collects both,
  `activitywatch.hostname` picks which one the day describes rather than the two
  being merged.
- **Sleep is a duration, not a hypnogram.** The Sleep Duration row reports how
  long each period lasted. Google Health returns full stage data and the
  connector discards it, so no stage detail exists anywhere in the application —
  in the database, the API or the DAG. Sleep onset and sleep efficiency are
  consequently unmeasured variables: the arrows into them still state what an
  analysis would have to assume, but nothing observes them.
- **Step-derived activity is smeared by sync interval.** A counter that syncs
  every 30 minutes locates movement to within 30 minutes, and the rule says so
  in each event's provenance. It never names an exercise type from cadence.
- **Personal baselines need history.** With fewer than 30 stored samples the
  rules fall back to a same-day baseline and label it as such in the details
  panel.
- **No live push.** The page polls the local API every 60 seconds; the Refresh
  control is immediate.
- **Vendor APIs are not implemented.** Oura, Fitbit, Garmin, Apple Health and
  Health Connect are documented extension points, not shipped clients. The only
  real integrations that exist and have been tested are Home Assistant's REST
  API and the wearable-via-Home-Assistant provider.

---

## Future causal-analysis extension points

The data model is built so that a later version can add multiple-day comparison,
lagged associations, candidate causal edges, N-of-1 estimation, confidence
intervals, intervention comparison and user-defined phenotypes — without
reshaping anything.

- Raw records are retained for 90 days and keyed by day, so multi-day queries
  need no schema change (`storage/repository.py`).
- `Repository.compute_baselines` already computes personal baselines across a
  configurable window; it generalises to lagged windows.
- Every derived feature carries `transformationRule`, `ruleVersion` and its
  thresholds, so a future analysis can filter to features produced by a known
  rule version.
- `TimelineEvent` and `TimelineSeries` are day-scoped by convention, not by
  structure — nothing prevents a range query returning the same types.
- `feature_engineering/pipeline.py` runs independent, individually failing
  rules; an association or estimation stage would be added after it, never
  inside it.

None of that is implemented, and no inactive UI controls hint at it.
