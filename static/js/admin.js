/* Operator dashboard. */
(function () {
  "use strict";
  const { h, t, api, money, dateTime, loc, toast, view, field, onSubmit, go, route, empty, mount, modal, confirmDialog } = CB;
  const root = document.getElementById("app");
  let me = null;
  let currency = "EGP";
  const charts = [];

  const NAV = [["/", "📊", "a_dashboard"], ["/routes", "🗺️", "a_routes"], ["/stops", "📍", "a_stops"], ["/buses", "🚌", "a_buses"],
    ["/pass_types", "🎫", "a_pass_types"], ["/discounts", "🏷️", "a_discounts"], ["/users", "👥", "a_users"],
    ["/verifications", "🪪", "a_verifications"], ["/payments", "💳", "a_payments"], ["/alerts", "🚧", "a_alerts"],
    ["/support", "💬", "a_support"], ["/orgs", "🏛️", "a_orgs"], ["/audit", "📜", "a_audit"], ["/exports", "⬇️", "a_exports"]];

  function layout(titleKey, content, actions) {
    charts.splice(0).forEach((c) => c.destroy());
    const path = location.hash.slice(1) || "/";
    const sidebar = h("aside.sidebar", { "aria-label": "Admin" },
      h("a.logo", { href: "/", style: { marginBottom: "16px" } }, "🚌 CloudBus"),
      h("nav", NAV.map(([p, ico, key]) => h("a", { href: "#" + p, "aria-current": path === p ? "page" : null,
        onclick: () => sidebar.classList.remove("open") }, h("span", { "aria-hidden": "true" }, ico), t(key)))),
      h("div.stack", { style: { marginTop: "24px" } },
        h("div.small.muted", me ? me.name : ""),
        h("div.row", h("button.btn.secondary.sm", { onclick: () => { CB.setLang(CB.lang === "ar" ? "en" : "ar"); dispatch(); } }, CB.lang === "ar" ? "English" : "العربية"),
          h("button.btn.secondary.sm", { onclick: async () => { await CB.logout(); loginScreen(); } }, t("logout")))));
    const main = h("main", { id: "main" },
      h("div.row.spread", { style: { marginBottom: "16px" } },
        h("div.row", h("button.icon-btn.menu-btn", { "aria-label": "Menu", onclick: () => sidebar.classList.toggle("open") }, "☰"), h("h1", { style: { margin: 0 } }, t(titleKey))),
        actions || null),
      content);
    mount(root, h("div.admin", sidebar, main));
    return main.lastChild;
  }
  const dispatch = () => window.dispatchEvent(new HashChangeEvent("hashchange"));

  function loginScreen() {
    mount(root, h("div.app", h("main.screen.stack-lg", { id: "main", style: { paddingTop: "64px" } },
      h("div.center", h("div", { style: { fontSize: "48px" } }, "🚌"), h("h1", "CloudBus Admin")),
      onSubmit(h("form.stack.card", { novalidate: true },
        field("identifier", t("email_or_phone"), { autocomplete: "username", required: true }),
        field("password", t("password"), { type: "password", autocomplete: "current-password", required: true }),
        h("button.btn.block", { type: "submit" }, t("login"))), async (d) => {
        const tokens = await api("/auth/login", { method: "POST", body: d });
        if (tokens.user.role !== "admin") throw new CB.ApiError(403, { error: { message: t("a_only_admins") } });
        CB.setSession(tokens); me = tokens.user;
        startRouter();
      }))));
  }

  // ---------- dashboard ----------
  route("/", () => {
    let days = 30;
    const sel = h("select.input", { "aria-label": "Period", style: { width: "auto" }, onchange: (e) => { days = Number(e.target.value); load(); } },
      [7, 30, 90].map((d) => h("option", { value: d, selected: d === days }, t("a_last_days", { n: d }))));
    const box = layout("a_dashboard", h("div"), sel);
    const load = () => view(box, () => api(`/admin/overview?days=${days}`), (o) => {
      currency = o.currency;
      const k = o.kpis;
      const pct = (v) => (v === null || v === undefined ? "—" : `${(v * 100).toFixed(1)}%`);
      const tiles = [["a_revenue", money(k.revenue_cents, currency)], ["a_active_passes", k.active_passes], ["a_rides", k.rides],
        ["a_mau", k.mau], ["a_arpu", money(k.arpu_cents, currency)], ["a_conversion", pct(k.conversion_rate)],
        ["a_churn", pct(k.churn_rate)], ["a_fraud_rate", pct(k.fraud_rate)]];
      const c1 = h("canvas", { "aria-label": t("a_revenue_by_day"), role: "img" });
      const c2 = h("canvas", { "aria-label": t("a_rides_by_route"), role: "img" });
      const c3 = h("canvas", { "aria-label": t("a_peak_hours"), role: "img" });
      const c4 = h("canvas", { "aria-label": t("a_scan_results"), role: "img" });
      const out = h("div",
        h("div.kpis", tiles.map(([key, v]) => h("div.card", h("div.small.muted", t(key)), h("div.kpi", v)))),
        h("div.charts",
          h("div.card", h("div.card-title", t("a_revenue_by_day")), h("div.chart-box", c1)),
          h("div.card", h("div.card-title", t("a_rides_by_route")), h("div.chart-box", c2)),
          h("div.card", h("div.card-title", t("a_peak_hours")), h("div.chart-box", c3)),
          h("div.card", h("div.card-title", t("a_scan_results")), h("div.chart-box", c4))));
      requestAnimationFrame(() => drawCharts(o, c1, c2, c3, c4));
      return out;
    }, { skeletonNodes: CB.skeleton(4) });
    load();
  });

  function drawCharts(o, c1, c2, c3, c4) {
    if (!window.Chart) return;
    const css = getComputedStyle(document.documentElement);
    const brand = css.getPropertyValue("--brand-600").trim() || "#2563eb";
    const text = css.getPropertyValue("--muted").trim();
    const grid = css.getPropertyValue("--line").trim();
    Chart.defaults.color = text;
    Chart.defaults.font.family = css.getPropertyValue("--font");
    const scales = { x: { grid: { color: grid } }, y: { grid: { color: grid }, beginAtZero: true } };
    const common = { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } } };
    charts.push(new Chart(c1, { type: "line", data: { labels: o.revenue_by_day.map((d) => d.date.slice(5)),
      datasets: [{ data: o.revenue_by_day.map((d) => d.amount_cents / 100), borderColor: brand, backgroundColor: brand + "22", fill: true, tension: .3, pointRadius: 0 }] },
    options: { ...common, scales } }));
    charts.push(new Chart(c2, { type: "bar", data: { labels: o.rides_by_route.map((r) => r.route),
      datasets: [{ data: o.rides_by_route.map((r) => r.rides), backgroundColor: brand, borderRadius: 6 }] }, options: { ...common, scales } }));
    charts.push(new Chart(c3, { type: "bar", data: { labels: o.rides_by_hour.map((r) => `${String(r.hour).padStart(2, "0")}`),
      datasets: [{ data: o.rides_by_hour.map((r) => r.rides), backgroundColor: "#0891b2", borderRadius: 4 }] }, options: { ...common, scales } }));
    const results = Object.entries(o.scan_results);
    const colors = { valid: "#059669", duplicate: "#0d9488", expired: "#d97706", fraud: "#dc2626", invalid: "#9ca3af", insufficient_funds: "#7c3aed" };
    charts.push(new Chart(c4, { type: "doughnut", data: { labels: results.map(([k]) => t("v_" + k)),
      datasets: [{ data: results.map(([, v]) => v), backgroundColor: results.map(([k]) => colors[k] || "#64748b"), borderWidth: 0 }] },
    options: { ...common, plugins: { legend: { display: true, position: "bottom" } } } }));
  }

  // ---------- generic CRUD ----------
  const CRUD = {
    routes: { title: "a_routes", cols: [["code"], ["name_en"], ["name_ar"], ["base_fare_cents", (v) => money(v, currency)], ["active", yesNo]],
      form: (o, ctx) => [field("code", "Code", { value: o.code || "", required: true, pattern: "[A-Z0-9-]+" }),
        field("name_en", "Name (EN)", { value: o.name_en || "", required: true }), field("name_ar", "الاسم (AR)", { value: o.name_ar || "", required: true, dir: "rtl" }),
        field("color", "Color", { type: "color", value: o.color || "#2563eb" }),
        field("base_fare_cents", "Base fare (piastres)", { type: "number", value: o.base_fare_cents || 1000, min: 100 }),
        field("daily_single_capacity", "Single tickets per day", { type: "number", value: o.daily_single_capacity || 200, min: 1 }),
        field("stops", "Stops (stop_id:minutes, one per line)", { type: "textarea", value: (o.stops || []).map((s) => `${s.id}:${s.minutes_from_start}`).join("\n"),
          hint: ctx.stops.map((s) => `${s.id}=${s.name_en}`).join(" · ") }),
        field("departures", "Departures (HH:MM, comma separated)", { value: (o.departures || []).join(", ") }),
        checkbox("active", "Active", o.active !== false)],
      parse: (d) => ({ ...d, base_fare_cents: Number(d.base_fare_cents), daily_single_capacity: Number(d.daily_single_capacity), active: d.active === "on",
        stops: d.stops.split(/\n+/).map((l) => l.trim()).filter(Boolean).map((l) => { const [id, m] = l.split(":"); return { stop_id: Number(id), minutes_from_start: Number(m) }; }),
        departures: d.departures.split(/[,\s]+/).filter(Boolean) }) },
    stops: { title: "a_stops", cols: [["id"], ["name_en"], ["name_ar"], ["lat"], ["lng"]],
      form: (o) => [field("name_en", "Name (EN)", { value: o.name_en || "", required: true }), field("name_ar", "الاسم (AR)", { value: o.name_ar || "", required: true, dir: "rtl" }),
        field("lat", "Latitude", { type: "number", step: "any", value: o.lat ?? 30.04 }), field("lng", "Longitude", { type: "number", step: "any", value: o.lng ?? 31.23 })],
      parse: (d) => ({ ...d, lat: Number(d.lat), lng: Number(d.lng) }) },
    buses: { title: "a_buses", cols: [["plate"], ["route_id", (v, ctx) => (ctx.routes.find((r) => r.id === v) || {}).code || "—"], ["capacity"], ["status", badge]],
      form: (o, ctx) => [field("plate", "Plate", { value: o.plate || "", required: true }),
        field("route_id", "Route", { options: [["", "—"], ...ctx.routes.map((r) => [r.id, `${r.code} · ${r.name_en}`])], value: o.route_id ?? "" }),
        field("capacity", "Capacity", { type: "number", value: o.capacity || 50 }),
        field("status", "Status", { options: [["active", "active"], ["maintenance", "maintenance"]], value: o.status || "active" })],
      parse: (d) => ({ ...d, route_id: d.route_id ? Number(d.route_id) : null, capacity: Number(d.capacity) }) },
    pass_types: { title: "a_pass_types", cols: [["code"], ["name_en"], ["multiplier", (v) => `${v[0]}/${v[1]} ×`], ["validity_days"], ["max_rides", (v) => v ?? "∞"], ["active", yesNo]],
      form: (o) => [field("code", "Code", { value: o.code || "", required: true }), field("name_en", "Name (EN)", { value: o.name_en || "" }),
        field("name_ar", "الاسم (AR)", { value: o.name_ar || "", dir: "rtl" }),
        field("multiplier_num", "Price multiplier ×", { type: "number", value: o.multiplier ? o.multiplier[0] : 1 }),
        field("multiplier_den", "÷ divisor", { type: "number", value: o.multiplier ? o.multiplier[1] : 1 }),
        field("validity_days", "Valid days", { type: "number", value: o.validity_days || 1 }),
        field("max_rides", "Max rides (empty = unlimited)", { type: "number", value: o.max_rides ?? "" }),
        checkbox("discountable", "Student/senior discount applies", o.discountable !== false), checkbox("active", "Active", o.active !== false)],
      parse: (d) => ({ code: d.code, name_en: d.name_en, name_ar: d.name_ar, multiplier_num: Number(d.multiplier_num), multiplier_den: Number(d.multiplier_den),
        validity_days: Number(d.validity_days), max_rides: d.max_rides ? Number(d.max_rides) : null, discountable: d.discountable === "on", active: d.active === "on" }) },
    promo_codes: { title: "a_discounts", cols: [["code"], ["kind"], ["value", (v, ctx, o) => (o.kind === "percent" ? `${v}%` : money(v, currency))],
      ["used_count", (v, ctx, o) => `${v}/${o.max_uses ?? "∞"}`], ["expires_at", (v) => (v ? dateTime(v) : "—")], ["active", yesNo]],
      form: (o) => [field("code", "Code", { value: o.code || "", required: true }),
        field("kind", "Type", { options: [["percent", "percent"], ["fixed", "fixed (piastres)"]], value: o.kind || "percent" }),
        field("value", "Value", { type: "number", value: o.value || 10 }), field("max_uses", "Max uses", { type: "number", value: o.max_uses ?? "" }),
        field("expires_at", "Expires", { type: "datetime-local", value: o.expires_at ? o.expires_at.slice(0, 16) : "" }), checkbox("active", "Active", o.active !== false)],
      parse: (d) => ({ code: d.code, kind: d.kind, value: Number(d.value), max_uses: d.max_uses ? Number(d.max_uses) : null,
        expires_at: d.expires_at ? new Date(d.expires_at).toISOString().slice(0, 19) : null, active: d.active === "on" }) },
    discounts: { title: "a_discounts", key: "code", cols: [["code"], ["percent", (v) => `${v}%`], ["active", yesNo]],
      form: (o) => [field("code", "Code", { options: [["student", "student"], ["senior", "senior"]], value: o.code || "student" }),
        field("percent", "Percent", { type: "number", min: 0, max: 100, value: o.percent ?? 40 }), checkbox("active", "Active", o.active !== false)],
      parse: (d) => ({ code: d.code, percent: Number(d.percent), active: d.active === "on" }) },
  };
  function yesNo(v) { return h(`span.badge.${v ? "ok" : ""}`, v ? t("yes") : t("no")); }
  function badge(v) { return h(`span.badge.${v === "active" ? "ok" : "warn"}`, v); }
  function checkbox(name, label, checked) { return h("label.check", h("input", { type: "checkbox", name, checked }), label); }

  async function crudContext() {
    const [routes, stops] = await Promise.all([api("/admin/routes"), api("/admin/stops")]);
    return { routes: routes.items, stops: stops.items };
  }

  function crudTable(kind, items, ctx, reload) {
    const cfg = CRUD[kind];
    const key = cfg.key || "id";
    return h("div.table-wrap", h("table", h("thead", h("tr", cfg.cols.map(([c]) => h("th", c.replace(/_/g, " "))), h("th", ""))),
      h("tbody", items.length ? items.map((o) => h("tr", cfg.cols.map(([c, fmt]) => h("td", fmt ? fmt(o[c], ctx, o) : String(o[c] ?? "—"))),
        h("td", h("div.row", h("button.btn.secondary.sm", { onclick: () => editModal(kind, o, ctx, reload) }, t("edit")),
          kind !== "discounts" ? h("button.btn.ghost.sm", { onclick: async () => {
            if (!(await confirmDialog(t("delete"), `${o.code || o.plate || o.name_en || o.id}?`, t("delete"), "danger"))) return;
            await api(`/admin/${kind}/${o[key]}`, { method: "DELETE" }); toast(t("saved"), "ok"); reload();
          } }, t("delete")) : null))))
        : h("tr", h("td", { colSpan: cfg.cols.length + 1 }, empty("📭", "—"))))));
  }

  function editModal(kind, o, ctx, reload) {
    const cfg = CRUD[kind];
    const isNew = !o[cfg.key || "id"];
    const form = onSubmit(h("form.stack", { novalidate: true }, cfg.form(o, ctx), h("button.btn.block", { type: "submit" }, isNew ? t("create") : t("save"))),
      async (d) => {
        const body = cfg.parse(d);
        if (isNew) await api(`/admin/${kind}`, { method: "POST", body });
        else {
          if (kind === "discounts") delete body.code; // primary key
          await api(`/admin/${kind}/${o[cfg.key || "id"]}`, { method: "PATCH", body });
        }
        document.querySelector(".modal-backdrop").remove();
        toast(t("saved"), "ok");
        reload();
      });
    modal(`${isNew ? t("a_new") : t("edit")} · ${t(cfg.title)}`, form);
  }

  for (const kind of ["routes", "stops", "buses", "pass_types"]) {
    route("/" + kind, () => {
      let ctx;
      const box = layout(CRUD[kind].title, h("div"), h("button.btn.sm", { onclick: () => editModal(kind, {}, ctx, load) }, "+ " + t("a_new")));
      const load = () => view(box, async () => { ctx = await crudContext(); return api(`/admin/${kind}`); },
        ({ items }) => crudTable(kind, items, ctx, load));
      load();
    });
  }

  route("/discounts", () => {
    const box = layout("a_discounts", h("div"), h("button.btn.sm", { onclick: () => editModal("promo_codes", {}, {}, load) }, "+ " + t("promo_code")));
    const load = () => view(box, async () => Promise.all([api("/admin/discounts"), api("/admin/promo_codes")]),
      ([d, p]) => h("div.stack-lg", h("h2", t("discount")), crudTable("discounts", d.items, {}, load), h("h2", t("promo_code")), crudTable("promo_codes", p.items, {}, load)));
    load();
  });

  // ---------- users ----------
  route("/users", () => {
    const q = h("input.input", { type: "search", placeholder: t("search"), "aria-label": t("search"), style: { maxWidth: "280px" } });
    const role = h("select.input", { "aria-label": "Role", style: { width: "auto" } }, ["", "rider", "validator", "admin", "sponsor"].map((r) => h("option", { value: r }, r || "all roles")));
    const box = layout("a_users", h("div"));
    box.before(h("div.toolbar", q, role));
    let timer;
    const params = () => new URLSearchParams(Object.entries({ q: q.value.trim(), role: role.value, limit: 100 }).filter(([, v]) => v !== ""));
    const load = () => view(box, () => api(`/admin/users?${params()}`),
      ({ items }) => h("div.table-wrap", h("table", h("thead", h("tr", ["Name", "Email / phone", "Role", "Status", "Discount", "Wallet", ""].map((c) => h("th", c)))),
        h("tbody", items.map((u) => h("tr", h("td", u.name), h("td.ltr", u.email || u.phone || ""),
          h("td", h("select.input", { "aria-label": "Role", style: { minHeight: "32px", width: "auto" }, onchange: async (e) => {
            try { await api(`/admin/users/${u.id}`, { method: "PATCH", body: { role: e.target.value } }); toast(t("saved"), "ok"); } catch (err) { toast(err.message, "err"); load(); }
          } }, ["rider", "validator", "admin", "sponsor"].map((r) => h("option", { value: r, selected: r === u.role }, r)))),
          h("td", badge(u.status)), h("td", u.discount_type !== "none" ? `${u.discount_type} (${u.discount_status})` : "—"),
          h("td.num", money(u.balance_cents, currency)),
          h("td", h("div.row", h("button.btn.secondary.sm", { onclick: () => userPasses(u) }, "🎫"),
            h(`button.btn.sm.${u.status === "suspended" ? "ok" : "danger"}`, { onclick: async () => {
              const next = u.status === "suspended" ? "active" : "suspended";
              if (!(await confirmDialog(next === "suspended" ? t("a_suspend") : t("a_unsuspend"), u.name, t("confirm"), next === "suspended" ? "danger" : "ok"))) return;
              try { await api(`/admin/users/${u.id}`, { method: "PATCH", body: { status: next, reason: "admin action" } }); load(); } catch (err) { toast(err.message, "err"); }
            } }, u.status === "suspended" ? t("a_unsuspend") : t("a_suspend"))))))))));
    q.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(load, 300); });
    role.addEventListener("change", load);
    load();
  });

  async function userPasses(u) {
    const content = h("div", CB.skeleton(2, "line"));
    modal(u.name, content);
    try {
      const { items } = await api(`/admin/users/${u.id}/passes`);
      mount(content, items.length ? h("ul.list", items.map((p) => h("li", h("span.badge", { style: { background: p.route.color, color: "#fff" } }, p.route.code),
        h("div.grow", h("div", p.pass_type.name_en), h("div.small.muted", `${p.valid_from} → ${p.valid_until} · ${money(p.price_cents, currency)}`)),
        h("span.badge", p.status),
        ["active", "expired"].includes(p.status) && p.price_cents > 0 ? h("button.btn.danger.sm", { onclick: async () => {
          if (!(await confirmDialog(t("a_refund"), `${money(p.price_cents, currency)} → wallet`, t("a_refund"), "danger"))) return;
          try { await api(`/admin/passes/${p.id}/refund`, { method: "POST", body: { reason: "admin refund" } }); toast(t("saved"), "ok"); document.querySelector(".modal-backdrop").remove(); }
          catch (err) { toast(err.message, "err"); }
        } }, t("a_refund")) : null))) : empty("🎫", t("no_passes")));
    } catch (err) { mount(content, CB.errorState(err)); }
  }

  // ---------- verifications ----------
  route("/verifications", () => {
    const box = layout("a_verifications", h("div"));
    const load = () => view(box, () => api("/admin/verifications"), ({ items }) => items.length ? h("ul.list", items.map((d) => h("li",
      h("div.grow", h("b", d.user_name), h("div.small.muted", `${d.kind} · ${d.original_name} · ${dateTime(d.created_at)}`)),
      h("button.btn.secondary.sm", { onclick: () => openDoc(d.id) }, t("a_view_doc")),
      h("button.btn.ok.sm", { onclick: () => review(d.id, true) }, t("a_approve")),
      h("button.btn.danger.sm", { onclick: () => review(d.id, false) }, t("a_reject")))))
      : empty("🪪", t("no_notifications")));
    async function review(id, approve) { await api(`/admin/verifications/${id}`, { method: "POST", body: { approve } }); toast(t("saved"), "ok"); load(); }
    async function openDoc(id) {
      const resp = await api(`/admin/verifications/${id}/file`, { raw: true });
      const url = URL.createObjectURL(await resp.blob());
      window.open(url, "_blank", "noopener");
    }
    load();
  });

  // ---------- payments ----------
  route("/payments", () => {
    const status = h("select.input", { "aria-label": "Status", style: { width: "auto" } }, ["", "succeeded", "pending", "failed", "refunded"].map((s) => h("option", { value: s }, s || "all")));
    const box = layout("a_payments", h("div"));
    box.before(h("div.toolbar", status));
    const load = () => view(box, () => api(`/admin/payments?limit=200${status.value ? "&status=" + status.value : ""}`), ({ items }) =>
      items.length ? h("div.table-wrap", h("table", h("thead", h("tr", ["Date", "User", "Purpose", "Description", "Amount", "Provider", "Status", ""].map((c) => h("th", c)))),
        h("tbody", items.map((p) => h("tr", h("td", dateTime(p.created_at)), h("td", p.user_name), h("td", p.purpose), h("td", p.description || ""),
          h("td.num", money(p.amount_cents, p.currency)), h("td", p.provider), h("td", h(`span.badge.${p.status === "succeeded" ? "ok" : p.status === "failed" ? "err" : "warn"}`, p.status)),
          h("td", p.status === "succeeded" ? h("button.btn.danger.sm", { onclick: () => refund(p) }, t("a_refund")) : null))))))
        : empty("💳", "—"));
    async function refund(p) {
      const target = await modal(t("a_refund"), h("p", `${p.description || p.purpose} · ${money(p.amount_cents, p.currency)}`),
        { actions: [{ label: t("cancel"), value: null, kind: "secondary" }, { label: "→ " + t("wallet_title"), value: "wallet" }, { label: "→ " + t("pay_card"), value: "card", kind: "danger" }] });
      if (!target) return;
      try { await api(`/admin/payments/${p.id}/refund`, { method: "POST", body: { target, reason: "admin refund" } }); toast(t("saved"), "ok"); load(); }
      catch (err) { toast(err.message, "err"); }
    }
    status.addEventListener("change", load);
    load();
  });

  // ---------- alerts ----------
  route("/alerts", () => {
    let routes = [];
    const box = layout("a_alerts", h("div"), h("button.btn.sm", { onclick: () => newAlert() }, "+ " + t("a_post_alert")));
    const load = () => view(box, async () => { routes = (await api("/admin/routes")).items; return api("/admin/alerts"); }, ({ items }) =>
      items.length ? h("ul.list", items.map((a) => h("li", h("span.badge.warn", a.severity), h("span.badge", (routes.find((r) => r.id === a.route_id) || {}).code),
        h("div.grow", h("div", loc(a, "message")), h("div.xs.muted", dateTime(a.created_at)))))) : empty("🚧", "—"));
    function newAlert() {
      const form = onSubmit(h("form.stack", { novalidate: true },
        field("route_id", t("a_routes"), { options: routes.map((r) => [r.id, `${r.code} · ${r.name_en}`]) }),
        field("severity", "Severity", { options: [["delay", "delay"], ["info", "info"], ["cancelled", "cancelled"]] }),
        field("message_en", "Message (EN)", { required: true }), field("message_ar", "الرسالة (AR)", { required: true, dir: "rtl" }),
        h("button.btn.block", { type: "submit" }, t("a_post_alert"))), async (d) => {
        await api("/admin/alerts", { method: "POST", body: { ...d, route_id: Number(d.route_id) } });
        document.querySelector(".modal-backdrop").remove(); toast(t("saved"), "ok"); load();
      });
      modal(t("a_post_alert"), form);
    }
    load();
  });

  // ---------- support ----------
  route("/support", () => {
    const box = layout("a_support", h("div"));
    const load = () => view(box, () => api("/admin/support"), ({ items }) => items.length ? h("ul.list", items.map((s) => h("li",
      h(`span.badge.${s.status === "open" ? "warn" : ""}`, s.status), h("span.badge", s.category),
      h("div.grow", h("b", s.user_name), h("div.small", s.message), h("div.xs.muted", dateTime(s.created_at))),
      s.status === "open" ? h("button.btn.secondary.sm", { onclick: async () => { await api(`/admin/support/${s.id}/close`, { method: "POST" }); load(); } }, t("a_close_ticket")) : null)))
      : empty("💬", t("no_notifications")));
    load();
  });

  // ---------- organisations ----------
  route("/orgs", () => {
    const box = layout("a_orgs", h("div"), h("button.btn.sm", { onclick: () => {
      const form = onSubmit(h("form.stack", { novalidate: true }, field("name", t("name"), { required: true }),
        field("kind", "Type", { options: [["university", "university"], ["company", "company"]] }),
        field("email_domain", "Email domain (optional)", { placeholder: "university.edu.eg" }),
        h("button.btn.block", { type: "submit" }, t("create"))), async (d) => {
        if (!d.email_domain) delete d.email_domain;
        await api("/admin/organizations", { method: "POST", body: d });
        document.querySelector(".modal-backdrop").remove(); load();
      });
      modal(t("a_orgs"), form);
    } }, "+ " + t("a_new")));
    const load = () => view(box, () => api("/admin/organizations"), ({ items }) => h("ul.list", items.map((o) =>
      h("li", h("span", o.kind === "university" ? "🎓" : "🏢"), h("div.grow", h("b", o.name), h("div.small.muted", o.email_domain || "")), h("span.mono.xs", `#${o.id}`)))));
    load();
  });

  // ---------- audit & exports ----------
  route("/audit", () => {
    const box = layout("a_audit", h("div"));
    view(box, () => api("/admin/audit?limit=200"), ({ items }) => h("div.table-wrap", h("table",
      h("thead", h("tr", ["Time", "Actor", "Action", "Entity", "Details", "IP"].map((c) => h("th", c)))),
      h("tbody", items.map((a) => h("tr", h("td", dateTime(a.created_at)), h("td", a.actor), h("td.mono", a.action),
        h("td", `${a.entity || ""} ${a.entity_id || ""}`), h("td.small", { style: { whiteSpace: "normal", maxWidth: "380px" } }, a.details ? JSON.stringify(a.details).slice(0, 160) : ""),
        h("td.mono.xs", a.ip || "")))))));
  });

  route("/exports", () => {
    layout("a_exports", h("div.grid", { style: { gridTemplateColumns: "repeat(auto-fill,minmax(220px,1fr))" } }, ["payments", "rides", "users", "receipts"].map((k) =>
      h("div.card.stack", h("div.card-title", k), h("button.btn.secondary", { onclick: async (e) => {
        e.target.disabled = true;
        try {
          const resp = await api(`/admin/export/${k}.csv`, { raw: true });
          const a = h("a", { href: URL.createObjectURL(await resp.blob()), download: `${k}.csv` });
          document.body.append(a); a.click(); a.remove();
        } catch (err) { toast(err.message, "err"); } finally { e.target.disabled = false; }
      } }, "⬇ " + t("a_download"))))));
  });

  let started = false;
  function startRouter() {
    if (started) return dispatch();
    started = true;
    CB.start();
  }

  CB.on("logged-out", loginScreen);
  (async function boot() {
    me = await CB.restoreSession();
    if (!me || me.role !== "admin") return loginScreen();
    startRouter();
  })();
})();
