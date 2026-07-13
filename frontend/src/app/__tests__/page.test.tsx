import { expect, test } from "vitest";
import { render, screen } from "@testing-library/react";
import Page from "../page";

test("Page renders a top-level heading", () => {
  render(<Page />);
  expect(screen.getByRole("heading", { level: 1 })).toBeDefined();
});
