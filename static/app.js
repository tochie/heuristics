"use strict";

const form = document.getElementById("form");
const urlInput = document.getElementById("url");
const submitBtn = document.getElementById("submit");
const statusEl = document.getElementById("status");
const resultsEl = document.getElementById("results");
const shotsInput = document.getElementById("shots");

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  const url = urlInput.value.trim();
  const body = {
    url: url || null,
    organization_description: val("org"),
    primary_user_tasks: val("tasks"),
    known_concerns: val("concerns"),
    page_content: val("content"),
    screenshots: await readShots(),
  };
  if (!body.url && !body.page_content && (!body.screenshots || !body.screenshots.length)) {
    setStatus("Provide a URL, screenshots, or page content.", true);
    return;
  }

  setBusy(true);
  resultsEl.hidden = true;
  resultsEl.innerHTML = "";
  setStatus("Starting the staged evaluation…", false);

  try {
    const res = await fetch("/api/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Something went wrong.");
    const report = await pollJob(data.job_id);
    render(report);
    setStatus("", false);
  } catch (err) {
    setStatus(err.message || String(err), true);
  } finally {
    setBusy(false);
  }
});

const STAGES = [
  "Analyzing evidence across the 8 dimensions…",
  "Assessing severity and confidence per finding…",
  "Generating prioritized recommendations…",
  "Assembling the structured report…",
];

async function pollJob(jobId) {
  const started = Date.now();
  for (;;) {
    await new Promise((r) => setTimeout(r, 4000));
    const elapsed = Math.round((Date.now() - started) / 1000);
    const stage = STAGES[Math.min(Math.floor(elapsed / 35), STAGES.length - 1)];
    setStatus(`${stage} (${elapsed}s — evaluations typically take 1–3 minutes)`, false);
    let res;
    try {
      res = await fetch(`/api/analyze/${jobId}`);
    } catch {
      continue; // transient network blip — keep polling
    }
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "The evaluation was lost.");
    if (data.status === "done") return data.report;
    if (data.status === "error") throw new Error(data.error);
    if (elapsed > 420) throw new Error("The evaluation timed out. Please try again.");
  }
}

function val(id) {
  const v = document.getElementById(id).value.trim();
  return v || null;
}

async function readShots() {
  const files = Array.from(shotsInput.files || []).slice(0, 3);
  const out = [];
  for (const f of files) {
    if (f.size > 4 * 1024 * 1024) {
      throw new Error(`Screenshot "${f.name}" is over 4 MB.`);
    }
    const b64 = await new Promise((resolve, reject) => {
      const r = new FileReader();
      r.onload = () => resolve(String(r.result).split(",")[1]);
      r.onerror = reject;
      r.readAsDataURL(f);
    });
    out.push({ media_type: f.type || "image/png", data: b64 });
  }
  return out;
}

function setBusy(busy) {
  submitBtn.disabled = busy;
  submitBtn.textContent = busy ? "Evaluating…" : "Evaluate";
}

function setStatus(msg, isError) {
  statusEl.textContent = msg;
  statusEl.classList.toggle("error", !!isError);
}

function esc(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
  ));
}

function list(items, ordered) {
  if (!Array.isArray(items) || items.length === 0) return "<p class='conf-reason'>None reported.</p>";
  const tag = ordered ? "ol" : "ul";
  return `<${tag}>${items.map((i) => `<li>${esc(i)}</li>`).join("")}</${tag}>`;
}

function sevClass(sev) {
  const v = String(sev || "").toLowerCase();
  if (v.startsWith("critical")) return "sev-critical";
  if (v.startsWith("high")) return "sev-high";
  if (v.startsWith("medium")) return "sev-medium";
  if (v.startsWith("low")) return "sev-low";
  return "sev-validate";
}

function confClass(c) {
  const v = String(c || "").toLowerCase();
  if (v.startsWith("high")) return "high";
  if (v.startsWith("med")) return "medium";
  return "low";
}

