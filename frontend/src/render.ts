import type { MessageOut, PartOut } from "./types";
import { renderMarkdown } from "./markdown";

function el<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  className?: string,
): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag);
  if (className) node.className = className;
  return node;
}

function pre(text: string, limit = 2000): HTMLPreElement {
  const node = el("pre", "mono");
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
  const bubble = el("div", "msg user");
  const meta = el("div", "msg-meta");
  meta.textContent = "you";
  bubble.append(meta);
  const body = el("div", "msg-body");
  body.textContent = text;
  bubble.append(body);
  container.append(bubble);
  scrollToBottom(container);
  return bubble;
}

export function appendError(container: HTMLElement, text: string): HTMLElement {
  const bubble = el("div", "msg error");
  const body = el("div", "msg-body");
  body.textContent = text;
  bubble.append(body);
  container.append(bubble);
  scrollToBottom(container);
  return bubble;
}

export interface ToolHandle {
  progress(text: string): void;
  finish(result: unknown, ok: boolean): void;
  element: HTMLElement;
}

export interface AssistantTurn {
  element: HTMLElement;
  addText(delta: string): void;
  replaceText(text: string): void;
  addTool(name: string, args: Record<string, unknown> | null): ToolHandle;
  addProgress(text: string): void;
  addError(text: string): void;
}

export function createAssistantTurn(container: HTMLElement): AssistantTurn {
  const turn = el("div", "turn assistant");
  container.append(turn);
  scrollToBottom(container);

  let text = "";
  let textEl: HTMLElement | null = null;

  const ensureTextEl = (): HTMLElement => {
    const last = turn.lastElementChild;
    const canMerge = textEl !== null && turn.contains(textEl) && last === textEl;
    if (!canMerge) {
      textEl = el("div", "msg-body text");
      turn.append(textEl);
      scrollToBottom(container);
    }
    return textEl!;
  };

  function addToolCard(name: string, args: Record<string, unknown> | null): ToolHandle {
    const card = el("div", "toolcard");
    const head = el("button", "toolcard-head");
    head.type = "button";
    const dot = el("span", "tool-dot");
    const label = el("span", "tool-name");
    label.textContent = name;
    const state = el("span", "tool-state running");
    state.textContent = "running";
    const chevron = el("span", "tool-chevron");
    chevron.textContent = "▸";
    head.append(dot, label, state, chevron);

    const body = el("div", "toolcard-body");
    body.hidden = true;
    if (args && Object.keys(args).length > 0) {
      const argsEl = el("div", "tool-args");
      argsEl.append(pre(jsonText(args), 600));
      body.append(argsEl);
    }
    const progressEl = el("div", "tool-progress");
    body.append(progressEl);
    const resultEl = el("div", "tool-result");
    resultEl.hidden = true;
    body.append(resultEl);
    card.append(head, body);
    turn.append(card);

    head.addEventListener("click", () => {
      body.hidden = !body.hidden;
      chevron.textContent = body.hidden ? "▸" : "▾";
    });

    const handle: ToolHandle = {
      progress(textLine: string) {
        const line = el("div", "tool-progress-line");
        line.textContent = textLine;
        progressEl.append(line);
        scrollToBottom(container);
      },
      finish(result: unknown, ok: boolean) {
        state.textContent = ok ? "done" : "error";
        state.classList.remove("running");
        state.classList.add(ok ? "done" : "error");
        if (result !== null && result !== undefined) {
          resultEl.hidden = false;
          resultEl.append(pre(jsonText(result), 6000));
        }
        if (!ok) state.textContent = "error";
        scrollToBottom(container);
      },
      element: card,
    };
    return handle;
  }

  return {
    element: turn,
    addText(delta: string) {
      text += delta;
      ensureTextEl().innerHTML = renderMarkdown(text);
      scrollToBottom(container);
    },
    replaceText(full: string) {
      text = full;
      ensureTextEl().innerHTML = renderMarkdown(text);
      scrollToBottom(container);
    },
    addTool: addToolCard,
    addProgress(line: string) {
      const node = el("div", "msg-progress");
      node.textContent = line;
      turn.append(node);
      scrollToBottom(container);
    },
    addError(msg: string) {
      const node = el("div", "msg-error");
      node.textContent = msg;
      turn.append(node);
      scrollToBottom(container);
    },
  };
}

export function renderMessages(container: HTMLElement, messages: MessageOut[]): void {
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

  container.textContent = "";
  container.append(...Array.from(host.childNodes));
  scrollToBottom(container);
}

export function scrollToBottom(container: HTMLElement): void {
  container.scrollTop = container.scrollHeight;
}
