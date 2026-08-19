# Singapore AIS Dataset Assessment

## 1. Executive Summary

**Verdict: `AMBER` — useful for chronological historical replay, but it requires an ETA estimator and important synthetic or external inputs.**

The CSV directly provides 609,975 timestamped AIS position reports for 5,879 stable anonymised vessel identifiers from 2023-10-01 through 2023-10-30. It includes latitude, longitude, speed over ground, course over ground, heading, navigation status, vessel type, anonymised destination values, and AIS ETA components. These observations are sufficient to reconstruct many historical vessel tracks and run a causally correct replay after sorting by observation time.

The dataset does **not** contain official scheduled ETA/ETD, official ETA revisions, actual terminal or berth assignments, PSA container records, real vessel-to-vessel container connections, official UCIDs, or loading cutoffs. AIS-reported ETA is not a substitute for an official schedule and must be treated cautiously. LATCH can use this file as its real movement layer, but arrival prediction must be derived and connection/terminal/container inputs must remain synthetic, assumed, or come from another source.

Labels used below are: **Observed fact** (read directly from the CSV), **Derived calculation** (computed from CSV values), **Interpretation** (assessment of fitness), **Project assumption**, and **Unknown**.

## 2. Why This Dataset Matters to LATCH

LATCH needs a time-ordered stream of vessel observations to reproduce what could have been known at each historical instant. This dataset provides that stream for Singapore waters. It can support trajectory reconstruction, time-progressive ETA estimates, delay signals, and a synthetic connection-risk experiment without exposing future rows to the detector.

It cannot independently establish whether a vessel was officially late or whether a real container connection failed. Those outcomes require schedule, terminal, berth, container, connection, and cutoff information that is absent here.

## 3. Dataset Identity and Reproducibility

| Item | Value | Classification |
| --- | --- | --- |
| Filename | `Singapore_anonymized.csv` | Observed fact |
| Repository-relative path | `Data Inspection/Singapore_anonymized.csv` | Observed fact |
| File size | 214,671,886 bytes (204.73 MiB; approximately 205 MiB) | Observed fact |
| SHA-256 | `a46b6f6f68e5d7f2cc87b3eaa0fe2cc74373cf8e9788b2a3156c4f4644bfad7e` | Derived calculation |
| Encoding | US-ASCII (also valid UTF-8) | Observed/detected fact |
| Delimiter | Comma | Observed/detected fact |
| Header rows | 1 | Observed fact |
| Data rows | 609,975 | Derived calculation |

## 4. File and Schema Overview

The file has 45 columns. “Integer-like float” means the CSV serialises the field with a decimal (for example `70.0`), although its AIS meaning is categorical or integral. Anonymised token fields are numbers in this export but should be treated as categorical identifiers, not quantities.

