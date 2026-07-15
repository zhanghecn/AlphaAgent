import { useCallback, useEffect, useRef, useState } from "react";

import type { LimitUpSignalSnapshot } from "@/api/limitUp";
import {
  EMPTY_BUY_ALERT_STATE,
  buyAlertContent,
  evaluateBuyAlerts,
  type BuyAlertState,
} from "./buyAlert";

const ENABLED_STORAGE_KEY = "alphaagent.limitUpBuyAlerts.enabled";
const STATE_STORAGE_KEY = "alphaagent.limitUpBuyAlerts.state";

export type BuyAlertPermission = NotificationPermission | "unsupported";

interface BuyAlertControls {
  enabled: boolean;
  permission: BuyAlertPermission;
  toggle: () => Promise<BuyAlertPermission>;
  test: () => Promise<BuyAlertPermission>;
}

let audioContext: AudioContext | null = null;

export function useBuyAlerts(snapshot: LimitUpSignalSnapshot | undefined): BuyAlertControls {
  const [enabled, setEnabled] = useState(readEnabled);
  const [permission, setPermission] = useState<BuyAlertPermission>(currentPermission);
  const alertState = useRef<BuyAlertState>(readAlertState());

  useEffect(() => {
    const result = evaluateBuyAlerts(snapshot, alertState.current, Date.now(), enabled);
    alertState.current = result.state;
    writeAlertState(result.state);
    if (!result.alerts.length) return;

    void playBuyAlertSound();
    for (const signal of result.alerts) {
      showNotification(buyAlertContent(signal), `limit-up:${snapshot?.trade_date}:${signal.vt_symbol}`);
    }
  }, [enabled, snapshot]);

  const toggle = useCallback(async () => {
    if (enabled) {
      setEnabled(false);
      writeEnabled(false);
      return currentPermission();
    }

    const audioReady = unlockAlertAudio();
    const nextPermission = await requestNotificationPermission();
    await audioReady;
    setPermission(nextPermission);
    setEnabled(true);
    writeEnabled(true);
    return nextPermission;
  }, [enabled]);

  const test = useCallback(async () => {
    const sound = playBuyAlertSound();
    const nextPermission = await requestNotificationPermission();
    setPermission(nextPermission);
    await sound;
    showNotification(
      {
        title: "AlphaAgent 买点提醒测试",
        body: "声音和桌面通知测试完成；真实买点会附带股票、涨幅和距板。",
      },
      "limit-up:test",
    );
    return nextPermission;
  }, []);

  return { enabled, permission, toggle, test };
}

async function requestNotificationPermission(): Promise<BuyAlertPermission> {
  if (typeof window === "undefined" || !("Notification" in window)) return "unsupported";
  try {
    if (window.Notification.permission === "default") {
      return await window.Notification.requestPermission();
    }
    return window.Notification.permission;
  } catch {
    return currentPermission();
  }
}

function showNotification(
  content: { title: string; body: string },
  tag: string,
): void {
  if (currentPermission() !== "granted") return;
  try {
    const notification = new window.Notification(content.title, { body: content.body, tag });
    notification.onclick = () => {
      window.focus();
      notification.close();
    };
  } catch {
    // Sound and in-page state remain available when desktop notifications fail.
  }
}

async function unlockAlertAudio(): Promise<AudioContext | null> {
  if (typeof window === "undefined") return null;
  try {
    const AudioContextConstructor = window.AudioContext
      ?? (window as typeof window & { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
    if (!AudioContextConstructor) return null;
    audioContext ??= new AudioContextConstructor();
    if (audioContext.state === "suspended") await audioContext.resume();
    return audioContext;
  } catch {
    return null;
  }
}

async function playBuyAlertSound(): Promise<void> {
  const context = await unlockAlertAudio();
  if (!context) return;
  const start = context.currentTime;
  playTone(context, 880, start, 0.12);
  playTone(context, 1_175, start + 0.14, 0.18);
}

function playTone(
  context: AudioContext,
  frequency: number,
  start: number,
  duration: number,
): void {
  const oscillator = context.createOscillator();
  const gain = context.createGain();
  oscillator.type = "sine";
  oscillator.frequency.setValueAtTime(frequency, start);
  gain.gain.setValueAtTime(0.0001, start);
  gain.gain.exponentialRampToValueAtTime(0.16, start + 0.015);
  gain.gain.exponentialRampToValueAtTime(0.0001, start + duration);
  oscillator.connect(gain);
  gain.connect(context.destination);
  oscillator.start(start);
  oscillator.stop(start + duration);
}

function currentPermission(): BuyAlertPermission {
  if (typeof window === "undefined" || !("Notification" in window)) return "unsupported";
  return window.Notification.permission;
}

function readEnabled(): boolean {
  if (typeof window === "undefined") return false;
  try {
    return window.localStorage.getItem(ENABLED_STORAGE_KEY) === "true";
  } catch {
    return false;
  }
}

function writeEnabled(enabled: boolean): void {
  try {
    window.localStorage.setItem(ENABLED_STORAGE_KEY, String(enabled));
  } catch {
    // Private browsing can reject storage while alerts still work for this page load.
  }
}

function readAlertState(): BuyAlertState {
  if (typeof window === "undefined") return copyEmptyState();
  try {
    const parsed = JSON.parse(window.localStorage.getItem(STATE_STORAGE_KEY) ?? "null") as Partial<BuyAlertState> | null;
    if (!parsed || typeof parsed.tradeDate !== "string") return copyEmptyState();
    const activeSymbols = Array.isArray(parsed.activeSymbols)
      ? parsed.activeSymbols.filter((value): value is string => typeof value === "string")
      : [];
    const lastAlertAt = Object.fromEntries(
      Object.entries(parsed.lastAlertAt ?? {}).filter(
        (entry): entry is [string, number] => typeof entry[1] === "number" && Number.isFinite(entry[1]),
      ),
    );
    return { tradeDate: parsed.tradeDate, activeSymbols, lastAlertAt };
  } catch {
    return copyEmptyState();
  }
}

function writeAlertState(state: BuyAlertState): void {
  try {
    window.localStorage.setItem(STATE_STORAGE_KEY, JSON.stringify(state));
  } catch {
    // State remains in memory if storage is unavailable.
  }
}

function copyEmptyState(): BuyAlertState {
  return {
    tradeDate: EMPTY_BUY_ALERT_STATE.tradeDate,
    activeSymbols: [],
    lastAlertAt: {},
  };
}
