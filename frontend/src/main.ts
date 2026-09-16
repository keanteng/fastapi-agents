import "./style.css";
import { api, ApiError } from "./api";
import { icon, prependIcon, replaceIcon } from "./icons";
import {
  appendError,
  appendNote,
  appendUserBubble,
  createAssistantTurn,
  renderEmptyState,
  renderMessages,
  scrollToBottom,
  type AssistantTurn,
  type ToolHandle,
} from "./render";
import { attachRunStream } from "./stream";
import { getTheme, initTheme, toggleTheme } from "./theme";
import {
  AlertDialog,
  Button,
  DropdownMenu,
  Sheet,
  Spinner,
  cx,
  el,
  initToaster,
  toast,
  type ToastVariant,
} from "./ui";
import type { RunStep, RunStatus } from "./types";

// ----- DOM refs -------------------------------------------------------------
const composerForm = document.querySelector<HTMLFormElement>("#composer-form")!;
const composerInput = document.querySelector<HTMLTextAreaElement>("#composer-input")!;
const sendBtn = document.querySelector<HTMLButtonElement>("#composer-send")!;
const stopBtn = document.querySelector<HTMLButtonElement>("#stop")!;
const attachBtn = document.querySelector<HTMLButtonElement>("#attach")!;
const fileInput = document.querySelector<HTMLInputElement>("#file-input")!;
const messagesEl = document.querySelector<HTMLElement>("#messages")!;
const conversationList = document.querySelector<HTMLElement>("#conversation-list")!;
const newChatBtn = document.querySelector<HTMLButtonElement>("#new-chat")!;
const sidebarEl = document.querySelector<HTMLElement>("#sidebar")!;
const sidebarToggle = document.querySelector<HTMLButtonElement>("#sidebar-toggle")!;
const themeToggle = document.querySelector<HTMLButtonElement>("#theme-toggle")!;
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

const sidebar = Sheet({ panel: sidebarEl });

// ----- Status badge ---------------------------------------------------------
type StatusKey = RunStatus | "idle" | "uploading";

const STATUS_META: Record<
  StatusKey,
  { variant: string; label: string; spinning?: boolean }
> = {
  idle: { variant: "outline", label: "idle" },
  pending: { variant: "default", label: "pending", spinning: true },
  running: { variant: "default", label: "running", spinning: true },
  uploading: { variant: "secondary", label: "uploading" },
  completed: { variant: "success", label: "completed" },
  failed: { variant: "destructive", label: "failed" },
  cancelled: { variant: "warning", label: "cancelled" },
};

function setStatus(status: StatusKey): void {
  const meta = STATUS_META[status];
  statusEl.className = `badge badge-${meta.variant}`;
  statusEl.dataset.status = status;
  statusEl.replaceChildren();
  if (meta.spinning) statusEl.append(icon("loader", 12));
  statusEl.append(document.createTextNode(meta.label));
  stopBtn.hidden = !(status === "running" || status === "pending");
}

// ----- Small helpers --------------------------------------------------------
function scrollBottom(): void {
  scrollToBottom(messagesEl);
}

function shortId(id: string): string {
  return id.length > 10 ? `${id.slice(0, 8)}…` : id;
}

function messageOf(err: unknown): string {
  if (err instanceof ApiError) return err.message;
  if (err instanceof Error) return err.message;
  return String(err);
}

function notify(
  title: string,
  variant: ToastVariant = "default",
  description?: string,
): void {
  toast(title, { variant, description });
}

function setComposerEnabled(enabled: boolean): void {
  sendBtn.disabled = !enabled;
  composerInput.disabled = !enabled;
  attachBtn.disabled = !enabled;
}

// ----- Theme ----------------------------------------------------------------
function renderThemeToggle(): void {
  const dark = getTheme() === "dark";
  replaceIcon(themeToggle, dark ? "sun" : "moon");
  const label = dark ? "Switch to light theme" : "Switch to dark theme";
  themeToggle.title = label;
  themeToggle.setAttribute("aria-label", label);
}

function initChrome(): void {
  initTheme();
  renderThemeToggle();
  initToaster();

  prependIcon(newChatBtn, "plus");
  prependIcon(attachBtn, "paperclip");
  prependIcon(sendBtn, "send");
  prependIcon(stopBtn, "square");
  prependIcon(sidebarToggle, "panel-left");

  const brand = document.querySelector<HTMLElement>(".sidebar-brand");
  if (brand) prependIcon(brand, "sparkles", 18);
  const upload = document.querySelector<HTMLElement>(".sidebar-upload");
  if (upload) prependIcon(upload, "file", 15);
}

// ----- Conversation sidebar -------------------------------------------------
function relativeTime(iso: string): string {
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "";
  const seconds = Math.max(0, Math.floor((Date.now() - then) / 1000));
  if (seconds < 45) return "just now";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days === 1) return "yesterday";
  if (days < 7) return `${days}d ago`;
  return new Date(iso).toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
  });
}

