import { type IconName, icon } from "../icons";
import { cx, el, setState } from "./core";

export type ToastVariant = "default" | "success" | "error" | "warning";

export interface ToastOptions {
  description?: string;
  duration?: number;
  variant?: ToastVariant;
  icon?: IconName;
}

let container: HTMLElement | null = null;

function ensureContainer(): HTMLElement {
  if (container && container.isConnected) return container;
  const existing = document.querySelector<HTMLElement>("#toaster");
  container = existing ?? el("div", { class: "toaster", attrs: { id: "toaster" } });
  container.classList.add("toaster");
  if (!existing) document.body.append(container);
  return container;
}

export function initToaster(): void {
  ensureContainer();
}

const DEFAULT_ICON: Record<ToastVariant, IconName> = {
  default: "sparkles",
  success: "check-circle",
  error: "x-circle",
  warning: "alert",
};

export function toast(title: string, opts: ToastOptions = {}): void {
  const variant = opts.variant ?? "default";
  const host = ensureContainer();

  const node = el("div", {
    class: cx("toast", `toast-${variant}`),
    attrs: { role: "status" },
  });

  const iconWrap = el("span", { class: "toast-icon" });
  iconWrap.append(icon(opts.icon ?? DEFAULT_ICON[variant], 18));

  const body = el("div", { class: "toast-body" });
  body.append(el("div", { class: "toast-title", text: title }));
  if (opts.description) {
    body.append(el("div", { class: "toast-description", text: opts.description }));
  }

  const close = el("button", {
    class: "btn btn-ghost btn-icon-sm",
    attrs: { type: "button", "aria-label": "Dismiss" },
  });
  close.append(icon("x", 14));

  node.append(iconWrap, body, close);
  host.append(node);

  let removed = false;
  const remove = (): void => {
    if (removed) return;
    removed = true;
    setState(node, "closed");
    window.setTimeout(() => node.remove(), 200);
  };

  close.addEventListener("click", remove);
  requestAnimationFrame(() => setState(node, "open"));
  window.setTimeout(remove, opts.duration ?? 4000);
}
