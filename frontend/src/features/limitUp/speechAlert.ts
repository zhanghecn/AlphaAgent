import type { LimitUpLiveSignal } from "@/api/limitUp";

export interface SpeechSettings {
  rate: number;
}

export const DEFAULT_SPEECH_RATE = 1;
export const MIN_SPEECH_RATE = 0.6;
export const MAX_SPEECH_RATE = 1.6;

export function buyAlertSpeechText(signal: LimitUpLiveSignal): string {
  const name = signal.name || signal.vt_symbol;
  const parts = [`买点提醒，${name}`];
  if (signal.change_pct != null && Number.isFinite(signal.change_pct)) {
    parts.push(`现涨 ${formatSpeechPct(signal.change_pct)}`);
  }
  if (signal.distance_to_limit_pct != null && Number.isFinite(signal.distance_to_limit_pct)) {
    parts.push(`距板 ${formatSpeechPct(signal.distance_to_limit_pct)}`);
  }
  if (signal.strategy_name) {
    parts.push(signal.strategy_name);
  }
  return parts.join("，");
}

export function formatSpeechPct(value: number): string {
  return `${value.toFixed(1)}%`;
}

export function speechSupported(): boolean {
  return typeof window !== "undefined" && "speechSynthesis" in window;
}

let cachedZhVoice: SpeechSynthesisVoice | null | undefined;

function pickChineseVoice(): SpeechSynthesisVoice | null {
  if (cachedZhVoice !== undefined) return cachedZhVoice;
  if (!speechSupported()) {
    cachedZhVoice = null;
    return null;
  }
  const voices = window.speechSynthesis.getVoices();
  cachedZhVoice = voices.find((voice) => /^zh([-_]|$)/i.test(voice.lang))
    ?? voices.find((voice) => /chinese|中文|普通话/i.test(voice.name))
    ?? null;
  return cachedZhVoice;
}

if (speechSupported()) {
  // Chrome 异步加载语音列表，加载完成后刷新缓存
  window.speechSynthesis.onvoiceschanged = () => {
    cachedZhVoice = undefined;
  };
}

export function cancelBuyAlertSpeech(): void {
  if (!speechSupported()) return;
  window.speechSynthesis.cancel();
}

export function speakBuyAlerts(
  signals: LimitUpLiveSignal[],
  settings: SpeechSettings = { rate: DEFAULT_SPEECH_RATE },
): void {
  if (!speechSupported() || !signals.length) return;
  const synth = window.speechSynthesis;
  synth.cancel();
  const voice = pickChineseVoice();
  for (const signal of signals) {
    const utterance = new SpeechSynthesisUtterance(buyAlertSpeechText(signal));
    if (voice) utterance.voice = voice;
    utterance.lang = voice?.lang ?? "zh-CN";
    utterance.rate = clampRate(settings.rate);
    utterance.pitch = 1;
    utterance.volume = 1;
    synth.speak(utterance);
  }
}

export function speakBuyAlertTest(settings: SpeechSettings = { rate: DEFAULT_SPEECH_RATE }): void {
  if (!speechSupported()) return;
  const synth = window.speechSynthesis;
  synth.cancel();
  const voice = pickChineseVoice();
  const utterance = new SpeechSynthesisUtterance("买点提醒测试，语音播报已开启");
  if (voice) utterance.voice = voice;
  utterance.lang = voice?.lang ?? "zh-CN";
  utterance.rate = clampRate(settings.rate);
  synth.speak(utterance);
}

function clampRate(rate: number): number {
  if (!Number.isFinite(rate)) return DEFAULT_SPEECH_RATE;
  return Math.min(MAX_SPEECH_RATE, Math.max(MIN_SPEECH_RATE, rate));
}
