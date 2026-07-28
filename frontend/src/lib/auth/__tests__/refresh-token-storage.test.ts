import { afterEach, describe, expect, it } from "vitest";
import {
  clearRefreshToken,
  loadRefreshToken,
  saveRefreshToken,
} from "../refresh-token-storage";

describe("refresh-token-storage", () => {
  afterEach(() => {
    window.localStorage.clear();
  });

  it("returns null when no refresh token has been stored", () => {
    expect(loadRefreshToken()).toBeNull();
  });

  it("round-trips a stored refresh token", () => {
    saveRefreshToken("refresh-1");
    expect(loadRefreshToken()).toBe("refresh-1");
  });

  it("clears the stored refresh token", () => {
    saveRefreshToken("refresh-1");
    clearRefreshToken();
    expect(loadRefreshToken()).toBeNull();
  });
});
