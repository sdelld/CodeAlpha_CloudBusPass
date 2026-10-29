/* Validator (conductor) app: pick bus → scan with camera or type code → instant VALID / EXPIRED / FRAUD.
   Offline: scans are queued on the device with their scan time and synced when the connection returns. */
(function () {
  "use strict";
  const { h, t, api, store, toast, mount, field, onSubmit, money, dateTime } = CB;
  const root = document.getElementById("app");
  const QUEUE = "cb_validator_queue";
  let busId = store.get("cb_validator_bus");
  let buses = store.get("cb_validator_buses", []);
  let stream = null;
  let scanning = false;
  let lastToken = null;

  const queue = () => store.get(QUEUE, []);
  const setQueue = (q) => store.set(QUEUE, q);

  function frame(content, { title = t("v_title") } = {}) {
    stopCamera();
    const bus = buses.find((b) => b.id === busId);
    const pending = queue().length;
    const app = h("div.app", { style: { paddingBottom: "24px" } },
      h("header.topbar", h("h1", "🎫 " + title),
        bus ? h("button.btn.secondary.sm", { onclick: chooseBus }, `🚌 ${bus.route_code} · ${bus.plate}`) : null,
        h("button.icon-btn", { "aria-label": "Language", onclick: () => { CB.setLang(CB.lang === "ar" ? "en" : "ar"); render(); } }, CB.lang === "ar" ? "EN" : "ع")),
      h("main.screen.stack-lg", { id: "main" },
        pending ? h("div.alert.warn.row.spread", t("v_pending", { n: pending }),
          h("button.btn.sm", { onclick: sync, disabled: !navigator.onLine }, t("v_sync_now"))) : null,
        content));
    mount(root, app);
    CB.offlineBar(app);
  }

  // ---------- auth ----------
  function loginScreen() {
    frame(onSubmit(h("form.stack", { novalidate: true },
      field("identifier", t("email_or_phone"), { autocomplete: "username", required: true }),
      field("password", t("password"), { type: "password", autocomplete: "current-password", required: true }),
      h("button.btn.block", { type: "submit" }, t("login"))), async (d) => {
      const tokens = await api("/auth/login", { method: "POST", body: d });
      if (!["validator", "admin"].includes(tokens.user.role)) throw new CB.ApiError(403, { error: { message: t("a_only_admins") } });
      CB.setSession(tokens);
      await loadBuses();
      render();
    }), { title: t("login") });
  }

  async function loadBuses() {
    buses = (await api("/validator/buses")).items;
    store.set("cb_validator_buses", buses);
  }

  function chooseBus() {
    frame(h("div.stack", h("h2", t("v_select_bus")),
      buses.length ? h("ul.list", buses.map((b) => h("li.tap", { onclick: () => { busId = b.id; store.set("cb_validator_bus", b.id); render(); } },
        h("span.badge.brand", b.route_code), h("span.grow.mono", b.plate), b.id === busId ? "✓" : null)))
        : CB.empty("🚌", t("loading"))));
  }

  // ---------- scanning ----------
  function scanScreen() {
    const video = h("video", { playsinline: true, muted: true, "aria-label": "Camera" });
    const cam = h("div.camera", video, h("div.frame"));
    const camBox = h("div.stack", h("button.btn.block", { onclick: () => startCamera(video, cam) }, "📷 " + t("v_start_camera")));
    const manual = onSubmit(h("form.row", { novalidate: true },
      h("div.grow", field("token", t("v_manual"), { autocomplete: "off", required: true, placeholder: "CB1.P.…", dir: "ltr" })),
      h("button.btn", { type: "submit", style: { alignSelf: "center" } }, t("v_validate"))), async (d) => { await submit(d.token.trim()); });
    const recentBox = h("div");
    frame(h("div.stack-lg", camBox, manual, h("h2", t("v_recent")), recentBox));
    loadRecent(recentBox);
    if (store.get("cb_validator_camera")) startCamera(video, cam, camBox);
    camBox.dataset.ready = "1";
    camBox._video = video; camBox._cam = cam;
  }

  async function startCamera(video, cam, box) {
    const camBox = box || document.querySelector('[data-ready="1"]');
    try {
      stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment" }, audio: false });
      video.srcObject = stream;
      await video.play();
      mount(camBox, cam);
      store.set("cb_validator_camera", true);
      scanning = true;
      scanLoop(video);
    } catch {
      store.set("cb_validator_camera", false);
      toast(t("v_camera_denied"), "err");
    }
  }
  function stopCamera() {
    scanning = false;
    if (stream) { stream.getTracks().forEach((tr) => tr.stop()); stream = null; }
  }
  function scanLoop(video) {
    const canvas = document.createElement("canvas");
    const ctx = canvas.getContext("2d", { willReadFrequently: true });
    const step = () => {
      if (!scanning || !video.isConnected) return;
      if (video.readyState === video.HAVE_ENOUGH_DATA) {
        canvas.width = video.videoWidth; canvas.height = video.videoHeight;
        ctx.drawImage(video, 0, 0);
        const img = ctx.getImageData(0, 0, canvas.width, canvas.height);
        const code = window.jsQR && jsQR(img.data, img.width, img.height, { inversionAttempts: "dontInvert" });
        if (code && code.data && code.data !== lastToken) {
          lastToken = code.data;
          if (navigator.vibrate) navigator.vibrate(60);
          submit(code.data);
          return;
        }
      }
      requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  }

  async function submit(token) {
    const scan = { token, bus_id: busId, client_scan_id: CB.uid().slice(0, 32), scanned_at: new Date(CB.now()).toISOString() };
    if (!navigator.onLine) return queueScan(scan);
    try {
      showResult(await api("/validator/scan", { method: "POST", body: scan }));
    } catch (err) {
      if (err.code === "network") return queueScan(scan);
      if (err.status === 401) return loginScreen();
      showResult({ result: "invalid", valid: false, reason: err.message });
    }
  }
  function queueScan(scan) {
    setQueue([...queue(), scan]);
    showResult({ result: "queued", valid: null, reason: t("v_queued_text") });
  }

  function showResult(r) {
    const label = t("v_" + r.result);
    const icon = { valid: "✔", duplicate: "✔", expired: "⏱", fraud: "✖", invalid: "✖", insufficient_funds: "✖", queued: "☁" }[r.result] || "?";
    frame(h("div.stack-lg",
      h(`div.scan-result.${r.result}`, { role: "alert" },
        h("div", { style: { fontSize: "64px", lineHeight: 1 } }, icon), h("div.big", label),
        r.passenger ? h("div", { style: { fontSize: "1.4rem", fontWeight: 700, marginTop: "8px" } }, r.passenger) : null,
        r.pass ? h("div", `${CB.lang === "ar" ? r.pass.type_ar : r.pass.type_en} · ${r.pass.route} · ${t("valid_until", { date: CB.date(r.pass.valid_until) })}`) : null,
        r.fare_cents ? h("div", t("v_fare_paid", { amount: money(r.fare_cents) })) : null,
        r.discount_type && r.discount_type !== "none" ? h("div.badge", { style: { marginTop: "8px", background: "rgba(255,255,255,.25)", color: "#fff" } },
          r.discount_type === "student" ? "🎓 " + t("student") : "👴 " + t("senior")) : null,
        r.reason ? h("div", { style: { marginTop: "10px", opacity: .95 } }, r.reason) : null),
      h("button.btn.block", { onclick: () => { lastToken = null; render(); }, autofocus: true }, t("v_scan_next"))));
    setTimeout(() => { const b = root.querySelector(".btn.block"); if (b) b.focus(); }, 50);
  }

  async function loadRecent(box) {
    try {
      const { items } = await api("/validator/recent");
      mount(box, items.length ? h("ul.list", items.slice(0, 10).map((r) => h("li",
        h(`span.badge.${["valid", "duplicate"].includes(r.result) ? "ok" : r.result === "expired" ? "warn" : "err"}`, t("v_" + r.result)),
        h("div.grow.small", r.reason || ""), h("span.xs.muted", dateTime(r.scanned_at)))))
        : h("p.muted.small", "—"));
    } catch { mount(box, h("p.muted.small", t("error_network"))); }
  }

  async function sync() {
    const q = queue();
    if (!q.length || !navigator.onLine) return;
    try {
      const { results } = await api("/validator/sync", { method: "POST", body: { scans: q.slice(0, 200) } });
      const done = new Set(results.map((r) => r.client_scan_id));
      setQueue(queue().filter((s) => !done.has(s.client_scan_id)));
      const bad = results.filter((r) => !r.valid).length;
      toast(t("v_synced", { n: results.length }) + (bad ? ` · ${bad} ✖` : ""), bad ? "err" : "ok");
      render();
    } catch (err) { if (err.status === 401) loginScreen(); }
  }

  function render() {
    if (!busId || !buses.find((b) => b.id === busId)) return chooseBus();
    scanScreen();
  }

  CB.on("online", sync);
  CB.on("logged-out", loginScreen);
  (async function boot() {
    if (!navigator.onLine && buses.length) return render();
    const me = await CB.restoreSession();
    if (!me || !["validator", "admin"].includes(me.role)) return loginScreen();
    try { await loadBuses(); } catch { /* use cached list */ }
    render();
    sync();
  })();
})();
