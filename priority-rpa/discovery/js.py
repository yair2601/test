"""JavaScript payloads injected into Priority frames.

All of these are strictly read-only: they query the DOM and attach passive
event listeners. None of them dispatch events, click, focus, or change values.
"""

# ---------------------------------------------------------------------------
# Element harvesting
# ---------------------------------------------------------------------------

HARVEST_JS = r"""
(opts) => {
  const MAX = opts.max_elements;
  const CAPTURE_VALUES = opts.capture_values;

  const txt = (s, n) => {
    if (!s) return "";
    s = String(s).replace(/\s+/g, " ").trim();
    return s.length > n ? s.slice(0, n) + "…" : s;
  };

  const cssPath = (el) => {
    const parts = [];
    let cur = el;
    while (cur && cur.nodeType === 1 && parts.length < 8) {
      if (cur.id && /^[A-Za-z][\w:.-]*$/.test(cur.id)) {
        parts.unshift("#" + CSS.escape(cur.id));
        break;
      }
      let seg = cur.tagName.toLowerCase();
      const parent = cur.parentElement;
      if (parent) {
        const sibs = Array.from(parent.children).filter(c => c.tagName === cur.tagName);
        if (sibs.length > 1) seg += ":nth-of-type(" + (sibs.indexOf(cur) + 1) + ")";
      }
      parts.unshift(seg);
      cur = cur.parentElement;
    }
    return parts.join(" > ");
  };

  const CONTROLS = "input, select, textarea";

  // Best-effort human label for a FIELD: <label for>, wrapping <label>,
  // aria-labelledby, the table column header above it, or the text beside it.
  // Buttons and links are deliberately excluded: their own text is the label,
  // and guessing from surrounding markup produced badly wrong answers
  // (a toolbar's whole text, or the previous button's caption).
  const labelFor = (el) => {
    const tag = el.tagName.toLowerCase();
    const isField = tag === "input" || tag === "select" || tag === "textarea"
                    || el.isContentEditable === true;
    if (!isField) return "";
    try {
      if (el.id) {
        const l = document.querySelector('label[for="' + CSS.escape(el.id) + '"]');
        if (l) return txt(l.innerText, 60);
      }
      const wrap = el.closest("label");
      if (wrap) return txt(wrap.innerText, 60);
      const ref = el.getAttribute("aria-labelledby");
      if (ref) {
        const n = document.getElementById(ref);
        if (n) return txt(n.innerText, 60);
      }
      // Grid cell: use the matching column header.
      const td = el.closest("td, th, [role='gridcell'], [role='cell']");
      if (td) {
        const row = td.parentElement;
        const idx = Array.from(row.children).indexOf(td);
        const table = el.closest("table, [role='grid'], [role='table']");
        if (table && idx >= 0) {
          const headRow = table.querySelector("thead tr, tr:first-child, [role='row']");
          if (headRow && headRow !== row) {
            const cells = headRow.children;
            if (cells[idx]) return txt(cells[idx].innerText || cells[idx].getAttribute("title"), 60);
          }
        }
      }
      // Fall back to the text immediately before the field, but only when it
      // is text and not another control.
      const prev = el.previousElementSibling;
      if (prev && prev.innerText && !prev.matches(CONTROLS + ", button, a")
          && !prev.querySelector(CONTROLS + ", button")) {
        return txt(prev.innerText, 60);
      }
      // Parent text is only meaningful when the parent wraps this one field.
      const p = el.parentElement;
      if (p && p.innerText && p.querySelectorAll(CONTROLS).length === 1) {
        return txt(p.innerText, 60);
      }
    } catch (e) { /* label lookup is best-effort only */ }
    return "";
  };

  const dataAttrs = (el) => {
    const out = {};
    for (const a of el.attributes) {
      if (a.name.startsWith("data-") || a.name.startsWith("aria-")) {
        out[a.name] = txt(a.value, 60);
      }
    }
    return out;
  };

  const SEL = [
    "input", "select", "textarea", "button",
    "a[href]", "[role]", "[contenteditable='true']",
    "[tabindex]", "[onclick]", "td", "th"
  ].join(", ");

  const seen = new Set();
  const elements = [];
  const nodes = document.querySelectorAll(SEL);

  for (const el of nodes) {
    if (elements.length >= MAX) break;
    if (seen.has(el)) continue;
    seen.add(el);

    const tag = el.tagName.toLowerCase();
    const role = el.getAttribute("role") || "";
    // Plain layout cells are noise unless they act like a control.
    if ((tag === "td" || tag === "th") && !role && !el.hasAttribute("onclick")) continue;

    let rect = null, visible = false;
    try {
      const r = el.getBoundingClientRect();
      rect = { x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height) };
      const st = window.getComputedStyle(el);
      visible = r.width > 0 && r.height > 0 && st.visibility !== "hidden" && st.display !== "none";
    } catch (e) { /* detached node */ }

    const rec = {
      tag: tag,
      type: el.getAttribute("type") || "",
      id: el.id || "",
      name: el.getAttribute("name") || "",
      cls: txt(el.className && el.className.baseVal !== undefined ? el.className.baseVal : el.className, 120),
      placeholder: el.getAttribute("placeholder") || "",
      title: el.getAttribute("title") || "",
      role: role,
      text: txt(el.innerText || el.value || "", 60),
      label: labelFor(el),
      maxlength: el.getAttribute("maxlength") || "",
      readonly: el.hasAttribute("readonly"),
      disabled: el.disabled === true,
      required: el.hasAttribute("required"),
      tabindex: el.getAttribute("tabindex") || "",
      visible: visible,
      rect: rect,
      attrs: dataAttrs(el),
      in_grid: !!el.closest("table, [role='grid'], [role='table']"),
      css_path: cssPath(el),
      options: [],
      value_sample: ""
    };

    if (tag === "select") {
      rec.options = Array.from(el.options).slice(0, 15).map(o => txt(o.textContent, 40));
    }
    if (CAPTURE_VALUES && (tag === "input" || tag === "textarea")) {
      rec.value_sample = txt(el.value, 40);
    }
    elements.push(rec);
  }

  // Grid / table structure — tells us whether lines are typed into cells.
  const grids = [];
  const tables = document.querySelectorAll("table, [role='grid'], [role='table']");
  for (const t of Array.from(tables).slice(0, 40)) {
    let rows = t.querySelectorAll("tr, [role='row']").length;
    let headers = [];
    const headRow = t.querySelector("thead tr, tr:first-child, [role='row']");
    if (headRow) {
      headers = Array.from(headRow.children).map(c => txt(c.innerText || c.getAttribute("title"), 30));
    }
    const inputs = t.querySelectorAll("input, select, textarea, [contenteditable='true']").length;
    let r = null;
    try {
      const b = t.getBoundingClientRect();
      r = { w: Math.round(b.width), h: Math.round(b.height) };
    } catch (e) { /* detached node */ }
    grids.push({
      css_path: cssPath(t),
      id: t.id || "",
      cls: txt(t.className && t.className.baseVal !== undefined ? t.className.baseVal : t.className, 120),
      rows: rows,
      headers: headers.filter(h => h),
      input_count: inputs,
      rect: r
    });
  }

  return {
    url: location.href,
    title: document.title,
    element_count: nodes.length,
    elements: elements,
    grids: grids
  };
}
"""