function render(d) {
  const ex = d.executive_summary || {};
  const score = d.overall_ux_score || {};
  const pct10 = score.score == null ? 0 : Math.max(0, Math.min(100, score.score * 10));

  const dimRows = (d.dimension_scores || []).map((r) => `
    <article class="metric">
      <div class="metric-top">
        <div class="metric-name">${esc(r.label)}<span class="weight">${esc(r.weight)}%</span></div>
        <div class="metric-score">${r.score == null ? "Validation Needed" : esc(r.score)}${r.score == null ? "" : '<span style="font-size:13px;color:var(--muted)">/10 — ' + esc(r.band) + "</span>"}</div>
      </div>
      <div class="bar"><i style="width:${r.score == null ? 0 : r.score * 10}%"></i></div>
      ${r.strengths && r.strengths.length ? `<ul class="evidence">${r.strengths.map((s) => `<li>${esc(s)}</li>`).join("")}</ul>` : ""}
      <p class="conf-reason">${r.concern_count} finding${r.concern_count === 1 ? "" : "s"}${r.insufficient_evidence ? " — insufficient evidence for a score" : ""}</p>
    </article>`).join("");

  const findings = (d.detailed_findings || []).map((f) => `
    <article class="metric finding-card">
      <div class="metric-top">
        <div class="metric-name">${esc(f.id)} · ${esc(f.dimension)}</div>
        <div><span class="sev ${sevClass(f.severity)}">${esc(f.severity)}</span></div>
      </div>
      <p class="finding">${esc(f.finding)}</p>
      <p class="conf-reason"><strong>Evidence:</strong> ${esc(f.supporting_evidence)}</p>
      <p class="conf-reason"><strong>User impact:</strong> ${esc(f.user_impact)}</p>
      <span class="conf ${confClass(f.confidence_level)}"><span class="dot"></span>
        Confidence: ${esc(f.confidence_level)} (${esc(f.confidence_percentage)}%)</span>
      <p class="conf-reason">${esc(f.confidence_justification)}</p>
      <p class="conf-reason">→ Recommendation ${esc(f.recommendation_ref)}</p>
    </article>`).join("");

  const recBlock = (label, recs) => !recs || !recs.length ? "" : `
    <h4 class="prio-title">${esc(label)} — ${esc((recs[0] || {}).priority_meaning || "")}</h4>
    ${recs.map((r) => `
      <article class="metric">
        <div class="metric-top">
          <div class="metric-name">${esc(r.id)} · ${esc(r.dimension)}${r.is_investigation ? ' · <em>investigation</em>' : ""}</div>
          <div class="weight">Effort: ${esc(r.estimated_effort)}</div>
        </div>
        <p class="finding">${esc(r.recommendation)}</p>
        <p class="conf-reason"><strong>Why:</strong> ${esc(r.reasoning)}</p>
        <p class="conf-reason"><strong>Expected benefit:</strong> ${esc(r.expected_user_benefit)}</p>
        <p class="conf-reason">For finding ${esc(r.related_finding)}</p>
      </article>`).join("")}`;

  const recs = d.prioritized_recommendations || {};
  const validation = (d.validation_requirements || []).map((v) =>
    `<li><strong>${esc(v.label)}</strong>: ${esc(v.finding)} <span class="weight">(${esc(v.finding_id)})</span></li>`).join("");

  const sevSummary = Object.entries(d.severity_summary || {})
    .map(([k, n]) => `<span class="sev ${sevClass(k)}">${esc(k)}: ${n}</span>`).join(" ");

  resultsEl.innerHTML = `
    <div class="overall">
      <div class="score-ring" style="--pct:${pct10}"><span>${score.score == null ? "—" : esc(score.score)}</span></div>
      <div class="overall-meta">
        <h2>${esc(score.display || "Overall UX Score")}</h2>
        ${ex.overall_assessment ? `<p class="summary">${esc(ex.overall_assessment)}</p>` : ""}
        <p class="url">${esc((d.meta || {}).page_title ? d.meta.page_title + " — " : "")}${esc(ex.website_reviewed || "")}</p>
      </div>
    </div>

    <div class="panel"><h3>Executive Summary</h3>
      ${String(ex.text || "").split(/\n\n+/).map((p) => `<p class="finding">${esc(p)}</p>`).join("")}
      ${list(ex.key_observations, false)}
    </div>

    <div class="cols">
      <div class="panel"><h3>Evaluation Scope</h3>${list((d.evaluation_scope || {}).evidence_supplied, false)}
        <p class="conf-reason">${esc((d.evaluation_scope || {}).scope_of_review || "")}</p></div>
      <div class="panel"><h3>Severity Summary</h3><p class="sev-row">${sevSummary || "No findings."}</p>
        <p class="conf-reason">${esc(score.interpretation || "")}</p></div>
    </div>

    <h3 class="section-title">Dimension Scores</h3>
    ${dimRows}

    <h3 class="section-title">Detailed Findings (${(d.detailed_findings || []).length})</h3>
    ${findings || "<p class='conf-reason'>No usability concerns were identified from the available evidence.</p>"}

    <h3 class="section-title">Prioritized Recommendations</h3>
    ${recBlock("Priority 1", recs["Priority 1"])}
    ${recBlock("Priority 2", recs["Priority 2"])}
    ${recBlock("Priority 3", recs["Priority 3"])}

    <div class="cols">
      <div class="panel"><h3>Validation Requirements</h3>
        ${validation ? `<ul>${validation}</ul>` : "<p class='conf-reason'>None flagged.</p>"}</div>
      <div class="panel"><h3>Evaluation Limitations</h3>${list(d.evaluation_limitations, false)}</div>
    </div>

    <div class="panel"><h3>Conclusion</h3>
      <p class="finding">${esc((d.conclusion || {}).text || "")}</p>
      ${list((d.conclusion || {}).next_steps, true)}
    </div>
  `;
  resultsEl.hidden = false;
}
