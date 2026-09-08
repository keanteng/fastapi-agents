import { api } from "./api";
import type { RunEvent, RunResponse, RunStep, RunStatus } from "./types";

const TERMINAL = new Set<RunStatus>(["completed", "failed", "cancelled"]);

export interface RunStreamHandlers {
  onDelta(text: string): void;
  onTextDone(text: string): void;
  onToolStarted(call: {
    tool_call_id: string;
    name: string;
    args: Record<string, unknown>;
  }): void;
  onStep(step: RunStep): void;
  onTerminal(run: RunResponse): void;
}

interface ToolStartedData {
  tool_call_id: string;
  name: string;
  args: Record<string, unknown>;
}

function eventOf(msg: MessageEvent<string>): RunEvent {
  return JSON.parse(msg.data) as RunEvent;
}

export function attachRunStream(runId: string, handlers: RunStreamHandlers): void {
  const source = new EventSource(`/api/v1/runs/${runId}/events`);
  let settled = false;
  let pollTimer: number | null = null;

  const stopPolling = (): void => {
    if (pollTimer !== null) {
      window.clearInterval(pollTimer);
      pollTimer = null;
    }
  };

  const settle = (run: RunResponse): void => {
    if (settled) return;
    settled = true;
    source.close();
    stopPolling();
    handlers.onTerminal(run);
  };

  const handleEvent = (msg: MessageEvent<string>): void => {
    const event = eventOf(msg);
    if (event.type === "response.output_text.delta") {
      handlers.onDelta((event.data.delta as string) ?? "");
    } else if (event.type === "response.output_text.done") {
      handlers.onTextDone((event.data.text as string) ?? "");
    } else if (event.type === "run.tool.started") {
      const d = event.data as unknown as ToolStartedData;
      handlers.onToolStarted(d);
    } else if (event.type === "run.step") {
      const step = (event.data as { step: RunStep }).step;
      if (step) handlers.onStep(step);
    } else if (event.type === "response.completed") {
      void api.getRun(runId).then(settle);
    } else if (event.type === "response.failed" || event.type === "run.cancelled") {
      void api.getRun(runId).then(settle);
    }
  };

  for (const name of [
    "response.output_text.delta",
    "response.output_text.done",
    "run.tool.started",
    "run.step",
    "response.completed",
    "response.failed",
    "run.cancelled",
  ]) {
    source.addEventListener(name, handleEvent as EventListener);
  }

  source.onerror = () => {
    // The server closed the stream (terminal already handled) or it failed;
    // fall back to polling the authoritative run state.
    if (settled) {
      source.close();
      return;
    }
    source.close();
    if (pollTimer === null) {
      pollTimer = window.setInterval(() => {
        void api
          .getRun(runId)
          .then((run) => {
            if (TERMINAL.has(run.status)) settle(run);
          })
          .catch(() => undefined);
      }, 1500);
    }
  };
}