# ---------------------------------------------------------------------------
# Passive recorder (clicks + non-character keys)
# ---------------------------------------------------------------------------
# Listeners are capture-phase and never call preventDefault/stopPropagation,
# so the user's own interaction with Priority is completely unaffected.
# Events are mirrored into sessionStorage so they survive a navigation.

RECORDER_JS = r"""
() => {
  if (window.__priRec) return "already";
  const KEY = "__priRecLog";

  const txt = (s, n) => {
    if (!s) return "";
    s = String(s).replace(/\s+/g, " ").trim();
    return s.length > n ? s.slice(0, n) + "…" : s;
  };

  const cssPath = (el) => {
    const parts = [];
    let cur = el;
    while (cur && cur.nodeType === 1 && parts.length < 8) {
      if (cur.id && /^[A-Za-z][\w:.-]*$/.test(cur.id)) { parts.unshift("#" + CSS.escape(cur.id)); break; }
      let seg = cur.tagName.toLowerCase();
      const p = cur.parentElement;
      if (p) {
        const sibs = Array.from(p.children).filter(c => c.tagName === cur.tagName);
        if (sibs.length > 1) seg += ":nth-of-type(" + (sibs.indexOf(cur) + 1) + ")";
      }
      parts.unshift(seg);
      cur = cur.parentElement;
    }
    return parts.join(" > ");
  };

  const describe = (el) => {
    if (!el || el.nodeType !== 1) return null;
    const attrs = {};
    for (const a of el.attributes) {
      if (a.name.startsWith("data-") || a.name.startsWith("aria-")) attrs[a.name] = txt(a.value, 60);
    }
    return {
      tag: el.tagName.toLowerCase(),
      type: el.getAttribute("type") || "",
      id: el.id || "",
      name: el.getAttribute("name") || "",
      cls: txt(el.className && el.className.baseVal !== undefined ? el.className.baseVal : el.className, 120),
      title: el.getAttribute("title") || "",
      role: el.getAttribute("role") || "",
      text: txt(el.innerText, 60),
      attrs: attrs,
      css_path: cssPath(el),
      frame_url: location.href
    };
  };

  const push = (entry) => {
    // sessionStorage is shared between same-origin frames of a tab, so every
    // entry carries the URL of the frame that produced it and the reader
    // re-attributes it. Without this, one click is reported in every frame.
    entry.frame_url = location.href;
    window.__priRec.log.push(entry);
    try {
      const prev = JSON.parse(sessionStorage.getItem(KEY) || "[]");
      prev.push(entry);
      sessionStorage.setItem(KEY, JSON.stringify(prev.slice(-500)));
    } catch (e) { /* storage may be unavailable */ }
  };

  window.__priRec = { log: [] };

  document.addEventListener("click", (e) => {
    const d = describe(e.target);
    if (!d) return;
    // Also record the nearest button/link ancestor — icon buttons wrap an <i>.
    let host = null;
    try {
      const h = e.target.closest("button, a, [role='button'], [onclick]");
      if (h && h !== e.target) host = describe(h);
    } catch (err) { /* ignore */ }
    push({ kind: "click", t: Date.now(), target: d, host: host });
  }, true);

  document.addEventListener("keydown", (e) => {
    // Privacy: only record shortcuts and control keys, never typed content.
    const mod = e.ctrlKey || e.altKey || e.metaKey;
    const special = e.key && e.key.length > 1;
    if (!mod && !special) return;
    if (e.key === "Shift" || e.key === "Control" || e.key === "Alt" || e.key === "Meta") return;
    push({
      kind: "key",
      t: Date.now(),
      key: e.key,
      ctrl: e.ctrlKey, alt: e.altKey, shift: e.shiftKey, meta: e.metaKey,
      target: describe(e.target)
    });
  }, true);

  return "installed";
}
"""

