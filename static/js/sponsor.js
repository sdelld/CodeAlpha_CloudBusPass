/* University / company portal: seats, invite codes, utilisation, buy more seats. */
(function () {
  "use strict";
  const { h, t, api, money, date, toast, view, field, onSubmit, mount, modal } = CB;
  const root = document.getElementById("app");

  function frame(content) {
    const main = h("main.screen.stack-lg", { id: "main" }, content);
    mount(root, h("div.app", { style: { maxWidth: "860px", paddingBottom: "32px" } },
      h("header.topbar", h("h1", "🏛️ " + t("s_title")),
        h("button.btn.secondary.sm", { onclick: () => { CB.setLang(CB.lang === "ar" ? "en" : "ar"); dashboard(); } }, CB.lang === "ar" ? "EN" : "ع"),
        h("button.btn.ghost.sm", { onclick: async () => { await CB.logout(); login(); } }, t("logout"))), main));
    return main;
  }

  function login() {
    frame(onSubmit(h("form.stack.card", { novalidate: true },
      field("identifier", t("email_or_phone"), { autocomplete: "username", required: true }),
      field("password", t("password"), { type: "password", autocomplete: "current-password", required: true }),
      h("button.btn.block", { type: "submit" }, t("login"))), async (d) => {
      const tokens = await api("/auth/login", { method: "POST", body: d });
      if (tokens.user.role !== "sponsor") throw new CB.ApiError(403, { error: { message: "Sponsor accounts only." } });
      CB.setSession(tokens); dashboard();
    }));
  }

  function dashboard() {
    const main = frame(null);
    view(main, async () => {
      const [d, routes] = await Promise.all([api("/sponsor/dashboard"), api("/routes")]);
      return { d, routes: routes.items, currency: routes.currency };
    }, ({ d, routes, currency }) => h("div.stack-lg",
      h("div.card.row.spread", h("div", h("h2", { style: { margin: 0 } }, d.organization.name),
        h("div.small.muted", d.organization.email_domain ? `@${d.organization.email_domain}` : d.organization.kind)),
      h("button.btn", { onclick: () => buy(routes, currency) }, "+ " + t("s_buy"))),
      h("div.kpis", [[t("s_seats"), d.totals.seats_total], [t("s_used"), d.totals.seats_used], [t("a_rides"), d.totals.rides]]
        .map(([l, v]) => h("div.card", h("div.small.muted", l), h("div.kpi", v)))),
      d.blocks.length ? h("div.stack", d.blocks.map((b) => h("div.card.stack",
        h("div.row.spread", h("b", `${b.route_code} · ${b.pass_type}`), h(`span.badge.${b.status === "active" ? "ok" : "warn"}`, b.status)),
        h("div.qr-timer", { style: { background: "var(--surface-2)" } }, h("i", { style: { width: `${(b.seats_used / b.seats_total) * 100}%` } })),
        h("div.small.muted", `${b.seats_used} / ${b.seats_total} · ${date(b.created_at)}`),
        h("div.row", h("span.small", t("s_invite") + ":"), h("code.badge.brand.mono", { style: { fontSize: "1rem" } }, b.invite_code),
          h("button.btn.ghost.sm", { onclick: async () => { try { await navigator.clipboard.writeText(b.invite_code); toast(t("copied"), "ok"); } catch { /* no clipboard */ } } }, "📋")),
        h("p.xs.muted", t("s_share")))))
        : CB.empty("🎟️", t("s_buy"))));
  }

  function buy(routes, currency) {
    const key = CB.uid();
    const form = onSubmit(h("form.stack", { novalidate: true },
      field("route_id", t("choose_route"), { options: routes.map((r) => [r.id, `${r.code} · ${CB.loc(r, "name")} · ${money(r.base_fare_cents * 30, currency)}/seat`]) }),
      field("seats", t("s_seats_count"), { type: "number", min: 10, max: 5000, value: 50, required: true }),
      h("button.btn.block", { type: "submit" }, t("topup_go"))), async (d) => {
      const pay = await api("/payments/checkout", { method: "POST", body: { purpose: "sponsor_seats", route_id: Number(d.route_id), pass_type: "monthly",
        seats: Number(d.seats), idempotency_key: key } });
      location.href = pay.checkout_url;
    });
    modal(t("s_buy"), form);
  }

  CB.on("logged-out", login);
  (async function boot() {
    const me = await CB.restoreSession();
    if (!me || me.role !== "sponsor") return login();
    dashboard();
  })();
})();
