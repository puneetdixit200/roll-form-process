const data = JSON.parse(document.getElementById("report-data").textContent);
const sequences = [
  ...data.sequences.map((s) => ({ type: "sequence", label: s.label, steps: s.steps })),
  ...data.composite_flowers.map((c) => ({ type: "composite", label: c.label, steps: c.passes, downloads: c.downloads })),
];
let activeSequence = 0;
let activeStep = 0;
let mode = "single";
let zoom = 1;
let panX = 0;
let panY = 0;
let playing = null;

function el(id) { return document.getElementById(id); }
function esc(v) { return String(v ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])); }
function fmt(v) {
  if (v === null || v === undefined || v === "") return "-";
  const n = Number(v);
  return Number.isFinite(n) ? esc(Math.round(n * 1000) / 1000) : esc(v);
}
function currentSeq() { return sequences[activeSequence] || { steps: [] }; }
function currentStep() { return currentSeq().steps[activeStep] || {}; }
function imageTransform() { return `translate(${panX}px,${panY}px) scale(${zoom})`; }

function init() {
  renderSummary();
  renderTabs();
  wireControls();
  wirePan();
  render();
}

function renderSummary() {
  const p = data.project;
  el("summary").innerHTML = `<h2>Project Summary</h2><div class="metrics">
    <div class="metric"><strong>${esc(p.drawing_id)}</strong>Drawing</div>
    <div class="metric"><strong>${esc((p.units || {}).confirmed ? "Confirmed" : "Unconfirmed")}</strong>Unit status</div>
    <div class="metric"><strong>${esc(p.validation_status)}</strong>Validation</div>
    <div class="metric"><strong>${p.confirmed_assemblies}</strong>Confirmed assemblies</div>
    <div class="metric"><strong>${p.confirmed_transitions}</strong>Confirmed transitions</div>
  </div>`;
  el("warnings").innerHTML = `<h2>Warnings</h2>${data.warnings.map((w) => `<p><span class="badge warn">${esc(w.code)}</span> ${esc(w.message)} ${esc((w.source_handles || []).join(" "))}</p>`).join("") || "<p>No warnings</p>"}`;
}

function renderTabs() {
  el("sequence-tabs").innerHTML = sequences.map((s, i) => `<button class="${i === activeSequence ? "active" : ""}" data-tab="${i}">${esc(s.label)}</button>`).join("");
  document.querySelectorAll("[data-tab]").forEach((b) => {
    b.onclick = () => { activeSequence = Number(b.dataset.tab); activeStep = 0; panX = 0; panY = 0; renderTabs(); render(); };
  });
}

function wireControls() {
  document.querySelector('[data-action="first"]').onclick = () => { activeStep = 0; render(); };
  document.querySelector('[data-action="prev"]').onclick = () => { activeStep = Math.max(0, activeStep - 1); render(); };
  document.querySelector('[data-action="next"]').onclick = () => { activeStep = Math.min(currentSeq().steps.length - 1, activeStep + 1); render(); };
  document.querySelector('[data-action="last"]').onclick = () => { activeStep = currentSeq().steps.length - 1; render(); };
  document.querySelector('[data-action="reset"]').onclick = () => { zoom = 1; panX = 0; panY = 0; renderPreview(); };
  document.querySelector('[data-action="zoom-in"]').onclick = () => { zoom = Math.min(4, zoom + 0.25); renderPreview(); };
  document.querySelector('[data-action="zoom-out"]').onclick = () => { zoom = Math.max(0.25, zoom - 0.25); renderPreview(); };
  document.querySelector('[data-action="fit"]').onclick = () => { zoom = 1; panX = 0; panY = 0; renderPreview(); };
  document.querySelector('[data-action="play"]').onclick = togglePlay;
  document.querySelector('[data-action="export-review"]').onclick = exportReviewDecisions;
  el("sequence-slider").oninput = (e) => { activeStep = Number(e.target.value); render(); };
  el("pass-selector").onchange = (e) => { activeStep = Number(e.target.value); render(); };
  document.querySelectorAll("[data-mode]").forEach((b) => { b.onclick = () => { mode = b.dataset.mode; render(); }; });
}

