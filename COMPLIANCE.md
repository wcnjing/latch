# COMPLIANCE — LATCH

PSA Code Sprint 2.0 requires that external data be open or public with sources,
owners and licences declared; that no copyleft (GPL/AGPL) dependency be used;
and that all third-party software **and AI models** be declared. This file is
that declaration for the whole repository. Workstream C keeps its own
package-level breakdown in [`console/DEPENDENCIES.md`](console/DEPENDENCIES.md);
the dataset is documented in full in
[`Data Inspection/singapore_ais_dataset_assessment.md`](Data%20Inspection/singapore_ais_dataset_assessment.md).

---

## 1. AI models

Two layers, for two different jobs. Neither is fine-tuned, neither is trained
on PSA data, and neither has authority to act — the Gate Controller imports no
model client by construction, so the model can rank options but cannot approve
one.

| Model | Owner | Access | Licence / terms | Used for |
|---|---|---|---|---|
| `claude-haiku-4-5` | Anthropic | Anthropic API, hosted | Proprietary, commercial API terms | Triage: is this connection worth deliberating on |
| `claude-opus-5` | Anthropic | Anthropic API, hosted | Proprietary, commercial API terms | Deliberation: ranking options the code enumerated |
| `qwen3:8b` | Alibaba Cloud (Qwen team) | Local, via Ollama | Apache-2.0 | Offline substitute for both layers; lets the suite run with no API spend |

Runtime selection is `--model {auto,fake,local,anthropic}`
(`src/latch/cli.py`). `fake` is a scripted stand-in with no model at all —
every figure produced under it is labelled as measuring the pipeline, not the
agent.

**Model-adjacent software**

| Software | Owner | Licence |
|---|---|---|
| Ollama (local model runner) | Ollama | MIT |
| `anthropic` Python SDK | Anthropic | MIT |

Model IDs and per-token prices live in `src/latch/config.py` so the cost
figures in the trace are computed, not asserted.

---

## 2. Data

| Source | Owner / creators | Licence | Use |
|---|---|---|---|
| [*AIS Data from 11 ports around the globe*, v1](https://doi.org/10.17632/r37vwd493d.1) (Singapore subset) | Andreas Hadjipieris, Neofytos Dimitriou, Ognjen Arandjelovic; collected via AISStream.io | CC BY 4.0 | The only real movement layer. Vessel positions and timing |

Everything else is synthetic and is labelled as such wherever it appears —
in the trace, in the console header, and in §*What is real and what is not* of
the [README](README.md). Container connections, terminal assignments, box
counts, ITT inventory and loading cut-offs have no public dataset and are
generated. No PSA data of any kind is used.

Attribution for CC BY 4.0 is carried in the dataset assessment document. The
dataset licence covers the data; it does not extend to this repository's own
source code.

---

## 3. Python dependencies

Three direct dependencies, twenty-three distributions including transitives.

| Package | Version | Licence | Direct? |
|---|---|---|---|
| `anthropic` | 0.122.0 | MIT | yes |
| `httpx` | 0.28.1 | BSD-3-Clause | yes |
| `python-dotenv` | 1.2.3 | BSD-3-Clause | yes |
| `pytest` | 9.1.1 | MIT | dev only |
| `annotated-types` | 0.8.0 | MIT | transitive |
| `anyio` | 4.14.2 | MIT | transitive |
| `certifi` | 2026.7.22 | **MPL-2.0** | transitive |
| `distro` | 1.9.0 | Apache-2.0 | transitive |
| `docstring_parser` | 0.18.0 | MIT | transitive |
| `h11` | 0.16.0 | MIT | transitive |
| `httpcore` | 1.0.9 | BSD-3-Clause | transitive |
| `idna` | 3.18 | BSD-3-Clause | transitive |
| `iniconfig` | 2.3.0 | MIT | dev, transitive |
| `jiter` | 0.16.0 | MIT | transitive |
| `packaging` | 26.3 | Apache-2.0 OR BSD-2-Clause | dev, transitive |
| `pluggy` | 1.6.0 | MIT | dev, transitive |
| `pydantic` | 2.13.4 | MIT | transitive |
| `pydantic_core` | 2.46.4 | MIT | transitive |
| `Pygments` | 2.21.0 | BSD-2-Clause | dev, transitive |
| `sniffio` | 1.3.1 | MIT OR Apache-2.0 | transitive |
| `typing-inspection` | 0.4.4 | MIT | transitive |
| `typing_extensions` | 4.16.0 | PSF-2.0 | transitive |

**No GPL, AGPL or LGPL.** Re-runnable:

```bash
uv run python -c "
from importlib.metadata import distributions
def lic(d):
    m = d.metadata
    return str(m.get('License-Expression') or m.get('License') or
               ' '.join(c for c in m.get_all('Classifier', []) if 'License' in c))
hits = [(d.metadata['Name'], lic(d)) for d in distributions() if 'GPL' in lic(d)]
print(hits or 'clean')"
```

**One flag worth raising rather than burying.** `certifi` is MPL-2.0, which is
copyleft — file-level, not project-level, and not GPL or AGPL, so it sits
outside the stated prohibition. It is the standard CA-certificate bundle,
pulled in by `httpx`, unmodified, and it imposes no obligation on this
repository's code. Declared explicitly so nobody has to discover it during
judging. The same applies to `lightningcss` (MPL-2.0) in the console
toolchain, which is build-time only and never reaches the browser bundle.

---

## 4. Console dependencies

Two runtime packages (`react`, `react-dom`, both MIT) and a build toolchain.
Full accounting, including a re-runnable copyleft scan across all 82 installed
packages, in [`console/DEPENDENCIES.md`](console/DEPENDENCIES.md).

---

## 5. Licensing of our own code

**All rights reserved. No licence is granted.**

This is deliberate, and it is not an oversight to be fixed by adding an MIT
`LICENSE` file. The competition terms state that IP in winning entries vests
in PSA, and that nothing may be publicly posted without PSA's written consent.
Attaching a permissive open-source licence would be a public grant that
contradicts both. The repository is private for the same reason.

If PSA wants a specific licence applied — before or after judging — that is
theirs to specify and we will apply it.

---

## 6. Write access

LATCH holds none, and claims none. Every write action terminates in a stub.
The interfaces are modelled on the message semantics of `COPRAR` (discharge
order amendment), `IFTMBF` (transport booking) and `IFTSAI` (schedule /
availability), named beside each `ActionKind` in `src/latch/models.py`. No
terminal operating system, berth planning system or carrier system is
contacted. The contribution is the decision layer above them.
