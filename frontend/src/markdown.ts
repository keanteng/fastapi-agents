// Minimal, dependency-free, XSS-safe Markdown renderer for assistant replies.
//
// Everything is HTML-escaped before it is emitted; raw HTML is never passed
// through. Supported constructs: headings, fenced code, inline code, bold,
// italic, strikethrough, links, blockquotes, unordered/ordered lists, tables
// and horizontal rules. Paragraph line breaks are preserved as <br>.

function esc(text: string): string {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function safeUrl(url: string): string | null {
  const candidate = url.trim();
  if (/^(https?:|mailto:)/i.test(candidate)) return candidate;
  return null;
}

function inline(text: string): string {
  let out = "";
  let i = 0;
  const n = text.length;

  while (i < n) {
    const rest = text.slice(i);

    if (rest[0] === "`") {
      const end = rest.indexOf("`", 1);
      if (end > 0) {
        out += `<code>${esc(rest.slice(1, end))}</code>`;
        i += end + 1;
        continue;
      }
    }

    const link = /^!?\[([^\]]*)\]\(([^)\s]*)\)/.exec(rest);
    if (link) {
      const url = safeUrl(link[2]);
      const label = inline(link[1]);
      if (url) {
        out += `<a href="${esc(url)}" target="_blank" rel="noopener noreferrer">${label}</a>`;
      } else {
        out += link[0][0] === "!" ? `![${link[1]}]` : `[${label}](${esc(link[2])})`;
      }
      i += link[0].length;
      continue;
    }

    if (rest.startsWith("**")) {
      const end = rest.indexOf("**", 2);
      if (end > 1) {
        out += `<strong>${inline(rest.slice(2, end))}</strong>`;
        i += end + 2;
        continue;
      }
    }

    if (rest.startsWith("~~")) {
      const end = rest.indexOf("~~", 2);
      if (end > 1) {
        out += `<del>${inline(rest.slice(2, end))}</del>`;
        i += end + 2;
        continue;
      }
    }

    if (rest[0] === "*") {
      const end = rest.indexOf("*", 1);
      if (end > 1) {
        out += `<em>${inline(rest.slice(1, end))}</em>`;
        i += end + 1;
        continue;
      }
    }

    out += esc(rest[0]);
    i += 1;
  }

  return out;
}

const FENCE = /^(`{3,}|~{3,})[ \t]*([\w-]*)[ \t]*$/;
const HEADING = /^(#{1,6})[ \t]+(.+)$/;
const UL = /^[ \t]*([-+*])[ \t]+(.+)$/;
const OL = /^[ \t]*\d+[.)][ \t]+(.+)$/;
const BQ = /^[ \t]*>[ \t]?(.*)$/;
const HR = /^(?:[ \t]*(?:\*[ \t]*){3,}|[ \t]*(?:-[ \t]*){3,}|[ \t]*(?:_[ \t]*){3,})$/;

function fenceCloser(marker: string): RegExp {
  return new RegExp(`^${marker}[ \t]*$`);
}

function tableCells(row: string): string[] {
  let cell = row.trim();
  if (cell.startsWith("|")) cell = cell.slice(1);
  if (cell.endsWith("|") && !cell.endsWith("\\|")) cell = cell.slice(0, -1);
  return cell.split("|").map((c) => c.trim());
}

function isTableSeparator(line: string): boolean {
  const cells = tableCells(line);
  return cells.length > 0 && cells.every((c) => /^:?-+:?$/.test(c));
}

function renderTable(header: string[], rows: string[][]): string {
  const head = header.map((c) => `<th>${inline(c)}</th>`).join("");
  const body = rows
    .map((row) => `<tr>${row.map((c) => `<td>${inline(c)}</td>`).join("")}</tr>`)
    .join("");
  return `<table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`;
}

export function renderMarkdown(text: string): string {
  const lines = text.replace(/\r\n?/g, "\n").split("\n");
  const blocks: string[] = [];
  let i = 0;
  const n = lines.length;

  while (i < n) {
    const raw = lines[i];
    const line = raw.trim();

    if (!line) {
      i += 1;
      continue;
    }

    const fence = FENCE.exec(line);
    if (fence) {
      const marker = fence[1];
      const lang = fence[2];
      const closer = fenceCloser(marker);
      const code: string[] = [];
      i += 1;
      while (i < n && !closer.test(lines[i])) {
        code.push(lines[i]);
        i += 1;
      }
      i += 1; // skip the closing fence
      const cls = lang ? ` class="language-${esc(lang)}"` : "";
      blocks.push(`<pre><code${cls}>${esc(code.join("\n"))}</code></pre>`);
      continue;
    }

    const heading = HEADING.exec(line);
    if (heading) {
      const level = heading[1].length;
      blocks.push(`<h${level}>${inline(heading[2])}</h${level}>`);
      i += 1;
      continue;
    }

    if (HR.test(line)) {
      blocks.push("<hr>");
      i += 1;
      continue;
    }

    if (line.startsWith("|") && i + 1 < n && isTableSeparator(lines[i + 1])) {
      const header = tableCells(line);
      const rows: string[][] = [];
      i += 2;
      while (i < n && lines[i].trim().startsWith("|")) {
        rows.push(tableCells(lines[i]));
        i += 1;
      }
      blocks.push(renderTable(header, rows));
      continue;
    }

    const bulletStart = UL.exec(line);
    if (bulletStart) {
      const items: string[] = [];
      while (i < n) {
        const item = UL.exec(lines[i]);
        if (!item) break;
        items.push(item[2]);
        i += 1;
      }
      blocks.push(`<ul>${items.map((item) => `<li>${inline(item)}</li>`).join("")}</ul>`);
      continue;
    }

    const numStart = OL.exec(line);
    if (numStart) {
      const items: string[] = [];
      while (i < n) {
        const item = OL.exec(lines[i]);
        if (!item) break;
        items.push(item[1]);
        i += 1;
      }
      blocks.push(`<ol>${items.map((item) => `<li>${inline(item)}</li>`).join("")}</ol>`);
      continue;
    }

    const quoteStart = BQ.exec(line);
    if (quoteStart) {
      const quote: string[] = [];
      while (i < n) {
        const item = BQ.exec(lines[i]);
        if (!item) break;
        quote.push(item[1]);
        i += 1;
      }
      blocks.push(`<blockquote>${quote.map((q) => inline(q)).join("<br>")}</blockquote>`);
      continue;
    }

    // Paragraph: gather consecutive non-empty lines that are not block starts.
    const paragraph: string[] = [];
    while (i < n) {
      const t = lines[i].trim();
      if (
        !t ||
        FENCE.test(t) ||
        HEADING.test(t) ||
        HR.test(t) ||
        UL.test(t) ||
        OL.test(t) ||
        BQ.test(t) ||
        (t.startsWith("|") && i + 1 < n && isTableSeparator(lines[i + 1]))
      ) {
        break;
      }
      paragraph.push(lines[i]);
      i += 1;
    }
    if (paragraph.length > 0) {
      blocks.push(`<p>${paragraph.map((p) => inline(p)).join("<br>")}</p>`);
    }
  }

  return blocks.join("\n");
}