| Column | Inferred type | Plain-English meaning |
| --- | --- | --- |
| `MessageType` | String | AIS message family; all inspected rows are position reports. |
| `AisVersion` | Integer-like float | AIS protocol/version value attached to vessel static data. |
| `CallSign` | Integer token | Anonymised vessel radio call-sign token; not the original call sign. |
| `Destination` | Integer token | Anonymised AIS-reported destination token; not readable destination text. |
| `DimensionA` | Float | Metres from AIS reference point toward the bow. |
| `DimensionB` | Float | Metres from AIS reference point toward the stern. |
| `DimensionC` | Float | Metres from AIS reference point toward port. |
| `DimensionD` | Float | Metres from AIS reference point toward starboard. |
| `Dte` | Boolean | Data terminal equipment readiness flag. |
| `EtaDay` | Integer-like float | Day component of vessel-reported AIS ETA. |
| `EtaHour` | Integer-like float | Hour component of vessel-reported AIS ETA. |
| `EtaMinute` | Integer-like float | Minute component of vessel-reported AIS ETA. |
| `EtaMonth` | Integer-like float | Month component of vessel-reported AIS ETA. |
| `FixType` | Integer-like float | Type of electronic position-fixing device. |
| `ImoNumber` | Integer token | Anonymised IMO-number token; not an original IMO number. |
| `MaximumStaticDraught` | Float | AIS-reported maximum present static draught, normally metres. |
| `MessageID` | Integer | Numeric AIS message identifier. |
| `Name` | Integer token | Anonymised name token from static-data fields. |
| `RepeatIndicator` | Integer | AIS repeat/relay indicator. |
| `Spare` | Integer | Reserved AIS payload bits. |
| `ShipType` | Integer-like float | AIS ship/cargo type code. |
| `Message.ShipStaticData.UserID` | Integer token | Anonymised vessel user identifier in static data. |
| `Valid` | Boolean | Export/source validity flag; all rows are `True`. |
| `MMSI` | Integer token | Anonymised MMSI token; not the original MMSI. |
| `ShipName` | Integer token | Anonymised ship-name token; not readable text. |
| `MetaData.latitude` | Float | Latitude copied into record metadata. |
| `MetaData.longitude` | Float | Longitude copied into record metadata. |
| `timestamp` | Datetime string | High-resolution observation/event timestamp used for replay. |
| `Geom` | WKT Point string | Geometry as `POINT(longitude latitude)`. |
| `ShipCommonDataID` | Integer | Row/common-data record identifier; unique per row, not a vessel identifier. |
| `Rounded_time` | Timezone-aware datetime string | Observation time rounded/binned to a 30-minute UTC boundary. |
| `index` | Integer-like float | Source/export index; not chronological order. |
| `Cog` | Float | Course over ground in degrees. |
| `CommunicationState` | Integer-like float | Encoded AIS radio communication-state field. |
| `Latitude` | Float | Vessel latitude in decimal degrees. |
| `Longitude` | Float | Vessel longitude in decimal degrees. |
| `NavigationalStatus` | Integer-like float | AIS navigation-status code. |
| `PositionAccuracy` | Boolean | AIS position-accuracy flag. |
| `Raim` | Boolean | Receiver Autonomous Integrity Monitoring flag. |
| `RateOfTurn` | Float | Encoded AIS rate-of-turn value; `-128` is an unavailable sentinel. |
| `speed` | Float | Speed over ground, conventionally knots. |
| `SpecialManoeuvreIndicator` | Integer-like float | AIS special-manoeuvre indicator/code. |
| `Timestamp` | Integer-like float | AIS radio-message UTC second-of-minute field, not the full event datetime. |
| `TrueHeading` | Integer-like float | True heading in degrees; `511` means unavailable. |
| `UserID` | Integer token | Stable anonymised vessel identifier used in this assessment. |

## 5. Temporal Coverage

| Statistic | Value | Classification |
| --- | --- | --- |
| Minimum `timestamp` | `2023-10-01 00:00:19.766745145` in the source (parsed to microsecond precision for calculations) | Observed fact |
| Maximum `timestamp` | `2023-10-30 23:59:52.818535080` in the source (parsed to microsecond precision for calculations) | Observed fact |
| Total coverage | 2,591,973.051790 seconds = 29 days, 23:59:33.051790 (effectively 30 days) | Derived calculation |
| Timestamp format | `YYYY-MM-DD HH:MM:SS.fraction`, with up to nanosecond-like fractional precision | Observed fact |
| Malformed `timestamp` values | 0 | Derived calculation |
| Records outside main period | 0; every observation is in October 2023 | Derived calculation |

The primary `timestamp` has **no timezone offset**. `Rounded_time` explicitly includes `+00:00`, strongly suggesting UTC, but the CSV itself contains no documentation proving that the timezone-free primary timestamp is UTC. Therefore the primary timezone is **unknown/inferred, not documented**. Replay should explicitly record a UTC assumption or obtain provenance confirmation before combining this data with schedules.

The physical row order is not globally chronological: 4,070 adjacent timestamp inversions were found. Within each vessel's rows, no inversions were found. A replay must therefore perform a global stable sort by parsed `timestamp` (with a deterministic tie-breaker) before emission.

## 6. Vessel Coverage and Observation Frequency

`UserID` was selected as the anonymised vessel key. It has 5,879 distinct values and equals both `MMSI` and `Message.ShipStaticData.UserID` on all 609,975 rows. This is strong evidence that the anonymised vessel mapping is consistent in this file. `ShipCommonDataID` is unique per row and is not appropriate as a vessel key.

