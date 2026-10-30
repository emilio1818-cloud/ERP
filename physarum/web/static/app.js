// Physarum – a little vanilla JS. No build step, no framework, works offline.
(function () {
  "use strict";
  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => Array.from(el.querySelectorAll(s));

  function toast(msg, undo) {
    $$(".toast").forEach((x) => x.remove());
    const t = document.createElement("div");
    t.className = "toast";
    t.setAttribute("role", "status");
    const span = document.createElement("span");
    span.textContent = msg;
    t.appendChild(span);
    if (undo) {
      const b = document.createElement("button");
      b.className = "small";
      b.textContent = "Rückgängig";
      b.addEventListener("click", () => {
        b.disabled = true;
        post(undo.url, undo.body || {}).then(handle(null));
      });
      t.appendChild(b);
    }
    document.body.appendChild(t);
    setTimeout(() => t.remove(), undo ? 9000 : 3600);
  }
  window.physarumToast = toast;

  function post(url, body) {
    return fetch(url, { method: "POST", body: new URLSearchParams(body), headers: { "X-Requested-With": "fetch" } })
      .then((r) => r.json());
  }
  // what the server answered: an error, a job, another page, a toast (with undo), a reload
  function handle(btn) {
    return (j) => {
      if (j.error) { toast(j.error); if (btn) btn.disabled = false; return; }
      if (j.job) { location.href = `/wachsen/${j.job}`; return; }
      if (j.next) { if (j.toast) toast(j.toast); setTimeout(() => (location.href = j.next), 700); return; }
      if (j.reload) {
        if (j.toast) sessionStorage.setItem("physarum-toast", JSON.stringify({ msg: j.toast, undo: j.undo || null }));
        location.reload();
        return;
      }
      if (j.toast) toast(j.toast, j.undo);
      const gone = btn && btn.closest("[data-remove]");
      if (gone) { gone.style.opacity = ".4"; setTimeout(() => gone.remove(), 300); }
    };
  }
  try {
    const pending = sessionStorage.getItem("physarum-toast");
    if (pending) { sessionStorage.removeItem("physarum-toast"); const p = JSON.parse(pending); toast(p.msg, p.undo); }
  } catch (e) { /* storage may be unavailable */ }

  // mobile navigation
  const menu = $("#menu-toggle");
  if (menu) menu.addEventListener("click", () => $(".side").classList.toggle("open"));

  // drop zones -----------------------------------------------------------------------------
  $$(".drop").forEach((zone) => {
    const input = $("input[type=file]", zone);
    const msg = $(".drop-msg", zone), said = msg && msg.textContent;
    const failed = (text) => { zone.classList.remove("over"); msg && (msg.textContent = said); toast(text); };
    const send = (files) => {
      const list = [...(files || [])].map((f) => (Array.isArray(f) ? f : [f, f.webkitRelativePath || f.name]));
      if (!list.length) return;
      const fd = new FormData();
      for (const [f, name] of list) fd.append("files", f, name);
      zone.classList.add("over");
      msg && (msg.textContent = `${list.length} Datei${list.length === 1 ? "" : "en"} werden übertragen …`);
      fetch("/einwerfen", { method: "POST", body: fd }).then((r) => r.json()).then((j) => {
        if (j.job) location.href = `/wachsen/${j.job}`;
        else failed(j.error || "Fehler beim Hochladen");
      }).catch(() => failed("Fehler beim Hochladen"));
    };
    // a dropped folder arrives as one unreadable "file": walk its entries, as "Ordner wählen" would give them
    const walk = async (entry, out) => {
      if (entry && entry.isFile) {
        out.push([await new Promise((ok, no) => entry.file(ok, no)), entry.fullPath.replace(/^\//, "")]);
      } else if (entry && entry.isDirectory) {
        const reader = entry.createReader();
        for (let batch; (batch = await new Promise((ok, no) => reader.readEntries(ok, no))).length;) {
          for (const e of batch) await walk(e, out);
        }
      }
      return out;
    };
    ["dragenter", "dragover"].forEach((e) => zone.addEventListener(e, (ev) => { ev.preventDefault(); zone.classList.add("over"); }));
    ["dragleave", "drop"].forEach((e) => zone.addEventListener(e, (ev) => { ev.preventDefault(); zone.classList.remove("over"); }));
    zone.addEventListener("drop", (ev) => {
      const entries = [...(ev.dataTransfer.items || [])].map((i) => i.webkitGetAsEntry && i.webkitGetAsEntry());
      if (!entries.some((e) => e && e.isDirectory)) return send(ev.dataTransfer.files);
      entries.reduce((p, e) => p.then((out) => walk(e, out)), Promise.resolve([])).then(send)
        .catch(() => failed("Der Ordner ließ sich nicht lesen – bitte „Ordner wählen“ oder ein ZIP einwerfen"));
    });
    $$("[data-pick]", zone).forEach((b) => b.addEventListener("click", (ev) => {
      ev.preventDefault();
      const which = b.dataset.pick === "folder" ? $("input[data-folder]", zone) : input;
      which && which.click();
    }));
    $$("input[type=file]", zone).forEach((inp) => inp.addEventListener("change", () => send(inp.files)));
  });

  // growth progress ----------------------------------------------------------------------------
  const prog = $("#job");
  if (prog) {
    const id = prog.dataset.job;
    const bar = $(".progress i", prog), log = $(".log", prog), msg = $("#job-msg");
    const tick = () => fetch(`/api/job/${id}`).then((r) => r.json()).then((j) => {
      bar.style.width = `${Math.round((j.progress || 0) * 100)}%`;
      log.textContent = (j.log || []).join("\n");
      log.scrollTop = log.scrollHeight;
      if (j.status === "done") { msg.textContent = "Fertig gewachsen."; setTimeout(() => (location.href = j.next || "/"), 900); return; }
      if (j.status === "error") { msg.textContent = "Fehler: " + (j.error || ""); return; }
      setTimeout(tick, 600);
    });
    tick();
  }

  // live search in lists -----------------------------------------------------------------------------
  const live = $("input[data-live]");
  if (live) {
    let timer = null;
    live.addEventListener("input", () => {
      clearTimeout(timer);
      timer = setTimeout(() => {
        const url = new URL(location.href);
        url.searchParams.set("q", live.value);
        url.searchParams.delete("seite");
        fetch(url.toString() + "&teil=1").then((r) => r.text()).then((html) => {
          $("#list-body").innerHTML = html;
          history.replaceState(null, "", url.toString());
        });
      }, 220);
    });
  }
  $$("tr[data-href]").forEach((tr) => tr.addEventListener("click", (ev) => {
    if (ev.target.closest("a,button,input,select")) return;
    location.href = tr.dataset.href;
  }));
  document.addEventListener("click", (ev) => {
    const tr = ev.target.closest("tr[data-href]");
    if (tr && !ev.target.closest("a,button,input,select") && !tr.dataset.bound) location.href = tr.dataset.href;
  });

  // reference pickers (autocomplete via datalist) ----------------------------------------------------
  function bindRef(inp) {
    if (inp.dataset.bound) return;
    inp.dataset.bound = "1";
    const list = document.getElementById(inp.getAttribute("list"));
    const hidden = inp.parentElement.querySelector("input[type=hidden]");
    let timer = null;
    inp.addEventListener("input", () => {
      if (hidden) hidden.value = "";
      const opt = list && Array.from(list.options).find((o) => o.value === inp.value);
      if (opt && hidden) { hidden.value = opt.dataset.id; inp.dispatchEvent(new CustomEvent("picked", { bubbles: true, detail: opt.dataset.id })); return; }
      clearTimeout(timer);
      timer = setTimeout(() => {
        fetch(`/api/suche?typen=${encodeURIComponent(inp.dataset.types)}&q=${encodeURIComponent(inp.value)}`)
          .then((r) => r.json()).then((items) => {
            if (!list) return;
            list.innerHTML = "";
            for (const it of items) {
              const o = document.createElement("option");
              o.value = it.title; o.dataset.id = it.id; o.label = it.sub || "";
              list.appendChild(o);
            }
          });
      }, 150);
    });
  }
  $$("input[data-ref]").forEach(bindRef);
  document.addEventListener("change", (ev) => {
    const inp = ev.target.closest("input[data-ref]");
    if (!inp) return;
    const list = document.getElementById(inp.getAttribute("list"));
    const hidden = inp.parentElement.querySelector("input[type=hidden]");
    if (!list || !hidden || hidden.value) return;
    const opts = Array.from(list.options).filter((o) => o.value.toLowerCase() === inp.value.trim().toLowerCase());
    if (opts.length === 1) { hidden.value = opts[0].dataset.id; inp.dispatchEvent(new CustomEvent("picked", { bubbles: true, detail: opts[0].dataset.id })); }
  });

  // formulas in forms ------------------------------------------------------------------------------------
  function num(v) {
    if (v === null || v === undefined || v === "") return null;
    let s = String(v).trim().replace(/\s|€/g, "");
    if (/^-?\d{1,3}(\.\d{3})+(,\d+)?$/.test(s) || /^-?\d+,\d+$/.test(s)) s = s.replace(/\./g, "").replace(",", ".");
    const x = parseFloat(s);
    return isNaN(x) ? null : x;
  }
  const fmt = (x) => (Math.round(x * 100) / 100).toFixed(2).replace(".", ",");
  function runFormulas(scope, formulas, lookups) {
    const val = (aid) => { const el = scope.querySelector(`[data-attr="${aid}"]`); return el ? el.value : null; };
    const byHand = (aid) => { const el = scope.querySelector(`[data-attr="${aid}"]`); return !!(el && el.dataset.touched); };
    let args = [];
    const set = (aid, v) => {
      const el = scope.querySelector(`[data-attr="${aid}"]`);
      if (!el || el.dataset.touched) return;
      // a value the page brought along (from the order, the last time) stays until one of its inputs is changed
      if (el.dataset.prefilled && !args.some(byHand)) return;
      el.value = v;
      el.closest(".field, td") && el.closest(".field, td").classList.add("computed");
    };
    for (let pass = 0; pass < 3; pass++) {
      for (const f of formulas) {
        const a = f.args || [];
        args = a.concat(f.ref ? [f.ref] : []);
        if (["mul", "add", "sub"].includes(f.op)) {
          const x = num(val(a[0])), y = num(val(a[1]));
          if (x === null || y === null) continue;
          set(f.attr, fmt(f.op === "mul" ? x * y : f.op === "add" ? x + y : x - y));
        } else if (f.op === "scale") {
          const x = num(val(a[0]));
          if (x !== null) set(f.attr, fmt(x * f.k));
        } else if (f.op === "date_add" || f.op === "date_default") {
          const d = val(a[0]);
          if (d) { const dt = new Date(d); dt.setDate(dt.getDate() + f.days); set(f.attr, dt.toISOString().slice(0, 10)); }
        } else if (f.op === "date_add_ref") {
          const d = val(a[0]);
          const refEl = scope.querySelector(`[data-attr="${f.ref}"]`);
          const days = refEl && lookups && lookups[refEl.value] && lookups[refEl.value][f.ref_attr];
          if (d && days !== undefined && days !== null) { const dt = new Date(d); dt.setDate(dt.getDate() + Number(days)); set(f.attr, dt.toISOString().slice(0, 10)); }
        }
      }
    }
  }
  $$("form[data-formulas]").forEach((form) => {
    $$("[data-attr]", form).forEach((el) => { if (el.value && el.type !== "hidden") el.dataset.prefilled = "1"; });
    const formulas = JSON.parse(form.dataset.formulas || "[]");
    const lineFormulas = JSON.parse(form.dataset.lineFormulas || "[]");
    const lookups = {};
    const total = form.dataset.total;
    const update = () => {
      runFormulas(form.querySelector(".head-fields") || form, formulas, lookups);
      let sum = 0, any = false;
      $$("tr.line", form).forEach((tr) => {
        runFormulas(tr, lineFormulas, lookups);
        const t = tr.querySelector(`[data-attr="${form.dataset.lineTotal}"]`);
        const x = t ? num(t.value) : null;
        if (x !== null) { sum += x; any = true; }
      });
      const out = $("#lines-sum", form);
      if (out) out.textContent = any ? fmt(sum) + " €" : "–";
    };
    form.addEventListener("input", (ev) => {
      if (ev.target.matches("[data-attr]") && ev.isTrusted) ev.target.dataset.touched = ev.target.value ? "1" : "";
      update();
    });
    form.addEventListener("picked", (ev) => {
      // a reference was chosen: fetch what the record knows (payment terms, prices)
      const id = ev.detail;
      const hidden = ev.target.parentElement.querySelector("input[type=hidden]");
      if (!ev.target.closest("tr.line") && hidden && form.dataset.type) {
        fetch(`/api/ableiten?typ=${encodeURIComponent(form.dataset.type)}&attr=${encodeURIComponent(hidden.dataset.attr)}&id=${id}`)
          .then((r) => r.json()).then((j) => {
            for (const [aid, v] of Object.entries(j.values || {})) {
              const el = form.querySelector(`.head-fields [data-attr="${aid}"]`);
              if (!el || el.dataset.touched) continue;
              if (v && typeof v === "object") {
                el.value = v.id;
                const t = el.parentElement.querySelector(`[data-attr="${aid}_t"]`);
                if (t) t.value = v.title;
              } else { el.value = v; }
              const box = el.closest(".field"); if (box) box.classList.add("computed");
            }
            const why = $("#derive-why");
            if (why && (j.why || []).length) { why.textContent = j.why.join(" · "); why.style.display = ""; }
            update();
          });
      }
      fetch(`/api/datensatz/${id}`).then((r) => r.json()).then((j) => {
        lookups[hidden ? hidden.value : id] = j.data;
        const tr = ev.target.closest("tr.line");
        if (tr && j.prices) {
          for (const [aid, v] of Object.entries(j.prices)) {
            const el = tr.querySelector(`[data-attr="${aid}"]`);
            if (el && !el.dataset.touched) el.value = fmt(v);
          }
        }
        update();
      });
    });
    const add = $("#add-line", form);
    if (add) add.addEventListener("click", (ev) => {
      ev.preventDefault();
      const tpl = $("#line-template", form);
      const tr = tpl.content.firstElementChild.cloneNode(true);
      const n = Date.now() % 100000 + $$("tr.line", form).length;
      $$("[name]", tr).forEach((el) => (el.name = el.name.replace("__N__", n)));
      $$("[list]", tr).forEach((el) => {
        const old = el.getAttribute("list"), id = old.replace("__N__", n);
        const dl = Array.from(tr.querySelectorAll("datalist")).find((d) => d.id === old);
        if (dl) dl.id = id;
        el.setAttribute("list", id);
      });
      $("tbody.lines", form).appendChild(tr);
      $$("input[data-ref]", tr).forEach(bindRef);
      update();
    });
    form.addEventListener("click", (ev) => {
      if (ev.target.matches(".del-line")) { ev.preventDefault(); ev.target.closest("tr").remove(); update(); }
    });
    const again = $("#like-last", form);
    if (again) again.addEventListener("click", (ev) => {
      ev.preventDefault();
      const party = form.querySelector(`[name="${again.dataset.party}"]`);
      if (!party || !party.value) { toast("Bitte zuerst " + again.dataset.partyName + " wählen"); return; }
      fetch(`/api/wie-letztes-mal?typ=${again.dataset.type}&partei=${party.value}`).then((r) => r.json()).then((j) => {
        if (!j.lines || !j.lines.length) { toast("Kein früherer Vorgang gefunden"); return; }
        $$("tr.line", form).forEach((tr) => tr.remove());
        for (const ln of j.lines) {
          add.click();
          const tr = $$("tr.line", form).pop();
          for (const [aid, v] of Object.entries(ln)) {
            if (v && typeof v === "object") {
              const t = tr.querySelector(`[data-attr="${aid}_t"]`), h = tr.querySelector(`[data-attr="${aid}"]`);
              if (t) t.value = v.title;
              if (h) h.value = v.id;
              continue;
            }
            const el = tr.querySelector(`[data-attr="${aid}"]`);
            if (el) el.value = typeof v === "number" ? (Number.isInteger(v) ? String(v) : fmt(v)) : v;
          }
        }
        toast(`${j.lines.length} Position(en) wie bei ${j.from} übernommen`);
        update();
      });
    });
    update();
  });

  // inline edit on records ----------------------------------------------------------------------------
  const editBtn = $("#edit-toggle");
  if (editBtn) editBtn.addEventListener("click", (ev) => {
    ev.preventDefault();
    $$(".view-mode").forEach((e) => e.classList.toggle("hide"));
    $$(".edit-mode").forEach((e) => e.classList.toggle("hide"));
  });

  // answers, actions (POST then reload or remove) ------------------------------------------------------------
  document.addEventListener("click", (ev) => {
    const b = ev.target.closest("[data-post]");
    if (!b || b.disabled) return;
    ev.preventDefault();
    if (b.dataset.confirm && !confirm(b.dataset.confirm)) return;
    const body = JSON.parse(b.dataset.body || "{}");
    if (b.dataset.prompt) {
      const answer = prompt(b.dataset.prompt);
      if (!answer || !answer.trim()) return;
      body[b.dataset.promptField || "reason"] = answer.trim();
    }
    b.disabled = true;
    post(b.dataset.post, body).then(handle(b)).catch(() => { toast("Das hat nicht geklappt."); b.disabled = false; });
  });
  // the lines of an invoice draft
  const posForm = $("form.positions");
  if (posForm) posForm.addEventListener("click", (ev) => {
    if (ev.target.matches(".del-pos")) {
      ev.preventDefault();
      if ($$("tr.line", posForm).length > 1) ev.target.closest("tr").remove();
      else $$("input", ev.target.closest("tr")).forEach((el) => (el.value = ""));
    }
    if (ev.target.matches("#add-pos")) {
      ev.preventDefault();
      const rows = $$("tr.line", posForm);
      const last = rows[rows.length - 1];
      const n = 1 + Math.max(...rows.map((tr) => Number((tr.querySelector("input").name.match(/^pos_(\d+)_/) || [0, 0])[1])));
      const tr = last.cloneNode(true);
      $$("input", tr).forEach((el) => {
        const field = el.name.replace(/^pos_\d+_/, "");
        el.name = `pos_${n}_${field}`;
        el.value = field === "qty" ? "1" : field === "rate" ? last.querySelector('[name$="_rate"]').value : "";
      });
      $("tbody.pos-rows", posForm).appendChild(tr);
      tr.querySelector("input").focus();
    }
  });
  // a step with its date ("✓ bezahlt" on a chosen day), undoable
  document.addEventListener("submit", (ev) => {
    const f = ev.target.closest("form[data-step]");
    if (!f) return;
    ev.preventDefault();
    const btn = f.querySelector("button");
    if (btn) btn.disabled = true;
    post(f.dataset.step, Object.fromEntries(new FormData(f))).then(handle(btn))
      .catch(() => { toast("Das hat nicht geklappt."); if (btn) btn.disabled = false; });
  });
  const prov = $("#prov-toggle");
  if (prov) prov.addEventListener("click", () => {
    const show = $$(".fact .prov").some((x) => x.classList.contains("hide"));
    $$(".fact .prov").forEach((x) => x.classList.toggle("hide", !show));
    prov.textContent = show ? "Herkunft ausblenden" : "Herkunft zeigen";
  });
  // the name for the protocol is kept as soon as one leaves the field, not only with Enter
  // no inline handlers (the page forbids inline script): print, reload, drop forms that never submit
  $$("[data-print]").forEach((b) => b.addEventListener("click", () => window.print()));
  $$("[data-reload]").forEach((b) => b.addEventListener("click", (ev) => { ev.preventDefault(); location.reload(); }));
  $$("form.drop").forEach((f) => f.addEventListener("submit", (ev) => ev.preventDefault()));
  if (document.body && document.body.hasAttribute("data-autoprint")) window.addEventListener("load", () => window.print());

  // "… und 12 weitere zeigen": the rest is already on the page, only folded away
  $$("[data-more]").forEach((b) => b.addEventListener("click", (ev) => {
    ev.preventDefault();
    const box = b.closest("[data-more-box]") || document;
    $$(b.dataset.more, box).forEach((x) => { if (x.closest("[data-more-box]") === box) x.hidden = false; });
    b.remove();
  }));

  const me = $("#me");
  if (me) me.addEventListener("change", () => {
    const body = new URLSearchParams({ name: me.value });
    fetch("/ich", { method: "POST", body, headers: { "x-requested-with": "fetch" } })
      .then(() => toast(me.value ? "Gemerkt: " + me.value : "Name entfernt"))
      .catch(() => toast("Das hat nicht geklappt."));
  });
  $$("details[data-remember]").forEach((d) => {
    try {
      const k = "open:" + d.dataset.remember;
      if (localStorage.getItem(k) === "1") d.open = true;
      d.addEventListener("toggle", () => localStorage.setItem(k, d.open ? "1" : "0"));
    } catch (e) { /* storage may be unavailable */ }
  });
})();
