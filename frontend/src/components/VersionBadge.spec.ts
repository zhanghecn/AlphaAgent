import { describe, expect, it } from "vitest";

import { canManageSystem } from "./VersionBadge";

describe("VersionBadge permissions", () => {
  it("only enables manual update controls for an administrator on release builds", () => {
    expect(canManageSystem(false, true)).toBe(false);
    expect(canManageSystem(true, false)).toBe(false);
    expect(canManageSystem(true, true)).toBe(true);
  });
});
