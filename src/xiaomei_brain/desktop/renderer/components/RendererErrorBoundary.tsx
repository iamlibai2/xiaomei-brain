import { Component, type ErrorInfo, type ReactNode } from "react";
import i18n from "../i18n";
import { Button } from "./ui";

interface Props {
  children: ReactNode;
}

interface State {
  error: Error | null;
}

function report(type: string, error: unknown, componentStack = ""): void {
  const normalized = error instanceof Error ? error : new Error(String(error));
  try {
    window.desktop?.reportRendererError({
      type,
      message: normalized.message,
      stack: normalized.stack,
      componentStack,
    });
  } catch (reportError) {
    console.error("Failed to report renderer error", reportError, normalized);
  }
}

export function installRendererErrorReporting(): () => void {
  const handleError = (event: ErrorEvent) => {
    report("window-error", event.error || event.message);
  };
  const handleRejection = (event: PromiseRejectionEvent) => {
    report("unhandled-rejection", event.reason);
  };
  window.addEventListener("error", handleError);
  window.addEventListener("unhandledrejection", handleRejection);
  return () => {
    window.removeEventListener("error", handleError);
    window.removeEventListener("unhandledrejection", handleRejection);
  };
}

export class RendererErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    report("react-boundary", error, info.componentStack || "");
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <main className="renderer-fatal-error" role="alert">
        <div className="renderer-fatal-error-card">
          <span className="renderer-fatal-error-mark">!</span>
          <h1>{i18n.t("renderer.errorTitle")}</h1>
          <p>{i18n.t("renderer.errorDescription")}</p>
          <code>{this.state.error.message}</code>
          <div className="renderer-fatal-error-actions">
            <Button variant="primary" onClick={() => window.location.reload()}>{i18n.t("renderer.reload")}</Button>
            <Button variant="secondary" onClick={() => { void window.desktop.openLogDirectory(); }}>
              {i18n.t("renderer.openLogs")}
            </Button>
          </div>
        </div>
      </main>
    );
  }
}