| Statistic | Value | Classification |
| --- | ---: | --- |
| Unique vessels | 5,879 | Derived calculation |
| Vessels present at multiple distinct timestamps | 5,836 (99.27%) | Derived calculation |
| Minimum observations per vessel | 1 | Derived calculation |
| Median observations per vessel | 41 | Derived calculation |
| Mean observations per vessel | 103.7549 | Derived calculation |
| Maximum observations per vessel | 1,063 | Derived calculation |
| Vessels with fewer than 2 observations | 43 (0.73%) | Derived calculation |
| Vessels with fewer than 3 observations | 99 (1.68%) | Derived calculation |
| Vessels with fewer than 5 observations | 219 (3.73%) | Derived calculation |
| Vessels with fewer than 10 observations | 931 (15.84%) | Derived calculation |

Using fewer than 10 observations as a conservative “too few for a useful trajectory” threshold, 931 vessels should be excluded or flagged. The threshold is a project interpretation, not a property encoded in the data.

Consecutive intervals were calculated after sorting observations within each `UserID`:

| Interval statistic | Value |
| --- | ---: |
| Median | 1,800.805 seconds (30m 0.805s) |
| 90th percentile | 3,029.371 seconds (50m 29.371s) |
| Maximum | 2,505,799.426 seconds (about 29 days 0h 3m 19s) |

The typical cadence is therefore approximately 30 minutes, but the extreme gap shows that continuity cannot be assumed for every vessel. An ETA model needs explicit staleness and gap handling.

## 7. Data Quality Checks

### Missing values

No blank, `NA`, `N/A`, `null`, `None`, or `NaN` lexical values were found. Consequently, the lexical missing-value percentage is **0.00% for every column**:

| Columns | Missing |
| --- | ---: |
| `MessageType`, `AisVersion`, `CallSign`, `Destination`, `DimensionA`, `DimensionB`, `DimensionC`, `DimensionD`, `Dte` | 0.00% each |
| `EtaDay`, `EtaHour`, `EtaMinute`, `EtaMonth`, `FixType`, `ImoNumber`, `MaximumStaticDraught`, `MessageID`, `Name` | 0.00% each |
| `RepeatIndicator`, `Spare`, `ShipType`, `Message.ShipStaticData.UserID`, `Valid`, `MMSI`, `ShipName`, `MetaData.latitude`, `MetaData.longitude` | 0.00% each |
| `timestamp`, `Geom`, `ShipCommonDataID`, `Rounded_time`, `index`, `Cog`, `CommunicationState`, `Latitude`, `Longitude` | 0.00% each |
| `NavigationalStatus`, `PositionAccuracy`, `Raim`, `RateOfTurn`, `speed`, `SpecialManoeuvreIndicator`, `Timestamp`, `TrueHeading`, `UserID` | 0.00% each |

This does **not** mean every value is semantically available. AIS uses sentinel/default values, and anonymisation replaces some strings with numeric tokens. Examples include `TrueHeading = 511` in 64,331 rows (10.55%) and `RateOfTurn = -128` in 70,481 rows (11.55%). Zero can also mean unavailable for some static/ETA fields, while zero speed is a legitimate stationary observation.

### Duplicates and validity

| Check | Result |
| --- | ---: |
| Exact duplicate rows (extra copies beyond the first) | 0 |
| Duplicate `UserID` + `timestamp` records (extra copies) | 0 |
| Latitude outside -90 to 90 | 0 |
| Longitude outside -180 to 180 | 0 |
| Negative speed | 0 |
| Course outside 0 to 360 | 0 |
| Invalid heading other than recognised `511` sentinel | 0 |
| Malformed primary timestamps | 0 |
| Timestamps outside October 2023 | 0 |

Other suspicious or cautionary values include speed as high as 102.3 knots, ETA hours up to 30, ETA minutes up to 63, ETA months up to 13, and a maximum per-vessel observation gap of about 29 days. The out-of-range ETA component values are AIS unavailable/default codes rather than usable clock values. Approximately 586,838 rows (96.21%) have ETA components within ordinary month/day/hour/minute ranges, but this does not prove that those values are current or accurate.

