import "./style.css";
import { api, ApiError } from "./api";
import {
  appendError,
  appendUserBubble,
  createAssistantTurn,
  renderMessages,
  scrollToBottom,
  type AssistantTurn,
  type ToolHandle,
} from "./render";
import { attachRunStream } from "./stream";
import type { RunStep, RunStatus } from "./types";

// ----- DOM refs -------------------------------------------------------------
const agentSelect = document.querySelector<HTMLSelectElement>("#agent")!;
const composerForm = document.querySelector<HTMLFormElement>("#composer-form")!;
const composerInput = document.querySelector<HTMLTextAreaElement>("#composer-input")!;
const sendBtn = document.querySelector<HTMLButtonElement>("#composer-send")!;
const stopBtn = document.querySelector<HTMLButtonElement>("#stop")!;
const attachBtn = document.querySelector<HTMLButtonElement>("#attach")!;
const fileInput = document.querySelector<HTMLInputElement>("#file-input")!;
const messagesEl = document.querySelector<HTMLElement>("#messages")!;
const conversationList = document.querySelector<HTMLElement>("#conversation-list")!;
const newChatBtn = document.querySelector<HTMLButtonElement>("#new-chat")!;
const statusEl = document.querySelector<HTMLElement>("#status")!;
const convLabel = document.querySelector<HTMLElement>("#conv-label")!;
const dropOverlay = document.querySelector<HTMLElement>("#drop-overlay")!;

// ----- State ----------------------------------------------------------------
let activeConversationId: string | null = null;
let currentRunId: string | null = null;
let busy = false;

const openTools = new Map<string, ToolHandle>();
let streamTurn: AssistantTurn | null = null;
let waitingEl: HTMLElement | null = null;
// True once the server told us the full assistant text (response.output_text.done).
let textDoneReceived = false;

// ----- Small helpers --------------------------------------------------------
function setStatus(status: RunStatus | "idle" | "uploading"): void {
  statusEl.textContent = status;
  statusEl.className = `status-${status}`;
  stopBtn.hidden = !(status === "running" || status === "pending");
}

function scrollBottom(): void {
  scrollToBottom(messagesEl);
}

function shortId(id: string): string {
  return id.length > 10 ? `${id.slice(0, 8)}…` : id;
}

function setComposerEnabled(enabled: boolean): void {
  sendBtn.disabled = !enabled;
  composerInput.disabled = !enabled;
  attachBtn.disabled = !enabled;
}

// ----- Conversation sidebar -------------------------------------------------
function renderConversationList(): void {
  conversationList.textContent = "";
  void api
    .conversations()
    .then((list) => {
      for (const conv of list) {
        const item = document.createElement("li");
        item.className =
          conv.conversation_id === activeConversationId
            ? "conversation-item active"
            : "conversation-item";

        const open = document.createElement("button");
        open.type = "button";
        open.className = "conversation-open";
        open.textContent =
          conv.preview?.replace(/\s+/g, " ") || "(empty conversation)";
        open.title = new Date(conv.updated_at).toLocaleString();
        open.addEventListener("click", () =>
          void openConversation(conv.conversation_id),
        );

        const del = document.createElement("button");
        del.type = "button";
        del.className = "conversation-delete";
        del.textContent = "×";
        del.title = "Delete conversation";
        del.addEventListener("click", (event) => {
          event.stopPropagation();
          void deleteConversation(conv.conversation_id);
        });

        item.append(open, del);
        conversationList.append(item);
      }
    })
    .catch(() => {
      // Backend unavailable; leave the list empty rather than crashing.
    });
  convLabel.textContent = activeConversationId ? shortId(activeConversationId) : "none";
}

async function openConversation(conversationId: string): Promise<void> {
  if (busy) return;
  activeConversationId = conversationId;
  currentRunId = null;
  messagesEl.textContent = "";
  streamTurn = null;
  openTools.clear();
  try {
    const detail = await api.conversation(conversationId);
    renderMessages(messagesEl, detail.messages);
  } catch (err) {
    appendError(messagesEl, `Failed to load conversation: ${messageOf(err)}`);
  }
  convLabel.textContent = shortId(conversationId);
  renderConversationList();
}