function renderConversationList(): void {
  conversationList.textContent = "";
  void api
    .conversations()
    .then((list) => {
      if (list.length === 0) {
        conversationList.append(
          el("li", {
            class: "conversation-empty",
            text: "No conversations yet",
          }),
        );
      }
      for (const conv of list) {
        const item = el("li", {
          class: cx(
            "conversation-item",
            conv.conversation_id === activeConversationId && "active",
          ),
        });

        const open = el("button", {
          class: "conversation-open",
          attrs: {
            type: "button",
            title: new Date(conv.updated_at).toLocaleString(),
          },
        });
        open.append(
          el("span", {
            class: "conv-preview",
            text: conv.preview?.replace(/\s+/g, " ") || "(empty conversation)",
          }),
          el("span", {
            class: "conv-time",
            text: relativeTime(conv.updated_at),
          }),
        );
        open.addEventListener("click", () =>
          void openConversation(conv.conversation_id),
        );

        const menuTrigger = Button({
          variant: "ghost",
          size: "icon-sm",
          icon: "ellipsis",
          class: "conversation-menu",
          title: "Conversation actions",
        });
        const menu = DropdownMenu(menuTrigger, [
          {
            label: "Delete",
            icon: "trash",
            variant: "destructive",
            onSelect: () => confirmDeleteConversation(conv.conversation_id),
          },
        ]);

        item.append(open, menu.element);
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
  sidebar.close();
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

function confirmDeleteConversation(conversationId: string): void {
  AlertDialog({
    title: "Delete conversation?",
    description:
      "This permanently removes the conversation and all of its messages.",
    confirmLabel: "Delete",
    destructive: true,
    onConfirm: () => void deleteConversation(conversationId),
  });
}

async function deleteConversation(conversationId: string): Promise<void> {
  try {
    await api.deleteConversation(conversationId);
    notify("Conversation deleted", "success");
  } catch (err) {
    appendError(messagesEl, `Failed to delete conversation: ${messageOf(err)}`);
    notify("Failed to delete conversation", "error", messageOf(err));
  }
  if (activeConversationId === conversationId) {
    activeConversationId = null;
    renderEmptyState(messagesEl);
  }
  renderConversationList();
}

function startNewChat(): void {
  if (busy) return;
  sidebar.close();
  activeConversationId = null;
  currentRunId = null;
  streamTurn = null;
  openTools.clear();
  convLabel.textContent = "none";
  renderEmptyState(messagesEl);
  renderConversationList();
  composerInput.focus();
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
async function sendMessage(text: string, attachment?: string): Promise<void> {
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
    const chip = el("div", { class: "msg-attach", text: `file: ${attachment}` });
    bubble.append(chip);
  }
  streamTurn = createAssistantTurn(messagesEl);
  waitingEl = el("div", { class: "assistant-wait" });
  waitingEl.append(Spinner(14), document.createTextNode("Agent is working…"));
  streamTurn.body.append(waitingEl);
  scrollBottom();

  const dismissWaiting = (): void => {
    if (waitingEl && waitingEl.isConnected) waitingEl.remove();
    waitingEl = null;
  };

  const body: Record<string, unknown> = { agent: "generalist", input: trimmed };
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
    notify("Run failed to start", "error", messageOf(err));
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
  note?: string | null;
}): Promise<void> {
  busy = false;
  setComposerEnabled(true);
  setStatus(run.status);

  for (const handle of openTools.values()) handle.finish("(interrupted)", false);
  openTools.clear();

  if (run.status === "failed") {
    const detail = run.error
      ? `Run failed (${run.error.code}): ${run.error.message}`
      : "Run failed.";
    streamTurn?.addError(detail);
    notify("Run failed", "error", run.error?.message);
    return;
  }
  if (run.status === "cancelled") {
    streamTurn?.addError("Run cancelled.");
    notify("Run cancelled", "warning");
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
  if (run.note) appendNote(messagesEl, run.note);
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
async function handleFile(file: File): Promise<void> {
  if (busy || !file) return;
  const typed = composerInput.value.trim();
  composerInput.value = "";
  autoResize(composerInput);
  setStatus("uploading");
  notify(`Uploading ${file.name}…`);
  try {
    const upload = await api.upload(file);
    const fileRef = `attached file "${upload.file_name}" (upload id ${upload.upload_id})`;
    const prompt = typed
      ? `${typed}\n\n(context: the ${fileRef} is available — use it if relevant.)`
      : `The user uploaded ${fileRef} but gave no instructions. Read the file, ` +
        `summarise it, and offer next steps such as answering questions, ` +
        `extracting entities, or running a compliance/PII check.`;
    notify(`Uploaded ${upload.file_name}`, "success");
    await sendMessage(prompt, upload.file_name);
  } catch (err) {
    appendError(messagesEl, `Upload failed: ${messageOf(err)}`);
    notify("Upload failed", "error", messageOf(err));
    setStatus("failed");
  }
}

// ----- Wiring ---------------------------------------------------------------
function autoResize(textarea: HTMLTextAreaElement): void {
  textarea.style.height = "auto";
  textarea.style.height = `${Math.min(textarea.scrollHeight, 200)}px`;
}

function init(): void {
  initChrome();

  // Surface unexpected JS errors in the transcript so bugs are never silent.
  window.addEventListener("unhandledrejection", (event) => {
    console.error("Unhandled rejection:", event.reason);
    appendError(messagesEl, `Unexpected error: ${messageOf(event.reason)}`);
    notify("Unexpected error", "error", messageOf(event.reason));
  });
  window.addEventListener("error", (event) => {
    console.error("Uncaught error:", event.error ?? event.message);
    appendError(messagesEl, `Unexpected error: ${event.message}`);
    notify("Unexpected error", "error", event.message);
  });

  themeToggle.addEventListener("click", () => {
    toggleTheme();
    renderThemeToggle();
  });
  sidebarToggle.addEventListener("click", () => sidebar.toggle());
  newChatBtn.addEventListener("click", startNewChat);

  composerForm.addEventListener("submit", (event) => {
    event.preventDefault();
    const text = composerInput.value;
    composerInput.value = "";
    autoResize(composerInput);
    void sendMessage(text);
  });
  stopBtn.addEventListener("click", () => void cancelRun());
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

  setStatus("idle");
  void renderConversationList();
  renderEmptyState(messagesEl);
  composerInput.focus();
}

init();