## 8. Available Information

| Required information | Present? | Evidence and qualification |
| --- | --- | --- |
| Anonymised vessel identifier | Yes | `UserID`; 5,879 stable tokens. |
| Latitude | Yes | `Latitude` and `MetaData.latitude`. |
| Longitude | Yes | `Longitude` and `MetaData.longitude`. |
| Speed over ground | Yes | `speed`; units inferred as knots from AIS convention. |
| Course over ground | Yes | `Cog`, degrees. |
| Heading | Yes, partly unavailable | `TrueHeading`; 511 sentinel on 10.55% of rows. |
| Navigation status | Yes | `NavigationalStatus`, coded AIS values. |
| Vessel type | Yes | `ShipType`, 20 distinct codes (70–89 in this subset). |
| Destination | Partly | `Destination` exists but contains anonymised numeric tokens, not readable ports. |
| AIS-reported ETA | Yes, with caveats | Month/day/hour/minute components exist; no year, timezone, or guaranteed freshness, and sentinel values occur. |

All statements in this table describe CSV availability. Unit descriptions and sentinel meanings rely on standard AIS interpretation and should be confirmed against the dataset producer's data dictionary.

## 9. Missing Information

The CSV does not contain:

- official scheduled ETA or ETD;
- an authoritative history of official ETA revisions;
- confirmed actual arrival/departure timestamps;
- actual PSA terminal or berth assignments;
- PSA container records or container event history;
- real inbound-to-outbound container connections;
- official UCIDs;
- official container loading cutoffs;
- readable vessel names, MMSIs, IMO numbers, call signs, or destination text;
- documentation proving the primary timestamp timezone, coordinate/cadence generation method, or anonymisation semantics.

AIS ETA fields represent vessel-reported values, not an official schedule or official revision history. They should be retained as a possible feature or comparison signal, not labelled as ground truth.

## 10. Suitability for Historical Replay

| Use | Assessment | Reasoning |
| --- | --- | --- |
| Reconstruct historical vessel trajectories | **Suitable for many vessels** | Stable identifiers, valid coordinates, nearly 30 days of observations, and median 41 observations per vessel. Sparse vessels and long gaps require filtering. |
| Estimate vessel arrival times | **Conditionally suitable** | Position, speed, course, vessel type, navigation status, and AIS ETA components are available, but there is no labelled official/actual arrival ground truth. A derived estimator and external validation target are needed. |
| Detect when an inbound vessel begins falling behind | **Conditionally suitable** | A causal ETA estimate can be recomputed at each observation, but “behind” needs a schedule/reference ETA absent from the CSV. |
| Measure when a synthetic connection first becomes at risk | **Suitable with explicit synthetic assumptions** | Time-ordered vessel estimates can feed a synthetic outbound connection, cutoff, and transfer-time model. Results are simulation outcomes, not evidence of real PSA connection failures. |
| Create a simple comparison baseline | **Suitable** | A deterministic rules baseline can use latest known position/speed and a fixed or route-based travel-time calculation, with strict as-of-time processing. |

Chronological replay is feasible without future leakage if the engine globally sorts by `timestamp`, advances a replay clock, and exposes only observations with `timestamp <= replay_clock`. Feature calculations, interpolation, normalization, and ETA estimation must use only each vessel's observations available at that clock. Dataset-wide future-derived aggregates must not be used unless fitted on a separate training period.

## 11. Suitability for ETA Estimation

The movement variables are adequate for a first ETA estimator: position, speed, course, heading, navigation status, vessel type, draught, and vessel-reported ETA are available. However, the dataset lacks a clear arrival event, destination coordinates in readable form, route definitions, and authoritative actual arrival timestamps. Therefore it can generate **arrival-time estimates**, but it cannot by itself provide a defensible supervised accuracy score against actual arrival.

A minimal causal estimator could estimate time to a defined Singapore arrival boundary or waypoint using the latest position and speed, with stale/zero-speed handling. A stronger model would need an externally defined destination/arrival geometry and actual arrival labels. AIS ETA may be used as a comparison feature only after sentinel parsing and year inference based solely on information known at the replay timestamp.