async function deleteConversation(conversationId: string): Promise<void> {
  try {
    await api.deleteConversation(conversationId);
  } catch (err) {
    appendError(messagesEl, `Failed to delete conversation: ${messageOf(err)}`);
  }
  if (activeConversationId === conversationId) {
    activeConversationId = null;
    messagesEl.textContent = "";
  }
  renderConversationList();
}

function startNewChat(): void {
  if (busy) return;
  activeConversationId = null;
  currentRunId = null;
  messagesEl.textContent = "";
  streamTurn = null;
  openTools.clear();
  convLabel.textContent = "none";
  renderConversationList();
}

// ----- Transcript rebuild after a run finishes ------------------------------
async function refreshTranscript(): Promise<void> {
  if (!activeConversationId) return;
  try {
    const detail = await api.conversation(activeConversationId);
    renderMessages(messagesEl, detail.messages);
  } catch {
    // leave the live transcript in place
  }
}

// ----- Run lifecycle --------------------------------------------------------
async function sendMessage(text: string, attachment?: string, agent?: string): Promise<void> {
  const trimmed = text.trim();
  if (!trimmed || busy) return;

  busy = true;
  setComposerEnabled(false);
  currentRunId = null;
  streamTurn = null;
  openTools.clear();
  textDoneReceived = false;
  waitingEl = null;
  setStatus("pending");

  const bubble = appendUserBubble(messagesEl, trimmed);
  if (attachment) {
    const chip = document.createElement("div");
    chip.className = "msg-attach";
    chip.textContent = `file: ${attachment}`;
    bubble.append(chip);
  }
  streamTurn = createAssistantTurn(messagesEl);
  waitingEl = document.createElement("div");
  waitingEl.className = "assistant-wait";
  waitingEl.textContent = "Agent is working…";
  streamTurn.element.append(waitingEl);
  scrollBottom();

  const dismissWaiting = (): void => {
    if (waitingEl && waitingEl.isConnected) waitingEl.remove();
    waitingEl = null;
  };

  const body: Record<string, unknown> = { agent: agent ?? agentSelect.value, input: trimmed };
  if (activeConversationId) body.conversation_id = activeConversationId;

  try {
    const run = await api.createRun(body);
    currentRunId = run.run_id;
    setStatus("running");
    if (run.conversation_id) activeConversationId = run.conversation_id;
    attachRunStream(run.run_id, {
      onDelta: (delta) => {
        dismissWaiting();
        if (delta) streamTurn?.addText(delta);
      },
      onTextDone: (text) => {
        textDoneReceived = true;
        dismissWaiting();
        if (text) streamTurn?.replaceText(text);
      },
      onToolStarted: (call) => {
        dismissWaiting();
        const turn =
          streamTurn ??
          (() => {
            streamTurn = createAssistantTurn(messagesEl);
            return streamTurn;
          })();
        const handle = turn.addTool(call.name, call.args ?? null);
        openTools.set(call.tool_call_id, handle);
      },
      onStep: (step: RunStep) => {
        dismissWaiting();
        handleStep(step);
      },
      onTerminal: (terminalRun) => {
        dismissWaiting();
        handleTerminal(terminalRun);
      },
    });
  } catch (err) {
    dismissWaiting();
    streamTurn?.addError(`Run failed to start: ${messageOf(err)}`);
    busy = false;
    setComposerEnabled(true);
    setStatus("failed");
  }
}

function handleStep(step: RunStep): void {
  if (step.type === "tool_call") {
    if (step.tool_call_id && openTools.has(step.tool_call_id)) {
      const handle = openTools.get(step.tool_call_id)!;
      openTools.delete(step.tool_call_id);
      handle.finish(step.result ?? "(no result)", true);
    }
    return;
  }
  if (step.type === "progress") {
    streamTurn?.addProgress(step.summary);
    return;
  }
}

async function handleTerminal(run: {
  status: RunStatus;
  conversation_id: string | null;
  error: { code: string; message: string } | null;
}): Promise<void> {
  busy = false;
  setComposerEnabled(true);
  setStatus(run.status);

  for (const handle of openTools.values()) handle.finish("(interrupted)", false);
  openTools.clear();

  if (run.status === "failed") {
    streamTurn?.addError(
      run.error ? `Run failed (${run.error.code}): ${run.error.message}` : "Run failed.",
    );
    return;
  }
  if (run.status === "cancelled") {
    streamTurn?.addError("Run cancelled.");
    return;
  }

  if (run.conversation_id) activeConversationId = run.conversation_id;
  convLabel.textContent = activeConversationId ? shortId(activeConversationId) : "none";
  if (!textDoneReceived) {
    // We never saw the full final text on the stream (e.g. polling fallback or
    // a dropped connection): rebuild from the persisted transcript so the
    // reply is never missing.
    await refreshTranscript();
  }
  renderConversationList();
  composerInput.focus();
}

