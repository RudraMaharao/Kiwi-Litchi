/* Bahi: small, dependency-free behaviour for the review screen and uploads. */
(function () {
  "use strict";
  const token = document.querySelector('meta[name="bahi-token"]').content;
  const $ = (s, el) => (el || document).querySelector(s);
  const $$ = (s, el) => Array.from((el || document).querySelectorAll(s));
  const uiCopy = (s) => String(s == null ? '' : s).replace(/\.(?=\s|$)/g, '');
  // Format generated help/flash text without changing transaction records.
  $$(".flash, .hint").forEach((el) => {
    const text = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
    while (text.nextNode()) text.currentNode.nodeValue = uiCopy(text.currentNode.nodeValue);
  });
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  async function postJSON(url, data) {
    const r = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Bahi-Token": token },
      body: JSON.stringify(data || {}),
    });
    const body = await r.json().catch(() => ({ error: "Bahi didn't answer · Is it still running?" }));
    if (!r.ok || body.error) throw new Error(body.error || "Something went wrong");
    return body;
  }

  async function pollJob(id, onProgress) {
    for (;;) {
      const r = await fetch("/jobs/" + id);
      const j = await r.json().catch(() => ({ status: "error", error: "Lost contact with Bahi" }));
      if (["done", "error", "missing"].includes(j.status)) return j;
      if (onProgress) onProgress(j.progress);
      await sleep(600);
    }
  }

  function progressHTML(p, fallback) {
    if (!p) return `<p>${esc(fallback)}</p><progress></progress>`;
    return `<p>${esc(p.message)}: ${p.done} of ${p.total}</p><progress max="${p.total}" value="${p.done}"></progress>`;
  }

  /* ------------------------------------------------------------ everywhere */
  const tallyEl = $("[data-tally-state]");
  if (tallyEl) {
    fetch("/api/tally").then((r) => r.json()).then((t) => {
      if (t && t.ok) {
        tallyEl.dataset.ok = "1";
        tallyEl.textContent = t.companies && t.companies.length ? "Tally: " + t.companies.join(", ") : "Tally connected";
      } else {
        tallyEl.dataset.ok = "0";
        tallyEl.textContent = "Tally not reachable";
        tallyEl.title = (t && t.error) || "";
      }
    }).catch(() => {});
  }

  $$("[data-filter]").forEach((input) => {
    const target = input.dataset.filter;
    input.addEventListener("input", () => {
      const q = input.value.trim().toLowerCase();
      $$(target).forEach((row) => {
        const hay = (row.dataset.search || row.textContent).toLowerCase();
        row.hidden = q !== "" && !hay.includes(q);
      });
    });
  });

  $$("select[data-autosubmit]").forEach((s) => s.addEventListener("change", () => s.form.submit()));

  $$("form[data-confirm]").forEach((f) => f.addEventListener("submit", (e) => {
    if (!window.confirm(f.dataset.confirm)) e.preventDefault();
  }));

  /* ------------------------------------------------------------ post to Tally */
  $$("[data-post-tally]").forEach((btn) => btn.addEventListener("click", async () => {
    const box = btn.closest("section, .actionbar").querySelector("#post-status") || $("#post-status");
    btn.disabled = true;
    box.innerHTML = progressHTML(null, "Connecting to Tally");
    try {
      const r = await fetch(btn.dataset.postTally, { method: "POST", headers: { "X-Bahi-Token": token } });
      const { job, error } = await r.json();
      if (error) throw new Error(error);
      const j = await pollJob(job, (p) => { box.innerHTML = progressHTML(p, "Posting"); });
      if (j.status !== "done") throw new Error(j.error || "Posting stopped");
      const res = j.result;
      let html = `<div class="result ${res.failed ? "result-bad" : "result-ok"}"><p><strong>${res.posted} voucher${res.posted === 1 ? "" : "s"} created in Tally</strong>${res.failed ? `, ${res.failed} not accepted` : ""}</p>`;
      if (res.ledgers.length) html += `<p>New ledgers created: ${res.ledgers.map(esc).join(", ")}</p>`;
      if (res.errors.length) html += "<ul>" + res.errors.slice(0, 8).map((e) => `<li>${esc(uiCopy(e.message))}</li>`).join("") + "</ul>";
      if (res.problems.length) html += "<ul>" + res.problems.map((p) => `<li>${esc(uiCopy(p))}</li>`).join("") + "</ul>";
      html += `<p><a href="${location.pathname}${location.search}">Refresh the list</a></p></div>`;
      box.innerHTML = html;
    } catch (err) {
      box.innerHTML = `<div class="result result-bad"><p>${esc(uiCopy(err.message))}</p></div>`;
      btn.disabled = false;
    }
  }));

  /* ------------------------------------------------------------ upload */
  const upload = $("#upload");
  if (upload) {
    const status = $("#upload-status");
    const input = $("#files", upload);
    const target = $(".dropzone-target", upload);
    const cid = upload.dataset.cid;
    let dropped = null;

    const showPicked = (files) => {
      const names = Array.from(files).map((f) => f.name);
      let el = $(".dz-picked", target);
      if (!el) { el = document.createElement("span"); el.className = "dz-picked"; target.appendChild(el); }
      el.textContent = names.length ? names.join(", ") : "";
    };
    input.addEventListener("change", () => { dropped = null; showPicked(input.files); });
    ["dragenter", "dragover"].forEach((t) => upload.addEventListener(t, (e) => { e.preventDefault(); upload.classList.add("is-over"); }));
    ["dragleave", "drop"].forEach((t) => upload.addEventListener(t, (e) => { e.preventDefault(); upload.classList.remove("is-over"); }));
    upload.addEventListener("drop", (e) => {
      if (e.dataTransfer && e.dataTransfer.files.length) { dropped = e.dataTransfer.files; showPicked(dropped); }
    });

    const render = (res) => {
      const parts = res.files.map((f) => {
        if (f.ok) {
          const verdict = { verified: "every row matches the running balance", partial: "some rows need a look", unverified: "no balance column to check" }[f.status] || f.status;
          return `<div class="result result-ok"><p><strong>${esc(f.name)}</strong>: ${esc(f.account)}, ${verdict}</p>
            <p>${f.ready} ready, ${f.review} to review${f.duplicates ? `, ${f.duplicates} already imported earlier` : ""}${f.skipped ? `, ${f.skipped} skipped` : ""}. <a href="${f.url}">Review</a></p>
            ${f.warnings.length ? "<ul>" + f.warnings.map((w) => `<li>${esc(w)}</li>`).join("") + "</ul>" : ""}</div>`;
        }
        if (f.password) {
          return `<div class="result result-bad"><p><strong>${esc(f.name)}</strong>: ${esc(uiCopy(f.error))}</p>
            <form data-retry="${esc(f.token)}"><label class="sr" for="pw-${esc(f.token)}">Password</label>
            <input id="pw-${esc(f.token)}" type="password" name="password" required autocomplete="off" placeholder="PDF password">
            <button class="btn btn-small" type="submit">Open</button></form></div>`;
        }
        return `<div class="result result-bad"><p><strong>${esc(f.name)}</strong>: ${esc(uiCopy(f.error))}</p></div>`;
      });
      return parts.join("") + `<p><a href="/c/${cid}">Refresh the statement list</a></p>`;
    };

    // place: the whole status area, or (for a password retry) just that file's block
    const run = async (url, form, place) => {
      const box = place || status;
      const show = (html) => { if (place) { place.innerHTML = html; } else { status.innerHTML = html; } };
      show(progressHTML(null, "Reading"));
      try {
        const r = await fetch(url, { method: "POST", body: form, headers: { "X-Bahi-Token": token } });
        const body = await r.json();
        if (!r.ok || body.error) throw new Error(body.error || "Upload failed");
        const j = await pollJob(body.job, (p) => show(progressHTML(p, "Reading")));
        if (j.status !== "done") throw new Error(j.error || "Reading stopped");
        const html = render(j.result);
        if (place) {
          const tpl = document.createElement("template");
          tpl.innerHTML = html;
          place.replaceWith(...Array.from(tpl.content.children).filter((el) => el.classList.contains("result")));
        } else {
          status.innerHTML = html;
        }
      } catch (err) {
        box.innerHTML = `<div class="result result-bad"><p>${esc(uiCopy(err.message))}</p></div>`;
      }
    };

    upload.addEventListener("submit", (e) => {
      e.preventDefault();
      const form = new FormData(upload);
      if (dropped) { form.delete("files"); Array.from(dropped).forEach((f) => form.append("files", f)); }
      if (!form.getAll("files").some((f) => f && f.name)) {
        status.innerHTML = `<div class="result result-bad"><p>Choose one or more statement files first</p></div>`;
        return;
      }
      run(upload.action, form);
    });

    status.addEventListener("submit", (e) => {
      const f = e.target.closest("form[data-retry]");
      if (!f) return;
      e.preventDefault();
      const form = new FormData();
      form.append("token", f.dataset.retry);
      form.append("password", f.password.value);
      const acc = upload.account_id && upload.account_id.value;
      if (acc) form.append("account_id", acc);
      run(`/c/${cid}/upload/retry`, form, f.closest(".result"));
    });
  }

  /* ------------------------------------------------------------ review */
  const table = $("#rows");
  if (!table) return;
  const cid = table.dataset.cid;
  const tbody = $("tbody", table);
  const bulk = $("[data-bulk]");
  let current = null;

  const visibleRows = () => $$("tr.row", tbody).filter((r) => !r.hidden);
  const setCurrent = (row, scroll) => {
    if (current) current.classList.remove("is-current");
    current = row;
    if (row) {
      row.classList.add("is-current");
      if (scroll) row.scrollIntoView({ block: "nearest" });
    }
  };
  const move = (step) => {
    const rows = visibleRows();
    if (!rows.length) return;
    const i = current ? rows.indexOf(current) : -1;
    const next = rows[Math.max(0, Math.min(rows.length - 1, i + step))] || rows[0];
    setCurrent(next, true);
  };

  const toast = (msg, bad) => {
    let el = $("#toast");
    if (!el) {
      el = document.createElement("p");
      el.id = "toast";
      el.setAttribute("role", "status");
      el.style.cssText = "position:fixed;left:50%;bottom:92px;transform:translateX(-50%);z-index:5;margin:0;padding:8px 14px;border-radius:6px;font-weight:600;box-shadow:0 2px 10px rgba(0,0,0,.18);";
      document.body.appendChild(el);
    }
    el.textContent = uiCopy(msg);
    el.style.background = bad ? "var(--red)" : "var(--ink)";
    el.style.color = "var(--sheet)";
    el.hidden = false;
    clearTimeout(el._t);
    el._t = setTimeout(() => { el.hidden = true; }, 3200);
  };

  const replaceRows = (rowsHtml) => {
    const tpl = document.createElement("template");
    Object.entries(rowsHtml || {}).forEach(([id, html]) => {
      const old = $("#t" + id, tbody);
      if (!old) return;
      tpl.innerHTML = html.trim();
      const fresh = tpl.content.firstElementChild;
      fresh.hidden = old.hidden;
      if (old === current) { fresh.classList.add("is-current"); current = fresh; }
      old.replaceWith(fresh);
    });
    updateBulk();
  };

  const setLedger = async (ids, ledger) => {
    try {
      const res = await postJSON(`/api/c/${cid}/ledger`, { ids, ledger, similar: true });
      replaceRows(res.rows);
      const readyEl = $("[data-ready-count]");
      if (readyEl && res.counts) readyEl.textContent = res.counts.ready || 0;
      toast(res.similar ? `${ledger}: set, and filled in ${res.similar} more row${res.similar === 1 ? "" : "s"} for the same party` : `${ledger}: set`);
    } catch (err) { toast(err.message, true); }
  };
  const setStatus = async (ids, action) => {
    try {
      const res = await postJSON(`/api/c/${cid}/status`, { ids, action });
      replaceRows(res.rows);
      const readyEl = $("[data-ready-count]");
      if (readyEl && res.counts) readyEl.textContent = res.counts.ready || 0;
    } catch (err) { toast(err.message, true); }
  };

  tbody.addEventListener("click", (e) => {
    const row = e.target.closest("tr.row");
    if (!row) return;
    if (row !== current) setCurrent(row, false);
    const act = e.target.closest("[data-action]");
    if (act) setStatus([+row.dataset.id], act.dataset.action);
    const dir = e.target.closest("[data-direction]");
    if (dir) postJSON(`/api/c/${cid}/direction`, { id: +row.dataset.id, direction: dir.dataset.direction })
      .then((res) => replaceRows(res.rows)).catch((err) => toast(err.message, true));
  });
  tbody.addEventListener("focusin", (e) => {
    const row = e.target.closest("tr.row");
    if (row && row !== current) setCurrent(row, false);
  });
  tbody.addEventListener("change", (e) => {
    const input = e.target.closest("[data-ledger]");
    if (input) {
      const v = input.value.trim();
      if (v && v !== input.dataset.orig) setLedger([+input.closest("tr").dataset.id], v);
      return;
    }
    if (e.target.matches("[data-select]")) updateBulk();
  });
  tbody.addEventListener("keydown", (e) => {
    const input = e.target.closest("[data-ledger]");
    if (!input) return;
    if (e.key === "Escape") { input.value = input.dataset.orig; input.blur(); }
    if (e.key === "Enter") {
      e.preventDefault();
      const row = input.closest("tr");
      input.blur();
      setTimeout(() => { setCurrent(row, false); move(1); }, 0);
    }
  });

  document.addEventListener("keydown", (e) => {
    const t = e.target;
    if (t.matches("input, select, textarea") || e.ctrlKey || e.metaKey || e.altKey) return;
    const k = e.key;
    if (k === "ArrowDown" || k === "j") { e.preventDefault(); move(1); }
    else if (k === "ArrowUp" || k === "k") { e.preventDefault(); move(-1); }
    else if (k === "/") { e.preventDefault(); const s = $("[data-search-key]"); if (s) s.focus(); }
    else if (!current) return;
    else if (k === "Enter") { const i = $("[data-ledger]", current); if (i) { e.preventDefault(); i.focus(); i.select(); } }
    else if (k === "a" || k === "A") { if ($('[data-action="approve"]', current)) setStatus([+current.dataset.id], "approve"); }
    else if (k === "s" || k === "S") { if ($('[data-action="skip"]', current)) setStatus([+current.dataset.id], "skip"); }
    else if (k === "x" || k === "X") { const c = $("[data-select]", current); if (c) { c.checked = !c.checked; updateBulk(); } }
  });

  const selectAll = $("[data-select-all]");
  if (selectAll) selectAll.addEventListener("change", () => {
    visibleRows().forEach((r) => { const c = $("[data-select]", r); if (c) c.checked = selectAll.checked; });
    updateBulk();
  });
  const selectedIds = () => $$("[data-select]:checked", tbody).map((c) => +c.closest("tr").dataset.id);
  function updateBulk() {
    if (!bulk) return;
    const n = selectedIds().length;
    bulk.hidden = n === 0;
    $("[data-bulk-count]", bulk).textContent = `${n} selected`;
  }
  if (bulk) {
    $("[data-bulk-set]", bulk).addEventListener("click", () => {
      const v = $("#bulk-ledger").value.trim();
      if (!v) { toast("Type a ledger first", true); return; }
      setLedger(selectedIds(), v);
    });
    $$("[data-bulk-action]", bulk).forEach((b) => b.addEventListener("click", () => setStatus(selectedIds(), b.dataset.bulkAction)));
  }
})();