## 12. Suitability for the Rules-Based Baseline

The dataset is sufficient for a simple deterministic baseline. At each observation, the baseline can retain the latest vessel state, estimate remaining travel time to an externally defined arrival point/geofence, and compare that estimate with an external or synthetic schedule. This gives LATCH a transparent benchmark for “first risk detected.”

The baseline must not treat file row order as time order, use later points to smooth earlier estimates, infer a completed trajectory before replay time, or use end-of-month statistics computed from the evaluation interval. Sparse-track and stale-observation rules must be fixed in advance.

## 13. Real Data vs Derived or Synthetic Inputs

| Project input                    | Status                | Likely source                       |
| -------------------------------- | --------------------- | ----------------------------------- |
| Vessel observation timestamp     | Real                  | Singapore AIS dataset               |
| Vessel trajectory                | Real                  | Singapore AIS dataset               |
| Speed and course                 | Real                  | Singapore AIS dataset               |
| Arrival-time estimate            | Derived               | ETA estimator                       |
| Official scheduled arrival       | Missing               | OCEANS-X or another source          |
| Inbound-to-outbound connection   | Synthetic             | UCID generator                      |
| Terminal assignment              | Synthetic or external | Project assumptions / external data |
| Inter-terminal transfer duration | Assumed               | Configurable project assumption     |
| Container volume                 | Synthetic             | UCID generator                      |
| Outbound loading cutoff          | Assumed               | Configurable project assumption     |

Additional classification:

- **Real/observed:** anonymised vessel identity within this file, observation time, position, motion fields, navigation status, vessel type, and raw AIS ETA components.
- **Derived:** cleaned trajectories, observation age, geofence crossings, arrival estimates, delay indicators, and first-risk time.
- **Synthetic:** container records, UCIDs, inbound-to-outbound connection graph, and container volumes unless another dataset is obtained.
- **Assumed:** terminal assignment when no external mapping exists, transfer duration, cutoff rules, minimum trajectory length, and risk thresholds.
- **External/unknown:** official schedules and revisions, berth/terminal truth, actual arrivals, PSA operational events, and dataset timezone/provenance documentation.

## 14. Limitations and Risks

- Coverage is only one month, so seasonal, monsoon, congestion, and long-term service-pattern variation cannot be evaluated.
- The typical sampling interval is about 30 minutes, which may miss short operational changes; gaps can be much longer.
- 15.84% of vessel identifiers have fewer than 10 observations; 43 vessels have only one observation.
- AIS data is self-reported and can be stale, miscoded, unavailable, or operationally inaccurate.
- Anonymised destination and identity fields prevent straightforward linkage to schedules or port calls without a trusted crosswalk.
- Primary timestamp timezone is absent; treating it as UTC is an inference from `Rounded_time`, not documented fact.
- AIS ETA has no year and includes sentinel values. Incorrect rollover inference could create large apparent delays.
- No official arrival/departure or connection outcomes exist for accuracy validation.
- Global row order is not chronological and must not be replayed directly.
- The 102.3-knot maximum speed deserves investigation or robust filtering even though it is non-negative and may represent an AIS outlier.

## 15. Final Verdict

**`AMBER` — useful but requires an ETA estimator or important synthetic assumptions.**

The dataset is a credible real-data foundation for replaying Singapore vessel movement chronologically. It is not sufficient as a complete historical LATCH truth set. A defensible demonstration can replay real AIS trajectories and derive causal arrival estimates while clearly labelling schedules, connections, terminals, volumes, transfer times, and cutoffs as external, synthetic, or assumed. It must not claim to reproduce real PSA container-connection outcomes from this CSV alone.

## 16. Recommended Next Steps

1. Obtain the producer's data dictionary and confirm timestamp timezone, AIS units/sentinels, anonymisation stability, and whether rows were resampled to roughly 30-minute cadence.
2. Define a Singapore arrival geofence or waypoint and a causal, deterministic ETA baseline using only observations available at replay time.
3. Seek OCEANS-X or another source for official scheduled arrivals, schedule revisions, and actual port-call timestamps; test whether anonymised AIS records can be linked lawfully and reliably.
4. Freeze and document synthetic/assumed connection, terminal, transfer-duration, volume, and cutoff inputs before evaluation.
5. Exclude or flag sparse/stale trajectories and investigate implausible speeds before calculating performance metrics.