function wirePan() {
  let dragging = false;
  let startX = 0;
  let startY = 0;
  el("preview-panel").addEventListener("mousedown", (event) => { dragging = true; startX = event.clientX - panX; startY = event.clientY - panY; });
  window.addEventListener("mouseup", () => { dragging = false; });
  window.addEventListener("mousemove", (event) => {
    if (!dragging) return;
    panX = event.clientX - startX;
    panY = event.clientY - startY;
    document.querySelectorAll("#preview-panel img").forEach((img) => { img.style.transform = imageTransform(); });
  });
}

function togglePlay() {
  if (playing) { clearInterval(playing); playing = null; return; }
  playing = setInterval(() => { activeStep = (activeStep + 1) % currentSeq().steps.length; render(); }, Number(el("speed-selector").value));
}

function render() {
  const steps = currentSeq().steps;
  activeStep = Math.max(0, Math.min(activeStep, steps.length - 1));
  el("step-label").textContent = `${currentStep().name || "Step"} ${activeStep + 1} of ${steps.length}`;
  el("sequence-slider").max = Math.max(0, steps.length - 1);
  el("sequence-slider").value = activeStep;
  el("pass-selector").innerHTML = steps.map((p, i) => `<option value="${i}" ${i === activeStep ? "selected" : ""}>${esc(p.name || p.stage_id)}</option>`).join("");
  document.querySelectorAll("[data-mode]").forEach((b) => b.classList.toggle("active", b.dataset.mode === mode));
  renderNavigator();
  renderPreview();
  renderEngineering();
  renderCards();
  renderComparison();
  renderProgression();
}

function renderNavigator() {
  el("sequence-navigator").innerHTML = `<h3>${esc(currentSeq().label)}</h3>${currentSeq().steps.map((p, i) => `<button class="${i === activeStep ? "active" : ""}" data-nav="${i}">${esc(p.name || p.stage_id)} <span class="badge">${esc(p.status)}</span></button>`).join("")}`;
  document.querySelectorAll("[data-nav]").forEach((b) => { b.onclick = () => { activeStep = Number(b.dataset.nav); render(); }; });
}

function imageSource(step, preferred) {
  if (!step) return "";
  if (preferred && step.downloads && step.downloads[preferred]) return step.downloads[preferred];
  return step.preview_path || step.downloads?.profile_png || step.downloads?.review_png || "";
}

function imgCell(step, label, preferred = null) {
  const src = imageSource(step, preferred);
  return `<div class="preview-cell"><strong>${esc(label)}</strong>${src ? `<img style="transform:${imageTransform()}" src="${esc(src)}">` : "<p>Preview unavailable</p>"}</div>`;
}

