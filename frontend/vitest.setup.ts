import { afterEach } from "vitest";
import { cleanup } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";

// Without `test.globals: true`, Testing Library does not auto-register cleanup.
afterEach(() => {
  cleanup();
});
