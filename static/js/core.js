/* Shared client core: storage, i18n, theme, API client with token refresh, DOM helpers, router, UI states. */
(function () {
  "use strict";

  // ---------- safe storage (private mode / blocked storage must not break the app) ----------
  const store = {
    get(k, fallback = null) { try { const v = localStorage.getItem(k); return v === null ? fallback : JSON.parse(v); } catch { return fallback; } },
    set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* ignore */ } },
    del(k) { try { localStorage.removeItem(k); } catch { /* ignore */ } },
  };

  // ---------- i18n ----------
  let lang = store.get("cb_lang") || (navigator.language || "en").slice(0, 2);
  if (!["en", "ar"].includes(lang)) lang = "en";
  function t(key, params) {
    const s = (CB_STRINGS[lang] && CB_STRINGS[lang][key]) || CB_STRINGS.en[key] || key;
    return params ? s.replace(/\{(\w+)\}/g, (_, p) => (params[p] ?? "")) : s;
  }
  function applyLang() {
    document.documentElement.lang = lang;
    document.documentElement.dir = lang === "ar" ? "rtl" : "ltr";
  }
  function setLang(l) { lang = l; store.set("cb_lang", l); applyLang(); }
  /** Pick the localized field: loc(route, "name") -> route.name_ar in Arabic. */
  const loc = (obj, field) => (obj ? obj[`${field}_${lang}`] || obj[`${field}_en`] || "" : "");

  // ---------- theme ----------
  function applyTheme() {
    const theme = store.get("cb_theme", "system");
    if (theme === "system") document.documentElement.removeAttribute("data-theme");
    else document.documentElement.setAttribute("data-theme", theme);
  }
  function setTheme(v) { store.set("cb_theme", v); applyTheme(); }

  // ---------- formatting ----------
  const nf = () => new Intl.NumberFormat(lang === "ar" ? "ar-EG" : "en-EG", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const money = (cents, cur = "EGP") => `${nf().format((cents || 0) / 100)} ${lang === "ar" && cur === "EGP" ? "ج.م" : cur}`;
  const date = (iso) => iso ? new Intl.DateTimeFormat(lang === "ar" ? "ar-EG" : "en-GB", { day: "numeric", month: "short", year: "numeric" })
    .format(new Date(iso.length === 10 ? iso + "T00:00:00" : iso + (iso.endsWith("Z") || iso.includes("+") ? "" : "Z"))) : "";
  const dateTime = (iso) => iso ? new Intl.DateTimeFormat(lang === "ar" ? "ar-EG" : "en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })
    .format(new Date(iso + (iso.endsWith("Z") || iso.includes("+") ? "" : "Z"))) : "";
  const now = () => Date.now() + (Number(store.get("cb_clock_offset", 0)) || 0);
  const uid = () => (crypto.randomUUID ? crypto.randomUUID().replace(/-/g, "") : Math.random().toString(36).slice(2) + Date.now().toString(36));

  // ---------- API client ----------
  let accessToken = null;
  let refreshing = null;
  class ApiError extends Error {
    constructor(status, body) {
      const e = (body && body.error) || {};
      super(e.message || t("error_generic"));
      this.status = status; this.code = e.code || "error"; this.details = e.details || {};
    }
  }
  async function refresh() {
    if (!refreshing) {
      refreshing = fetch("/api/v1/auth/refresh", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}", credentials: "same-origin" })
        .then(async (r) => { const b = await r.json().catch(() => ({})); if (!r.ok) throw new ApiError(r.status, b); accessToken = b.access_token; store.set("cb_user", b.user); return b; })
        .finally(() => { refreshing = null; });
    }
    return refreshing;
  }
  async function api(path, { method = "GET", body, form, retry = true, raw = false } = {}) {
    const headers = {};
    if (accessToken) headers.Authorization = `Bearer ${accessToken}`;
    if (body !== undefined) headers["Content-Type"] = "application/json";
    let resp;
    try {
      resp = await fetch(`/api/v1${path}`, { method, headers, credentials: "same-origin", body: form || (body !== undefined ? JSON.stringify(body) : undefined) });
    } catch {
      throw new ApiError(0, { error: { code: "network", message: t("error_network") } });
    }
    if (resp.status === 401 && retry && !path.startsWith("/auth/")) {
      try { await refresh(); } catch { CB.emit("logged-out"); throw new ApiError(401, { error: { code: "unauthorized", message: t("login") } }); }
      return api(path, { method, body, form, retry: false, raw });
    }
    const serverDate = Date.parse(resp.headers.get("Date") || "");
    // Rotating QR codes depend on the clock: remember how far this phone's clock is from the server's.
    if (serverDate) store.set("cb_clock_offset", serverDate - Date.now());
    if (raw && resp.ok) return resp;
    const data = resp.status === 204 ? {} : await resp.json().catch(() => ({}));
    if (!resp.ok) throw new ApiError(resp.status, data);
    return data;
  }
  function setSession(tokens) { accessToken = tokens.access_token; store.set("cb_user", tokens.user); }
  async function restoreSession() { try { await refresh(); return store.get("cb_user"); } catch { return null; } }
  async function logout() {
    try { await api("/auth/logout", { method: "POST", body: {} }); } catch { /* ignore */ }
    accessToken = null; store.del("cb_user"); store.del("cb_cache"); CB.emit("logged-out");
  }

  // ---------- events ----------
  const listeners = {};
  const on = (ev, fn) => ((listeners[ev] = listeners[ev] || []).push(fn));
  const emit = (ev, data) => (listeners[ev] || []).forEach((fn) => fn(data));

  // ---------- DOM ----------
  /** h("button.btn.secondary", {onclick}, "text", child) — tiny hyperscript; strings are text (never HTML). */
  function h(sel, attrs, ...children) {
    const [tag, ...classes] = sel.split(".");
    const el = document.createElement(tag || "div");
    if (classes.length) el.className = classes.join(" ");
    if (attrs && (typeof attrs !== "object" || attrs instanceof Node || Array.isArray(attrs))) { children.unshift(attrs); attrs = null; }
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v === null || v === undefined || v === false) continue;
      if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2), v);
      else if (k === "style" && typeof v === "object") {
        for (const [prop, val] of Object.entries(v)) {
          if (prop.startsWith("--")) el.style.setProperty(prop, val); // CSS custom properties need setProperty
          else el.style[prop] = val;
        }
      }
      else if (k === "class") el.className += (el.className ? " " : "") + v;
      else if (k in el && k !== "list" && k !== "form") el[k] = v;
      else el.setAttribute(k, v === true ? "" : v);
    }
    for (const c of children.flat(Infinity)) {
      if (c === null || c === undefined || c === false) continue;
      el.append(c instanceof Node ? c : document.createTextNode(String(c)));
    }
    return el;
  }
  const $ = (s, root = document) => root.querySelector(s);
  function mount(root, ...nodes) { root.replaceChildren(...nodes.flat()); }

  // ---------- UI pieces ----------
  function toast(msg, kind = "") {
    let box = $(".toasts");
    if (!box) { box = h("div.toasts", { role: "status", "aria-live": "polite" }); document.body.append(box); }
    const el = h(`div.toast${kind ? "." + kind : ""}`, msg);
    box.append(el);
    setTimeout(() => el.remove(), 3800);
  }
  function modal(title, content, { actions = [] } = {}) {
    return new Promise((resolve) => {
      const close = (v) => { back.remove(); document.removeEventListener("keydown", esc); resolve(v); };
      const esc = (e) => { if (e.key === "Escape") close(null); };
      const box = h("div.modal", { role: "dialog", "aria-modal": "true", "aria-label": title },
        h("div.row.spread", h("h2", { style: { margin: 0 } }, title), h("button.icon-btn", { "aria-label": t("close"), onclick: () => close(null) }, "✕")),
        h("div", { style: { marginTop: "16px" } }, content),
        actions.length ? h("div.row", { style: { marginTop: "20px", justifyContent: "flex-end" } },
          actions.map((a) => h(`button.btn${a.kind ? "." + a.kind : ""}`, { onclick: () => close(a.value) }, a.label))) : null);
      const back = h("div.modal-backdrop", { onclick: (e) => { if (e.target === back) close(null); } }, box);
      document.body.append(back);
      document.addEventListener("keydown", esc);
      const focusable = box.querySelector("input, select, textarea, button.btn");
      (focusable || box.querySelector("button")).focus();
      box.closeModal = close;
    });
  }
  const confirmDialog = (title, text, okLabel = t("confirm"), kind = "") =>
    modal(title, h("p", text), { actions: [{ label: t("cancel"), value: false, kind: "secondary" }, { label: okLabel, value: true, kind }] });

  const skeleton = (n = 3, kind = "card") => h("div", { "aria-busy": "true", "aria-label": t("loading") },
    Array.from({ length: n }, () => h(`div.skeleton.sk-${kind}`)));
  const empty = (art, title, text, action) => h("div.empty", h("div.art", { "aria-hidden": "true" }, art), h("h3", title), text ? h("p", text) : null, action || null);
  const errorState = (err, onRetry) => h("div.empty", { role: "alert" }, h("div.art", "⚠️"), h("h3", err.message || t("error_generic")),
    onRetry ? h("button.btn.secondary", { onclick: onRetry }, t("retry")) : null);

  /** Render loading -> (success | empty | error) for an async load. */
  async function view(root, load, render, { skeletonNodes } = {}) {
    mount(root, skeletonNodes || skeleton());
    try {
      const data = await load();
      mount(root, render(data));
    } catch (err) {
      if (err.status === 401) return;
      mount(root, errorState(err, () => view(root, load, render, { skeletonNodes })));
    }
  }

  /** Form helper: field(name, label, {type, hint, ...}) and inline error display from 422 details. */
  function field(name, label, opts = {}) {
    const { hint, type = "text", options, ...rest } = opts;
    const id = `f_${name}_${Math.random().toString(36).slice(2, 7)}`;
    const input = options
      ? h("select.input", { id, name, ...rest }, options.map(([v, l]) => h("option", { value: v, selected: String(rest.value) === String(v) }, l)))
      : type === "textarea" ? h("textarea.input", { id, name, rows: 4, ...rest }) : h("input.input", { id, name, type, ...rest });
    const err = h("div.error", { id: id + "_err", "aria-live": "polite" });
    input.setAttribute("aria-describedby", id + "_err");
    return h("label.field", { for: id, "data-field": name }, h("span", label), input, hint ? h("div.hint", hint) : null, err);
  }
  function showErrors(form, err) {
    form.querySelectorAll(".field").forEach((f) => { f.classList.remove("invalid"); f.querySelector(".error").textContent = ""; });
    const details = (err.details && (err.details.json || err.details.form || err.details.query)) || {};
    let shown = false;
    for (const [name, msgs] of Object.entries(details)) {
      const f = form.querySelector(`[data-field="${name}"]`);
      if (f) { f.classList.add("invalid"); f.querySelector(".error").textContent = [].concat(msgs).join(" "); shown = true; }
    }
    if (err.details && err.details.field) {
      const f = form.querySelector(`[data-field="${err.details.field}"]`);
      if (f) { f.classList.add("invalid"); f.querySelector(".error").textContent = err.message; shown = true; }
    }
    if (!shown) toast(err.message, "err");
    const first = form.querySelector(".invalid .input");
    if (first) first.focus();
  }
  /** Wire a submit handler with busy state + error display. */
  function onSubmit(form, handler) {
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const btn = form.querySelector('button[type="submit"]');
      const label = btn && btn.textContent;
      if (btn) { btn.disabled = true; btn.replaceChildren(h("span.spinner"), label); }
      try { await handler(Object.fromEntries(new FormData(form).entries())); }
      catch (err) { showErrors(form, err); }
      finally { if (btn && btn.isConnected) { btn.disabled = false; btn.textContent = label; } }
    });
    return form;
  }

  // ---------- hash router ----------
  const routes = [];
  function route(pattern, handler) { routes.push({ re: new RegExp("^" + pattern.replace(/:(\w+)/g, "(?<$1>[^/]+)") + "$"), handler }); }
  function go(path) { if (location.hash === "#" + path) dispatch(); else location.hash = path; }
  function dispatch() {
    const path = location.hash.slice(1) || "/";
    for (const r of routes) {
      const m = path.match(r.re);
      if (m) { r.handler(m.groups || {}); emit("navigate", path); window.scrollTo(0, 0); return; }
    }
    go("/");
  }
  function start() { window.addEventListener("hashchange", dispatch); dispatch(); }

  // ---------- connectivity ----------
  function offlineBar(container) {
    const bar = h("div.offline-bar", { role: "status", hidden: navigator.onLine }, t("offline_bar"));
    window.addEventListener("online", () => { bar.hidden = true; emit("online"); });
    window.addEventListener("offline", () => { bar.hidden = false; });
    container.prepend(bar);
  }

  applyLang();
  applyTheme();
  window.CB = { store, t, loc, setLang, get lang() { return lang; }, setTheme, money, date, dateTime, uid, now, api, ApiError,
    setSession, restoreSession, logout, refresh, on, emit, h, $, mount, toast, modal, confirmDialog, skeleton, empty,
    errorState, view, field, showErrors, onSubmit, route, go, start, offlineBar };
})();
