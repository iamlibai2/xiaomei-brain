export type EmbodimentCommandStatus = "completed" | "failed" | "rejected";

export interface EmbodimentCommandRequest {
  commandId: string;
  embodimentId: string;
  command: string;
  arguments: Record<string, unknown>;
  agentId: string;
  sessionId: string;
  signal: AbortSignal;
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
const activeCommands = new Map<string, AbortController>();

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
  request: Omit<EmbodimentCommandRequest, "signal">,
): Promise<EmbodimentCommandResult> {
  const handler = handlers.get(request.command);
  if (!handler) {
    return { status: "rejected", error: `Desktop 不支持命令: ${request.command}` };
  }
  const controller = new AbortController();
  activeCommands.set(request.commandId, controller);
  try {
    return await handler({ ...request, signal: controller.signal });
  } catch (error) {
    if (controller.signal.aborted) {
      return { status: "rejected", error: "Desktop command cancelled" };
    }
    return {
      status: "failed",
      error: error instanceof Error ? error.message : String(error),
    };
  } finally {
    if (activeCommands.get(request.commandId) === controller) {
      activeCommands.delete(request.commandId);
    }
  }
}

export function cancelEmbodimentCommand(commandId: string): boolean {
  const controller = activeCommands.get(commandId);
  if (!controller) return false;
  controller.abort();
  return true;
}
