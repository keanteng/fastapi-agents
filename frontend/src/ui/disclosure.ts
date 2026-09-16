import { cx, el, setState, uid, type ClassValue } from "./core";

export interface CollapsibleOptions {
  open?: boolean;
  class?: ClassValue;
}

export interface CollapsibleParts {
  element: HTMLElement;
  trigger: HTMLButtonElement;
  body: HTMLElement;
  setOpen(open: boolean): void;
  isOpen(): boolean;
}

/**
 * Accessible disclosure built on `grid-template-rows` height animation.
 * `trigger` must be a button; `body` is the panel content.
 */
export function Collapsible(
  trigger: HTMLButtonElement,
  body: HTMLElement,
  opts: CollapsibleOptions = {},
): CollapsibleParts {
  const element = el("div", { class: cx("collapsible", opts.class) });
  const content = el("div", { class: "collapsible-content" });
  const inner = el("div", { class: "collapsible-content-inner" });
  inner.append(body);
  content.append(inner);

  const contentId = uid("collapsible");
  content.id = contentId;
  trigger.setAttribute("aria-controls", contentId);

  element.append(trigger, content);

  let open = opts.open ?? false;

  const render = (): void => {
    setState(element, open ? "open" : "closed");
    trigger.setAttribute("aria-expanded", String(open));
  };

  trigger.addEventListener("click", () => {
    open = !open;
    render();
  });
  render();

  return {
    element,
    trigger,
    body,
    setOpen(next: boolean) {
      open = next;
      render();
    },
    isOpen: () => open,
  };
}
