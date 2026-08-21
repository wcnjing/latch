# DEPENDENCIES — LATCH operator console (workstream C)

Every third-party library the console pulls in, with its licence.

**No GPL, AGPL or LGPL anywhere in the tree.** Verified by walking every
`package.json` under `node_modules` and matching `/GPL/i` against the declared
licence field — zero hits across 82 installed packages. Re-runnable:

```bash
node -e "const fs=require('fs'),path=require('path');const hits=[];(function w(d){for(const e of fs.readdirSync(d,{withFileTypes:true})){if(!e.isDirectory())continue;const p=path.join(d,e.name);if(e.name.startsWith('@')){w(p);continue}const f=path.join(p,'package.json');if(fs.existsSync(f)){try{const j=JSON.parse(fs.readFileSync(f,'utf8'));const l=typeof j.license==='string'?j.license:(j.license||{}).type||'UNKNOWN';if(/GPL/i.test(l))hits.push(j.name+' '+l)}catch{}}}})('node_modules');console.log(hits.length?hits:'clean')"
```

## Ships in the browser bundle

Only three packages reach the user. Everything else is build-time.

| Package | Version | Licence | Why |
|---|---|---|---|
| `react` | 19.2.8 | MIT | UI runtime |
| `react-dom` | 19.2.8 | MIT | DOM renderer |
| `scheduler` | 0.28.0 | MIT | React's cooperative scheduler; transitive, not chosen directly |

## Build-time only

| Package | Version | Licence | Why |
|---|---|---|---|
| `vite` | 7.3.6 | MIT | Dev server and bundler |
| `@vitejs/plugin-react` | 5.2.0 | MIT | JSX transform and fast refresh |
| `typescript` | 5.9.3 | Apache-2.0 | Type checking. Emits no runtime code — `noEmit` is set |
| `tailwindcss` | 4.3.3 | MIT | Styling. Compiles to plain CSS; nothing of Tailwind ships as JS |
| `@tailwindcss/vite` | 4.3.3 | MIT | Tailwind's Vite integration |
| `esbuild` | 0.28.2 | MIT | Bundles `scripts/smoke.ts` for the adapter check. Transitive via Vite |

## Transitive licences worth naming

Everything not MIT or ISC, so a reviewer does not have to take "no copyleft" on
trust:

| Package | Licence | Note |
|---|---|---|
| `typescript` | Apache-2.0 | Permissive. Build-time |
| `baseline-browser-mapping` | Apache-2.0 | Browser support data, via Vite |
| `detect-libc` | Apache-2.0 | Platform detection for native binaries, via Tailwind |
| `source-map-js` | BSD-3-Clause | Source maps, via PostCSS |
| `caniuse-lite` | CC-BY-4.0 | Browser support **data**, not code. Attribution-only |
| `lightningcss` | MPL-2.0 | CSS transformer inside Tailwind v4 |
| `lightningcss-win32-x64-msvc` | MPL-2.0 | Prebuilt native binary for the above |

**On the two MPL-2.0 packages.** MPL-2.0 is file-level copyleft: it reaches
modified copies of MPL-licensed *files*, not code that merely calls them. We do
not modify Lightning CSS, it is a build-time transformer inside Tailwind, and
none of it ships in the bundle. This is compatible with a proprietary
submission. If the competition's terms turn out to prohibit weak copyleft at
any depth, Tailwind v4 can be replaced with hand-written CSS — the console uses
Tailwind for layout and colour tokens and nothing that would be hard to
reproduce.

Full breakdown across the tree: MIT 69, ISC 6, Apache-2.0 3, MPL-2.0 2,
BSD-3-Clause 1, CC-BY-4.0 1.

## Python side (A and B, not added by C)

The console adds no Python dependencies. `scripts/capture_fixtures.py` imports
`latch` from `src/` and uses only the standard library. A's and B's own
dependencies are declared in `pyproject.toml` and are not C's to record here.

## Deliberately not used

Recorded because their absence is a choice, not an oversight:

- **No charting library.** The confidence waterfall, the slack comparison and
  the timeline are hand-built SVG and CSS. A chart library would have been more
  code in the bundle for four bespoke visuals, and the waterfall in particular
  needs to read clearly in a screen recording rather than look like a default
  chart.
- **No component library.** Consistent visual language matters more here than
  breadth of components, and the console has roughly a dozen of them.
- **No state management library.** One store, plain React state and context.
- **No date library.** Two format helpers over `Intl.DateTimeFormat`.
- **No test runner yet.** `npm run smoke` bundles `scripts/smoke.ts` with
  esbuild and runs it under Node, which covers the adapter — the one place a
  fixture regeneration can silently break something.
