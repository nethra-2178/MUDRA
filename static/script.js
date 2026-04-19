/* ══════════════════════════════════════════════
   MUDRA  |  script.js
   ══════════════════════════════════════════════ */
"use strict";

const API_BASE  = "";
let currentLang = "en";
let selectedFile = null;

/* ── Utility ───────────────────────────────────────────────────────── */
function showToast(msg, duration = 3000) {
  const t = document.getElementById("toast");
  if (!t) return;
  t.textContent = msg;
  t.classList.add("show");
  setTimeout(() => t.classList.remove("show"), duration);
}
function formatBytes(b) {
  if (b < 1024)    return b + " B";
  if (b < 1048576) return (b / 1024).toFixed(1) + " KB";
  return (b / 1048576).toFixed(1) + " MB";
}
function fileIcon(ext) {
  const m = { pdf:"📋", jpg:"🖼️", jpeg:"🖼️", png:"🖼️",
              bmp:"🖼️", tiff:"🖼️", webp:"🖼️" };
  return m[ext.toLowerCase()] || "📄";
}

/* ── Language toggle ───────────────────────────────────────────────── */
function applyLanguage(lang) {
  currentLang = lang;
  document.documentElement.lang = lang === "ta" ? "ta" : "en";
  document.querySelectorAll("[data-en]").forEach(el => {
    const v = el.getAttribute(`data-${lang}`);
    if (v) el.textContent = v;
  });
  document.querySelectorAll("option[data-en]").forEach(opt => {
    const v = opt.getAttribute(`data-${lang}`);
    if (v) opt.textContent = v;
  });
  document.querySelectorAll(".lang-btn").forEach(btn =>
    btn.classList.toggle("active", btn.dataset.lang === lang)
  );
  const activeExpl = document.querySelector(".expl-tab.active");
  if (activeExpl) showExplTab(activeExpl.dataset.expl);
}
document.querySelectorAll(".lang-btn").forEach(btn =>
  btn.addEventListener("click", () => applyLanguage(btn.dataset.lang))
);

/* ── Gauge score computation ───────────────────────────────────────────
   `score` from the backend is ALWAYS authenticity confidence (higher = more genuine).
   We derive three values that add up to 100 so the bars make intuitive sense.

   Logic:
     real      = score              (how authentic it looks)
     fake      = 100 - score        (how suspicious it looks)
     uncertain = the "middle zone"  pulled from both ends

   For clear verdicts (verified / forged) we keep uncertain small (≤15).
   For uncertain verdict we give uncertain a much larger share.
   All three always sum to exactly 100.
──────────────────────────────────────────────────────────────────────── */
function computeGaugeValues(score, verdict) {
  const s = Math.round(score);
  let real, fake, uncertain;

  if (verdict === "verified") {
    uncertain = Math.max(0, Math.round((100 - s) * 0.3));  // small uncertain slice
    fake      = Math.max(0, 100 - s - uncertain);
    real      = 100 - uncertain - fake;
  } else if (verdict === "forged") {
    uncertain = Math.max(0, Math.round(s * 0.3));           // small uncertain slice
    real      = Math.max(0, s - uncertain);
    fake      = 100 - real - uncertain;
  } else {
    // uncertain verdict — give uncertain a big centre chunk
    real      = Math.max(0, Math.round(s * 0.55));
    fake      = Math.max(0, Math.round((100 - s) * 0.55));
    uncertain = 100 - real - fake;
  }

  // clamp so nothing goes negative due to rounding
  real      = Math.max(0, Math.min(100, real));
  fake      = Math.max(0, Math.min(100, fake));
  uncertain = Math.max(0, 100 - real - fake);

  return { real, uncertain, fake };
}

/* ── Upload page ───────────────────────────────────────────────────── */
const uploadForm  = document.getElementById("upload-form");
const dropZone    = document.getElementById("drop-zone");
const fileInput   = document.getElementById("file-input");
const filePreview = document.getElementById("file-preview");
const fileIconEl  = document.getElementById("file-icon");
const fileNameEl  = document.getElementById("file-name");
const fileSizeEl  = document.getElementById("file-size");
const btnRemove   = document.getElementById("btn-remove");
const btnAnalyse  = document.getElementById("btn-analyse");
const loadingOvl  = document.getElementById("loading-overlay");

