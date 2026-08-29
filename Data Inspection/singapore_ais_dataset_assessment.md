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

### Source attribution and licence

The source dataset is [*AIS Data from 11 ports around the globe*, version 1](https://doi.org/10.17632/r37vwd493d.1), DOI `10.17632/r37vwd493d.1`. Its contributors/dataset creators are Andreas Hadjipieris, Neofytos Dimitriou, and Ognjen Arandjelovic. The Mendeley record identifies the AISStream.io API as the original collection source and publishes the dataset under the [Creative Commons Attribution 4.0 International licence (CC BY 4.0)](https://creativecommons.org/licenses/by/4.0/).

This project uses the Singapore subset and the anonymised vessel identifiers
supplied by the dataset. For the historical experiment, it modifies and
transforms the source data by sorting observations chronologically, handling
AIS unavailable/sentinel values, applying exploratory geofence segmentation,
creating deterministic derived call identities, and creating position-derived
arrival estimates. These derived and transformed fields are project outputs;
they are not claimed to be official PSA records. The dataset licence applies
to the dataset and its use here; this attribution does not assert or add a
licence for the team's original source code.

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
- **Derived:** cleaned trajectories, historical observation-quality/gap flags, geofence crossings, arrival estimates, delay indicators, and first-risk time.
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

Using the explicitly exploratory circular boundary described below, 694 vessels produced a first outside-to-inside crossing and 611 produced a benchmark-eligible `derived_geofence_arrival` under the initial Stage 2 rule. This exceeds the preconfigured feasibility threshold of 30 benchmark-eligible events. The count is large enough to proceed with historical replay and a later ETA experiment, subject to boundary validation.

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
- permits explicit quality-based exclusion only when evaluating whether a derived event is benchmark-eligible;
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
| Feasibility threshold | 30 benchmark-eligible events | Project decision threshold |

The full-data feasibility run excluded an event from the benchmark-eligible count when its vessel had fewer than 10 total observations, the crossing followed a gap longer than 6 hours, the crossing observation had an implausible non-sentinel speed, or fewer than 3 observations existed before the crossing. Stale observations and unavailable heading/rate of turn were flagged and retained but were not, by themselves, event exclusions.

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

Event exclusion reasons can overlap. There were 37 crossings with fewer than three preceding observations, 46 whose crossing followed a long gap, and 3 on sparse vessel tracks. These reasons reduced 694 crossings to 611 benchmark-eligible events; the reason total is greater than the excluded-event total because some events had more than one reason.

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

## Stage 3: Arrival-event validation and causal arrival updates

### Stage 3 conclusion

The Stage 2 event-volume gate remains passed after replacing the one-event-per-vessel shortcut with deterministic approach episodes. The corrected run found 1,853 raw outside-to-inside candidate crossings. It accepted 1,382 reset-confirmed calls and neutrally classified 471 crossings as `crossings_suppressed_before_reset`. Of the accepted calls, 886 are benchmark-eligible and 496 are benchmark-excluded with explicit reasons.

These remain `derived_geofence_arrival` events at an **exploratory, non-official** boundary. They are not official PSA calls, schedules, berth arrivals, or accuracy labels. `reference_arrival` is also derived: it is the first eligible causal prediction in an approach episode, not an official schedule.

No synthetic UCID generator or Watcher was implemented. The raw AIS CSV was not modified, and the analysis retained no generated replay dataset, cache, or temporary database.

This historical benchmark is conditioned on reset-confirmed, derived
boundary-crossing calls. It does not evaluate scheduled calls that were
cancelled, diverted, disappeared from AIS coverage, or did not cross the
exploratory boundary during the data window. An approach without an observed
crossing is not evidence of a failed arrival: it could be unscheduled,
diverted, transiting, anchored, outside AIS coverage, or right-censored by the
data window. Unfinished armed episodes are therefore neither emitted nor
counted as negative training or evaluation labels; a future analysis could
report them separately as `right_censored_approach` with `outcome = UNKNOWN`.

PR #2 predicts vessel arrival timing. The later Watcher will predict whether a
synthetic inbound-to-outbound container connection is feasible. Its later
positive and negative evaluation labels will be `connection_feasible` and
`connection_infeasible`; they will not be “vessel crossed the boundary” and
“vessel did not cross the boundary.”

### Crossing and reset rule

An accepted call must be an observed outside-to-inside crossing: the immediately preceding vessel position is more than 5.0 km from the configured centre and the crossing position is at or within 5.0 km. The implementation uses boundary hysteresis to define approach episodes:

1. An initially outside vessel begins an armed approach episode.
2. An armed outside-to-inside crossing becomes one accepted call.
3. After that crossing, the vessel is disarmed.
4. It can be rearmed only after **two consecutive vessel observations** are each at least 2.0 km beyond the boundary, or 7.0 km from the configured centre.
5. A point inside the reset radius clears a partial confirmation. One isolated point beyond the reset radius therefore cannot create a repeat call.
6. Outside-to-inside recrossings before confirmation are counted neutrally as `crossings_suppressed_before_reset` rather than asserted to be jitter or duplicates.

This deterministic rule permits reset-separated visits by the same vessel while reducing sensitivity to one noisy reset-distance point. It does not prove that every accepted event is an official or genuinely distinct port call. The 2.0 km distance and two-observation confirmation are exploratory assumptions and are emitted in the report configuration. Changing boundary geometry requires a new `boundary.version`; the current geometry version is `exploratory-circle-v1`.

`call_id` is separate from `vessel_id` and is the stable prefix `call_` plus the first 20 hexadecimal characters of SHA-256 over boundary version, vessel ID, crossing timestamp, and crossing source-row number. Thus identical input and configuration reproduce the same ID, while reset-separated visits by one vessel receive different IDs.

### Causal update rule and schema

For every accepted call, the unfiltered historical update stream is ordered by `observed_at`, original source-row number, then `call_id`. Each available `predicted_arrival` is the observation time plus straight-line distance to the boundary divided by that observation's speed over ground. It uses only that row and prior continuous-segment state. No later trajectory point, crossing time, total future track length, or later AIS value is a prediction input.

`CausalArrivalUpdate` is the causal-value projection. It contains no `derived_geofence_arrival`, benchmark eligibility, exclusion reason, or other crossing outcome. `DerivedArrivalEvent` separately owns the retrospective crossing timestamp and call-level evaluation metadata. Historical `call_id` membership is necessarily segmented retrospectively for this AIS benchmark; it is an association key, not a claim that the future crossing was known at update time. Consequently, this is not presented as a fully live call-membership stream.

The canonical unfiltered API is
`iter_retrospectively_segmented_arrival_updates`, which emits updates from all
1,382 accepted calls, including the 496 calls later excluded from the
benchmark. `iter_eligible_benchmark_updates` is the separately named selection
API and emits updates only from the 886 retrospectively benchmark-eligible
calls. Eligibility is read from `DerivedArrivalEvent.benchmark_eligible`; it
never changes the causal values held by an update.

Every retained pre-event observation produces a causal update with `prediction_status = AVAILABLE` or `INELIGIBLE`. Ineligible updates have `predicted_arrival = null` and retain their reason codes. Only available updates count toward `eligible_pre_event_observations`. The first available prediction in the current continuous segment becomes the derived `reference_arrival`. Earlier ineligible updates have `reference_arrival = null`; later updates carry the reference already known by then.

Source event-time replay consumes an observation at its own timestamp, but that fact is not downstream freshness and is no longer represented as a zero-valued update field. At a later assessment time, the downstream contract is `data_age_minutes = assessed_at - source_update.observed_at`, expressed in elapsed minutes. Both timestamps must be timezone-aware, and an assessment before the source observation is rejected rather than producing a negative age. For example, an observation at 12:00 assessed at 14:00 has `data_age_minutes = 120`. Stale-observation and long-observation-gap reason codes remain separate descriptions of historical observation quality.

Each update contains:

- `call_id`, `vessel_id`, and `observed_at`;
- `prediction_status`, derived causal `reference_arrival`, and nullable causal `predicted_arrival`;
- `data_quality` and historical `quality_reason_codes`;
- `source_type = real_ais_observation` and `boundary_version`; and
- the complete `source_observation`, including original source-row provenance and retained real AIS fields.

The source observation is nested rather than overwritten. Recognised AIS unavailable sentinels become `None` with explicit flags; no real speed, course, heading, turn rate, status, position, or AIS-reported ETA is replaced by a derived prediction.

The fewer-than-10-observations sparse-track classification depends on the
whole historical vessel track. It is therefore attached only to retrospective
`DerivedArrivalEvent` quality/eligibility metadata and aggregate reporting, not
to `VesselObservation` or `CausalArrivalUpdate` reason codes.

### Prediction eligibility and quality handling

| Condition | Deterministic handling |
| --- | --- |
| Zero or speed below 0.5 knots | Retain observation; add `zero_or_near_zero_speed`; do not predict from it |
| Speed above 50 knots | Retain value; add `implausible_speed`; do not predict from it |
| AIS speed unavailable (`102.3` or blank) | Preserve as unavailable; add `speed_unavailable`; do not predict from it |
| Stale observation (>60 minutes since prior vessel message) | Retain and flag; do not predict from it |
| Long gap (>6 hours) | Break the prior continuous approach segment; retain the gap-bearing outside row as `INELIGIBLE`; derive any new reference only from a later eligible outside row |
| Moving away by more than 0.05 km versus the prior episode point | Retain; add `moving_away_from_boundary`; do not predict from it |
| Fewer than 3 eligible pre-event observations after the most recent continuity break | Accept crossing identity; keep its updates in the unfiltered retrospectively segmented stream; exclude the call only from the explicit benchmark iterator |
| Missing/unavailable course, heading, turn rate, navigation status, or AIS ETA | Preserve as unavailable with applicable flags; these non-speed fields are not fabricated and do not drive the baseline ETA |
| Missing required vessel ID, timestamp, latitude, or longitude | Reject explicitly during CSV validation/parsing; a crossing cannot be derived without these fields |

Configured call exclusions continue to apply to crossing-row quality. The full-data run used the Stage 2 convention that sparse tracks, crossing rows after long gaps, and crossing rows with implausible speed are excluded. Reasons can overlap, so reason totals need not equal excluded-call totals.

### Aggregate validation report

| Result | Value |
| --- | ---: |
| Vessels assessed | 5,879 |
| Raw candidate crossings | 1,853 |
| Crossings suppressed before reset confirmation | 471 |
| Accepted calls | 1,382 |
| Vessels represented by accepted calls | 688 |
| Benchmark-eligible calls | 886 |
| Benchmark-excluded calls | 496 |

Accepted-call data quality was 158 `good`, 728 `degraded`, and 496 `excluded`. The unfiltered retrospectively segmented stream across all accepted calls contains 35,379 updates: 6,766 `AVAILABLE` and 28,613 `INELIGIBLE`. The explicit benchmark iterator contains 30,832 updates from benchmark-eligible calls only: 6,303 `AVAILABLE` and 24,529 `INELIGIBLE`. The difference is 4,547 retained updates from benchmark-excluded calls. Degraded does not mean discarded: for example, unavailable heading or a moving-away row remains visible in provenance while eligible rows in the same call can still produce predictions.

Exclusion reasons were:

| Reason | Calls |
| --- | ---: |
| Fewer than 3 eligible pre-event observations in the current segment | 494 |
| Crossing after a long observation gap | 111 |
| Sparse vessel track | 2 |

Eligible pre-event history percentiles for benchmark-eligible calls were:

| Metric | Min | P05 | P25 | P50 | P75 | P95 | Mean | Max |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Eligible observations | 3 | 3 | 4 | 6 | 8 | 15 | 7.11 | 44 |
| Lookback hours | 1.02 | 1.66 | 3.17 | 7.98 | 25.24 | 55.38 | 16.57 | 109.79 |

Observation-level quality counts were 5,808 sparse-track, 26,484 stale, 9,320 long-gap, 2 implausible-speed, 1,616 speed-unavailable, 17,141 course-unavailable, 64,331 heading-unavailable, and 70,481 rate-of-turn-unavailable flags.

Accepted calls by day:

| UTC-assumed day | Calls | UTC-assumed day | Calls | UTC-assumed day | Calls |
| --- | ---: | --- | ---: | --- | ---: |
| Oct 1 | 54 | Oct 10 | 44 | Oct 19 | 60 |
| Oct 2 | 70 | Oct 11 | 32 | Oct 20 | 59 |
| Oct 3 | 66 | Oct 12 | 43 | Oct 21 | 69 |
| Oct 4 | 59 | Oct 13 | 55 | Oct 22 | 6 |
| Oct 5 | 64 | Oct 14 | 51 | Oct 25 | 57 |
| Oct 6 | 50 | Oct 15 | 28 | Oct 26 | 54 |
| Oct 8 | 25 | Oct 16 | 60 | Oct 27 | 58 |
| Oct 9 | 61 | Oct 17 | 67 | Oct 28 | 46 |
|  |  | Oct 18 | 49 | Oct 29 / Oct 30 | 50 / 45 |

Days absent from the table had zero accepted calls under this boundary and reset rule.

### Human-readable validation sample

| Category | Vessel / call | Evidence |
| --- | --- | --- |
| Normal approach | `1342` / `call_c61c839ab9468d39473a` | Three eligible, unflagged updates before the 2023-10-01 01:37:59 crossing |
| Sparse track | `1369` / `call_fdbe1b5141e466c794a4` | Seven eligible observations retained; call excluded by the fewer-than-10-total-observations convention |
| Stale track | `4712` / `call_6d8dec6507db08a91053` | Stale and zero/near-zero-speed rows retained; only two eligible rows, so call excluded |
| Suspected duplicate recrossing | `4499` at 2023-10-01 02:12:06 | Recrossing suppressed because the vessel had not completed two observations beyond the 7.0 km reset radius |
| Repeated visits | `4678` | Eleven calls were separated by the confirmed reset; each has a distinct deterministic `call_id` |
| Moving away | `4564` / `call_38b3fae3f7ebf3d68df2` | Moving-away and zero/near-zero-speed rows are retained as ineligible updates; six available predictions remain |

The repeated-visit sample demonstrates the configured episode semantics, not twelve independently verified official port calls.

### Example causal call timelines

Times below use the unconfirmed UTC assumption. The outcome is shown for retrospective interpretation only.

| Call | Observed at | Status | Predicted arrival | Reference arrival | Retrospective outcome |
| --- | --- | --- | --- | --- | --- |
| `call_c61c839ab9468d39473a` | 2023-10-01 00:14:57 | available | 2023-10-01 01:01:45 | 2023-10-01 01:01:45 | 2023-10-01 01:37:59 |
|  | 2023-10-01 00:28:18 | available | 2023-10-01 01:10:13 | 2023-10-01 01:01:45 |  |
|  | 2023-10-01 01:14:09 | available | 2023-10-01 01:19:03 | 2023-10-01 01:01:45 |  |
| `call_38b3fae3f7ebf3d68df2` | 2023-10-01 01:13:00 | available | 2023-10-01 02:46:56 | 2023-10-01 02:46:56 | 2023-10-01 06:12:01 |
|  | 2023-10-01 03:10:00 | ineligible: moving away, near-zero speed | null | 2023-10-01 02:46:56 |  |
|  | 2023-10-01 03:44:09 | ineligible: near-zero speed | null | 2023-10-01 02:46:56 |  |
|  | 2023-10-01 05:14:20 | available | 2023-10-01 05:40:01 | 2023-10-01 02:46:56 |  |
| `call_f95b53341cab0374559f` | 2023-10-01 23:10:57 | ineligible: long gap | null | null | 2023-10-02 02:39:33 |
|  | 2023-10-01 23:44:46 | available | 2023-10-02 01:33:32 | 2023-10-02 01:33:32 |  |
|  | 2023-10-02 00:13:52 | available | 2023-10-02 01:13:43 | 2023-10-02 01:33:32 |  |
|  | 2023-10-02 01:29:04 | available | 2023-10-02 01:39:23 | 2023-10-02 01:33:32 |  |

The `call_f95…` example demonstrates the continuity rule: its gap-bearing row is retained, but the reference begins at the first later available update rather than spanning the prior track. The examples also show the limitations of a straight-line current-speed baseline: an update can remain substantially early when a vessel later slows, turns, waits, or follows a channel. The retrospective outcome column is presented only for assessment and is absent from `CausalArrivalUpdate`.

### Stage 3 verification

The automated suite covers future-data isolation at and before a cutoff,
non-empty early-record stability when later observations change benchmark
eligibility, deterministic call IDs and predictions, retained updates from
benchmark-excluded accepted calls, explicit benchmark filtering, the
outcome-free causal projection, downstream data-age validation, confirmed reset
suppression, multiple reset-separated calls by one vessel, stable chronological
sorting, stale and long-gap segment handling, first-available reference
selection, missing/sentinel speed, and preservation of source provenance and
quality flags.

```bash
UV_CACHE_DIR=/tmp/latch-uv-cache uv run pytest -q
```

Result after the Stage 3 review pass: **105 passed**.

## Stage 4: Synthetic connection topology and UCID contract

### Scope and causal boundary

`latch.synthetic` is a deterministic synthetic benchmark-generation layer.
PR #3 consumes `iter_retrospectively_segmented_arrival_updates`, not
`DerivedArrivalEvent` and not the retrospectively benchmark-eligible iterator.
The population nevertheless remains retrospectively segmented into accepted
PR #2 calls because PR #2 does not expose a completely live call-population
primitive. This limitation is structural and must remain visible in any later
historical result.

`latch.synthetic` is not currently wired into the existing runtime/demo
connection path based on `latch.connections`. Existing Watcher,
historical-run, demo, console, and deck figures are not outputs of
`latch.synthetic`. Integrating it with, or replacing, the runtime connection
layer is a separate future integration decision.

The source `call_id` is used only to group updates long enough to locate the
first `AVAILABLE` update. That update is immediately projected into
`SyntheticCallCandidate`. The projection contains the causal observation time,
first reference arrival, source observation row, boundary version, and source
type. It contains no vessel, candidate, or call identifier. The generator does
not consume `derived_geofence_arrival`, benchmark eligibility, exclusion
reasons, later predictions, or crossing metadata for candidate ordering,
pairing, seeded rank, UCID identity, process assumptions, or difficulty.

An anonymised vessel ID and the PR #2 source call ID survive only in
`UCIDAssignment` for audit lineage. Vessel ID is additionally used as a guard
that prevents the same vessel from being both sides of a connection. It is not
part of candidate ordering, candidate digest, or seeded pairing rank.

### UCID identity and terminal topology

The synthetic UCID identifies a time-bound reference-arrival connection slot
rather than the calls temporarily assigned to it. Its identity consists only
of:

- port UN/LOCODE `SGSIN`;
- origin and destination `Terminal`;
- the immutable reference-arrival window formed by the inbound and outbound
  first-`AVAILABLE` causal reference arrivals;
- topology/schema version; and
- deterministic sequence and canonical SHA-256 digest.

It excludes vessel-call assignments, candidate/call/vessel IDs, process
scenario, cargo-ready offset, transfer mode or duration, cargo cut-off lead,
planned cut-off, planning margin, difficulty, impact, and optional box count.
Consequently LOW, REFERENCE, and CONSERVATIVE projections of one connection
share one UCID, and changing an assignment without changing the planned slot
does not create a different connection identity.

The reference-arrival window is the immutable interval between those two
causal reference arrivals used to identify this synthetic benchmark
connection. It is not an official vessel schedule, berth window, cargo cutoff
window, or PSA service window. It is frozen before any process scenario is
projected.

Topology quotas contain only terminal direction, transfer mode, an optional
raw reference-arrival-gap band, impact band, and exact count. Raw gap is
`outbound_reference_arrival - inbound_reference_arrival`; it is causal and
scenario-independent. A deterministic global matching step assigns unique
ordered candidate pairs across all requested quota slots. Difficulty is not a
topology input and is computed only after UCIDs are frozen.

The core terminal set is Tuas and Pasir Panjang, reusing `Terminal` and always
recording `TerminalResolution.SIMULATED` for assignments. SMDG Terminal Code
List v20260609 identifiers are stored as two fields rather than concatenated:

| Terminal | Port UN/LOCODE | SMDG terminal code |
|---|---|---|
| Tuas | `SGSIN` | `PSATUA` |
| Pasir Panjang | `SGSIN` | `PSAPPT` |

Same-terminal connections use transfer mode `NONE` and zero transfer duration.
Inter-terminal connections use `ROAD` or `SEA`, with duration supplied by the
experimental scenario configuration. `cargo_ready_offset` already absorbs
generic terminal handling before an IGT leg.

### Timing model and provenance

The only process timing equations are:

```text
cargo_ready_at = inbound_reference_arrival + cargo_ready_offset
planned_cutoff = outbound_reference_arrival - cargo_cutoff_lead
planning_margin = planned_cutoff - cargo_ready_at - transfer_duration
```

There is no synthetic outbound departure or service duration, and no separate
discharge or yard-release duration. `impact_band` is required; an exact
synthetic `box_count` is optional.

Every registered value carries two independent axes: `ValueOrigin` is REAL,
DERIVED, or SYNTHETIC; `AssumptionBasis` is PUBLIC_ANCHOR, EXPERIMENTAL, or
NOT_APPLICABLE. The important classifications are:

| Field or choice | Value origin | Assumption basis |
|---|---|---|
| AIS source fields | REAL | NOT_APPLICABLE |
| First `AVAILABLE` reference arrival | DERIVED | NOT_APPLICABLE |
| Reference-arrival window and raw gap | DERIVED | NOT_APPLICABLE |
| Optional raw-gap quota band | SYNTHETIC | EXPERIMENTAL |
| Candidate ID | DERIVED | NOT_APPLICABLE |
| Retrospective source-call lineage | DERIVED | EXPERIMENTAL |
| Anonymised vessel lineage | REAL | NOT_APPLICABLE |
| Tuas/Pasir Panjang identities | REAL | PUBLIC_ANCHOR |
| Terminal assignment and candidate pairing | SYNTHETIC | EXPERIMENTAL |
| Transfer-mode assignment and duration | SYNTHETIC | EXPERIMENTAL |
| Process scenario/configuration, `cargo_ready_offset`, and `cargo_cutoff_lead` | SYNTHETIC | EXPERIMENTAL |
| `cargo_ready_at`, `planned_cutoff`, `planning_margin`, and difficulty band | DERIVED | EXPERIMENTAL |
| Impact band and optional exact box count | SYNTHETIC | EXPERIMENTAL |

The public evidence set is intentionally limited to:

1. UNECE/SMDG, *White Paper on Transshipment: the potential of closer
   integration between actors in the transport industry*, November 2025, for
   UCID, connection feasibility, and the feeder cargo cut-off context.
2. MPA/PSA, *Expression of Interest to Design and Develop Autonomous
   Inter-Gateway Feeder*, 2026, for the Pasir Panjang/Tuas cluster context and
   road/sea IGT modes.
3. MPA/PSA, *aIGF EOI Clarifications*, 2026, for the approximately 13 nm route
   and four-hour aIGF transit mission-profile reference.
4. SMDG Terminal Code List v20260609 for `SGSIN` + `PSAPPT` and `SGSIN` +
   `PSATUA`.

The four-hour figure is evidence metadata only. It is not a total container
transfer time and never supplies a road or sea duration. Likewise, the
configured cut-off lead is an experimental benchmark assumption informed by
the white paper's statement that feeder cut-off is generally only a few hours
before arrival; it is not presented as an official PSA rule.

### Tiny deterministic fixture

PR #3 commits only three requested topology quota cells:

| Origin → destination | Mode | Raw reference-arrival-gap band | Impact | Count | Exact boxes |
|---|---|---|---|---:|---:|
| Tuas → Tuas | NONE | 6 h to <12 h | SMALL | 1 | omitted |
| Tuas → Pasir Panjang | ROAD | <6 h | MEDIUM | 1 | 24 |
| Pasir Panjang → Tuas | SEA | ≥13 h | LARGE | 1 | 60 |

These cells are a contract fixture, not a complete Cartesian product and not
an estimate of PSA prevalence. The fixed seed is
`latch-pr3-tiny-fixture-seed`. LOW/REFERENCE/CONSERVATIVE assumptions are:

**TEST-ONLY SYNTHETIC FIXTURE VALUES. NOT PSA OPERATIONAL ESTIMATES OR
PREVALENCE.**

| Scenario | Cargo-ready offset | Cargo cut-off lead | Road duration | Sea duration |
|---|---:|---:|---:|---:|
| LOW | 1 h | 2 h | 0.75 h | 1.5 h |
| REFERENCE | 2 h | 3 h | 1 h | 2 h |
| CONSERVATIVE | 3 h | 4 h | 2 h | 3 h |

Difficulty is projected independently for every scenario: negative margin is
INFEASIBLE, zero to less than 2 hours is TIGHT, 2 to less than 6 hours is
STANDARD, and at least 6 hours is COMFORTABLE. Generation is pure and
canonical. Deterministic global allocation succeeds whenever the requested
slots have a feasible unique-pair matching and raises `ImpossibleQuotaError`
without partial output otherwise.

PR #3 itself implements no Watcher states, outcome labels, no-ITT risk
evaluation, delay baseline, historical performance or lead-time metrics,
agent logic, UI, or API integration. PR #4 adds a separate causal assessment
path; historical quota design and the actual full-data experiment remain
deferred to PR #5.

Candidate-pair enumeration and SHA-256 ranking are currently quadratic in the
candidate count for each quota cell. Historical CSV generation remains
intentionally disabled. Before enabling full historical generation, this
scalability cost must be addressed or explicitly accepted with a bounded input
size; it is not a merge blocker for the tiny contract fixture.

### Stage 4 verification

Focused tests cover fixed-seed determinism, input permutation, actual
final-crossing changes, source-call rekeying, anonymised vessel-ID changes,
self-vessel rejection, mode/topology constraints, UCID stability under call
reassignment, end-to-end process sensitivity and impact changes, independent
provenance completeness, exact and impossible quotas, overlapping-pool global
allocation, input immutability, the unfiltered PR #2 adapter, CLI rejection of
unconfigured historical CSV generation, and byte-equivalent regeneration of
the committed fixture.

## Stage 5: PR #4 causal connection-risk Watcher

### Runtime assessment contract

PR #4 joins a fixed PR #3 `SyntheticConnection` to the latest `AVAILABLE` PR
#2 `CausalArrivalUpdate` for each source call at or before an explicit
`assessed_at`. It selects exactly the configured LOW, REFERENCE, or
CONSERVATIVE process projection. It does not regenerate topology or UCIDs and
does not reuse the projection's reference-time `cargo_ready_at`,
`planned_cutoff`, `planning_margin`, or difficulty as current risk output.

The current calculation is:

```text
inbound_cargo_ready_at = inbound_predicted_arrival + cargo_ready_offset
outbound_cargo_cutoff = outbound_predicted_arrival - cargo_cutoff_lead
current_plan_ready_at = inbound_cargo_ready_at + transfer_duration
current_plan_slack = outbound_cargo_cutoff - current_plan_ready_at
no_itt_slack = outbound_cargo_cutoff - inbound_cargo_ready_at
```

The warning margin is configured by the caller. Available assessments are
SAFE above that margin, WATCH when slack is positive through and including the
margin, and AT_RISK at zero or below. `UNAVAILABLE` is an assessment status,
not a severity, and is returned without fabricated slack when either leg lacks
a causal prediction. Terminal prevention is avoidable exactly when
`current_plan_slack < 0` and `no_itt_slack >= 0`. For same-terminal
connections the benchmark invariant requires mode NONE and zero transfer
duration, so both slack values are equal.

Watcher-level quality is the weaker GOOD/DEGRADED quality of the two selected
AIS-derived updates. That observation quality is kept separate from explicit
synthetic/experimental provenance for terminals and process assumptions. An
available assessment with an exact synthetic box count can be adapted to the
legacy `RiskEvent`/Agent Core boundary. The adapter preserves actual PR #2
reference and predicted arrivals; it does not manufacture vessel times from
slack. Unavailable or box-count-free assessments are not adapted into work.

### Derived reference-delay baseline

The deliberately simple derived reference-delay baseline accepts only the
selected inbound causal update, assessment time, and configured threshold:

```text
delay = inbound_predicted_arrival - inbound_reference_arrival
alert = delay >= configured_threshold
```

It ignores outbound timing, terminal assignment, topology, transfer mode and
duration, cargo assumptions, boxes, and the no-ITT counterfactual. The
reference is the first available derived PR #2 prediction, not an official
vessel schedule. Neither this threshold nor the Watcher warning margin or PR
#3 process settings is a PSA or industry operating standard.

### Anti-hindsight boundary

Selection rejects updates observed after `assessed_at` and retains the latest
earlier available prediction even if a later ineligible row exists. It never
falls back to a final derived geofence crossing, later trajectory point,
retrospective benchmark eligibility or call-level quality, future ETA
revision, PR #3 reference-window timing, or final connection outcome.
Historical `call_id` is only an opaque join key. Because call membership was
retrospectively segmented in PR #2, this remains an explicit benchmark
limitation rather than a claim of fully live call discovery.

PR #4 adds no outcome labels, recall, precision, lead-time metric, false-alert
rate, sensitivity experiment, or headline historical result. Those evaluation
questions remain PR #5 scope. The synthetic connections and assumptions are
not actual PSA operational data.

## Stage 6: PR #5 Phase 2 causal historical Watcher foundation

The separate `scripts/run_historical.py --mode watcher-eval` path now composes
PR #2 real AIS-derived causal arrival updates, PR #3 synthetic connections,
and PR #4 `assess_connection()`. The existing default runner remains the
legacy inbound-only agent demonstration and its figures keep their prior
meaning.

PR #3's current candidate-pair enumeration is quadratic per quota cell. This
phase does not expand it. It declares a deterministic causal-order prefix of
accepted/reset-confirmed calls and a separate four-cell historical quota
configuration. The default bound is 256 source calls and eight connections
per cell; both values are exposed by the CLI. This is an explicitly bounded,
retrospectively constructed benchmark, not a full historical connection
population and not a prevalence estimate.

Live replay uses `observed_at`, original source-row number, then `call_id` as
its stable order. Each graph connection has an activation cursor equal to the
later of its inbound and outbound first-available candidate observation
cursors. No assessment occurs before that cursor. This prevents the completed
synthetic graph from revealing a future outbound candidate at an earlier
Watcher timestamp, including at tied timestamps whose source rows differ. It
does not solve retrospective call discovery: source call membership and the
overall graph are still known only after derived geofence crossings.

Connections join to replay state only with
`assignment.inbound_source_call_id` and
`assignment.outbound_source_call_id`. At every active source update,
`assess_connection()` receives chronological prefixes for those two calls and
selects its own current causal predictions. PR #3 reference-arrival timestamps
are not substituted into slack. The embedded derived reference-delay baseline
is copied into the evaluation record from the same assessment and therefore
retains the same selected inbound causal prediction.

Final `DerivedArrivalEvent` values, including the final derived geofence
crossing, eligibility, exclusions, and completed-call quality, are held in a
separate evaluation-only view. They are never accepted by the causal replay
state or passed into the Watcher. Phase 2 intentionally stops at assessment
records and diagnostic counts: it constructs no retrospective feasibility
outcome, invokes no agent or case registry, and writes no legacy `TraceStore`
metric or historical figure.

## Stage 7: PR #5 Phase 3 retrospective synthetic scenario evaluation

Phase 3 preserves the Stage 6 causal replay exactly. Only after that replay is
complete, a frozen `RetrospectiveConnectionOutcome` joins each fixed PR #3
UCID to its inbound and outbound final PR #2 derived geofence crossings. This
outcome type is structurally separate from `CausalArrivalUpdate`,
`ConnectionRiskAssessment`, `RiskEvent`, and live replay state, and no outcome
field is accepted by `assess_connection()`.

For one selected PR #3 process scenario, the exact evaluation arithmetic is:

```text
retrospective_inbound_ready = final inbound derived crossing
                              + cargo-ready offset
                              + selected transfer duration
retrospective_outbound_cutoff = final outbound derived crossing
                                - cargo cut-off lead
retrospective_slack = retrospective_outbound_cutoff
                      - retrospective_inbound_ready
```

Slack at or below zero is `INFEASIBLE`; positive slack is `FEASIBLE`. The only
legitimate interpretation is **connection infeasible under this synthetic
process scenario**. The label is not an observed missed PSA connection, actual
cargo result, actual UCID result, or PSA ground truth.

The evaluation also retains, without merging it into the primary label:

```text
retrospective_no_itt_slack = final outbound derived crossing
                             - cargo cut-off lead
                             - (final inbound derived crossing
                                + cargo-ready offset)
```

An infeasible transferred scenario with positive no-ITT slack is described
only as a **synthetic terminal-prevention opportunity**. It is not described
as a connection actually saved.

### Fixed-horizon and detector methodology

The assessment-row population is not the scoring denominator. For each UCID
and T−6h, T−3h, and T−1h:

```text
evaluation_time = retrospective_outbound_cutoff - horizon
selected = latest causal assessment whose assessed_at <= evaluation_time
```

An assessment after the horizon is never selected, and the scorer never looks
forward for a nearest row. No assessment at or before the horizon is
unavailable, not silently SAFE. The horizon set is configurable, with these
three values frozen as benchmark defaults.

The primary Watcher detector treats `WATCH` and `AT_RISK` as alert-positive and
`SAFE` as negative. Under the default experimental settings, causal scenario
slack `<= 0` is `AT_RISK`, positive slack `<= 2h` is `WATCH`, and larger slack
is `SAFE`. The baseline alert is copied from the same selected assessment,
using the same selected inbound causal prediction. It is positive when the
inbound predicted arrival is at least 15 minutes later than its first
available derived PR #2 reference arrival. This is the PR #4 derived
reference-delay baseline, not the separately calibrated detector in
`eval_detection.py`.

The available-support connection-level matrix has TP, FP, TN, FN, and
unavailable as separate categories, with rates computed only from the four
available categories. The end-to-end effective matrix has TP, FP, TN, and FN:
unavailable INFEASIBLE is an effective FN and unavailable FEASIBLE is an
effective TN. Its rates are computed directly from those effective counts.
Every view reports actual-positive and actual-negative denominators; rates
with zero denominators are `null`. Common support includes a UCID/horizon only
when both detectors are available. The baseline is embedded in the same row,
so common and detector-available supports coincided in this run. Accuracy is
not used as the headline metric.

### Default bounded benchmark composition

This run is labelled the **retrospective synthetic connection benchmark**.
It used the deterministic seed and current four historical quota cells, the
first 256 accepted calls under the existing safety cap, the two-hour Watcher
warning margin, the 15-minute reference-delay threshold, and the dataset SHA-256
`a46b6f6f68e5d7f2cc87b3eaa0fe2cc74373cf8e9788b2a3156c4f4644bfad7e`.

| Composition item | Result |
|---|---:|
| Accepted/reset-confirmed PR #2 calls before bounding | 1,382 |
| Bounded replay calls | 256 |
| First-available PR #3 candidate calls | 237 |
| Synthetic connections | 32 |
| Valid retrospective outcomes | 32 |
| Scoring exclusions | 0 |
| REFERENCE feasible/infeasible scenarios | 23 / 9 |
| Same-terminal/inter-terminal | 16 / 16 |
| Transfer modes | 16 none / 8 road / 8 sea |
| Causal assessment rows | 1,202 |
| Causally activated UCIDs | 32 |

These counts describe benchmark composition, not PSA connection prevalence.
The 32 connections comprise eight in each declared quota cell: Tuas→Tuas
none/small, Pasir Panjang→Pasir Panjang none/medium, Tuas→Pasir Panjang
road/medium, and Pasir Panjang→Tuas sea/large.

### REFERENCE availability and performance

Fixed-horizon coverage differs sharply from Phase 2's event-triggered replay,
where every assessment happened only after graph activation and the smoke
sample had no unavailable assessment pairs:

| Horizon | Available | Unavailable | Availability | Exposed reason |
|---|---:|---:|---:|---|
| T−6h | 12 | 20 | 37.5% | no assessment at/before horizon |
| T−3h | 18 | 14 | 56.2% | no assessment at/before horizon |
| T−1h | 24 | 8 | 75.0% | no assessment at/before horizon |

Available-support confusion and rates are:

| Horizon | Detector | TP | FP | TN | FN | Unavailable | P | N | Recall | Precision | FAR |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| T−6h | Watcher | 2 | 0 | 10 | 0 | 20 | 2 | 10 | 2/2 = 100.0% | 2/2 = 100.0% | 0/10 = 0.0% |
| T−6h | reference-delay | 1 | 6 | 4 | 1 | 20 | 2 | 10 | 1/2 = 50.0% | 1/7 = 14.3% | 6/10 = 60.0% |
| T−3h | Watcher | 2 | 0 | 14 | 2 | 14 | 4 | 14 | 2/4 = 50.0% | 2/2 = 100.0% | 0/14 = 0.0% |
| T−3h | reference-delay | 4 | 10 | 4 | 0 | 14 | 4 | 14 | 4/4 = 100.0% | 4/14 = 28.6% | 10/14 = 71.4% |
| T−1h | Watcher | 3 | 0 | 18 | 3 | 8 | 6 | 18 | 3/6 = 50.0% | 3/3 = 100.0% | 0/18 = 0.0% |
| T−1h | reference-delay | 6 | 11 | 7 | 0 | 8 | 6 | 18 | 6/6 = 100.0% | 6/17 = 35.3% | 11/18 = 61.1% |

End-to-end effective confusion and directly corresponding rates are:

| Horizon | Detector | TP | FP | TN | FN | P | N | Recall | Precision | FAR |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| T−6h | Watcher | 2 | 0 | 23 | 7 | 9 | 23 | 2/9 = 22.2% | 2/2 = 100.0% | 0/23 = 0.0% |
| T−6h | reference-delay | 1 | 6 | 17 | 8 | 9 | 23 | 1/9 = 11.1% | 1/7 = 14.3% | 6/23 = 26.1% |
| T−3h | Watcher | 2 | 0 | 23 | 7 | 9 | 23 | 2/9 = 22.2% | 2/2 = 100.0% | 0/23 = 0.0% |
| T−3h | reference-delay | 4 | 10 | 13 | 5 | 9 | 23 | 4/9 = 44.4% | 4/14 = 28.6% | 10/23 = 43.5% |
| T−1h | Watcher | 3 | 0 | 23 | 6 | 9 | 23 | 3/9 = 33.3% | 3/3 = 100.0% | 0/23 = 0.0% |
| T−1h | reference-delay | 6 | 11 | 12 | 3 | 9 | 23 | 6/9 = 66.7% | 6/17 = 35.3% | 11/23 = 47.8% |

Common support coincided with detector-available support here. At T−6h it
contained only 2 infeasible and 10 feasible cases, so 2/2 = 100.0% Watcher
recall has a very small denominator and must not stand alone.

**On the bounded retrospective synthetic benchmark, the connection-aware
Watcher was substantially more selective than the inbound reference-delay
baseline, producing fewer false alerts, while the baseline retained higher
sensitivity at later horizons.** This is a precision/false-alert versus recall
trade-off. The Watcher produced no false-positive synthetic connections at the
three fixed horizons. The baseline had higher common-support recall at T−3h
and T−1h but many more false positives, and its median first-alert lead time
was longer in this run. The population is only 32 synthetic connections; these
figures are not production performance and do not establish detector
superiority.

The paired common-support disagreements were:

| Horizon | Retrospective label | Both | Watcher only | Baseline only | Neither |
|---|---|---:|---:|---:|---:|
| T−6h | INFEASIBLE | 1 | 1 | 0 | 0 |
| T−6h | FEASIBLE | 0 | 0 | 6 | 4 |
| T−3h | INFEASIBLE | 2 | 0 | 2 | 0 |
| T−3h | FEASIBLE | 0 | 0 | 10 | 4 |
| T−1h | INFEASIBLE | 3 | 0 | 3 | 0 |
| T−1h | FEASIBLE | 0 | 0 | 11 | 7 |

These paired counts show that the connection-aware Watcher produced far fewer
alerts on retrospectively feasible scenarios in this bounded synthetic
population, while the baseline caught additional infeasible scenarios at the
later horizons. They do not establish real operational superiority.

### Lead time, churn, and no-ITT result

For each retrospectively infeasible scenario, first-alert search is restricted
to causal assessments no later than its synthetic cut-off. Repeated later
alerts do not replace the first one, and Watcher and baseline are searched
independently.

| Detector | Caught | Missed | Median lead | p25 | p75 | Min | Max |
|---|---:|---:|---:|---:|---:|---:|---:|
| Watcher | 6 | 3 | 1.76h | 0.56h | 10.06h | 0.02h | 25.95h |
| reference-delay | 7 | 2 | 3.66h | 2.24h | 4.62h | 0.02h | 25.95h |

Lead time is synthetic decision time before a synthetic cut-off; it does not
prove that a scenario could have been operationally rescued. Before each
cut-off, Watcher severity churn had median 0 transitions per connection, p90
0.9, 28/32 (87.5%) with zero transitions, and 0/32 above the descriptive
`>4` diagnostic threshold. This threshold is not a PSA alert-fatigue target.
The REFERENCE result contained 0/9 synthetic terminal-prevention opportunities.

### Scenario sensitivity and reproducibility

PR #3 already carries LOW, REFERENCE, and CONSERVATIVE projections on every
UCID, so the benchmark scores all three on the exact same 32 connections and
source population. It does not fabricate assumptions or regenerate the graph:

| Scenario | Feasible / infeasible | Availability T−6/T−3/T−1 | Watcher caught | Watcher median lead | Baseline caught | Baseline median lead | Churn median / p90 | No-ITT opportunities |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| LOW | 25 / 7 | 12 / 19 / 28 | 5/7 | 1.76h | 7/7 | 4.66h | 0 / 1.0 | 0/7 |
| REFERENCE | 23 / 9 | 12 / 18 / 24 | 6/9 | 1.76h | 7/9 | 3.66h | 0 / 0.9 | 0/9 |
| CONSERVATIVE | 23 / 9 | 11 / 13 / 19 | 4/9 | 7.65h | 6/9 | 3.05h | 0 / 0.9 | 0/9 |

The versioned `historical-watcher-report-v2` JSON structure contains the
population limit/version/digest, dataset and graph digests, deterministic
synthetic seed, quota definitions, Watcher and baseline thresholds, exact
process assumptions, horizon definitions, each scenario's composition and
exclusions, availability, available-support/end-to-end-effective/common-support metrics, paired
comparisons, lead-time, churn, terminal-prevention opportunity result, and
explicit provenance and limitations. Keys and ordered collections are stable;
no run timestamp is added. Two identical bounded runs produce identical
payloads.

The console prints the selected scenario scorecard. Optional deterministic
JSON output is enabled with:

```bash
uv run python scripts/run_historical.py --mode watcher-eval \
  --output historical-watcher-report.json
```

Alternative deterministic pairing seeds can be inspected with
`--seed-sensitivity-seeds`, which reuses the same bounded source calls and
prints a clearly secondary diagnostic. It does not change the frozen primary
seed or enter the primary JSON report.

For the illustrative seeds `sensitivity-a`, `sensitivity-b`, and
`sensitivity-c`, Watcher false positives ranged from 1 to 3 per fixed horizon,
rather than zero under the frozen primary pairing. The primary zero-FP result
is therefore pairing-seed sensitive. Three alternatives remain only a future
robustness prompt, not a substitute benchmark.

The provenance boundary remains: AIS observations are real; causal ETA values
and final geofence crossings are derived; UCIDs, assignments, terminal modes,
cut-offs, cargo offsets, transfers, and scenario outcomes are synthetic. The
benchmark is bounded, retrospectively call-segmented, activation-conditioned,
small, and not a prevalence sample. It feeds no alerts to the agent or
`CaseRegistry`, makes no container-saved or missed-connection-prevented claim,
and does not overwrite legacy historical-run, `eval_eta.py`,
`eval_detection.py`, or `TraceStore` evidence.

## Stage 8: PR #6 final Watcher refinement and prevention capability evidence

PR #6 preserves the PR #5 replay, 32-connection graph, UCIDs, LOW/REFERENCE/
CONSERVATIVE assumptions, two-hour Watcher margin, 15-minute inbound-delay
baseline, and slack arithmetic. It adds evaluation-only diagnostics and
separate challenge populations; it does not add or alter AIS observations,
detector features, topology, or process assumptions.

### Data provenance hierarchy

The final Watcher evidence has three provenance layers.

**REAL AIS**

- vessel observations;
- observation timestamps; and
- vessel trajectories represented by positions, speeds, headings, and other
  received AIS fields.

**DERIVED**

- deterministic call segmentation over accepted/reset-confirmed approach
  episodes;
- causal arrival predictions from current and prior continuous-segment state;
- each call's first available reference arrival;
- final exploratory geofence crossings used only for retrospective evaluation;
  and
- whether inbound and outbound causal timing support existed by a historical
  assessment horizon.

**SYNTHETIC / EXPERIMENTAL**

- UCID vessel-call pairings;
- terminal assignment;
- cargo-ready and cutoff process assumptions;
- transfer mode and duration;
- synthetic cargo cutoff;
- LOW/REFERENCE/CONSERVATIVE feasibility outcomes;
- historical benchmark connection labels; and
- deliberately curated retrospective-prevention and causal-actionability
  challenge populations.

Early support limitations originate primarily in the AIS-derived timing layer.
At REFERENCE T−6h, 7 of 9 retrospectively infeasible synthetic connections did
not yet have sufficient causal support: 2 had neither leg supported and 5
lacked outbound support. This means the replay had not yet derived usable
timing for both vessel legs. It does not mean that the synthetic connection or
its assignments were missing. Synthetic pairing determines which legs must be
available, but it neither provides nor removes historical causal vessel
observations.

### Frozen historical evidence

The historical experiment remains one fixed 32-connection synthetic
population:

| Scenario | Retrospectively infeasible | Retrospective prevention opportunities |
|---|---:|---:|
| LOW | 7 | 0 |
| REFERENCE | 9 | 0 |
| CONSERVATIVE | 9 | 0 |

Zero opportunities is retained as the historical result. No transfer duration,
cutoff, terminal assignment, scenario assumption, or connection pairing was
changed to manufacture examples.

The predeclared 0h/1h/2h/3h/4h warning-margin study reused this exact population
and causal stream. Wider margins did not provide consistent sensitivity gains
and introduced false positives in several cells. Missing early causal support
remained a major limitation. The two-hour margin is retained without any claim
that it is optimal; choosing a threshold after observing which one looked best
would be post-hoc benchmark tuning.

At REFERENCE 2h T−1h, the Watcher produced 3 alerts with 33.3% recall,
100.0% precision, and 0 false positives. The unchanged inbound-delay baseline
produced 17 alerts with 66.7% recall, 35.3% precision, and 11 false positives.
The baseline was more sensitive and the connection-aware Watcher more
selective. These synthetic benchmark results do not establish universal
detector superiority or operational PSA performance.

Median Watcher state transitions per connection were 0 across tested cells,
p90 was at most 1, and wider margins did not materially increase repeated alert
entries. No hysteresis was added.

### Deliberately curated retrospective prevention challenge

The separate `terminal-prevention-challenge-v1` population searches a broader
valid AIS-derived candidate-pair space and is explicitly labelled
**DELIBERATELY CURATED / DETERMINISTIC SYNTHETIC CHALLENGE SELECTION**.
Retrospective final crossings deliberately select four cases in each category:

- `RETROSPECTIVE_PREVENTION_OPPORTUNITY`;
- `UNRECOVERABLE_WITH_NO_ITT`; and
- `FEASIBLE_WITH_ITT`.

For the four retrospective-prevention cases, three received a Watcher alert
before cutoff. Only TPC-01 reached a causal assessment with current-plan slack
at or below zero while no-ITT slack remained positive. TPC-02 had no causal
assessment before cutoff. TPC-03 and TPC-04 alerted only after causal no-ITT
slack was already non-positive. These are curated capability counts, not
operational recall or a historical prevalence estimate.

Retrospective preventability uses final derived crossing timing and asks
whether the synthetic final outcome would become feasible if ITT duration were
removed. A causal prevention signal uses only predictions available at one
replay moment and requires:

```text
current_plan_slack <= 0
and no_itt_slack > 0
```

The two labels are intentionally independent. A retrospectively preventable
connection need not remain preventable when sufficient causal information
arrives.

### Deliberately curated causal-actionability capability set

The separately identified `causal-actionability-capability-v1` set is labelled
**DELIBERATELY CURATED CAUSAL-ACTIONABILITY CAPABILITY SET**. Under unchanged
REFERENCE assumptions, the deliberate search found 5,051 candidate
configurations with at least one qualifying causal prevention signal and
selected four by canonical rank. The 5,051 configurations are not actual
opportunities, prevalence, expected operational frequency, or a percentage of
PSA connections.

All four CAP examples represent the causal signal correctly. CAP-01 is
retrospectively unrecoverable; CAP-02 through CAP-04 are retrospectively
feasible with ITT. This is legitimate because the causal assessment records
what was predicted at one historical replay moment, while retrospective
metadata records the later final synthetic outcome.

The capability set proves only that the signal can exist and be represented.
It does not prove that intervention would ultimately be required, that removing
ITT would guarantee the final outcome, or that a causal prediction would remain
unchanged as later AIS observations arrive. It makes no claim that a real PSA
container was saved or rescued.

The reviewed deterministic report SHA-256 values are
`aeb9c340b773d1ea60211971b18b613b186afbe64c85eda3cdf9e2393479bac8`
for `watcher-refinement-report-v1` and
`285c734784e604f74a1135b592b559f69b616c4cd20f8f2dca62080ec560b2ce`
for `terminal-prevention-challenge-v1`. The approximately 5.9 MB refinement
report and temporary challenge JSON files are not tracked; their generation
commands and full technical interpretation are recorded in
`docs/pr6-watcher-refinement.md`.