function renderPreview() {
  const steps = currentSeq().steps;
  const s = currentStep();
  const prev = steps[Math.max(0, activeStep - 1)];
  const next = steps[Math.min(steps.length - 1, activeStep + 1)];
  el("zoom-label").textContent = `${Math.round(zoom * 100)}%`;
  let html = "";
  if (mode === "previous-current") html = `<div class="preview-strip">${imgCell(prev, prev.name || "Previous")}${imgCell(s, s.name || "Current")}</div>`;
  else if (mode === "overlay") html = `<div class="overlay-stack">${[prev, s, next].map((p) => p ? `<img style="opacity:.58;transform:${imageTransform()}" src="${esc(imageSource(p))}">` : "").join("")}<p class="badge">Previous / Current / Next overlay</p></div>`;
  else if (mode === "cumulative") html = `<div class="overlay-stack">${steps.slice(0, activeStep + 1).map((p) => `<img style="opacity:.45;transform:${imageTransform()}" src="${esc(imageSource(p))}">`).join("")}<p class="badge">Cumulative to selected pass</p></div>`;
  else if (mode === "complete") html = `<div class="overlay-stack">${steps.map((p) => `<img style="opacity:.35;transform:${imageTransform()}" src="${esc(imageSource(p))}">`).join("")}<p class="badge">Complete flower</p></div>`;
  else if (mode === "original-normalized") html = `<div class="preview-strip">${imgCell(s, "Original coordinates", "profile_original_coordinates_png")}${imgCell(s, "Normalized geometry", "profile_normalized_png")}</div>`;
  else if (mode === "strip-outline") html = `<div class="preview-strip">${imgCell(s, "Strip outline", "profile_outline_png")}</div>`;
  else if (mode === "neutral-line") html = `<div class="preview-strip">${imgCell(s, "Neutral line", "profile_neutral_line_png")}</div>`;
  else if (mode === "bend-zones") html = `<div class="preview-strip">${imgCell(s, "Neutral line with bend zones", "profile_neutral_line_png")}</div><div class="zone-overlay">${bendZoneTable(s)}</div>`;
  else if (mode === "outline-neutral") html = `<div class="overlay-stack"><img style="opacity:.72;transform:${imageTransform()}" src="${esc(imageSource(s, "profile_outline_png"))}"><img style="opacity:.9;transform:${imageTransform()}" src="${esc(imageSource(s, "profile_neutral_line_png"))}"><p class="badge">Strip outline + derived neutral line</p></div>`;
  else html = `<div class="preview-strip">${imgCell(s, s.name || "Selected pass")}</div>`;
  el("preview-panel").innerHTML = html;
}

function exportReviewDecisions() {
  const payload = {
    schema_version: 1,
    drawing_units: {
      detected_unit: data.project.units?.detected || "Unitless",
      engineer_confirmed_unit: null,
      conversion_factor_to_mm: null,
      confirmed_by: "",
      confirmed_at: "",
      notes: ""
    },
    composite_passes: currentSeq().steps.map((step) => ({
      pass_id: step.pass_id,
      confirmed: false,
      confirmed_order: step.engineer_confirmed_order,
      profile_representation: step.profile_type,
      neutral_line_confirmed: false,
      physical_bends_confirmed: false,
      station_link_confirmed: false,
      notes: ""
    }))
  };
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = "manual_review_decisions.json";
  link.click();
  URL.revokeObjectURL(link.href);
}

