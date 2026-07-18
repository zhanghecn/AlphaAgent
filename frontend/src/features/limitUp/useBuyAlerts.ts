import { useCallback, useEffect, useRef, useState } from "react";

import type { LimitUpLiveSignal, LimitUpSignalSnapshot } from "@/api/limitUp";
import {
  EMPTY_BUY_ALERT_STATE,
  buyAlertContent,
  evaluateBuyAlerts,
  type BuyAlertState,
} from "./buyAlert";
import {
  playBuyAlertSound,
  unlockBuyAlertAudio,
} from "./buyAlertSound";
import {
  DEFAULT_SPEECH_RATE,
  cancelBuyAlertSpeech,
  speakBuyAlertTest,
  speakBuyAlerts,
  speechSupported,
} from "./speechAlert";

const ENABLED_STORAGE_KEY = "alphaagent.limitUpBuyAlerts.enabled";
const STATE_STORAGE_KEY = "alphaagent.limitUpBuyAlerts.state";
const RATE_STORAGE_KEY = "alphaagent.limitUpBuyAlerts.speechRate";

export type BuyAlertPermission = NotificationPermission | "unsupported";

export interface BuyAlertBannerItem {
  key: string;
  signal: LimitUpLiveSignal;
  alertedAt: number;
}

interface BuyAlertControls {
  enabled: boolean;
  permission: BuyAlertPermission;
  speechAvailable: boolean;
  speechRate: number;
  banner: BuyAlertBannerItem[];
  toggle: () => Promise<BuyAlertPermission>;
  test: () => Promise<BuyAlertPermission>;
  setSpeechRate: (rate: number) => void;
  dismissBanner: () => void;
}

export function useBuyAlerts(snapshot: LimitUpSignalSnapshot | undefined): BuyAlertControls {
  const [enabled, setEnabled] = useState(readEnabled);
  const [permission, setPermission] = useState<BuyAlertPermission>(currentPermission);
  const [speechRate, setSpeechRateState] = useState(readSpeechRate);
  const [banner, setBanner] = useState<BuyAlertBannerItem[]>([]);
  const alertState = useRef<BuyAlertState>(readAlertState());

  useEffect(() => {
    const result = evaluateBuyAlerts(snapshot, alertState.current, Date.now(), enabled);
    alertState.current = result.state;
    writeAlertState(result.state);
    if (!result.alerts.length) return;

    void playBuyAlertSound();
    speakBuyAlerts(result.alerts, { rate: speechRate });
    setBanner(result.alerts.map((signal) => ({
      key: `${snapshot?.trade_date}:${signal.vt_symbol}`,
      signal,
      alertedAt: Date.now(),
    })));
    for (const signal of result.alerts) {
      showNotification(buyAlertContent(signal), `limit-up:${snapshot?.trade_date}:${signal.vt_symbol}`);
    }
  }, [enabled, snapshot, speechRate]);

  const toggle = useCallback(async () => {
    if (enabled) {
      setEnabled(false);
      writeEnabled(false);
      cancelBuyAlertSpeech();
      return currentPermission();
    }

    const audioReady = unlockBuyAlertAudio();
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
    speakBuyAlertTest({ rate: speechRate });
    await sound;
    showNotification(
      {
        title: "AlphaAgent 买点提醒测试",
        body: "声音、语音播报和桌面通知测试完成；真实买点会读出股票名、涨幅和距板。",
      },
      "limit-up:test",
    );
    return nextPermission;
  }, [speechRate]);

  const setSpeechRate = useCallback((rate: number) => {
    setSpeechRateState(rate);
    writeSpeechRate(rate);
  }, []);

  const dismissBanner = useCallback(() => {
    setBanner([]);
    cancelBuyAlertSpeech();
  }, []);

  return {
    enabled,
    permission,
    speechAvailable: speechSupported(),
    speechRate,
    banner,
    toggle,
    test,
    setSpeechRate,
    dismissBanner,
  };
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

function readSpeechRate(): number {
  if (typeof window === "undefined") return DEFAULT_SPEECH_RATE;
  try {
    const raw = window.localStorage.getItem(RATE_STORAGE_KEY);
    const value = raw == null ? NaN : Number(raw);
    return Number.isFinite(value) && value > 0 ? value : DEFAULT_SPEECH_RATE;
  } catch {
    return DEFAULT_SPEECH_RATE;
  }
}

function writeSpeechRate(rate: number): void {
  try {
    window.localStorage.setItem(RATE_STORAGE_KEY, String(rate));
  } catch {
    // Rate stays in memory when storage is unavailable.
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