if (uploadForm) {
  ["dragenter","dragover"].forEach(ev =>
    dropZone.addEventListener(ev, e => { e.preventDefault(); dropZone.classList.add("dragover"); })
  );
  ["dragleave","drop"].forEach(ev =>
    dropZone.addEventListener(ev, e => { e.preventDefault(); dropZone.classList.remove("dragover"); })
  );
  dropZone.addEventListener("drop", e => { const f = e.dataTransfer.files[0]; if (f) setFile(f); });
  fileInput.addEventListener("change", () => { if (fileInput.files[0]) setFile(fileInput.files[0]); });

  function setFile(file) {
    const allowed = [".pdf",".jpg",".jpeg",".png",".bmp",".tiff",".webp"];
    const ext = "." + file.name.split(".").pop().toLowerCase();
    if (!allowed.includes(ext)) { showToast(`❌ Unsupported file type: ${ext}`); return; }
    if (file.size > 20*1024*1024) { showToast("❌ File must be under 20 MB."); return; }
    selectedFile = file;
    const ec = ext.slice(1);
    if (fileIconEl) fileIconEl.textContent = fileIcon(ec);
    if (fileNameEl) fileNameEl.textContent = file.name;
    if (fileSizeEl) fileSizeEl.textContent = formatBytes(file.size);
    if (filePreview) filePreview.classList.add("visible");
    if (btnAnalyse)  btnAnalyse.disabled = false;
  }

  if (btnRemove) {
    btnRemove.addEventListener("click", () => {
      selectedFile = null;
      fileInput.value = "";
      if (filePreview) filePreview.classList.remove("visible");
      if (btnAnalyse)  btnAnalyse.disabled = true;
    });
  }

  uploadForm.addEventListener("submit", async e => {
    e.preventDefault();
    if (!selectedFile) { showToast("Please select a file first."); return; }
    btnAnalyse.disabled = true;
    btnAnalyse.classList.add("loading");
    if (loadingOvl) loadingOvl.classList.add("active");

    const docType  = document.getElementById("doc-type")?.value || "generic";
    const formData = new FormData();
    formData.append("file",     selectedFile);
    formData.append("doc_type", docType);

    try {
      const resp = await fetch(`${API_BASE}/analyse`, { method:"POST", body:formData });
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({}));
        throw new Error(err.error || `Server error ${resp.status}`);
      }
      const data = await resp.json();
      sessionStorage.setItem("mudra_result", JSON.stringify(data));
      sessionStorage.setItem("mudra_lang",   currentLang);
      window.location.href = "/result";
    } catch (err) {
      showToast("❌ " + err.message, 5000);
      btnAnalyse.disabled = false;
      btnAnalyse.classList.remove("loading");
      if (loadingOvl) loadingOvl.classList.remove("active");
    }
  });
}

/* ── Result page ───────────────────────────────────────────────────── */
const verdictBanner = document.getElementById("verdict-banner");

if (verdictBanner) {
  const raw      = sessionStorage.getItem("mudra_result");
  const savedLang = sessionStorage.getItem("mudra_lang") || "en";
  if (!raw) {
    window.location.href = "/";
  } else {
    renderResult(JSON.parse(raw));
    applyLanguage(savedLang);
  }
}

