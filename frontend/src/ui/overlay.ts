import { type IconName, icon } from "../icons";
import { el, setState, uid } from "./core";
import { Button } from "./primitives";

/* ----- Shared overlay helpers --------------------------------------------- */
let scrollLocks = 0;
let previousOverflow = "";

function lockScroll(): void {
  if (scrollLocks === 0) {
    previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
  }
  scrollLocks += 1;
}

function unlockScroll(): void {
  scrollLocks = Math.max(0, scrollLocks - 1);
  if (scrollLocks === 0) document.body.style.overflow = previousOverflow;
}

const FOCUSABLE =
  'a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])';

function focusables(root: HTMLElement): HTMLElement[] {
  return Array.from(root.querySelectorAll<HTMLElement>(FOCUSABLE)).filter(
    (node) => node.getClientRects().length > 0,
  );
}

export interface OverlayHandle {
  panel: HTMLElement;
  close(): void;
}

interface OpenPanelOptions {
  restoreFocus?: HTMLElement | null;
  initialFocus?: HTMLElement;
  onClose?: () => void;
}

function openPanel(panel: HTMLElement, opts: OpenPanelOptions = {}): OverlayHandle {
  const backdrop = el("div", { class: "overlay-backdrop" });
  const restore =
    opts.restoreFocus ?? (document.activeElement as HTMLElement | null);
  document.body.append(backdrop, panel);
  lockScroll();

  const raf = requestAnimationFrame(() => {
    setState(backdrop, "open");
    setState(panel, "open");
  });

  let closed = false;

  const close = (): void => {
    if (closed) return;
    closed = true;
    cancelAnimationFrame(raf);
    document.removeEventListener("keydown", onKeydown, true);
    setState(backdrop, "closed");
    setState(panel, "closed");
    window.setTimeout(() => {
      backdrop.remove();
      panel.remove();
    }, 160);
    unlockScroll();
    restore?.focus?.();
    opts.onClose?.();
  };

  const onKeydown = (event: KeyboardEvent): void => {
    if (event.key === "Escape") {
      event.preventDefault();
      close();
      return;
    }
    if (event.key !== "Tab") return;
    const items = focusables(panel);
    if (items.length === 0) {
      event.preventDefault();
      panel.focus();
      return;
    }
    const first = items[0];
    const last = items[items.length - 1];
    const active = document.activeElement;
    if (event.shiftKey && (active === first || !panel.contains(active))) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && active === last) {
      event.preventDefault();
      first.focus();
    }
  };

  panel.setAttribute("tabindex", "-1");
  document.addEventListener("keydown", onKeydown, true);
  backdrop.addEventListener("click", close);
  (opts.initialFocus ?? focusables(panel)[0] ?? panel).focus();

  return { panel, close };
}

/* ----- Alert dialog ------------------------------------------------------- */
export interface AlertDialogOptions {
  title: string;
  description?: string;
  confirmLabel?: string;
  cancelLabel?: string;
  destructive?: boolean;
  onConfirm?: () => void;
}

export function AlertDialog(opts: AlertDialogOptions): OverlayHandle {
  const panel = el("div", {
    class: "dialog-panel",
    attrs: { role: "alertdialog", "aria-modal": "true" },
  });

  const titleId = uid("dialog-title");
  const descId = uid("dialog-desc");
  const header = el("div", { class: "dialog-header" });
  header.append(
    el("div", { class: "dialog-title", text: opts.title, attrs: { id: titleId } }),
  );
  if (opts.description) {
    header.append(
      el("div", {
        class: "dialog-description",
        text: opts.description,
        attrs: { id: descId },
      }),
    );
  }
  panel.setAttribute("aria-labelledby", titleId);
  if (opts.description) panel.setAttribute("aria-describedby", descId);

  const cancel = Button({ variant: "outline", text: opts.cancelLabel ?? "Cancel" });
  const confirm = Button({
    variant: opts.destructive ? "destructive" : "default",
    text: opts.confirmLabel ?? "Confirm",
  });
  const footer = el("div", { class: "dialog-footer" });
  footer.append(cancel, confirm);
  panel.append(header, footer);

  const handle = openPanel(panel, { initialFocus: confirm });
  cancel.addEventListener("click", () => handle.close());
  confirm.addEventListener("click", () => {
    opts.onConfirm?.();
    handle.close();
  });
  return handle;
}

/* ----- Sheet (mobile sidebar) --------------------------------------------- */
export interface SheetOptions {
  panel: HTMLElement;
  onOpenChange?: (open: boolean) => void;
}

