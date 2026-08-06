export type EmbodimentCommandStatus = "completed" | "failed" | "rejected";

export interface EmbodimentCommandRequest {
  commandId: string;
  embodimentId: string;
  command: string;
  arguments: Record<string, unknown>;
  agentId: string;
  sessionId: string;
}

export interface EmbodimentCommandResult {
  status: EmbodimentCommandStatus;
  result?: Record<string, unknown>;
  error?: string;
}

type EmbodimentCommandHandler = (
  request: EmbodimentCommandRequest,
) => EmbodimentCommandResult | Promise<EmbodimentCommandResult>;

const handlers = new Map<string, EmbodimentCommandHandler>();

/** Register one allowlisted Desktop action. Raw JavaScript is never accepted. */
export function registerEmbodimentCommand(
  command: string,
  handler: EmbodimentCommandHandler,
): () => void {
  handlers.set(command, handler);
  return () => {
    if (handlers.get(command) === handler) handlers.delete(command);
  };
}

export async function executeEmbodimentCommand(
  request: EmbodimentCommandRequest,
): Promise<EmbodimentCommandResult> {
  const handler = handlers.get(request.command);
  if (!handler) {
    return { status: "rejected", error: `Desktop 不支持命令: ${request.command}` };
  }
  try {
    return await handler(request);
  } catch (error) {
    return {
      status: "failed",
      error: error instanceof Error ? error.message : String(error),
    };
  }
}
