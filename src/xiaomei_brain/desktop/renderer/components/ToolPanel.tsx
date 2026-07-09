import React from "react";

interface Props {
  toolName: string;
  status: string;
  params?: unknown;
  result?: unknown;
  onClose: () => void;
}

export function ToolPanel({ toolName, status, params, result, onClose }: Props) {
  return (
    <div className="tool-panel">
      <div className="tool-panel-header">
        <h3>Tool: {toolName}</h3>
        <button className="tool-panel-close" onClick={onClose}>
          ✕
        </button>
      </div>
      <div className="tool-panel-body">
        <div className="tool-field">
          <label>Status</label>
          <span className={`tool-status ${status}`}>{status}</span>
        </div>

        {params !== undefined && (
          <div className="tool-field">
            <label>Arguments</label>
            <pre className="tool-json">
              {typeof params === "string" ? params : JSON.stringify(params, null, 2)}
            </pre>
          </div>
        )}

        {result !== undefined && (
          <div className="tool-field">
            <label>Result</label>
            <pre className="tool-json">
              {typeof result === "string" ? result : JSON.stringify(result, null, 2)}
            </pre>
          </div>
        )}
      </div>
    </div>
  );
}
