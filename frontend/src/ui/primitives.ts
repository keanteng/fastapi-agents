import { icon, type IconName } from "../icons";
import { cx, el, type ClassValue } from "./core";

/* ----- Button ------------------------------------------------------------- */
export type ButtonVariant =
  | "default"
  | "secondary"
  | "outline"
  | "ghost"
  | "destructive";

export type ButtonSize = "default" | "sm" | "lg" | "icon" | "icon-sm";

export interface ButtonOptions {
  variant?: ButtonVariant;
  size?: ButtonSize;
  class?: ClassValue;
  text?: string;
  icon?: IconName;
  iconSize?: number;
  title?: string;
  type?: "button" | "submit";
  disabled?: boolean;
  hidden?: boolean;
  id?: string;
  onClick?: (event: MouseEvent) => void;
}

export function Button(opts: ButtonOptions = {}): HTMLButtonElement {
  const variant = opts.variant ?? "default";
  const size = opts.size ?? "default";
  const node = el("button", {
    class: cx(
      "btn",
      `btn-${variant}`,
      size !== "default" && `btn-${size}`,
      opts.class,
    ),
  });
  node.type = opts.type ?? "button";
  if (opts.id) node.id = opts.id;
  if (opts.disabled) node.disabled = true;
  if (opts.hidden) node.hidden = true;
  if (opts.title) node.title = opts.title;
  if (opts.icon) node.append(icon(opts.icon, opts.iconSize ?? 16));
  if (opts.text) node.append(document.createTextNode(opts.text));
  if (opts.onClick) node.addEventListener("click", opts.onClick);
  return node;
}

/* ----- Badge -------------------------------------------------------------- */
export type BadgeVariant =
  | "default"
  | "secondary"
  | "outline"
  | "success"
  | "warning"
  | "destructive";

export interface BadgeOptions {
  variant?: BadgeVariant;
  icon?: IconName;
  iconSize?: number;
  class?: ClassValue;
  id?: string;
}

export function Badge(text: string, opts: BadgeOptions = {}): HTMLSpanElement {
  const node = el("span", {
    class: cx("badge", `badge-${opts.variant ?? "default"}`, opts.class),
  });
  if (opts.id) node.id = opts.id;
  if (opts.icon) node.append(icon(opts.icon, opts.iconSize ?? 12));
  if (text) node.append(document.createTextNode(text));
  return node;
}

/* ----- Card --------------------------------------------------------------- */
export function Card(opts: { class?: ClassValue } = {}): HTMLDivElement {
  return el("div", { class: cx("card", opts.class) });
}

export function CardHeader(): HTMLDivElement {
  return el("div", { class: "card-header" });
}

export function CardTitle(text: string): HTMLDivElement {
  return el("div", { class: "card-title", text });
}

export function CardContent(): HTMLDivElement {
  return el("div", { class: "card-content" });
}

/* ----- Input / Textarea --------------------------------------------------- */
export interface TextareaOptions {
  id?: string;
  placeholder?: string;
  rows?: number;
  class?: ClassValue;
  ariaLabel?: string;
}

export function Textarea(opts: TextareaOptions = {}): HTMLTextAreaElement {
  const node = el("textarea", { class: cx("textarea", opts.class) });
  if (opts.id) node.id = opts.id;
  if (opts.placeholder) node.placeholder = opts.placeholder;
  if (opts.rows) node.rows = opts.rows;
  if (opts.ariaLabel) node.setAttribute("aria-label", opts.ariaLabel);
  return node;
}

export function Input(opts: TextareaOptions = {}): HTMLInputElement {
  const node = el("input", { class: cx("input", opts.class) });
  if (opts.id) node.id = opts.id;
  if (opts.placeholder) node.placeholder = opts.placeholder;
  if (opts.ariaLabel) node.setAttribute("aria-label", opts.ariaLabel);
  return node;
}

/* ----- Separator ---------------------------------------------------------- */
export function Separator(
  orientation: "horizontal" | "vertical" = "horizontal",
): HTMLDivElement {
  return el("div", {
    class: cx("separator", `separator-${orientation}`),
    attrs: { role: "separator", "aria-orientation": orientation },
  });
}

/* ----- Avatar ------------------------------------------------------------- */
export interface AvatarOptions {
  icon?: IconName;
  label?: string;
  class?: ClassValue;
}

export function Avatar(opts: AvatarOptions = {}): HTMLSpanElement {
  const node = el("span", {
    class: cx("avatar", opts.class),
    attrs: { "aria-hidden": true },
  });
  if (opts.icon) node.append(icon(opts.icon, 16));
  else if (opts.label) node.textContent = opts.label;
  return node;
}

/* ----- Skeleton / Spinner ------------------------------------------------- */
export interface SkeletonOptions {
  width?: string;
  height?: string;
  class?: ClassValue;
}

export function Skeleton(opts: SkeletonOptions = {}): HTMLSpanElement {
  const node = el("span", { class: cx("skeleton", opts.class) });
  if (opts.width) node.style.width = opts.width;
  if (opts.height) node.style.height = opts.height;
  return node;
}

export function Spinner(size = 16): HTMLSpanElement {
  const node = el("span", {
    class: "spinner",
    attrs: { role: "status", "aria-label": "Loading" },
  });
  node.append(icon("loader", size));
  return node;
}

/* ----- Tooltip ------------------------------------------------------------ */
export function withTooltip(
  trigger: HTMLElement,
  label: string,
): HTMLSpanElement {
  const wrap = el("span", { class: "tooltip" });
  const content = el("span", {
    class: "tooltip-content",
    text: label,
    attrs: { role: "tooltip" },
  });
  wrap.append(trigger, content);
  if (!trigger.getAttribute("aria-label") && !trigger.textContent?.trim()) {
    trigger.setAttribute("aria-label", label);
  }
  return wrap;
}

/* ----- Alert / progress / empty state ------------------------------------- */
export type AlertVariant = "default" | "destructive";

export interface AlertOptions {
  variant?: AlertVariant;
  title?: string;
  icon?: IconName;
  class?: ClassValue;
}

export function Alert(text: string, opts: AlertOptions = {}): HTMLDivElement {
  const node = el("div", {
    class: cx(
      "alert",
      opts.variant === "destructive" && "alert-destructive",
      opts.class,
    ),
    attrs: { role: "alert" },
  });
  node.append(
    icon(opts.icon ?? (opts.variant === "destructive" ? "alert" : "activity"), 16),
  );
  const body = el("div");
  if (opts.title) body.append(el("div", { class: "alert-title", text: opts.title }));
  body.append(
    el("div", {
      class: opts.title ? "alert-description" : undefined,
      text,
    }),
  );
  node.append(body);
  return node;
}

export function ProgressLine(text: string): HTMLDivElement {
  const node = el("div", { class: "run-progress" });
  node.append(icon("activity", 14), el("span", { text }));
  return node;
}

export interface EmptyStateOptions {
  title: string;
  description?: string;
  icon?: IconName;
}

export function EmptyState(opts: EmptyStateOptions): HTMLDivElement {
  const node = el("div", { class: "empty-state" });
  const badge = el("span", { class: "empty-state-icon" });
  badge.append(icon(opts.icon ?? "sparkles", 20));
  node.append(badge, el("div", { class: "empty-state-title", text: opts.title }));
  if (opts.description) {
    node.append(el("div", { class: "empty-state-description", text: opts.description }));
  }
  return node;
}
