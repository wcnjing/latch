/**
 * Adapter smoke check. Runs `toViewModel` over every captured fixture and
 * prints what the console would show, asserting the things that would
 * silently rot after a fixture regeneration:
 *
 *   - the unverified-field list this adapter reconstructs still matches B's
 *     own `unverified_inputs` count
 *   - the confidence waterfall still lands on B's computed value
 *   - every reason code and every timeline step has operator English
 *   - service success still agrees with `Resolution.is_service_success`
 *
 *   npm run smoke
 */
import { readFileSync, readdirSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

import { byCriticality, toViewModel } from '../src/adapters/toViewModel';
import type { FixtureBundle } from '../src/adapters/types';

const here = dirname(fileURLToPath(import.meta.url));
const dir = join(here, '..', 'fixtures');

const bundles = readdirSync(dir)
  .filter((f) => f.endsWith('.json') && f !== 'index.json')
  .sort()
  .map((f) => JSON.parse(readFileSync(join(dir, f), 'utf8')) as FixtureBundle);

let problems = 0;
const fail = (msg: string) => {
  problems += 1;
  console.log(`  !! ${msg}`);
};

for (const vm of bundles.map(toViewModel).sort(byCriticality)) {
  const c = vm.confidence;
  console.log(
    `${vm.id.padEnd(14)} ${vm.severityLabel.padEnd(8)} ${vm.stateLabel.padEnd(13)}` +
      `boxes=${String(vm.boxes).padStart(3)} prio=${String(Math.round(vm.priority)).padStart(4)} ` +
      `conf=${c ? c.value.toFixed(4) : '   -  '} ` +
      `gate=${(vm.gate?.requiredRoleLabel ?? '-').padEnd(21)}` +
      `rescue=${vm.rescuableByRemovingItt ? 'Y' : 'n'} steps=${vm.timeline.length}`,
  );

  if (vm.gate?.escalation) {
    const e = vm.gate.escalation;
    console.log(
      `               autonomy ${e.wouldHaveBeenLabel} -> ${e.becameLabel}  (${e.reasons.join('; ')})`,
    );
  }
  if (c?.degradations.length) {
    for (const d of c.degradations) {
      console.log(`               ${d.tool} ${d.what} x${d.attempts} -> ${d.fallback}`);
    }
  }

  if (c && !c.unverifiedFieldsReconciled) {
    fail(
      `${vm.id}: reconstructed ${c.unverifiedFields.length} unverified field(s), ` +
        `B counted ${c.unverifiedCount}`,
    );
  }
  if (c) {
    const last = c.waterfall.at(-1);
    if (!last || Math.abs(last.running - c.value) > 0.0002) {
      fail(`${vm.id}: waterfall ends at ${last?.running}, B computed ${c.value}`);
    }
  }
  for (const r of vm.reasons) if (!r.title) fail(`${vm.id}: unmapped reason code ${r.code}`);
  for (const t of vm.timeline) if (!t.title) fail(`${vm.id}: timeline step ${t.seq} has no title`);
  if (vm.outcome && vm.outcome.serviceSuccess !== vm.raw.trace.outcome.service_success) {
    fail(`${vm.id}: service success disagrees with B`);
  }
  if (vm.gate?.rung.advisoryOnly && vm.approval?.actionable) {
    fail(`${vm.id}: rung 1 must not offer an approve control`);
  }
}

console.log(`\n${bundles.length} fixtures, ${problems} problem(s)`);
process.exit(problems ? 1 : 0);
