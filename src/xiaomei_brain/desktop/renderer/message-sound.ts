import { isDesktopSpeechActive } from "./embodiment";

let enabled = true;
let liveVoiceActive = false;

export function setMessageSoundEnabled(value: boolean): void {
  enabled = value;
}

export function setLiveVoiceActive(value: boolean): void {
  liveVoiceActive = value;
}

/** Play one restrained local chime without loading an external audio asset. */
export async function playMessageSound(): Promise<void> {
  if (!enabled || liveVoiceActive || isDesktopSpeechActive()) return;

  const context = new AudioContext();
  try {
    await context.resume();
    playTone(context, 620, 0, 0.11, 0.032);
    playTone(context, 820, 0.1, 0.17, 0.026);
    window.setTimeout(() => {
      void context.close().catch(() => undefined);
    }, 420);
  } catch {
    void context.close().catch(() => undefined);
  }
}

function playTone(
  context: AudioContext,
  frequency: number,
  delay: number,
  duration: number,
  volume: number,
): void {
  const start = context.currentTime + delay;
  const oscillator = context.createOscillator();
  const gain = context.createGain();
  oscillator.type = "sine";
  oscillator.frequency.setValueAtTime(frequency, start);
  gain.gain.setValueAtTime(0.0001, start);
  gain.gain.exponentialRampToValueAtTime(volume, start + 0.018);
  gain.gain.exponentialRampToValueAtTime(0.0001, start + duration);
  oscillator.connect(gain);
  gain.connect(context.destination);
  oscillator.start(start);
  oscillator.stop(start + duration + 0.01);
}