function renderEngineering() {
  const s = currentStep();
  const matches = s.individual_profile_matches || [];
  const thickness = s.sheet_thickness || {};
  el("engineering-panel").innerHTML = `<h3>${esc(s.name || s.stage_id)}</h3><p><span class="badge warn">Candidate extraction - not approved for production use</span><span class="badge">${esc(s.tooling_link_status || "Tooling unlinked")}</span>${s.requires_review ? '<span class="badge warn">Review required</span>' : ""}</p>
  ${rows([["Sequence ID", s.sequence_id], ["Pass ID", s.pass_id], ["Profile ID", s.profile_id], ["Inferred order", s.inferred_order], ["Engineer-confirmed order", s.engineer_confirmed_order], ["Profile type", s.profile_type], ["Physical bend zones", s.physical_forming_bend_count ?? s.bend_count], ["Physical zone angle", s.physical_total_bend_angle ?? s.total_bend_angle], ["Expected neutral length", s.expected_neutral_length], ["Generated neutral length", s.generated_neutral_length], ["Neutral length error %", s.neutral_length_error_percent], ["Neutral length status", s.neutral_length_status], ["Developed length", s.developed_length_drawing_units], ["Developed length mm", s.developed_length_mm], ["Width", s.width], ["Height", s.height], ["Sheet thickness", thickness.value ?? s.sheet_thickness_drawing_units], ["Thickness method", thickness.calculation_method], ["Thickness samples", thickness.sampling_count], ["Thickness variation", thickness.variation], ["Thickness confidence", thickness.confidence], ["Contour confidence", s.contour_confidence ?? s.confidence], ["Order confidence", s.order_confidence], ["Duplicate group", s.duplicate_group_id]])}
  <details open><summary>Engineer review controls</summary>
    <label><input type="checkbox"> Confirm pass</label>
    <label><input type="checkbox"> Confirm neutral line</label>
    <label><input type="checkbox"> Confirm physical bends</label>
    <label>Known sheet thickness <input placeholder="drawing units"></label>
    <label>Stage type <select><option>intermediate flower section</option><option>actual machine station</option><option>reference geometry</option></select></label>
    <textarea placeholder="Review notes"></textarea>
  </details>
  <details><summary>Source entities</summary><pre>${esc((s.source_handles || []).join("\n"))}</pre><pre>${esc((s.source_layers || []).join("\n"))}</pre></details>
  <details><summary>Transformation matrix</summary><pre>${esc(JSON.stringify(s.transform_matrix_4x4 || [], null, 2))}</pre></details>
  <details open><summary>Bend zones</summary>${bendZoneTable(s)}</details>
  <details><summary>Diagnostics</summary>${rows([["Raw corner count", s.raw_geometry_corner_count], ["Vertex-level turn count", s.vertex_turn_count], ["Raw turning angle", s.raw_total_turning_angle]])}</details>
  <details open><summary>Individual-profile matches</summary>${matches.length ? matches.map((m) => `<p><span class="badge ${m.exact_match ? "ok" : "warn"}">${m.exact_match ? "Exact profile match" : "Similar profile match"}</span> ${esc(m.individual_profile_id)} score ${fmt(m.similarity_score)} diff ${fmt(m.geometric_difference)} <button data-stage="${esc(m.individual_profile_id)}">View matched station</button></p>`).join("") : "<p>No matched individual drawing</p>"}</details>
  <div class="downloads"><h4>Downloads</h4>${downloads(s.downloads || {})}</div>`;
}

function rows(items) { return items.map(([k, v]) => `<div class="data-row"><span>${esc(k)}</span><span>${fmt(v)}</span></div>`).join(""); }
function downloads(d) { return Object.entries(d).filter(([, v]) => v).map(([k, v]) => `<a href="${esc(v)}">${esc(k)}</a>`).join("") || "<p>No files available</p>"; }
function bendZoneTable(step) {
  const zones = step.bend_zones || step.physical_bends || [];
  return smallTable(["Zone", "u", "Angle", "Length", "Vertices"], zones.map((z) => [z.bend_zone_id || z.bend_id, z.u, z.signed_bend_angle, z.zone_length, z.contributing_vertex_count]));
}

function renderCards() {
  el("pass-cards").innerHTML = currentSeq().steps.map((p, i) => `<div class="pass-card ${i === activeStep ? "active" : ""}" data-card="${i}"><strong>${esc(p.name || p.stage_id)}</strong>${imageSource(p) ? `<img src="${esc(imageSource(p))}">` : ""}<p>${esc(p.profile_type || p.region_type)}</p><p>W ${fmt(p.width)} H ${fmt(p.height)} L ${fmt(p.developed_length_drawing_units)}</p><p>Bends ${fmt(p.physical_forming_bend_count ?? p.bend_count)} <span class="badge">${esc(p.status)}</span>${p.requires_review ? '<span class="badge warn">Review required</span>' : ""}</p></div>`).join("");
  document.querySelectorAll("[data-card]").forEach((c) => { c.onclick = () => { activeStep = Number(c.dataset.card); render(); }; });
}