function renderResult(data) {
  const verdict      = (data.verdict || "uncertain").toLowerCase();
  const score        = typeof data.score === "number" ? data.score : 50;
  const roundedScore = Math.round(score);

  /* Banner class */
  verdictBanner.classList.add(verdict);

  /* Verdict meta text */
  const vm = {
    verified:  { icon:"✅", label:"Document Verified",       labelTa:"ஆவணம் சரிபார்க்கப்பட்டது",
                 title:"This document appears genuine",       titleTa:"இந்த ஆவணம் உண்மையானதாக தெரிகிறது" },
    forged:    { icon:"❌", label:"Forgery Detected",         labelTa:"போலி கண்டறியப்பட்டது",
                 title:"This document may be forged",         titleTa:"இந்த ஆவணம் போலியாக இருக்கலாம்" },
    uncertain: { icon:"⚠️", label:"Result Uncertain",        labelTa:"முடிவு நிச்சயமற்றது",
                 title:"Could not determine authenticity",    titleTa:"நம்பகத்தன்மையை தீர்மானிக்க முடியவில்லை" },
  }[verdict] || { icon:"⚠️", label:"Result Uncertain", labelTa:"முடிவு நிச்சயமற்றது",
                  title:"Could not determine authenticity", titleTa:"நம்பகத்தன்மையை தீர்மானிக்க முடியவில்லை" };

  document.getElementById("verdict-icon").textContent = vm.icon;

  const vLabel = document.getElementById("verdict-label");
  vLabel.setAttribute("data-en", vm.label); vLabel.setAttribute("data-ta", vm.labelTa);
  vLabel.textContent = vm.label;

  const vTitle = document.getElementById("verdict-title");
  vTitle.setAttribute("data-en", vm.title); vTitle.setAttribute("data-ta", vm.titleTa);
  vTitle.textContent = vm.title;

  /* Dynamic subtitle with real counts */
  const highCount    = (data.anomalies||[]).filter(a=>a.severity==="high").length;
  const medCount     = (data.anomalies||[]).filter(a=>a.severity==="medium").length;
  const failedChecks = (data.checks||[]).filter(c=>c.status==="fail").length;
  let sub, subTa;
  if (verdict === "verified") {
    sub   = "All forensic checks passed — no signs of tampering detected.";
    subTa = "அனைத்து தடயவியல் சரிபார்ப்புகளும் தேர்ச்சி — திருத்தல் அறிகுறி இல்லை.";
  } else if (verdict === "forged") {
    sub   = `${failedChecks} check(s) failed with ${highCount} critical issue(s). Do not accept this document.`;
    subTa = `${failedChecks} சரிபார்ப்பு தோல்வி, ${highCount} முக்கியமான பிரச்சனை. இந்த ஆவணத்தை ஏற்க வேண்டாம்.`;
  } else {
    const total = highCount + medCount;
    sub   = `${total} issue(s) found (${highCount} critical, ${medCount} moderate). Manual verification required.`;
    subTa = `${total} பிரச்சனை கண்டறியப்பட்டது (${highCount} முக்கியமானது, ${medCount} மிதமானது). கைமுறை சரிபார்ப்பு தேவை.`;
  }
  const vSub = document.getElementById("verdict-subtitle");
  vSub.setAttribute("data-en", sub); vSub.setAttribute("data-ta", subTa);
  vSub.textContent = sub;

  /* Cert pill */
  if (data.cert_id) {
    document.getElementById("cert-id-val").textContent = data.cert_id.toUpperCase();
    const pill = document.getElementById("cert-pill");
    if (pill) pill.style.display = "";
  }

  /* ── Score ring ────────────────────────────────────────────────────
     score is authenticity confidence: higher = more genuine.
     Ring shows number + REAL/UNCERTAIN/FAKE pill + one-liner below.
  ──────────────────────────────────────────────────────────────────── */
  const scoreRing = document.getElementById("score-ring");
  if (scoreRing) scoreRing.classList.add(verdict);

  const scoreNumEl = document.getElementById("score-num");
  if (scoreNumEl) scoreNumEl.textContent = roundedScore;

  const scoreTagEl = document.getElementById("score-tag");
  if (scoreTagEl) {
    const tagMap = {
      verified:  { en:"REAL",      ta:"உண்மை" },
      uncertain: { en:"UNCERTAIN", ta:"நிச்சயமற்றது" },
      forged:    { en:"FAKE",      ta:"போலி" },
    };
    const tag = tagMap[verdict] || tagMap.uncertain;
    scoreTagEl.setAttribute("data-en", tag.en);
    scoreTagEl.setAttribute("data-ta", tag.ta);
    scoreTagEl.textContent = tag.en;
  }

  const scoreMeaningEl = document.getElementById("score-meaning");
  if (scoreMeaningEl) {
    let m, mTa;
    if (verdict === "verified") {
      m   = `${roundedScore}/100 — document looks genuine`;
      mTa = `${roundedScore}/100 — ஆவணம் உண்மையானதாக தெரிகிறது`;
    } else if (verdict === "forged") {
      m   = `${roundedScore}/100 — high chance of forgery`;
      mTa = `${roundedScore}/100 — போலியாக இருக்கும் வாய்ப்பு அதிகம்`;
    } else {
      const total = highCount + medCount;
      m   = `${roundedScore}/100 — ${total} issue(s) need review`;
      mTa = `${roundedScore}/100 — ${total} பிரச்சனை சரிபார்க்க வேண்டும்`;
    }
    scoreMeaningEl.setAttribute("data-en", m);
    scoreMeaningEl.setAttribute("data-ta", mTa);
    scoreMeaningEl.textContent = m;
  }

  /* Animate ring arc */
  const circumference = 289.03;
  const offset = circumference - (score / 100) * circumference;
  setTimeout(() => {
    const rf = document.getElementById("ring-fill");
    if (rf) rf.style.strokeDashoffset = offset;
  }, 120);

  /* ── 3-bar gauge ────────────────────────────────────────────────────
     Compute Real / Uncertain / Fake percentages and animate bars.
  ──────────────────────────────────────────────────────────────────── */
  const { real, uncertain: unc, fake } = computeGaugeValues(score, verdict);

  const setBar = (id, pctId, value) => {
    const bar = document.getElementById(id);
    const pct = document.getElementById(pctId);
    if (bar) setTimeout(() => { bar.style.width = value + "%"; }, 180);
    if (pct) pct.textContent = value + "%";
  };

  setBar("bar-real",      "pct-real",      real);
  setBar("bar-uncertain", "pct-uncertain", unc);
  setBar("bar-fake",      "pct-fake",      fake);

  /* ── Checks ──────────────────────────────────────────────────────── */
  const checksList = document.getElementById("checks-list");
  if (checksList && Array.isArray(data.checks) && data.checks.length) {
    checksList.innerHTML = data.checks.map(c => {
      const icon = { pass:"✅", fail:"❌", warn:"⚠️", skip:"⏭️" }[c.status] || "🔍";
      return `<div class="check-item">
        <span class="check-status">${icon}</span>
        <div class="check-content">
          <div class="check-name">${escHtml(c.name)}</div>
          ${c.detail ? `<div class="check-detail">${escHtml(c.detail)}</div>` : ""}
        </div>
      </div>`;
    }).join("");
  } else {
    checksList.innerHTML = `<div class="check-item"><span class="check-status">ℹ️</span>
      <div class="check-content"><div class="check-name">No checks returned.</div></div></div>`;
  }

  /* ── Anomalies ───────────────────────────────────────────────────── */
  const anomList = document.getElementById("anomalies-list");
  if (anomList) {
    if (Array.isArray(data.anomalies) && data.anomalies.length) {
      anomList.innerHTML = data.anomalies.map(a => {
        const sev     = (a.severity||"low").toLowerCase();
        const sevIcon = sev==="high" ? "🔴" : sev==="medium" ? "🟡" : "🟢";
        return `<div class="anomaly-item ${sev}">
          <span class="anomaly-icon">${sevIcon}</span>
          <span>${escHtml(a.text)}</span>
        </div>`;
      }).join("");
    } else {
      anomList.innerHTML = `<div class="anomaly-item low">
        <span class="anomaly-icon">🟢</span> No anomalies detected.</div>`;
    }
  }

  /* ── Explanation ─────────────────────────────────────────────────── */
  const explEn = document.getElementById("expl-en");
  const explTa = document.getElementById("expl-ta");
  if (explEn) explEn.textContent = data.explanation?.en || "No explanation available.";
  if (explTa) {
    explTa.textContent = data.explanation?.ta || "விளக்கம் கிடைக்கவில்லை.";
    explTa.setAttribute("data-lang","ta");
  }

  /* ── ELA Heatmap ─────────────────────────────────────────────────── */
  const heatmapWrap = document.getElementById("heatmap-wrap");
  if (heatmapWrap) {
    heatmapWrap.innerHTML = data.ela_heatmap_url
      ? `<img src="${escHtml(data.ela_heatmap_url)}" alt="ELA Heatmap" loading="lazy"
           onerror="this.parentElement.innerHTML='<span style=color:#666;font-size:13px>Heatmap unavailable</span>'" />`
      : `<span style="color:#666;font-size:13px;">No heatmap generated.</span>`;
  }

  /* ── Metadata table ──────────────────────────────────────────────── */
  const metaTable = document.getElementById("meta-table");
  if (metaTable && data.metadata) {
    const labelMap = {
      filename:        { en:"Filename",      ta:"கோப்பு பெயர்" },
      filetype:        { en:"File Type",     ta:"கோப்பு வகை" },
      filesize:        { en:"File Size",     ta:"கோப்பு அளவு" },
      software:        { en:"Software",      ta:"மென்பொருள்" },
      datetime:        { en:"Date Modified", ta:"திருத்திய தேதி" },
      datetimeoriginal:{ en:"Date Taken",    ta:"எடுத்த தேதி" },
      make:            { en:"Camera Make",   ta:"கேமரா உற்பத்தியாளர்" },
      model:           { en:"Camera Model",  ta:"கேமரா மாடல்" },
    };
    metaTable.innerHTML = Object.entries(data.metadata).map(([k,v]) => {
      const lk    = k.toLowerCase();
      const label = labelMap[lk]?.en || k;
      return `<tr>
        <td data-en="${label}" data-ta="${labelMap[lk]?.ta||label}">${label}</td>
        <td>${escHtml(String(v))}</td>
      </tr>`;
    }).join("");
  }

  /* ── Download link ───────────────────────────────────────────────── */
  const btnDownload = document.getElementById("btn-download");
  if (btnDownload && data.assets?.certificate_url)
    btnDownload.href = data.assets.certificate_url;
}

/* ── Explanation tabs ────────────────────────────────────────────────── */
document.querySelectorAll(".expl-tab").forEach(tab => {
  tab.addEventListener("click", () => {
    document.querySelectorAll(".expl-tab").forEach(t => t.classList.remove("active"));
    tab.classList.add("active");
    showExplTab(tab.dataset.expl);
  });
});
function showExplTab(lang) {
  const en = document.getElementById("expl-en");
  const ta = document.getElementById("expl-ta");
  if (!en || !ta) return;
  en.style.display = lang==="ta" ? "none" : "";
  ta.style.display = lang==="ta" ? ""     : "none";
}

/* ── Escape util ─────────────────────────────────────────────────────── */
function escHtml(str) {
  return String(str)
    .replace(/&/g,"&amp;").replace(/</g,"&lt;")
    .replace(/>/g,"&gt;").replace(/"/g,"&quot;");
}