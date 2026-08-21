/**
 * Fixture loading. The console reads `console/fixtures/`, which is captured
 * from B's real pipeline by `scripts/capture_fixtures.py`.
 *
 * It deliberately does NOT read the repo's top-level `fixtures/`. Those are
 * hand-scripted and disagree with the code they document — see CONTRACTS.md
 * section 10.
 *
 * Swapping to a live feed replaces this module and nothing else: everything
 * downstream consumes the view model, not these shapes.
 */

import type { FixtureBundle, FixtureIndex } from '../adapters/types';

import index from '../../fixtures/index.json';
import safe from '../../fixtures/01-safe.json';
import watch from '../../fixtures/02-watch.json';
import rescuable from '../../fixtures/03-at-risk-rescuable.json';
import notRescuable from '../../fixtures/04-at-risk-not-rescuable.json';
import failureInjection from '../../fixtures/05-failure-injection.json';
import approvalDeclined from '../../fixtures/05b-approval-declined.json';
import approvalLapsed from '../../fixtures/05c-approval-lapsed.json';
import lapsed from '../../fixtures/06-lapsed.json';
import declined from '../../fixtures/07-customer-declined.json';
import superseded from '../../fixtures/08-superseded.json';
import stale from '../../fixtures/09-stale.json';
import contentionWinner from '../../fixtures/10-contention-winner.json';
import contentionLoser from '../../fixtures/11-contention-loser.json';

export const FIXTURE_INDEX = index as unknown as FixtureIndex;

export const BUNDLES: FixtureBundle[] = [
  safe,
  watch,
  rescuable,
  notRescuable,
  failureInjection,
  lapsed,
  declined,
  superseded,
  stale,
  contentionWinner,
  contentionLoser,
] as unknown as FixtureBundle[];

/** The failure-injection run. Demo mode plays this one back. */
export const DEMO_BUNDLE = failureInjection as unknown as FixtureBundle;

/**
 * The same run with the approval declined instead of approved. Held out of the
 * queue — it shares a connection id with `DEMO_BUNDLE`, and two rows for one
 * connection is exactly what the risk queue must not do. It is what the
 * decline control plays instead.
 */
export const DEMO_DECLINED_BUNDLE = approvalDeclined as unknown as FixtureBundle;

/** The same run again, with nobody signing. What the auto-decline plays. */
export const DEMO_LAPSED_BUNDLE = approvalLapsed as unknown as FixtureBundle;