DRAIN_JS = r"""
() => {
  const KEY = "__priRecLog";
  let stored = [];
  try {
    stored = JSON.parse(sessionStorage.getItem(KEY) || "[]");
    sessionStorage.removeItem(KEY);
  } catch (e) { /* storage may be unavailable */ }
  const live = (window.__priRec && window.__priRec.log) || [];
  if (window.__priRec) window.__priRec.log = [];
  // sessionStorage is the superset; fall back to the live array if it failed.
  return stored.length >= live.length ? stored : live;
}
"""

# Lightweight signature used for before/after diffing.
SIGNATURE_JS = r"""
() => {
  const txt = (s, n) => {
    if (!s) return "";
    s = String(s).replace(/\s+/g, " ").trim();
    return s.length > n ? s.slice(0, n) + "…" : s;
  };
  const cssPath = (el) => {
    const parts = [];
    let cur = el;
    while (cur && cur.nodeType === 1 && parts.length < 8) {
      if (cur.id && /^[A-Za-z][\w:.-]*$/.test(cur.id)) { parts.unshift("#" + CSS.escape(cur.id)); break; }
      let seg = cur.tagName.toLowerCase();
      const p = cur.parentElement;
      if (p) {
        const sibs = Array.from(p.children).filter(c => c.tagName === cur.tagName);
        if (sibs.length > 1) seg += ":nth-of-type(" + (sibs.indexOf(cur) + 1) + ")";
      }
      parts.unshift(seg);
      cur = cur.parentElement;
    }
    return parts.join(" > ");
  };
  const out = {};
  const nodes = document.querySelectorAll("input, select, textarea, button, [role], a[href], tr");
  let i = 0;
  for (const el of nodes) {
    if (i++ > 3000) break;
    let visible = false;
    try {
      const r = el.getBoundingClientRect();
      const st = window.getComputedStyle(el);
      visible = r.width > 0 && r.height > 0 && st.visibility !== "hidden" && st.display !== "none";
    } catch (e) { /* detached node */ }
    const key = cssPath(el);
    if (!key) continue;
    out[key] = {
      tag: el.tagName.toLowerCase(),
      label: txt(el.getAttribute("title") || el.getAttribute("aria-label") || el.innerText, 40),
      id: el.id || "",
      name: el.getAttribute("name") || "",
      visible: visible,
      disabled: el.disabled === true,
      readonly: el.hasAttribute("readonly")
    };
  }
  return { url: location.href, nodes: out, row_count: document.querySelectorAll("tr, [role='row']").length };
}
"""
