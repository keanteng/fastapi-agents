import { icon, replaceIcon } from "./icons";
import { renderMarkdown } from "./markdown";
import {
  Alert,
  Avatar,
  Badge,
  Button,
  Collapsible,
  EmptyState,
  el,
  withTooltip,
} from "./ui";
import type { MessageOut, PartOut } from "./types";

function pre(text: string, limit = 6000): HTMLPreElement {
  const node = el("pre", { class: "tool-pre" });
  const clipped = text.length > limit ? `${text.slice(0, limit)}\n…[truncated]` : text;
  node.textContent = clipped;
  return node;
}

export function jsonText(value: unknown): string {
  if (value === null || value === undefined) return "(none)";
  if (typeof value === "string") return value;
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

export function appendUserBubble(container: HTMLElement, text: string): HTMLElement {
  const bubble = el("div", { class: "message-user", text });
  container.append(bubble);
  scrollToBottom(container);
  return bubble;
}

export function appendNote(container: HTMLElement, text: string): HTMLElement {
  const node = el("div", { class: "message-system", text });
  container.append(node);
  scrollToBottom(container);
  return node;
}

export function appendError(container: HTMLElement, text: string): HTMLElement {
  const node = Alert(text, { variant: "destructive", class: "turn-error" });
  container.append(node);
  scrollToBottom(container);
  return node;
}

export function renderEmptyState(container: HTMLElement): void {
  container.textContent = "";
  container.append(
    EmptyState({
      title: "How can I help?",
      description:
        "Ask a question, or attach a file and the agent will decide which tools to use.",
      icon: "sparkles",
    }),
  );
}

export interface ToolHandle {
  progress(text: string): void;
  finish(result: unknown, ok: boolean): void;
  element: HTMLElement;
}

interface ToolEntry {
  name: string;
  running: boolean;
  failed: boolean;
  progressEl: HTMLElement;
  resultEl: HTMLElement;
  stateEl: HTMLElement;
}

interface ToolGroupHandle {
  element: HTMLElement;
  addTool(name: string, args: Record<string, unknown> | null): ToolHandle;
  addProgress(text: string): void;
}

/**
 * A single ChatGPT-style disclosure holding every tool call of one assistant
 * turn. It stays collapsed by default and summarises activity on one compact
 * line ("Running web_search…", "Ran 3 tools"), so the transcript isn't flooded
 * with a card per call. Expanding reveals each call's arguments and result.
 */
function createToolGroup(): ToolGroupHandle {
  const trigger = el("button", {
    class: "collapsible-trigger toolgroup-trigger",
    attrs: { type: "button" },
  });
  const groupIcon = el("span", { class: "tool-icon" });
  groupIcon.append(icon("wrench", 15));
  const summary = el("span", { class: "tool-group-summary", text: "Working…" });
  const stateSlot = el("span", { class: "tool-state" });
  const chevron = el("span", { class: "tool-chevron" });
  chevron.append(icon("chevron-down", 15));
  trigger.append(groupIcon, summary, stateSlot, chevron);

  const list = el("div", { class: "tool-group-list" });
  const parts = Collapsible(trigger, list, { class: "toolgroup" });

  const entries: ToolEntry[] = [];

  const renderSummary = (): void => {
    stateSlot.replaceChildren();
    if (entries.length === 0) {
      summary.textContent = "Working…";
      return;
    }
    const running = entries.find((entry) => entry.running);
    if (running) {
      summary.textContent = `Running ${running.name}…`;
      stateSlot.append(Badge("running", { variant: "default", icon: "loader" }));
      return;
    }
    summary.textContent =
      entries.length === 1 ? `Ran ${entries[0].name}` : `Ran ${entries.length} tools`;
    const failures = entries.filter((entry) => entry.failed).length;
    stateSlot.append(
      failures > 0
        ? Badge(`${failures} error${failures > 1 ? "s" : ""}`, {
            variant: "destructive",
            icon: "x",
          })
        : Badge("done", { variant: "success", icon: "check" }),
    );
  };
  renderSummary();

  const addTool = (
    name: string,
    args: Record<string, unknown> | null,
  ): ToolHandle => {
    const entryEl = el("div", { class: "tool-entry" });
    const head = el("div", { class: "tool-entry-head" });
    const entryIcon = el("span", { class: "tool-icon" });
    entryIcon.append(icon("wrench", 14));
    const stateEl = el("span", { class: "tool-entry-state" });
    stateEl.append(Badge("running", { variant: "default", icon: "loader" }));
    head.append(entryIcon, el("span", { class: "tool-name", text: name }), stateEl);

    const bodyEl = el("div", { class: "toolcard-body" });
    if (args && Object.keys(args).length > 0) {
      const argsWrap = el("div");
      argsWrap.append(
        el("div", { class: "tool-label", text: "Arguments" }),
        pre(jsonText(args), 600),
      );
      bodyEl.append(argsWrap);
    }
    const progressEl = el("div", { class: "tool-progress" });
    const resultEl = el("div", { class: "tool-result" });
    resultEl.hidden = true;
    bodyEl.append(progressEl, resultEl);
    entryEl.append(head, bodyEl);
    list.append(entryEl);

    const entry: ToolEntry = {
      name,
      running: true,
      failed: false,
      progressEl,
      resultEl,
      stateEl,
    };
    entries.push(entry);
    renderSummary();

    const handle: ToolHandle = {
      progress(textLine: string) {
        progressEl.append(el("div", { class: "tool-progress-line", text: textLine }));
      },
      finish(result: unknown, ok: boolean) {
        entry.running = false;
        entry.failed = !ok;
        stateEl.replaceChildren(
          Badge(ok ? "done" : "error", {
            variant: ok ? "success" : "destructive",
            icon: ok ? "check" : "x",
          }),
        );
        if (result !== null && result !== undefined && result !== "") {
          resultEl.hidden = false;
          resultEl.append(
            el("div", { class: "tool-label", text: "Result" }),
            pre(jsonText(result)),
          );
        }
        renderSummary();
      },
      element: entryEl,
    };
    return handle;
  };

  return {
    element: parts.element,
    addTool,
    addProgress(text: string) {
      const running = [...entries].reverse().find((entry) => entry.running);
      (running ? running.progressEl : list).append(
        el("div", { class: "tool-progress-line", text }),
      );
    },
  };
}

export interface AssistantTurn {
  element: HTMLElement;
  body: HTMLElement;
  addText(delta: string): void;
  replaceText(text: string): void;
  addTool(name: string, args: Record<string, unknown> | null): ToolHandle;
  addProgress(text: string): void;
  addError(text: string): void;
}

export function createAssistantTurn(container: HTMLElement): AssistantTurn {
  const turn = el("div", { class: "turn-assistant" });
  turn.append(Avatar({ icon: "sparkles" }));
  const body = el("div", { class: "turn-body" });
  turn.append(body);
  container.append(turn);
  scrollToBottom(container);

  const actions = el("div", { class: "turn-actions" });
  const copyBtn = Button({
    variant: "ghost",
    size: "icon-sm",
    icon: "copy",
    title: "Copy response",
  });
  copyBtn.hidden = true;
  actions.append(withTooltip(copyBtn, "Copy response"));
  body.append(actions);

  let text = "";
  let textEl: HTMLElement | null = null;

  const refreshActions = (): void => {
    copyBtn.hidden = text.length === 0;
    body.append(actions); // keep the action row last
  };

  const ensureTextEl = (): HTMLElement => {
    // Only reuse the current block if nothing (e.g. a tool card) was added
    // after it since the last delta.
    const canMerge = textEl !== null && textEl.nextElementSibling === actions;
    if (!canMerge) {
      textEl = el("div", { class: "prose" });
      body.insertBefore(textEl, actions);
      scrollToBottom(container);
    }
    return textEl!;
  };

  let copiedTimer: number | null = null;
  copyBtn.addEventListener("click", () => {
    void (async () => {
      if (!text) return;
      try {
        await navigator.clipboard.writeText(text);
      } catch {
        return;
      }
      replaceIcon(copyBtn, "check");
      if (copiedTimer !== null) window.clearTimeout(copiedTimer);
      copiedTimer = window.setTimeout(() => replaceIcon(copyBtn, "copy"), 1200);
    })();
  });

  // One disclosure per turn, created lazily the first time a tool runs and
  // kept above the action row so every tool call collapses together.
  let toolGroup: ToolGroupHandle | null = null;
  const ensureToolGroup = (): ToolGroupHandle => {
    if (toolGroup === null) {
      toolGroup = createToolGroup();
      body.insertBefore(toolGroup.element, actions);
    }
    return toolGroup;
  };

  function addToolCard(
    name: string,
    args: Record<string, unknown> | null,
  ): ToolHandle {
    const raw = ensureToolGroup().addTool(name, args);
    refreshActions();
    scrollToBottom(container);
    return {
      element: raw.element,
      progress(textLine: string) {
        raw.progress(textLine);
        scrollToBottom(container);
      },
      finish(result: unknown, ok: boolean) {
        raw.finish(result, ok);
        scrollToBottom(container);
      },
    };
  }

  return {
    element: turn,
    body,
    addText(delta: string) {
      text += delta;
      ensureTextEl().innerHTML = renderMarkdown(text);
      refreshActions();
      scrollToBottom(container);
    },
    replaceText(full: string) {
      text = full;
      ensureTextEl().innerHTML = renderMarkdown(text);
      refreshActions();
      scrollToBottom(container);
    },
    addTool: addToolCard,
    addProgress(line: string) {
      ensureToolGroup().addProgress(line);
      refreshActions();
      scrollToBottom(container);
    },
    addError(msg: string) {
      body.append(Alert(msg, { variant: "destructive" }));
      refreshActions();
      scrollToBottom(container);
    },
  };
}

export function renderMessages(container: HTMLElement, messages: MessageOut[]): void {
  if (messages.length === 0) {
    renderEmptyState(container);
    return;
  }

  // Build into a detached host first and only swap it in on success, so a
  // mid-build error can never blank the transcript ("messages disappear").
  const host = document.createElement("div");
  const openTools = new Map<string, ToolHandle>();
  let lastAssistant: AssistantTurn | null = null;

  const flush = (): void => {
    for (const handle of openTools.values()) handle.finish("(result unavailable)", false);
    openTools.clear();
    lastAssistant = null;
  };

  function handlePart(part: PartOut): void {
    if (part.role === "user") {
      if (part.content) appendUserBubble(host, part.content);
      lastAssistant = null;
      return;
    }
    if (part.role === "assistant") {
      if (!lastAssistant) lastAssistant = createAssistantTurn(host);
      if (part.content) lastAssistant.addText(part.content);
      return;
    }
    if (part.role !== "tool") return;

    if (part.kind.includes("tool-call")) {
      const id = part.tool_call_id ?? `${part.tool_name}-${Math.random().toString(36).slice(2)}`;
      if (!lastAssistant) lastAssistant = createAssistantTurn(host);
      const handle = lastAssistant.addTool(part.tool_name ?? "tool", part.tool_args ?? null);
      openTools.set(id, handle);
      return;
    }
    // tool-return
    const id = part.tool_call_id ?? "";
    const handle = openTools.get(id);
    if (handle) {
      handle.finish(part.tool_result ?? "", true);
      openTools.delete(id);
    }
  }

  try {
    for (const message of messages) {
      for (const part of message.parts) {
        handlePart(part);
      }
    }
  } catch (err) {
    // Keep whatever is currently on screen; never wipe to an empty chat.
    console.error("renderMessages failed", err);
    return;
  }
  flush();

  if (host.childNodes.length === 0) {
    renderEmptyState(container);
    return;
  }
  container.textContent = "";
  container.append(...Array.from(host.childNodes));
  scrollToBottom(container);
}

export function scrollToBottom(container: HTMLElement): void {
  container.scrollTop = container.scrollHeight;
}
