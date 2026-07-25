import { afterEach } from "vitest";
import { cleanup } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";

// Without `test.globals: true`, @testing-library/react does not auto-detect
// `afterEach` to register its own cleanup -- register it once here instead
// of repeating `afterEach(cleanup)` in every test file that calls `render`.
afterEach(() => {
  cleanup();
});