export interface SheetHandle {
  open(): void;
  close(): void;
  toggle(): void;
  isOpen(): boolean;
}

export function Sheet(opts: SheetOptions): SheetHandle {
  const panel = opts.panel;
  const backdrop = el("div", { class: "sheet-backdrop" });
  backdrop.hidden = true;
  document.body.append(backdrop);

  let open = false;
  let priorFocus: HTMLElement | null = null;

  const setOpen = (next: boolean): void => {
    if (open === next) return;
    open = next;
    panel.dataset.open = String(open);
    if (open) {
      priorFocus = document.activeElement as HTMLElement | null;
      backdrop.hidden = false;
      requestAnimationFrame(() => setState(backdrop, "open"));
      lockScroll();
      focusables(panel)[0]?.focus();
    } else {
      setState(backdrop, "closed");
      window.setTimeout(() => {
        if (!open) backdrop.hidden = true;
      }, 200);
      unlockScroll();
      priorFocus?.focus?.();
    }
    opts.onOpenChange?.(open);
  };

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && open) setOpen(false);
  });
  backdrop.addEventListener("click", () => setOpen(false));

  const mql = window.matchMedia("(max-width: 820px)");
  const onChange = (event: MediaQueryListEvent): void => {
    if (!event.matches) setOpen(false);
  };
  if (typeof mql.addEventListener === "function") {
    mql.addEventListener("change", onChange);
  }

  return {
    open: () => setOpen(true),
    close: () => setOpen(false),
    toggle: () => setOpen(!open),
    isOpen: () => open,
  };
}

/* ----- Dropdown menu ------------------------------------------------------ */
export interface DropdownItem {
  label: string;
  icon?: IconName;
  variant?: "default" | "destructive";
  onSelect?: () => void;
}

export interface DropdownHandle {
  element: HTMLElement;
}

export function DropdownMenu(
  trigger: HTMLButtonElement,
  items: DropdownItem[],
): DropdownHandle {
  const wrapper = el("span", { class: "dropdown-wrapper" });
  wrapper.append(trigger);
  trigger.setAttribute("aria-haspopup", "menu");
  trigger.setAttribute("aria-expanded", "false");

  let menu: HTMLElement | null = null;
  let open = false;

  function close(): void {
    if (!open || !menu) return;
    open = false;
    const node = menu;
    menu = null;
    setState(node, "closed");
    window.setTimeout(() => node.remove(), 120);
    trigger.setAttribute("aria-expanded", "false");
    document.removeEventListener("click", onDocClick, true);
    document.removeEventListener("keydown", onKeydown);
    window.removeEventListener("scroll", close, true);
    window.removeEventListener("resize", close);
  }

  function onDocClick(event: MouseEvent): void {
    if (event.target === trigger) return;
    if (menu && event.target instanceof Node && menu.contains(event.target)) return;
    close();
  }

  function onKeydown(event: KeyboardEvent): void {
    if (event.key === "Escape" && open) {
      close();
      trigger.focus();
    }
  }

  function openMenu(): void {
    if (menu) return;
    const node = el("div", { class: "dropdown", attrs: { role: "menu" } });
    for (const item of items) {
      const button = el("button", {
        class: "dropdown-item",
        attrs: {
          type: "button",
          role: "menuitem",
          "data-variant": item.variant ?? "default",
        },
      });
      if (item.icon) button.append(icon(item.icon, 16));
      button.append(document.createTextNode(item.label));
      button.addEventListener("click", () => {
        close();
        item.onSelect?.();
      });
      node.append(button);
    }
    document.body.append(node);
    const rect = trigger.getBoundingClientRect();
    node.style.top = `${Math.round(rect.bottom + 4)}px`;
    node.style.right = `${Math.round(window.innerWidth - rect.right)}px`;
    menu = node;
    open = true;
    requestAnimationFrame(() => {
      if (menu) setState(menu, "open");
    });
    trigger.setAttribute("aria-expanded", "true");
    document.addEventListener("click", onDocClick, true);
    document.addEventListener("keydown", onKeydown);
    window.addEventListener("scroll", close, true);
    window.addEventListener("resize", close);
    node.querySelector<HTMLElement>(".dropdown-item")?.focus();
  };

  trigger.addEventListener("click", (event) => {
    event.preventDefault();
    event.stopPropagation();
    if (open) close();
    else openMenu();
  });

  return { element: wrapper };
}