async function cancelRun(): Promise<void> {
  if (!currentRunId) return;
  setStatus("cancelled");
  stopBtn.hidden = true;
  try {
    await api.cancelRun(currentRunId);
  } catch {
    // the run may already be terminal
  }
}

// ----- Uploads --------------------------------------------------------------
function note(text: string): void {
  const node = document.createElement("div");
  node.className = "msg system";
  node.textContent = text;
  messagesEl.append(node);
  scrollBottom();
}

async function handleFile(file: File): Promise<void> {
  if (busy || !file) return;
  setStatus("uploading");
  note(`Uploading ${file.name}…`);
  try {
    const upload = await api.upload(file);
    note(`Uploaded ${upload.file_name}. Starting compliance check…`);
    await sendMessage(
      `Please check the uploaded file "${upload.file_name}" (upload id ${upload.upload_id}) ` +
        `for compliance with our data-protection policy: PII, sensitive data and secrets. ` +
        `Give the verdict and the reasons.`,
      upload.file_name,
      "generalist",
    );
  } catch (err) {
    note(`Upload failed: ${messageOf(err)}`);
    setStatus("failed");
  }
}

// ----- Errors ---------------------------------------------------------------
function messageOf(err: unknown): string {
  if (err instanceof ApiError) return err.message;
  if (err instanceof Error) return err.message;
  return String(err);
}

// ----- Wiring ---------------------------------------------------------------
function autoResize(textarea: HTMLTextAreaElement): void {
  textarea.style.height = "auto";
  textarea.style.height = `${Math.min(textarea.scrollHeight, 200)}px`;
}

function init(): void {
  // Surface unexpected JS errors in the transcript so bugs are never silent.
  window.addEventListener("unhandledrejection", (event) => {
    console.error("Unhandled rejection:", event.reason);
    note(`Unexpected error: ${messageOf(event.reason)}`);
  });
  window.addEventListener("error", (event) => {
    console.error("Uncaught error:", event.error ?? event.message);
    note(`Unexpected error: ${event.message}`);
  });

  composerForm.addEventListener("submit", (event) => {
    event.preventDefault();
    const text = composerInput.value;
    composerInput.value = "";
    autoResize(composerInput);
    void sendMessage(text);
  });
  stopBtn.addEventListener("click", () => void cancelRun());
  newChatBtn.addEventListener("click", startNewChat);
  composerInput.addEventListener("input", () => autoResize(composerInput));
  composerInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      composerForm.requestSubmit();
    }
  });

  attachBtn.addEventListener("click", () => fileInput.click());
  fileInput.addEventListener("change", () => {
    const file = fileInput.files?.[0];
    fileInput.value = "";
    if (file) void handleFile(file);
  });

  // Drag & drop anywhere over the chat (only for actual file drags).
  const hasFiles = (event: DragEvent): boolean =>
    Array.from(event.dataTransfer?.types ?? []).includes("Files");
  document.addEventListener("dragenter", (event) => {
    if (!hasFiles(event)) return;
    event.preventDefault();
    dropOverlay.hidden = false;
  });
  document.addEventListener("dragover", (event) => {
    if (hasFiles(event)) event.preventDefault();
  });
  document.addEventListener("dragleave", () => {
    dropOverlay.hidden = true;
  });
  document.addEventListener("drop", (event) => {
    if (!hasFiles(event)) return;
    event.preventDefault();
    dropOverlay.hidden = true;
    const file = event.dataTransfer?.files?.[0];
    if (file) void handleFile(file);
  });

  void api
    .agents()
    .then((list) => {
      for (const agent of list) {
        const opt = document.createElement("option");
        opt.value = agent.name;
        opt.textContent = agent.name;
        agentSelect.append(opt);
      }
    })
    .catch((err) => appendError(messagesEl, `Failed to load agents: ${messageOf(err)}`));

  void renderConversationList();
  composerInput.focus();
}

init();
