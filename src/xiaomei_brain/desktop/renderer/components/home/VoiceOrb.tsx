import { useEffect, useRef } from "react";

export type VoiceOrbPhase = "listening" | "waiting" | "hearing" | "processing" | "speaking";

interface VoiceOrbProps {
  levelRef: React.MutableRefObject<number>;
  phase: VoiceOrbPhase;
}

const COLORS: Record<VoiceOrbPhase, [string, string, string]> = {
  listening: ["#8b83f6", "#70c8ce", "#b49aef"],
  waiting: ["#8d879d", "#7f9298", "#9c8faa"],
  hearing: ["#6f78ee", "#49bcc6", "#a376e6"],
  processing: ["#8178ed", "#a379e4", "#62b9cc"],
  speaking: ["#6d8eea", "#79c7bd", "#9c82e6"],
};

export function VoiceOrb({ levelRef, phase }: VoiceOrbProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const phaseRef = useRef(phase);

  useEffect(() => {
    phaseRef.current = phase;
  }, [phase]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const context = canvas.getContext("2d");
    if (!context) return;

    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
    let frame = 0;
    let visualLevel = 0;

    const draw = (time: number) => {
      const ratio = Math.min(window.devicePixelRatio || 1, 2);
      const displaySize = 96;
      const size = Math.round(displaySize * ratio);
      if (canvas.width !== size || canvas.height !== size) {
        canvas.width = size;
        canvas.height = size;
      }
      context.setTransform(ratio, 0, 0, ratio, 0, 0);
      context.clearRect(0, 0, displaySize, displaySize);

      const currentPhase = phaseRef.current;
      const microphoneLevel = Math.min(1, Math.max(0, levelRef.current * 18));
      const syntheticLevel = currentPhase === "speaking"
        ? 0.24 + Math.sin(time / 115) * 0.09 + Math.sin(time / 53) * 0.05
        : currentPhase === "processing"
          ? 0.12 + Math.sin(time / 240) * 0.05
          : 0.035;
      const targetLevel = currentPhase === "hearing"
        ? Math.max(microphoneLevel, 0.08)
        : syntheticLevel;
      visualLevel += (targetLevel - visualLevel) * 0.16;

      const colors = COLORS[currentPhase];
      const still = reducedMotion.matches;
      const t = still ? 0 : time / 1000;
      drawGlow(context, 48, 48, 27 + visualLevel * 7, colors[1]);
      drawBlob(context, 48, 48, 24 + visualLevel * 8, t, visualLevel, colors, still);

      frame = window.requestAnimationFrame(draw);
    };

    frame = window.requestAnimationFrame(draw);
    return () => window.cancelAnimationFrame(frame);
  }, [levelRef]);

  return (
    <canvas
      ref={canvasRef}
      className="voice-live-orb"
      width={96}
      height={96}
      aria-hidden="true"
    />
  );
}

function drawGlow(
  context: CanvasRenderingContext2D,
  x: number,
  y: number,
  radius: number,
  color: string,
) {
  const gradient = context.createRadialGradient(x, y, radius * 0.15, x, y, radius * 1.5);
  gradient.addColorStop(0, withAlpha(color, 0.22));
  gradient.addColorStop(0.52, withAlpha(color, 0.1));
  gradient.addColorStop(1, withAlpha(color, 0));
  context.fillStyle = gradient;
  context.beginPath();
  context.arc(x, y, radius * 1.55, 0, Math.PI * 2);
  context.fill();
}

function drawBlob(
  context: CanvasRenderingContext2D,
  x: number,
  y: number,
  radius: number,
  time: number,
  level: number,
  colors: [string, string, string],
  still: boolean,
) {
  const pulse = still ? 0 : Math.sin(time * 2.2) * 0.018;
  const drift = still ? 0 : Math.sin(time * 0.9) * 0.035;
  const stretchX = 1 + pulse + level * 0.2;
  const stretchY = 1 - pulse * 0.5 - level * 0.055;
  context.save();
  context.translate(x, y);
  context.rotate(drift);
  context.scale(stretchX, stretchY);
  context.shadowBlur = 14;
  context.shadowColor = withAlpha(colors[0], 0.34);
  context.beginPath();
  context.arc(0, 0, radius, 0, Math.PI * 2);
  const gradient = context.createLinearGradient(-radius, -radius, radius, radius);
  gradient.addColorStop(0, colors[0]);
  gradient.addColorStop(0.48, colors[1]);
  gradient.addColorStop(1, colors[2]);
  context.fillStyle = gradient;
  context.fill();

  const highlight = context.createRadialGradient(
    -radius * 0.35,
    -radius * 0.42,
    1,
    -radius * 0.2,
    -radius * 0.25,
    radius * 1.1,
  );
  highlight.addColorStop(0, "rgba(255,255,255,.48)");
  highlight.addColorStop(0.38, "rgba(255,255,255,.08)");
  highlight.addColorStop(1, "rgba(255,255,255,0)");
  context.fillStyle = highlight;
  context.fill();
  context.restore();
}

function withAlpha(hex: string, alpha: number): string {
  const normalized = hex.replace("#", "");
  const red = Number.parseInt(normalized.slice(0, 2), 16);
  const green = Number.parseInt(normalized.slice(2, 4), 16);
  const blue = Number.parseInt(normalized.slice(4, 6), 16);
  return `rgba(${red},${green},${blue},${alpha})`;
}
