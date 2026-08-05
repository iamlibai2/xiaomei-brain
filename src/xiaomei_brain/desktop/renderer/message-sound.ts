import { isDesktopSpeechActive } from "./embodiment";
import type { DesktopSettings } from "./types";

type MessageSound = DesktopSettings["messageSound"];

let liveVoiceActive = false;
let audioContext: AudioContext | null = null;
let selectedSound: MessageSound = "soft";

export function setMessageSound(value: MessageSound): void {
  selectedSound = value;
}

export function setLiveVoiceActive(value: boolean): void {
  liveVoiceActive = value;
}

/**
 * Unlock Web Audio while a user gesture is still active. Chromium may refuse
 * to start a new AudioContext when the Agent reply arrives several seconds
 * after the click that sent the message.
 */
export function initializeMessageSound(): () => void {
  const unlock = () => {
    void ensureAudioContext().catch((error) => {
      console.warn(`[message-sound] failed to unlock audio: ${String(error)}`);
    });
  };
  window.addEventListener("pointerdown", unlock, { capture: true, passive: true });
  window.addEventListener("keydown", unlock, { capture: true });
  return () => {
    window.removeEventListener("pointerdown", unlock, { capture: true });
    window.removeEventListener("keydown", unlock, { capture: true });
  };
}

/** Play one restrained local chime without loading an external audio asset. */
export async function playMessageSound(): Promise<void> {
  if (selectedSound === "none" || liveVoiceActive || isDesktopSpeechActive()) return;

  await play(selectedSound);
}

export async function previewMessageSound(sound: MessageSound): Promise<void> {
  if (sound === "none") return;
  await play(sound);
}

async function play(sound: MessageSound): Promise<void> {
  try {
    const context = await ensureAudioContext();
    if (sound === "crisp") {
      playTone(context, 980, 0, 0.1, 0.24, "triangle");
    } else if (sound === "bubble") {
      playGlide(context, 420, 760, 0, 0.18, 0.22);
      playTone(context, 920, 0.14, 0.09, 0.13);
    } else {
      playTone(context, 620, 0, 0.11, 0.22);
      playTone(context, 820, 0.1, 0.17, 0.16);
    }
  } catch (error) {
    console.warn(`[message-sound] playback failed: ${String(error)}`);
  }
}

async function ensureAudioContext(): Promise<AudioContext> {
  if (!audioContext || audioContext.state === "closed") {
    audioContext = new AudioContext();
  }
  if (audioContext.state === "suspended") await audioContext.resume();
  return audioContext;
}

function playTone(
  context: AudioContext,
  frequency: number,
  delay: number,
  duration: number,
  volume: number,
  type: OscillatorType = "sine",
): void {
  const start = context.currentTime + delay;
  const oscillator = context.createOscillator();
  const gain = context.createGain();
  oscillator.type = type;
  oscillator.frequency.setValueAtTime(frequency, start);
  gain.gain.setValueAtTime(0.0001, start);
  gain.gain.exponentialRampToValueAtTime(volume, start + 0.018);
  gain.gain.exponentialRampToValueAtTime(0.0001, start + duration);
  oscillator.connect(gain);
  gain.connect(context.destination);
  oscillator.start(start);
  oscillator.stop(start + duration + 0.01);
}

function playGlide(
  context: AudioContext,
  from: number,
  to: number,
  delay: number,
  duration: number,
  volume: number,
): void {
  const start = context.currentTime + delay;
  const oscillator = context.createOscillator();
  const gain = context.createGain();
  oscillator.type = "sine";
  oscillator.frequency.setValueAtTime(from, start);
  oscillator.frequency.exponentialRampToValueAtTime(to, start + duration);
  gain.gain.setValueAtTime(0.0001, start);
  gain.gain.exponentialRampToValueAtTime(volume, start + 0.025);
  gain.gain.exponentialRampToValueAtTime(0.0001, start + duration);
  oscillator.connect(gain);
  gain.connect(context.destination);
  oscillator.start(start);
  oscillator.stop(start + duration + 0.01);
}