## Appendix A: Inspection Method

Assessment generated: `2026-08-18 15:42:49 +0800` (Asia/Kuala_Lumpur; system rendered zone as `+08`).

- Python used for analysis: `Python 3.10.7` (system interpreter; standard library only).
- Repository-relative CSV path: `Data Inspection/Singapore_anonymized.csv`.
- SHA-256: `a46b6f6f68e5d7f2cc87b3eaa0fe2cc74373cf8e9788b2a3156c4f4644bfad7e`.
- No dependency was installed and the CSV was never modified.

The inspection used streaming `csv.DictReader` passes. Per-column null/type/value checks were accumulated without loading the CSV as a dataframe. A temporary on-disk SQLite database outside the repository stored only vessel ID, timestamp, numeric time, and a SHA-256 row digest. SQL grouping/window operations calculated duplicates, per-vessel counts, and chronologically sorted intervals. The temporary database was deleted on completion.

Key shell commands and analysis approach:

```bash
ls -lh 'Data Inspection/Singapore_anonymized.csv'
stat -f 'bytes=%z modified=%Sm' -t '%Y-%m-%dT%H:%M:%S%z' 'Data Inspection/Singapore_anonymized.csv'
shasum -a 256 'Data Inspection/Singapore_anonymized.csv'
file -I 'Data Inspection/Singapore_anonymized.csv'
wc -l 'Data Inspection/Singapore_anonymized.csv'
python3 --version
```

The Python analysis, executed from standard input with `python3`, performed:

1. streaming header, row-count, lexical missingness, inferred-type, bounds, sentinel, and timestamp parsing checks;
2. streaming SHA-256 row digests for exact-duplicate grouping;
3. temporary SQLite `GROUP BY` checks for exact and vessel/timestamp duplicates;
4. temporary SQLite `LAG(...) OVER (PARTITION BY vessel ORDER BY timestamp)` for observation gaps;
5. streaming checks of global and within-vessel row ordering; and
6. aggregate-only output—no full records or large extracts were retained in this report.

Fractional timestamp digits beyond Python 3.10's microsecond precision were truncated only for interval arithmetic; the original strings were retained for min/max comparison. This can affect reported intervals by less than one microsecond and is immaterial at the observed cadence.

## Appendix B: Key Statistics

| Metric | Value |
| --- | ---: |
| File bytes | 214,671,886 |
| Data rows | 609,975 |
| Columns | 45 |
| Unique vessels (`UserID`) | 5,879 |
| Historical coverage | 29d 23:59:33.051790 |
| Median observations/vessel | 41 |
| Mean observations/vessel | 103.7549 |
| Maximum observations/vessel | 1,063 |
| Median consecutive interval | 1,800.805 s |
| 90th-percentile interval | 3,029.371 s |
| Maximum interval | 2,505,799.426 s |
| Exact duplicate rows | 0 |
| Duplicate vessel/timestamp rows | 0 |
| Malformed primary timestamps | 0 |
| Invalid latitude / longitude | 0 / 0 |
| Negative speed | 0 |
| Globally adjacent timestamp inversions | 4,070 |
| Vessels with fewer than 10 observations | 931 (15.84%) |
| Rows with ordinary-range AIS ETA components | 586,838 (96.21%) |
| Rows with unavailable heading sentinel (`511`) | 64,331 (10.55%) |
| Rows with unavailable rate-of-turn sentinel (`-128`) | 70,481 (11.55%) |

## Stage 2: Trajectory and Arrival Feasibility

### Stage 2 conclusion

**Feasibility result: sufficient for the historical experiment prototype, but not validated as real PSA arrivals.**

Using the explicitly exploratory circular boundary described below, 694 vessels produced a first outside-to-inside crossing and 611 produced a usable `derived_geofence_arrival`. This exceeds the preconfigured feasibility threshold of 30 usable events. The count is large enough to proceed with historical replay and a later ETA experiment, subject to boundary validation.

