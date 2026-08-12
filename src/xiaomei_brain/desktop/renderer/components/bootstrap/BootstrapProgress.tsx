import { useTranslation } from "react-i18next";
import type { BootstrapStep } from "../../types";

const CUSTOM_STEPS: Array<{ id: string; steps: BootstrapStep[] }> = [
  { id: "runtime", steps: ["runtime"] },
  { id: "inference", steps: ["inference"] },
  { id: "embedding", steps: ["embedding"] },
  { id: "optional", steps: ["optional_services"] },
  { id: "identity", steps: ["identity"] },
  { id: "agent", steps: ["agent"] },
  { id: "model", steps: ["model"] },
  { id: "complete", steps: ["complete"] },
];

const QUICK_STEPS: Array<{ id: string; steps: BootstrapStep[] }> = [
  { id: "prepare", steps: ["runtime", "inference", "embedding", "agent"] },
  { id: "identity", steps: ["identity"] },
  { id: "model", steps: ["model"] },
  { id: "complete", steps: ["complete"] },
];

export function BootstrapProgress({ mode, current }: {
  mode: "quick" | "custom" | "";
  current: BootstrapStep;
}) {
  const { t } = useTranslation();
  if (!mode) return null;
  const items = mode === "quick" ? QUICK_STEPS : CUSTOM_STEPS;
  const found = items.findIndex((item) => item.steps.includes(current));
  const currentIndex = found < 0 ? 0 : found;

  return (
    <ol className={`bootstrap-stepper ${mode === "quick" ? "is-quick" : "is-custom"}`}>
      {items.map((item, index) => {
        const completed = current === "complete" ? index < items.length - 1 : index < currentIndex;
        const active = current === "complete" ? index === items.length - 1 : index === currentIndex;
        return (
          <li key={item.id} className={completed ? "complete" : active ? "active" : ""} aria-current={active ? "step" : undefined}>
            <span aria-hidden="true">{completed ? "✓" : index + 1}</span>
            <small>{t(`bootstrap.steps.${item.id}`)}</small>
          </li>
        );
      })}
    </ol>
  );
}
