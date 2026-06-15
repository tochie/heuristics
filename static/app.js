"use strict";

const form = document.getElementById("form");
const urlInput = document.getElementById("url");
const submitBtn = document.getElementById("submit");
const statusEl = document.getElementById("status");
const resultsEl = document.getElementById("results");

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  const url = urlInput.value.trim();
  if (!url) return;

  setBusy(true);
  resultsEl.hidden = true;
  resultsEl.innerHTML = "";
  setStatus("Fetching the page and asking Claude to review it… this can take 20–40s.", false);

  try {
    const res = await fetch("/api/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Something went wrong.");
    render(data);
    setStatus("", false);
  } catch (err) {
    setStatus(err.message || String(err), true);
  } finally {
    setBusy(false);
  }
});

function setBusy(busy) {
  submitBtn.disabled = busy;
  submitBtn.textContent = busy ? "Analyzing…" : "Analyze";
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

function confClass(c) {
  const v = String(c || "").toLowerCase();
  if (v.startsWith("high")) return "high";
  if (v.startsWith("med")) return "medium";
  if (v.startsWith("low")) return "low";
  return "";
}

function render(d) {
  const pct = Math.max(0, Math.min(100, Number(d.overall_score) || 0));
  const metrics = (d.metric_order || Object.keys(d.metrics || {}))
    .map((k) => ({ key: k, ...(d.metrics[k] || {}) }));

  const metricCards = metrics.map((m) => {
    const score = m.score == null ? "–" : m.score;
    const barPct = m.score == null ? 0 : (m.score / 10) * 100;
    const cc = confClass(m.confidence);
    return `
      <article class="metric">
        <div class="metric-top">
          <div class="metric-name">${esc(m.label || m.key)}<span class="weight">${esc(m.weight)}%</span></div>
          <div class="metric-score">${esc(score)}<span style="font-size:13px;color:var(--muted)">/10</span></div>
        </div>
        <div class="bar"><i style="width:${barPct}%"></i></div>
        <p class="finding">${esc(m.finding)}</p>
        <span class="conf ${cc}"><span class="dot"></span>Confidence: ${esc(m.confidence || "—")}</span>
        ${m.confidence_reason ? `<p class="conf-reason">${esc(m.confidence_reason)}</p>` : ""}
        ${Array.isArray(m.evidence) && m.evidence.length
          ? `<ul class="evidence">${m.evidence.map((e) => `<li>${esc(e)}</li>`).join("")}</ul>`
          : ""}
      </article>`;
  }).join("");

  resultsEl.innerHTML = `
    <div class="overall">
      <div class="score-ring" style="--pct:${pct}"><span>${pct}</span></div>
      <div class="overall-meta">
        <h2>Overall UX Score</h2>
        ${d.summary ? `<p class="summary">${esc(d.summary)}</p>` : ""}
        <p class="url">${esc(d.title ? d.title + " — " : "")}${esc(d.url)}</p>
      </div>
    </div>

    <div class="cols">
      <div class="panel"><h3>Strengths</h3>${list(d.strengths, false)}</div>
      <div class="panel"><h3>Issues</h3>${list(d.issues, false)}</div>
    </div>

    <h3 class="section-title">Metric breakdown</h3>
    ${metricCards}

    <h3 class="section-title">Recommendations</h3>
    <div class="recs">${list(d.recommendations, true)}</div>
  `;
  resultsEl.hidden = false;
}