This is an **interpretation of a project-defined geofence**, not evidence of 611 actual port or terminal arrivals. The boundary is not an official PSA terminal, berth, pilot-station, or port limit. Some crossings may represent transit traffic, anchorage movement, or repeat local movement. An authoritative boundary or port-call source is still needed before reporting arrival accuracy or operational performance.

### Prototype implementation

The replay and feasibility prototype is implemented in `src/latch/replay.py`, with focused coverage in `tests/test_replay.py`. It:

- streams selected CSV fields into a temporary disk-backed SQLite database rather than loading the full CSV into Python memory;
- globally sorts by the exact source timestamp string, then original source row number as a deterministic stable tie-breaker;
- parses the primary timestamp and attaches configurable timezone metadata;
- defaults to UTC while recording `timezone_assumption_confirmed = false`;
- uses `UserID` as the stable anonymised vessel identifier;
- converts recognised AIS sentinels to unavailable values, including speed `102.3`, course `360`, heading `511`, rate of turn `-128`, navigation status `15`, and invalid ETA components;
- preserves all observations and attaches quality flags rather than silently deleting rows;
- permits explicit quality-based exclusion only when evaluating whether a derived event is usable;
- detects the first outside-to-inside crossing per vessel and names it `derived_geofence_arrival`; and
- calculates each ETA revision from only the current observation's position and speed, so later trajectory points cannot affect an earlier estimate.

AIS-reported ETA remains in each observation as an optional comparison field. It is not used as an official schedule, official revision history, or arrival label.

### Configured assumptions

| Configuration | Prototype value | Classification |
| --- | ---: | --- |
| Primary timestamp timezone | UTC, unconfirmed | Project assumption inferred from `Rounded_time` |
| Boundary label | `exploratory_singapore_waypoint_not_official` | Project label |
| Boundary centre | 1.264° N, 103.840° E | Exploratory project assumption |
| Boundary radius | 5.0 km | Exploratory project assumption |
| Sparse-track threshold | Fewer than 10 observations | Evaluation assumption |
| Stale-observation threshold | Previous vessel observation older than 60 minutes | Evaluation assumption |
| Long-gap threshold | Previous vessel observation older than 6 hours | Evaluation assumption |
| Implausible-speed threshold | Greater than 50 knots after AIS sentinel handling | Evaluation assumption |
| Minimum pre-event observations | 3 | Evaluation assumption |
| Minimum speed for ETA | 0.5 knots | Prototype assumption |
| Feasibility threshold | 30 usable events | Project decision threshold |

The full-data feasibility run excluded an event from the usable count when its vessel had fewer than 10 total observations, the crossing followed a gap longer than 6 hours, the crossing observation had an implausible non-sentinel speed, or fewer than 3 observations existed before the crossing. Stale observations and unavailable heading/rate of turn were flagged and retained but were not, by themselves, event exclusions.

Using total per-vessel observation count for sparse-track exclusion is dataset-level evaluation metadata. It is not an input to the causal ETA calculation and must not become a feature available to the replay-time detector.

### Aggregate feasibility results

| Result | Value | Classification |
| --- | ---: | --- |
| Vessels assessed | 5,879 | Derived calculation |
| Observations assessed | 609,975 | Derived calculation |
| Vessels crossing boundary | 694 | Derived event count |
| Usable `derived_geofence_arrival` events | 611 | Derived event count after configured exclusions |
| Preconfigured sufficiency threshold | 30 | Project assumption |
| Boundary sufficient for prototype experiment | Yes | Interpretation against threshold |

Usable events had the following history available before their crossing:

| Metric | Minimum | Median | Mean | Maximum |
| --- | ---: | ---: | ---: | ---: |
| Observations before event | 3 | 27 | 96.35 | 961 |
| Available lookback (hours) | 1.10 | 30.22 | 118.91 | 705.53 |

Quality flags were counted per observation, not per vessel:

| Quality flag | Flagged observations |
| --- | ---: |
| Fewer than 10 vessel observations | 5,808 |
| Stale observation (>60 minutes since prior vessel observation) | 26,484 |
| Long observation gap (>6 hours) | 9,320 |
| Implausible non-sentinel speed (>50 knots) | 2 |
| Heading unavailable (`511`) | 64,331 |
| Rate of turn unavailable (`-128`) | 70,481 |

