import { afterEach } from "vitest";
import { cleanup } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";

// RTL's automatic per-test cleanup only self-registers when it detects
// Vitest's *global* afterEach; this project keeps `globals: false`
// (vitest.config.ts) so `tsc --noEmit` doesn't need an extra ambient-types
// dependency for `**/*.test.tsx`. Registering it explicitly here gets the
// same isolation (each test starts from an empty DOM) without that
// tradeoff.
afterEach(cleanup);

// `Intl.DateTimeFormat(undefined, ...)` -- what lib/appointments/datetime.ts
// deliberately uses, so the app follows each viewer's own locale -- resolves
// to whatever locale the *runtime* defaults to. That default belongs to the
// machine, not the project: a workstation here resolves to en-NL (24-hour,
// "13:00") while the CI runner resolves to en-US (12-hour, "1:00 PM"). Tests
// asserting on formatted times therefore passed locally and failed in CI
// (lib/appointments/datetime.test.ts, plus the two appointments component
// tests that query slot buttons by their rendered label).
//
// Pinning the default here makes the suite deterministic on any runner while
// leaving production behavior untouched: application code still passes
// `undefined` and still follows the real viewer's locale. en-GB is chosen
// because it is 24-hour, matching how those assertions are written. An
// explicit locale from a caller always wins over this default.
const OriginalDateTimeFormat = Intl.DateTimeFormat;
const TEST_LOCALE = "en-GB";

function PinnedDateTimeFormat(
  locales?: Intl.LocalesArgument,
  options?: Intl.DateTimeFormatOptions,
): Intl.DateTimeFormat {
  return new OriginalDateTimeFormat(locales ?? TEST_LOCALE, options);
}
PinnedDateTimeFormat.supportedLocalesOf = OriginalDateTimeFormat.supportedLocalesOf;

Intl.DateTimeFormat = PinnedDateTimeFormat as unknown as typeof Intl.DateTimeFormat;
