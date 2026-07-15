import { afterEach, describe, expect, it, vi } from "vitest";

import {
  BUY_ALERT_RINGTONE_DURATION_SECONDS,
  BUY_ALERT_RINGTONE_PATTERN,
  playBuyAlertSound,
} from "./buyAlertSound";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("buy alert ringtone", () => {
  it("plays repeated double tones for at least four seconds", () => {
    expect(BUY_ALERT_RINGTONE_DURATION_SECONDS).toBeGreaterThanOrEqual(4);
    expect(BUY_ALERT_RINGTONE_PATTERN).toHaveLength(12);
    expect(BUY_ALERT_RINGTONE_PATTERN.filter((tone) => tone.frequency === 880)).toHaveLength(6);
    expect(BUY_ALERT_RINGTONE_PATTERN.filter((tone) => tone.frequency === 1_175)).toHaveLength(6);
  });

  it("keeps every ordered tone inside the declared duration", () => {
    const offsets = BUY_ALERT_RINGTONE_PATTERN.map((tone) => tone.offset);

    expect(offsets).toEqual([...offsets].sort((left, right) => left - right));
    expect(BUY_ALERT_RINGTONE_PATTERN.every(
      (tone) => tone.offset >= 0
        && tone.duration > 0
        && tone.offset + tone.duration <= BUY_ALERT_RINGTONE_DURATION_SECONDS,
    )).toBe(true);
    expect(Math.max(...BUY_ALERT_RINGTONE_PATTERN.map(
      (tone) => tone.offset + tone.duration,
    ))).toBeGreaterThanOrEqual(3.8);
  });

  it("does not schedule a second ringtone while the first is playing", async () => {
    const starts: number[] = [];
    class FakeAudioContext {
      currentTime = 10;
      state = "running";
      destination = {};

      createOscillator() {
        return {
          type: "sine",
          frequency: { setValueAtTime: vi.fn() },
          connect: vi.fn(),
          start: (at: number) => starts.push(at),
          stop: vi.fn(),
        };
      }

      createGain() {
        return {
          gain: {
            setValueAtTime: vi.fn(),
            exponentialRampToValueAtTime: vi.fn(),
          },
          connect: vi.fn(),
        };
      }
    }
    vi.stubGlobal("window", { AudioContext: FakeAudioContext });

    await playBuyAlertSound();
    await playBuyAlertSound();

    expect(starts).toHaveLength(BUY_ALERT_RINGTONE_PATTERN.length);
  });
});
