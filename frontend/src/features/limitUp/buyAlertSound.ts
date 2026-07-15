export interface BuyAlertTone {
  frequency: number;
  offset: number;
  duration: number;
  peakGain: number;
}

export const BUY_ALERT_RINGTONE_DURATION_SECONDS = 4.05;
export const BUY_ALERT_RINGTONE_PATTERN: BuyAlertTone[] = Array.from(
  { length: 6 },
  (_, round) => {
    const roundStart = round * 0.68;
    return [
      { frequency: 880, offset: roundStart, duration: 0.18, peakGain: 0.12 },
      { frequency: 1_175, offset: roundStart + 0.2, duration: 0.28, peakGain: 0.15 },
    ];
  },
).flat();

let audioContext: AudioContext | null = null;
let ringtonePlayingUntil = 0;

export async function unlockBuyAlertAudio(): Promise<AudioContext | null> {
  if (typeof window === "undefined") return null;
  try {
    const AudioContextConstructor = window.AudioContext
      ?? (window as typeof window & { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
    if (!AudioContextConstructor) return null;
    if (audioContext?.state === "closed") audioContext = null;
    audioContext ??= new AudioContextConstructor();
    if (audioContext.state === "suspended") await audioContext.resume();
    return audioContext;
  } catch {
    return null;
  }
}

export async function playBuyAlertSound(): Promise<void> {
  const context = await unlockBuyAlertAudio();
  if (!context || context.currentTime < ringtonePlayingUntil) return;

  const start = context.currentTime;
  ringtonePlayingUntil = start + BUY_ALERT_RINGTONE_DURATION_SECONDS;
  for (const tone of BUY_ALERT_RINGTONE_PATTERN) {
    playTone(context, tone, start + tone.offset);
  }
}

function playTone(context: AudioContext, tone: BuyAlertTone, start: number): void {
  const oscillator = context.createOscillator();
  const gain = context.createGain();
  const end = start + tone.duration;

  oscillator.type = "sine";
  oscillator.frequency.setValueAtTime(tone.frequency, start);
  gain.gain.setValueAtTime(0.0001, start);
  gain.gain.exponentialRampToValueAtTime(tone.peakGain, start + 0.018);
  gain.gain.exponentialRampToValueAtTime(0.0001, end);
  oscillator.connect(gain);
  gain.connect(context.destination);
  oscillator.start(start);
  oscillator.stop(end);
}
