import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

const css = await readFile(new URL('../src/index.css', import.meta.url), 'utf8');
const tour = await readFile(new URL('../src/components/ProductTour.tsx', import.meta.url), 'utf8');

assert.equal(
  css.includes('backdrop-filter'),
  false,
  'recording-safe UI must not use backdrop-filter',
);
assert.equal(
  css.includes('9999px'),
  false,
  'the walkthrough must not use a viewport-sized box shadow',
);
assert.equal(
  /animation\s*:[^;]*\binfinite\b/.test(css),
  false,
  'recording-safe progress indicators must not animate forever',
);
assert.equal(
  (tour.match(/className="tour-dimmer"/g) ?? []).length,
  4,
  'the walkthrough must dim around the spotlight with four stable panels',
);

console.log('recording-safe rendering checks passed');