Event exclusion reasons can overlap. There were 37 crossings with fewer than three preceding observations, 46 whose crossing followed a long gap, and 3 on sparse vessel tracks. These reasons reduced 694 crossings to 611 usable events; the reason total is greater than the excluded-event total because some events had more than one reason.

### Example causal ETA revisions

The ETA below is a deliberately simple straight-line estimate to the circular boundary at current speed over ground. It is a causal plumbing prototype, not the full ETA model.

| Vessel | Observation time (UTC assumed) | ETA at that observation | Distance to boundary | Speed | Derived crossing |
| --- | --- | --- | ---: | ---: | --- |
| `1342` | 2023-10-01 00:14:57 | 2023-10-01 01:01:45 | 8.96 km | 6.2 kn | 2023-10-01 01:37:59 |
| `1342` | 2023-10-01 00:28:18 | 2023-10-01 01:10:13 | 6.73 km | 5.2 kn | 2023-10-01 01:37:59 |
| `1342` | 2023-10-01 01:14:09 | 2023-10-01 01:19:03 | 1.00 km | 6.6 kn | 2023-10-01 01:37:59 |
| `276` | 2023-10-01 00:14:53 | 2023-10-01 00:47:19 | 8.11 km | 8.1 kn | 2023-10-01 02:14:44 |
| `276` | 2023-10-01 00:28:13 | 2023-10-01 01:02:00 | 5.63 km | 5.4 kn | 2023-10-01 02:14:44 |
| `276` | 2023-10-01 01:15:03 | 2023-10-01 01:19:06 | 1.55 km | 12.4 kn | 2023-10-01 02:14:44 |
| `4904` | 2023-10-01 01:37:44 | 2023-10-01 03:04:05 | 7.20 km | 2.7 kn | 2023-10-01 03:10:34 |
| `4904` | 2023-10-01 02:14:24 | 2023-10-01 02:39:30 | 3.64 km | 4.7 kn | 2023-10-01 03:10:34 |
| `4904` | 2023-10-01 02:24:24 | 2023-10-01 02:45:10 | 2.95 km | 4.6 kn | 2023-10-01 03:10:34 |

These revisions demonstrate that estimates change as new observations arrive. They also demonstrate why a full model is not yet justified: straight-line constant-speed ETA can be early or unstable when a vessel slows, turns, anchors, or follows a channel.

### Determinism, causality, and test results

The focused tests cover:

- global chronological ordering and source-row tie-breaking;
- identical early ETA output when later trajectory rows are changed;
- recognised AIS sentinel conversion;
- preservation and flagging of stale and long-gap observations;
- preservation of sparse/implausible observations with configured event exclusion;
- deterministic repeated feasibility results; and
- use of the `derived_geofence_arrival` name.

Command executed:

```bash
UV_CACHE_DIR=/tmp/latch-uv-cache uv run pytest -q
```

Result: **89 passed**. The cache override kept tool cache files outside the repository.

Full-data feasibility command:

```bash
UV_CACHE_DIR=/tmp/latch-uv-cache uv run python -m latch.replay \
  'Data Inspection/Singapore_anonymized.csv'
```

The command emits aggregate JSON only. Temporary SQLite databases are created in the operating-system temporary directory and deleted when iteration finishes. No replay dataset, cache, or temporary database is committed or retained in the repository.

### Decision before a full ETA model

Proceed to a fuller ETA experiment only after treating the following as gates:

1. validate or replace the exploratory waypoint/geofence using an authoritative port-call or boundary source;
2. confirm the primary timestamp timezone;
3. define what counts as an inbound arrival rather than transit or local re-entry;
4. obtain actual arrival labels or an external port-call reference for accuracy evaluation; and
5. freeze a train/evaluation split so route or vessel statistics cannot leak future evaluation observations.

Until those gates are met, the Stage 2 result supports **event-volume feasibility**, not arrival-label validity or ETA accuracy. No synthetic UCID generator was built in this stage.