function renderComparison() {
  const steps = currentSeq().steps;
  const a = steps[Math.max(0, activeStep - 1)] || {};
  const b = currentStep();
  el("comparison-panel").innerHTML = `<h3>Sequence Comparison</h3><p>Compare Pass <select id="compare-a">${steps.map((p, i) => `<option value="${i}" ${i === Math.max(0, activeStep - 1) ? "selected" : ""}>${esc(p.name)}</option>`)}</select> with Pass <select id="compare-b">${steps.map((p, i) => `<option value="${i}" ${i === activeStep ? "selected" : ""}>${esc(p.name)}</option>`)}</select></p>${rows([["Width change", (b.width || 0) - (a.width || 0)], ["Height change", (b.height || 0) - (a.height || 0)], ["Developed-length difference", (b.developed_length_drawing_units || 0) - (a.developed_length_drawing_units || 0)], ["Bend-count change", (b.physical_forming_bend_count || 0) - (a.physical_forming_bend_count || 0)], ["Mean contour distance", "drawing units only"], ["Maximum contour distance", "drawing units only"]])}`;
}

function renderProgression() {
  const seq = currentSeq();
  if (seq.type !== "composite") {
    el("progression-panel").innerHTML = "<h3>Flower Progression</h3><p>No composite-flower progression data for this sequence.</p>";
    return;
  }
  const flower = data.composite_flowers.find((item) => item.label === seq.label) || {};
  const bends = flower.bend_progression || [];
  const lengths = flower.developed_length_progression || [];
  const alignment = flower.station_alignment || [];
  const stepChanges = flower.profile_step_changes || [];
  const bendEvents = flower.bend_change_events || [];
  const segmentEvents = flower.segment_change_events || [];
  const completion = flower.review_completion || {};
  el("progression-panel").innerHTML = `<h3>Bend Progression</h3>${smallTable(["Bend ID", "Pass", "Angle", "Status"], bends.map((b) => [b.bend_id, b.pass_id, b.signed_angle, b.activation_status]))}
    <h3>Developed-length graph</h3><div>${lengths.map((p) => `<div class="data-row"><span>${esc(p.pass_id)}</span><span>${fmt(p.developed_length_drawing_units)} drawing units <span class="badge">${esc(p.classification)}</span></span></div>`).join("")}</div>
    <h3>What Changed?</h3>${smallTable(["From", "To", "Width Δ", "Height Δ", "Length Δ", "Max displacement", "Classification"], stepChanges.map((c) => [c.from_pass_id, c.to_pass_id, c.width_delta, c.height_delta, c.developed_length_delta, c.maximum_material_point_displacement, (c.classifications || []).join(", ")]))}
    <details open><summary>Bend change events</summary>${smallTable(["From", "To", "Bend", "Angle Δ", "Radius Δ", "Change"], bendEvents.map((e) => [e.from_pass_id, e.to_pass_id, e.bend_id, e.angle_delta, e.radius_delta, e.change_classification]))}</details>
    <details><summary>Segment change events</summary>${smallTable(["From", "To", "Segment", "Length Δ", "Orientation Δ", "Change"], segmentEvents.map((e) => [e.from_pass_id, e.to_pass_id, e.segment_index, e.length_delta, e.orientation_delta, e.change_classification]))}</details>
    <h3>Station alignment view</h3>${smallTable(["Composite pass", "Matched drawing", "Status", "Score"], alignment.map((a) => [a.composite_pass_id, a.individual_profile_id || "Unmatched", a.link_status, a.similarity_score]))}
    <h3>Review completion</h3>${rows([["Passes confirmed", completion.passes_confirmed || 0], ["Orders confirmed", completion.orders_confirmed || 0], ["Bends confirmed", completion.bends_confirmed || 0], ["Units confirmed", completion.units_confirmed || false], ["Station links confirmed", completion.station_links_confirmed || 0], ["Tooling links confirmed", completion.tooling_links_confirmed || 0]])}`;
}

function smallTable(headings, rowsData) {
  return `<table><thead><tr>${headings.map((h) => `<th>${esc(h)}</th>`).join("")}</tr></thead><tbody>${rowsData.slice(0, 80).map((row) => `<tr>${row.map((cell) => `<td>${fmt(cell)}</td>`).join("")}</tr>`).join("")}</tbody></table>`;
}

document.addEventListener("DOMContentLoaded", init);
