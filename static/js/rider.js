/* Rider web app. Pass in ≤ 3 taps: open app → "Pass" tab. */
(function () {
  "use strict";
  const { h, t, api, money, date, dateTime, loc, store, toast, view, field, onSubmit, go, route, empty, mount, modal } = CB;
  const root = document.getElementById("app");
  let user = store.get("cb_user");
  let currency = "EGP";
  const qrTimers = new Set();
  const stopQrTimers = () => { qrTimers.forEach(clearInterval); qrTimers.clear(); };

  // ---------- offline cache of what's needed to show passes ----------
  const cache = {
    get: () => store.get("cb_cache", {}),
    set: (patch) => store.set("cb_cache", { ...store.get("cb_cache", {}), ...patch }),
  };

  // ---------- rotating QR (same algorithm as the server, see buspass/services/qr.py) ----------
  async function hmacHex(secret, msg) {
    const enc = new TextEncoder();
    const key = await crypto.subtle.importKey("raw", enc.encode(secret), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
    const sig = await crypto.subtle.sign("HMAC", key, enc.encode(msg));
    return [...new Uint8Array(sig)].map((b) => b.toString(16).padStart(2, "0")).join("");
  }
  async function makeToken(qr, id) {
    const win = Math.floor(CB.now() / 1000 / qr.window_seconds);
    const sig = (await hmacHex(qr.secret, `CB1.${qr.kind}.${id}.${win}`)).slice(0, 20);
    return { token: `CB1.${qr.kind}.${id}.${win}.${sig}`, remaining: qr.window_seconds - Math.floor(CB.now() / 1000) % qr.window_seconds };
  }
  function qrImage(text) {
    const q = qrcode(0, "M");
    q.addData(text);
    q.make();
    return h("img", { src: q.createDataURL(8, 2), alt: "QR code", width: 260, height: 260 });
  }
  /** Live QR block: re-renders when the 30 s window rolls over. */
  function liveQr(qr, id) {
    const imgBox = h("div");
    const bar = h("i", { style: { width: "100%" } });
    const label = h("div.small.muted");
    const wrap = h("div.qr-wrap", imgBox, h("div.qr-timer", { "aria-hidden": "true" }, bar), label,
      h("div.xs.mono.ltr", { style: { color: "#64748b", wordBreak: "break-all" } }));
    let last = null;
    let seen = false;
    const timer = setInterval(tick, 1000);
    qrTimers.add(timer);
    async function tick() {
      if (!wrap.isConnected) {
        if (seen) { clearInterval(timer); qrTimers.delete(timer); }
        return; // not mounted yet
      }
      seen = true;
      const { token, remaining } = await makeToken(qr, id);
      if (token !== last) { last = token; mount(imgBox, qrImage(token)); wrap.lastChild.textContent = token; }
      bar.style.width = `${(remaining / qr.window_seconds) * 100}%`;
      label.replaceChildren(navigator.onLine ? h("span", h("span.live-dot"), " ", t("code_refresh", { s: remaining })) : t("offline_ok"));
    }
    requestAnimationFrame(tick);
    return wrap;
  }

  // ---------- shell ----------
  const TABS = [["/", "🏠", "tab_home"], ["/pass", "🎫", "tab_pass"], ["/routes", "🗺️", "tab_routes"], ["/wallet", "👛", "tab_wallet"], ["/profile", "👤", "tab_profile"]];
  let unread = 0;
  function shell(title, content, { back, tabs = true, actions } = {}) {
    stopQrTimers();
    const path = location.hash.slice(1) || "/";
    const tabBase = "/" + (path.split("/")[1] || "");
    const top = h("header.topbar",
      back ? h("button.icon-btn", { "aria-label": t("back"), onclick: () => (history.length > 1 ? history.back() : go(back)) }, CB.lang === "ar" ? "→" : "←") : null,
      h("h1", title),
      actions || null,
      tabs ? h("a.icon-btn", { href: "#/notifications", "aria-label": t("notifications"), style: { position: "relative", textDecoration: "none" } },
        "🔔", unread ? h("span.badge.err", { style: { position: "absolute", top: "0", insetInlineEnd: "-4px", padding: "0 6px" } }, unread) : null) : null);
    const main = h("main.screen", { id: "main" }, content);
    const nav = tabs ? h("div.tabs", h("nav", { "aria-label": "Main" }, TABS.map(([p, ico, key]) =>
      h("a", { href: "#" + p, "aria-current": (p === "/" ? path === "/" : tabBase === p || (p === "/pass" && tabBase === "/passes")) ? "page" : null },
        h("span.ico", { "aria-hidden": "true" }, ico), t(key))))) : null;
    const app = h("div.app", top, main);
    mount(root, app, nav);
    CB.offlineBar(app);
    return main;
  }
  function needAuth(fn) {
    return (params) => {
      if (!user) return go(store.get("cb_onboarded") ? "/login" : "/welcome");
      fn(params);
    };
  }
  async function refreshUnread() {
    try { unread = (await api("/me/notifications")).unread; } catch { /* offline */ }
  }

  // ---------- onboarding & auth ----------
  route("/welcome", () => {
    let i = 0;
    const slides = [["🚌", "ob1_title", "ob1_text"], ["📱", "ob2_title", "ob2_text"], ["📍", "ob3_title", "ob3_text"]];
    const finish = (to) => { store.set("cb_onboarded", true); go(to); };
    function draw() {
      const [art, title, text] = slides[i];
      mount(root, h("div.onboard",
        h("div", { style: { display: "flex", justifyContent: "flex-end" } }, h("button.btn.ghost.sm", { onclick: () => finish("/login") }, t("skip"))),
        h("div.art", { "aria-hidden": "true" }, art), h("h1", t(title)), h("p.muted", t(text)),
        h("div.dots", { "aria-hidden": "true" }, slides.map((_, k) => h(`i${k === i ? ".on" : ""}`))),
        i < slides.length - 1
          ? h("button.btn.block", { onclick: () => { i++; draw(); } }, t("next"))
          : h("div.stack", h("button.btn.block", { onclick: () => finish("/register") }, t("get_started")),
            h("button.btn.ghost.block", { onclick: () => finish("/login") }, t("have_account"))),
        langSwitch()));
    }
    draw();
  });

  function langSwitch() {
    return h("div.row", { style: { justifyContent: "center" } },
      h("button.btn.ghost.sm", { onclick: () => { CB.setLang(CB.lang === "ar" ? "en" : "ar"); CB.start.redraw(); } }, CB.lang === "ar" ? "English" : "العربية"));
  }
  CB.start.redraw = () => window.dispatchEvent(new HashChangeEvent("hashchange"));

  function afterLogin(tokens) {
    CB.setSession(tokens);
    user = tokens.user;
    if (user.language && user.language !== CB.lang) CB.setLang(user.language);
    if (user.role === "validator") return (location.href = "/validator");
    if (user.role === "admin") return (location.href = "/admin");
    if (user.role === "sponsor") return (location.href = "/sponsor");
    go("/");
  }

  route("/login", () => {
    let mode = "password";
    const box = h("div");
    function draw() {
      const form = mode === "password"
        ? onSubmit(h("form.stack", { novalidate: true },
          field("identifier", t("email_or_phone"), { autocomplete: "username", required: true, inputmode: "email" }),
          field("password", t("password"), { type: "password", autocomplete: "current-password", required: true }),
          h("button.btn.block", { type: "submit" }, t("login"))),
          async (d) => afterLogin(await api("/auth/login", { method: "POST", body: d })))
        : onSubmit(h("form.stack", { novalidate: true },
          field("target", t("email_or_phone"), { autocomplete: "username", required: true }),
          h("button.btn.block", { type: "submit" }, t("send_code"))),
          async (d) => { const r = await api("/auth/otp/request", { method: "POST", body: d }); otpStep(r, "login"); });
      mount(box, h("div.segmented", { role: "group" },
        h("button", { type: "button", "aria-pressed": String(mode === "password"), onclick: () => { mode = "password"; draw(); } }, t("with_password")),
        h("button", { type: "button", "aria-pressed": String(mode === "code"), onclick: () => { mode = "code"; draw(); } }, t("with_code"))),
      h("div", { style: { marginTop: "16px" } }, form));
    }
    draw();
    shell(t("login"), h("div.stack-lg", h("div.center", h("div", { style: { fontSize: "56px" } }, "🚌"), h("h2", t("app_name"))),
      box, h("p.center.small", t("no_account"), " ", h("a", { href: "#/register" }, t("register"))), langSwitch()), { tabs: false });
  });

  route("/register", () => {
    let usePhone = false;
    const box = h("div");
    function draw() {
      mount(box, onSubmit(h("form.stack", { novalidate: true },
        field("name", t("name"), { autocomplete: "name", required: true }),
        usePhone ? field("phone", t("phone"), { type: "tel", autocomplete: "tel", required: true, placeholder: "01012345678", dir: "ltr" })
          : field("email", t("email"), { type: "email", autocomplete: "email", required: true }),
        h("button.btn.ghost.sm", { type: "button", onclick: () => { usePhone = !usePhone; draw(); } }, usePhone ? t("use_email") : t("use_phone")),
        field("password", t("password"), { type: "password", autocomplete: "new-password", required: true, minlength: 8, hint: t("password_hint") }),
        h("button.btn.block", { type: "submit" }, t("register"))),
      async (d) => {
        const r = await api("/auth/register", { method: "POST", body: { ...d, language: CB.lang } });
        otpStep(r, "verify");
      }));
    }
    draw();
    shell(t("register"), h("div.stack-lg", box, h("p.center.small", t("has_account"), " ", h("a", { href: "#/login" }, t("login")))), { tabs: false, back: "/login" });
  });

  function otpStep(r, purpose) {
    const form = onSubmit(h("form.stack", { novalidate: true },
      h("p", t("code_sent", { to: r.sent_to })),
      r.dev_code ? h("div.alert.info", t("demo_code", { code: r.dev_code })) : null,
      field("code", t("enter_code"), { inputmode: "numeric", autocomplete: "one-time-code", maxlength: 6, class: "otp", required: true, value: "" }),
      h("button.btn.block", { type: "submit" }, t("verify"))),
    async (d) => {
      const path = purpose === "verify" ? "/auth/verify" : "/auth/otp/login";
      afterLogin(await api(path, { method: "POST", body: { target: r.target, code: d.code } }));
    });
    shell(t("enter_code"), form, { tabs: false, back: "/login" });
    form.querySelector("input").focus();
  }

  // ---------- home ----------
  route("/", needAuth(() => {
    const main = shell(t("hello", { name: (user.name || "").split(" ")[0] }), null);
    view(main, async () => {
      const [passes, wallet, routes, offers] = await Promise.all([
        api("/passes"), api("/me/wallet"), api("/routes"), api("/me/offers").catch(() => ({ items: [] }))]);
      cache.set({ passes: passes.items, wallet_qr: wallet.qr, user });
      currency = routes.currency;
      refreshUnread();
      return { passes: passes.items, wallet, routes: routes.items, offers: offers.items };
    }, ({ passes, wallet, routes, offers }) => {
      const active = passes.filter((p) => p.status === "active");
      const favs = routes.filter((r) => r.favorite);
      return h("div.stack-lg",
        active.length ? passCard(active[0], () => go(`/pass/${active[0].id}`)) :
          h("div.card", empty("🎫", t("no_active_pass"), t("no_active_pass_text"), h("a.btn", { href: "#/buy" }, t("buy_pass")))),
        h("div.card.row.spread", h("div", h("div.small.muted", t("wallet_balance")), h("div.balance", money(wallet.balance_cents, currency))),
          h("a.btn", { href: "#/wallet/topup" }, t("top_up"))),
        h("section", h("div.row.spread", h("h2", t("favorites")), h("a.small", { href: "#/routes" }, t("routes_title"))),
          favs.length ? h("ul.list", favs.map((r) => routeRow(r))) : h("p.muted.small", t("no_favorites"))),
        offers.length ? h("section", h("h2", t("offers")), h("div.grid", offers.map((o) =>
          h("div.card.flat", h("div.row.spread", h("b", loc(o, "title")), h("span.badge.brand", o.partner)), h("p.small.muted", { style: { margin: "6px 0 0" } }, loc(o, "body")))))) : null);
    }, { skeletonNodes: CB.skeleton(3) });
  }));

  function passCard(p, onclick) {
    return h(`div.pass-card${onclick ? ".card.tap" : ""}`, { style: { "--route": p.route.color }, onclick, role: onclick ? "button" : null, tabindex: onclick ? 0 : null,
      onkeydown: onclick ? (e) => (e.key === "Enter" ? onclick() : null) : null },
    h("div.row.spread", h("span.route-code", p.route.code), statusBadge(p.status)),
    h("h2", loc(p.pass_type, "name")), h("div", loc(p.route, "name")),
    h("div.meta", p.status === "upcoming" ? t("pass_upcoming", { date: date(p.valid_from) }) : t("valid_until", { date: date(p.valid_until) }),
      p.rides_used ? ` · ${t("rides_used", { n: p.rides_used })}` : ""),
    onclick ? h("div", { style: { marginTop: "12px" } }, h("span.btn.sm.secondary", t("show_pass"))) : null);
  }
  function statusBadge(status) {
    const kind = { active: "ok", upcoming: "brand", expired: "", used: "", refunded: "warn", revoked: "err", cancelled: "" }[status];
    return h(`span.badge${kind ? "." + kind : ""}`, { style: { background: "rgba(255,255,255,.9)" } }, t("status_" + status));
  }
  function routeRow(r) {
    return h("li.tap", { onclick: () => go(`/routes/${r.id}`), role: "link", tabindex: 0, onkeydown: (e) => e.key === "Enter" && go(`/routes/${r.id}`) },
      h("span.badge", { style: { background: r.color, color: "#fff", minWidth: "44px", justifyContent: "center" } }, r.code),
      h("div.grow", h("div", { style: { fontWeight: 600 } }, loc(r, "name")),
        h("div.small.muted", r.next_departures && r.next_departures.length ? `${t("next_departures")}: ${r.next_departures.join(" · ")}` : "")),
      h("span.muted", CB.lang === "ar" ? "‹" : "›"));
  }

  // ---------- pass (works offline from cache) ----------
  route("/pass", () => {
    const cached = cache.get();
    if (!user && !(cached.passes || []).length) return go("/login");
    const main = shell(t("pass_title"), null, { actions: h("a.btn.ghost.sm", { href: "#/passes" }, t("all_passes")) });
    const renderPasses = (passes, walletQr) => {
      const active = passes.filter((p) => ["active", "upcoming"].includes(p.status) && p.qr);
      return h("div.stack-lg",
        active.length ? active.map((p) => h("div", passCard(p), p.status === "active" ? liveQrFor(p) : null))
          : h("div.card", empty("🎫", t("no_active_pass"), t("no_active_pass_text"), navigator.onLine ? h("a.btn", { href: "#/buy" }, t("buy_pass")) : null)),
        walletQr ? h("div.card.stack", h("div.card-title", "👛 " + t("pay_per_ride")), h("p.small.muted", t("pay_per_ride_text")),
          active.length ? h("details", h("summary.btn.secondary.sm", t("show_pass")), liveQr(walletQr, walletQr.id)) : liveQr(walletQr, walletQr.id)) : null);
    };
    const liveQrFor = (p) => liveQr(p.qr, p.id);
    if (!navigator.onLine || !user) { mount(main, renderPasses(cached.passes || [], cached.wallet_qr)); return; }
    view(main, async () => {
      const [passes, wallet] = await Promise.all([api("/passes"), api("/me/wallet")]);
      cache.set({ passes: passes.items, wallet_qr: wallet.qr });
      return { passes: passes.items, walletQr: wallet.qr };
    }, ({ passes, walletQr }) => renderPasses(passes, walletQr), { skeletonNodes: CB.skeleton(1) });
  });

  route("/pass/:id", needAuth(({ id }) => {
    const main = shell(t("pass_title"), null, { back: "/pass" });
    view(main, () => api(`/passes/${id}`), (p) => {
      const renew = h("input", { type: "checkbox", checked: p.auto_renew, disabled: p.pass_type.max_rides === 1 || p.status !== "active",
        onchange: async (e) => {
          try { await api(`/passes/${p.id}`, { method: "PATCH", body: { auto_renew: e.target.checked } }); toast(t("saved"), "ok"); }
          catch (err) { e.target.checked = !e.target.checked; toast(err.message, "err"); }
        } });
      return h("div.stack-lg", passCard(p), p.qr && p.status === "active" ? liveQr(p.qr, p.id) : null,
        h("div.card.stack",
          h("label.check", renew, h("div", h("b", t("auto_renew")), h("div.small.muted", t("auto_renew_text")))),
          p.qr ? h("div", h("b", t("lost_phone")), h("p.small.muted", t("lost_phone_text")),
            h("button.btn.secondary.sm", { onclick: async () => {
              if (!(await CB.confirmDialog(t("lost_phone"), t("lost_phone_text"), t("block_old_codes"), "danger"))) return;
              await api(`/passes/${p.id}/rotate-key`, { method: "POST" });
              toast(t("blocked_ok"), "ok");
              CB.start.redraw();
            } }, t("block_old_codes"))) : null));
    });
  }));

  route("/passes", needAuth(() => {
    const main = shell(t("all_passes"), null, { back: "/pass", actions: h("a.btn.sm", { href: "#/buy" }, "+ " + t("buy_pass")) });
    view(main, () => api("/passes"), ({ items }) => h("div.stack-lg",
      items.length ? h("ul.list", items.map((p) => h("li.tap", { onclick: () => go(`/pass/${p.id}`) },
        h("span.badge", { style: { background: p.route.color, color: "#fff" } }, p.route.code),
        h("div.grow", h("div", { style: { fontWeight: 600 } }, loc(p.pass_type, "name")),
          h("div.small.muted", `${date(p.valid_from)} – ${date(p.valid_until)}`)),
        h(`span.badge.${p.status === "active" ? "ok" : ""}`, t("status_" + p.status)))))
        : empty("🎫", t("no_passes"), null, h("a.btn", { href: "#/buy" }, t("buy_pass"))),
      redeemCard()));
  }));

  function redeemCard() {
    return h("div.card", h("div.card-title", t("redeem_code")), onSubmit(h("form.row", { novalidate: true },
      h("div.grow", field("code", t("redeem_code"), { required: true, autocapitalize: "characters", placeholder: "CUFALL26" })),
      h("button.btn", { type: "submit", style: { alignSelf: "center" } }, t("redeem"))),
    async (d) => { const p = await api("/passes/redeem", { method: "POST", body: { code: d.code } }); toast(t("redeem_ok"), "ok"); go(`/pass/${p.id}`); }));
  }

  // ---------- buy ----------
  route("/buy", needAuth(() => buyFlow()));
  route("/buy/:routeId", needAuth(({ routeId }) => buyFlow(Number(routeId))));

  function buyFlow(preselect) {
    const main = shell(t("buy_pass"), null, { back: "/" });
    view(main, async () => {
      const [routes, types, wallet] = await Promise.all([api("/routes"), api("/pass-types"), api("/me/wallet")]);
      return { routes: routes.items, types: types.items, wallet, currency: routes.currency };
    }, ({ routes, types, wallet, currency: cur }) => {
      currency = cur;
      const state = { route_id: preselect || (routes[0] && routes[0].id), pass_type: "monthly", promo_code: "", pay: "wallet",
        start_date: new Date(CB.now()).toISOString().slice(0, 10), idempotency_key: CB.uid() };
      const quoteBox = h("div.card.flat", { "aria-live": "polite" });
      const payBtn = h("button.btn.block", { type: "button" });
      const typeGrid = h("div.choice-grid", { role: "group", "aria-label": t("choose_product") });
      const payGroup = h("div.segmented", { role: "group", "aria-label": t("pay_with") });
      let quote = null;

      function drawTypes() {
        mount(typeGrid, types.map((pt) => h("button.choice", { type: "button", "aria-pressed": String(state.pass_type === pt.code),
          onclick: () => { state.pass_type = pt.code; drawTypes(); refreshQuote(); } },
        h("b", loc(pt, "name")), h("span.small.muted", `${t("valid_days", { n: pt.validity_days })} · ${pt.max_rides === 1 ? t("one_ride") : t("unlimited")}`))));
      }
      function drawPay() {
        mount(payGroup, [["wallet", t("pay_wallet", { amount: money(wallet.balance_cents, currency) })], ["card", t("pay_card")]].map(([k, l]) =>
          h("button", { type: "button", "aria-pressed": String(state.pay === k), onclick: () => { state.pay = k; drawPay(); drawQuote(); } }, l)));
      }
      function drawQuote(err) {
        if (err) { mount(quoteBox, h("div.alert.err", err.message)); payBtn.disabled = true; return; }
        if (!quote) { mount(quoteBox, h("div.skeleton.sk-line"), h("div.skeleton.sk-line")); payBtn.disabled = true; return; }
        const label = (l) => ({ base: t("base_price"), student_discount: t("student_discount"), senior_discount: t("senior_discount") }[l.label] || t("promo", { code: l.code || "" }));
        mount(quoteBox, h("div.stack", quote.lines.map((l) => h("div.row.spread", h("span", label(l)), h("span.num", money(l.amount_cents, currency)))),
          h("hr", { style: { border: 0, borderTop: "1px solid var(--line)", width: "100%" } }),
          h("div.row.spread", h("b", t("total")), h("b.num", { style: { fontSize: "1.3rem" } }, money(quote.total_cents, currency)))));
        const short = state.pay === "wallet" && wallet.balance_cents < quote.total_cents;
        payBtn.disabled = short;
        payBtn.textContent = t("buy_now", { amount: money(quote.total_cents, currency) });
        if (short) mount(quoteBox, quoteBox.firstChild, h("div.alert.warn", { style: { marginTop: "12px" } }, `${t("wallet_balance")}: ${money(wallet.balance_cents, currency)} — `,
          h("a", { href: "#/wallet/topup" }, t("top_up"))));
      }
      let seq = 0;
      async function refreshQuote() {
        const mine = ++seq;
        quote = null; drawQuote();
        const q = new URLSearchParams({ route_id: state.route_id, pass_type: state.pass_type });
        if (state.promo_code) q.set("promo_code", state.promo_code);
        try { const r = await api(`/passes/quote?${q}`); if (mine === seq) { quote = r; drawQuote(); } }
        catch (err) { if (mine === seq) { promoField.classList.toggle("invalid", err.code.startsWith("promo")); promoField.querySelector(".error").textContent = err.code.startsWith("promo") ? err.message : ""; if (err.code.startsWith("promo")) { state.promo_code = ""; refreshQuote(); } else drawQuote(err); } }
      }
      const routeSelect = field("route_id", t("choose_route"), { options: routes.map((r) => [r.id, `${r.code} · ${loc(r, "name")}`]), value: state.route_id,
        onchange: (e) => { state.route_id = Number(e.target.value); refreshQuote(); } });
      const dateField = field("start_date", t("start_date"), { type: "date", value: state.start_date, min: state.start_date,
        onchange: (e) => { state.start_date = e.target.value; } });
      const promoField = field("promo_code", t("promo_code"), { autocapitalize: "characters", placeholder: "WELCOME20" });
      const promoInput = promoField.querySelector("input");
      const applyBtn = h("button.btn.secondary", { type: "button", onclick: () => { state.promo_code = promoInput.value.trim(); promoField.classList.remove("invalid"); promoField.querySelector(".error").textContent = ""; refreshQuote(); } }, t("apply"));

      payBtn.addEventListener("click", async () => {
        payBtn.disabled = true;
        const body = { route_id: state.route_id, pass_type: state.pass_type, start_date: state.start_date, idempotency_key: state.idempotency_key };
        if (state.promo_code) body.promo_code = state.promo_code;
        try {
          if (state.pay === "wallet") {
            const p = await api("/passes", { method: "POST", body });
            toast(t("purchase_ok"), "ok");
            go(`/pass/${p.id}`);
          } else {
            const pay = await api("/payments/checkout", { method: "POST", body: { purpose: "pass", ...body } });
            location.href = pay.checkout_url;
          }
        } catch (err) { toast(err.message, "err"); payBtn.disabled = false; }
      });
      drawTypes(); drawPay(); refreshQuote();
      return h("div.stack-lg", routeSelect, h("div", h("div.small", { style: { fontWeight: 600, marginBottom: "4px" } }, t("choose_product")), typeGrid),
        dateField, h("div.row", { style: { alignItems: "flex-end" } }, h("div.grow", promoField), h("div", { style: { marginBottom: "22px" } }, applyBtn)),
        h("div", h("div.small", { style: { fontWeight: 600, marginBottom: "4px" } }, t("pay_with")), payGroup), quoteBox, payBtn);
    });
  }

  // ---------- payment result (return from checkout) ----------
  route("/payment/:id", needAuth(({ id }) => {
    const main = shell(t("payment_title"), null, { tabs: false, back: "/" });
    let tries = 0;
    async function poll() {
      try {
        const p = await api(`/payments/${id}`);
        if (p.status === "pending" && tries++ < 20) {
          mount(main, h("div.empty", h("div.spinner"), h("h3", t("payment_pending"))));
          return setTimeout(poll, 1500);
        }
        const ok = p.status === "succeeded";
        mount(main, h("div.empty", h("div.art", ok ? "✅" : "❌"), h("h3", ok ? t("payment_ok") : t("payment_failed")),
          h("p", p.description || "", " · ", money(p.amount_cents, p.currency)),
          h("a.btn", { href: p.purpose === "topup" ? "#/wallet" : "#/pass" }, p.purpose === "topup" ? t("go_to_wallet") : t("go_to_pass"))));
      } catch (err) { mount(main, CB.errorState(err, poll)); }
    }
    poll();
  }));

  // ---------- wallet ----------
  route("/wallet", needAuth(() => {
    const main = shell(t("wallet_title"), null);
    view(main, () => api("/me/wallet"), (w) => {
      currency = w.currency;
      return h("div.stack-lg",
        h("div.card.stack", h("div.small.muted", t("wallet_balance")), h("div.balance", money(w.balance_cents, w.currency)),
          h("div.row", h("a.btn.grow", { href: "#/wallet/topup" }, t("top_up")), h("a.btn.secondary.grow", { href: "#/pass" }, t("pay_per_ride")))),
        h("div.row.spread", h("h2", t("transactions")), h("a.small", { href: "#/receipts" }, t("receipts"))),
        w.transactions.length ? h("ul.list", w.transactions.map((tx) => h("li",
          h("span", { "aria-hidden": "true", style: { fontSize: "22px" } }, { topup: "⬆️", ride: "🚌", pass_purchase: "🎫", refund: "↩️" }[tx.kind] || "•"),
          h("div.grow", h("div", t("kind_" + tx.kind)), h("div.small.muted", dateTime(tx.created_at))),
          h(`b.num${tx.amount_cents > 0 ? "" : ".muted"}`, { style: { color: tx.amount_cents > 0 ? "var(--ok)" : null } },
            (tx.amount_cents > 0 ? "+" : "") + money(tx.amount_cents, w.currency)))))
          : empty("👛", t("no_transactions")));
    });
  }));

  route("/wallet/topup", needAuth(() => {
    const amounts = [5000, 10000, 20000, 50000];
    let chosen = 10000;
    const grid = h("div.choice-grid");
    const custom = field("amount", t("topup_custom"), { type: "number", min: 20, max: 5000, step: 1, inputmode: "numeric" });
    function draw() {
      mount(grid, amounts.map((a) => h("button.choice.center", { type: "button", "aria-pressed": String(chosen === a), onclick: () => { chosen = a; custom.querySelector("input").value = ""; draw(); } },
        h("b", money(a, currency)))));
    }
    draw();
    const key = CB.uid();
    const form = onSubmit(h("form.stack-lg", { novalidate: true }, h("div.small", { style: { fontWeight: 600 } }, t("topup_amount")), grid, custom,
      h("button.btn.block", { type: "submit" }, t("topup_go"))), async (d) => {
      const amount = d.amount ? Math.round(Number(d.amount) * 100) : chosen;
      const pay = await api("/payments/checkout", { method: "POST", body: { purpose: "topup", amount_cents: amount, idempotency_key: key } });
      location.href = pay.checkout_url;
    });
    shell(t("top_up"), form, { back: "/wallet" });
  }));

  route("/receipts", needAuth(() => {
    const main = shell(t("receipts"), null, { back: "/wallet" });
    view(main, () => api("/me/receipts"), ({ items, currency: cur }) => items.length
      ? h("ul.list", items.map((r) => h("li.tap", { onclick: () => receiptModal(r, cur) },
        h("div.grow", h("div", r.description), h("div.small.muted.mono", `${r.number} · ${dateTime(r.created_at)}`)), h("b.num", money(r.amount_cents, cur)))))
      : empty("🧾", t("no_receipts")));
  }));

  function receiptModal(r, cur) {
    modal(t("receipt"), h("div.stack",
      h("div.row.spread", h("b", t("app_name")), h("span.mono", r.number)),
      h("div.muted.small", dateTime(r.created_at)),
      h("div", r.description),
      r.discount_cents ? h("div.row.spread", h("span", t("discount")), h("span.num", "−" + money(r.discount_cents, cur))) : null,
      h("div.row.spread", h("b", t("total")), h("b.num", money(r.amount_cents, cur))),
      h("div.small.muted", `${t("pay_with")}: ${r.method}`),
      h("button.btn.secondary.no-print", { onclick: () => window.print() }, t("print"))));
  }

  // ---------- routes ----------
  route("/routes", () => {
    const main = shell(t("routes_title"), null);
    view(main, () => api("/routes"), ({ items }) => {
      const list = h("ul.list");
      const input = h("input.input", { type: "search", placeholder: t("search_routes"), "aria-label": t("search_routes") });
      function draw() {
        const q = input.value.trim().toLowerCase();
        const shown = items.filter((r) => !q || [r.code, r.name_en, r.name_ar, r.origin_en, r.destination_en, r.origin_ar, r.destination_ar].join(" ").toLowerCase().includes(q));
        mount(list, shown.length ? shown.map((r) => routeRow(r)) : h("li", h("span.muted", t("no_routes"))));
      }
      input.addEventListener("input", draw);
      draw();
      return h("div.stack", input, list);
    });
  });

  route("/routes/:id", ({ id }) => {
    const main = shell("", null, { back: "/routes" });
    let liveTimer;
    view(main, () => api(`/routes/${id}`), (r) => {
      main.parentElement.querySelector(".topbar h1").textContent = `${r.code} · ${loc(r, "name")}`;
      const favBtn = user ? h("button.btn.secondary.sm", { "aria-pressed": String(r.favorite), onclick: async () => {
        r.favorite = !r.favorite;
        await api(`/me/favorites/${r.id}`, { method: r.favorite ? "PUT" : "DELETE" });
        favBtn.textContent = r.favorite ? "★ " + t("remove_favorite") : "☆ " + t("add_favorite");
      } }, r.favorite ? "★ " + t("remove_favorite") : "☆ " + t("add_favorite")) : null;
      const liveBox = h("div");
      const total = r.stops[r.stops.length - 1].minutes_from_start || 1;
      async function loadLive() {
        if (!liveBox.isConnected && liveTimer) return clearInterval(liveTimer);
        try {
          const live = await api(`/routes/${r.id}/live`);
          mount(liveBox, h("div.bus-track", { style: { "--route": r.color } }, h("div.rail"),
            live.buses.map((b) => h("span.bus", { title: b.plate, style: { insetInlineStart: `calc(${(b.progress * 100).toFixed(1)}% - 0px)` } }, "🚌"))),
          h("ul.list", live.buses.map((b) => h("li", h("span", "🚌"),
            h("div.grow", h("div.mono.small", b.plate), h("div.small.muted", t("eta", { n: b.eta_minutes, stop: loc(b, "next_stop") }))),
            h(`span.badge.${{ low: "ok", medium: "warn", high: "err" }[b.occupancy]}`, t("occupancy_" + b.occupancy))))));
        } catch { /* keep last positions */ }
      }
      loadLive();
      liveTimer = setInterval(loadLive, 15000);
      return h("div.stack-lg", { style: { "--route": r.color } },
        r.alerts.map((a) => h(`div.alert.${a.severity === "info" ? "info" : "warn"}`, loc(a, "message"))),
        h("div.row.wrap", h("span.badge.brand", t("fare", { amount: money(r.base_fare_cents, currency) })), favBtn,
          user ? h("a.btn.sm", { href: `#/buy/${r.id}` }, t("buy_pass")) : null),
        h("section", h("h2", t("next_departures")), h("div.row.wrap", r.next_departures.map((d) => h("span.badge", { class: "ltr" }, d)))),
        h("section", h("div.row.spread", h("h2", t("live_buses")), h("span.badge", h("span.live-dot"), " ", t("simulated"))), liveBox),
        h("section", h("h2", t("stops")), h("ol.timeline", r.stops.map((s) => h("li", h("span.stop-dot"),
          h("div.grow", h("div", { style: { fontWeight: 600 } }, loc(s, "name")), h("div.small.muted", `+${s.minutes_from_start} min`)))))),
        h("p.xs.muted", `${total} min`));
    });
  });

  // ---------- activity ----------
  route("/trips", needAuth(() => {
    const main = shell(t("trips"), null, { back: "/profile" });
    view(main, () => api("/me/trips"), ({ items }) => items.length
      ? h("ul.list", items.map((r) => h("li", h("span", "🚌"), h("div.grow", h("div", `${r.route_code} · ${loc(r, "route_name")}`),
        h("div.small.muted", `${dateTime(r.scanned_at)} · ${r.bus_plate || ""}`)), r.fare_cents ? h("span.num", money(r.fare_cents, currency)) : null)))
      : empty("🗺️", t("no_trips")));
  }));

  route("/notifications", needAuth(() => {
    const main = shell(t("notifications"), null, { back: "/", actions: h("button.btn.ghost.sm", { onclick: async () => {
      await api("/me/notifications/read", { method: "POST", body: {} }); unread = 0; CB.start.redraw();
    } }, t("mark_all_read")) });
    view(main, () => api("/me/notifications"), ({ items }) => items.length
      ? h("ul.list", items.map((n) => h("li", { style: { background: n.read ? null : "var(--brand-50)" } },
        h("span", { "aria-hidden": "true", style: { fontSize: "20px" } }, { payment: "💳", expiring: "⏰", delay: "🚧", renewal: "🔁", account: "👤", support: "💬" }[n.kind] || "🔔"),
        h("div.grow", h("b", n.title), h("div.small", n.body), h("div.xs.muted", dateTime(n.created_at))))))
      : empty("🔔", t("no_notifications")));
  }));

  // ---------- profile ----------
  route("/profile", needAuth(() => {
    const main = shell(t("profile_title"), null);
    view(main, () => api("/me"), (me) => {
      user = me; store.set("cb_user", me);
      const kindLabel = me.discount_type === "senior" ? t("senior") : t("student");
      const discount = { none: t("discount_none"), pending: t("discount_pending", { kind: kindLabel }),
        approved: t("discount_approved", { kind: kindLabel }), rejected: t("discount_rejected") }[me.discount_status];
      const seg = (current, options, onPick) => h("div.segmented", options.map(([v, l]) =>
        h("button", { type: "button", "aria-pressed": String(current === v), onclick: () => onPick(v) }, l)));
      return h("div.stack-lg",
        h("div.card.row", h("div", { style: { fontSize: "40px" } }, "👤"), h("div.grow", h("b", me.name), h("div.small.muted.ltr", me.email || me.phone))),
        h("ul.list",
          h("li.tap", { onclick: () => go("/trips") }, "🗺️", h("span.grow", t("trips"))),
          h("li.tap", { onclick: () => go("/receipts") }, "🧾", h("span.grow", t("receipts"))),
          h("li.tap", { onclick: () => go("/passes") }, "🎫", h("span.grow", t("all_passes"))),
          h("li.tap", { onclick: () => go("/support") }, "💬", h("span.grow", t("support")))),
        h("div.card.stack", h("div.card-title", t("discount_title")),
          h(`div.alert.${me.discount_status === "approved" ? "ok" : me.discount_status === "pending" ? "warn" : "info"}`, discount),
          me.discount_status !== "approved" && me.discount_status !== "pending" ? uploadForm() : null),
        h("div.card.stack", h("div.small", { style: { fontWeight: 600 } }, t("language")),
          seg(CB.lang, [["en", "English"], ["ar", "العربية"]], async (v) => {
            CB.setLang(v); try { await api("/me", { method: "PATCH", body: { language: v } }); } catch { /* offline */ } CB.start.redraw();
          }),
          h("div.small", { style: { fontWeight: 600 } }, t("theme")),
          seg(store.get("cb_theme", "system"), [["system", t("theme_system")], ["light", t("theme_light")], ["dark", t("theme_dark")]],
            (v) => { CB.setTheme(v); CB.start.redraw(); })),
        h("details.card", h("summary", { style: { fontWeight: 700, cursor: "pointer" } }, "🔒 " + t("security")),
          h("div.stack", { style: { marginTop: "12px" } }, onSubmit(h("form.stack", { novalidate: true },
            field("current_password", t("current_password"), { type: "password", autocomplete: "current-password" }),
            field("new_password", t("new_password"), { type: "password", autocomplete: "new-password", minlength: 8, hint: t("password_hint") }),
            h("button.btn.secondary", { type: "submit" }, t("change_password"))), async (d) => {
            await api("/me/password", { method: "POST", body: d }); toast(t("saved"), "ok");
          }),
          h("button.btn.secondary", { onclick: async () => {
            if (!(await CB.confirmDialog(t("lost_phone"), t("lost_phone_text"), t("block_old_codes"), "danger"))) return;
            await api("/me/wallet/rotate-key", { method: "POST" });
            const passes = await api("/passes");
            await Promise.all(passes.items.filter((p) => p.qr).map((p) => api(`/passes/${p.id}/rotate-key`, { method: "POST" })));
            toast(t("blocked_ok"), "ok");
          } }, t("block_old_codes")))),
        h("button.btn.danger.block", { onclick: async () => { await CB.logout(); user = null; go("/login"); } }, t("logout")));
    });
  }));

  function uploadForm() {
    const form = h("form.stack", { novalidate: true },
      field("kind", t("doc_kind"), { options: [["student", t("student")], ["senior", t("senior")]] }),
      field("file", t("file"), { type: "file", accept: "image/jpeg,image/png,application/pdf", required: true }),
      h("button.btn.secondary", { type: "submit" }, t("upload_doc")));
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const fd = new FormData(form);
      const f = fd.get("file");
      if (!f || !f.size) return CB.showErrors(form, { details: { field: "file" }, message: t("required") });
      if (f.size > 5 * 1024 * 1024) return CB.showErrors(form, { details: { field: "file" }, message: t("file") });
      try { await api("/me/verification", { method: "POST", form: fd }); toast(t("upload_ok"), "ok"); CB.start.redraw(); }
      catch (err) { CB.showErrors(form, err); }
    });
    return form;
  }

  route("/support", needAuth(() => {
    const form = onSubmit(h("form.stack", { novalidate: true },
      field("category", t("support_category"), { options: ["payment", "pass", "app", "bus", "other"].map((c) => [c, t("cat_" + c)]) }),
      field("message", t("support_message"), { type: "textarea", required: true, minlength: 10, maxlength: 2000 }),
      h("button.btn.block", { type: "submit" }, t("send"))), async (d) => {
      await api("/me/support", { method: "POST", body: d });
      toast(t("support_sent"), "ok");
      go("/profile");
    });
    shell(t("support"), form, { back: "/profile" });
  }));

  // ---------- boot ----------
  CB.on("logged-out", () => { user = null; if (navigator.onLine) go("/login"); });
  (async function boot() {
    if (user && navigator.onLine) {
      const restored = await CB.restoreSession();
      if (!restored) user = null;
      else user = restored;
    }
    if (!user && !location.hash.match(/^#\/(login|register|welcome|routes|pass)/)) {
      location.hash = store.get("cb_onboarded") ? "/login" : "/welcome";
    }
    CB.start();
    if ("serviceWorker" in navigator) navigator.serviceWorker.register("/app/sw.js", { scope: "/app" }).catch(() => {});
  })();
})();
