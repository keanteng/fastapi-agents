export type ClassValue = string | false | null | undefined;

export function cx(...values: ClassValue[]): string {
  return values.filter(Boolean).join(" ");
}

export interface ElOptions {
  class?: ClassValue;
  text?: string;
  html?: string;
  attrs?: Record<string, string | number | boolean | null | undefined>;
  children?: (Node | null | undefined | false)[];
}

export function el<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  opts: ElOptions = {},
): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag);
  if (opts.class) node.className = cx(opts.class);
  if (opts.text !== undefined) node.textContent = opts.text;
  if (opts.html !== undefined) node.innerHTML = opts.html;
  if (opts.attrs) {
    for (const [key, value] of Object.entries(opts.attrs)) {
      if (value === null || value === undefined || value === false) continue;
      node.setAttribute(key, value === true ? "" : String(value));
    }
  }
  if (opts.children) {
    for (const child of opts.children) {
      if (child) node.append(child);
    }
  }
  return node;
}

export function setState(node: HTMLElement, state: "open" | "closed"): void {
  node.dataset.state = state;
}

let uidCounter = 0;

export function uid(prefix = "ui"): string {
  uidCounter += 1;
  return `${prefix}-${uidCounter}`;
}
