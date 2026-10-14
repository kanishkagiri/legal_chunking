// LEGALGUARD frontend logic

let currentMode = "graph";
let activeData = null;

document.addEventListener("DOMContentLoaded", () => {
  initModeSelector();
  initTabs();
  initModal();

  const submitBtn = document.getElementById("submit-btn");
  const queryInput = document.getElementById("query-input");

  submitBtn.addEventListener("click", () => handleQuerySubmit());
  queryInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleQuerySubmit();
    }
  });
});

function initModeSelector() {
  const selector = document.getElementById("mode-select");
  selector.addEventListener("change", () => {
    currentMode = selector.value;
  });
}

function initTabs() {
  const tabs = document.querySelectorAll(".tab-btn");
  tabs.forEach((tab) => {
    tab.addEventListener("click", () => {
      tabs.forEach((t) => t.classList.remove("active"));
      tab.classList.add("active");

      const targetId = tab.getAttribute("data-tab");
      document.querySelectorAll(".tab-pane").forEach((pane) => {
        pane.classList.remove("active");
      });
      document.getElementById(targetId).classList.add("active");
    });
  });
}

function initModal() {
  const modal = document.getElementById("provision-modal");
  const closeBtn = document.getElementById("modal-close-btn");

  closeBtn.addEventListener("click", () => modal.classList.add("hidden"));
  modal.addEventListener("click", (e) => {
    if (e.target === modal) modal.classList.add("hidden");
  });
}

async function handleQuerySubmit() {
  const queryInput = document.getElementById("query-input");
  const question = queryInput.value.trim();
  if (!question) return;

  const topk = 8;
  const submitBtn = document.getElementById("submit-btn");
  const btnText = document.getElementById("btn-text");
  const btnSpinner = document.getElementById("btn-spinner");
  const btnIcon = document.getElementById("btn-icon");
  const queryStatus = document.getElementById("query-status-text");
  const queryTimer = document.getElementById("query-timer");
  const startedAt = performance.now();
  const updateTimer = () => {
    const elapsed = Math.floor((performance.now() - startedAt) / 1000);
    const minutes = String(Math.floor(elapsed / 60)).padStart(2, "0");
    const seconds = String(elapsed % 60).padStart(2, "0");
    if (queryTimer) queryTimer.textContent = `Elapsed: ${minutes}:${seconds}`;
  };
  const timerInterval = window.setInterval(updateTimer, 250);

  submitBtn.disabled = true;
  btnText.textContent = "Ask";
  if (queryStatus) {
    queryStatus.classList.remove("error");
    queryStatus.textContent = "Searching the Act and checking supporting claims. Local answer generation may take around 20 seconds.";
  }
  updateTimer();
  btnSpinner.classList.remove("hidden");
  btnIcon.classList.add("hidden");

  try {
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        question,
        mode: currentMode,
        top_k: topk,
      }),
    });

    if (!response.ok) {
      const err = await response.json();
      throw new Error(err.detail || "Server returned an error");
    }

    const data = await response.json();
    activeData = data;
    renderResults(data);
    if (queryStatus) queryStatus.textContent = "Response ready.";
  } catch (error) {
    if (queryStatus) {
      queryStatus.classList.add("error");
      queryStatus.textContent = `Could not complete the inquiry: ${error.message}`;
    } else {
      alert(`Could not complete the inquiry: ${error.message}`);
    }
  } finally {
    window.clearInterval(timerInterval);
    updateTimer();
    submitBtn.disabled = false;
    btnText.textContent = "Ask";
    btnSpinner.classList.add("hidden");
    btnIcon.classList.remove("hidden");
  }
}

function renderResults(data) {
  const resultsContainer = document.getElementById("results-container");
  resultsContainer.classList.remove("hidden");

  // Abstention Banner (if present)
  const abstentionBanner = document.getElementById("abstention-banner");
  if (abstentionBanner) {
    const abstentionMsg = document.getElementById("abstention-message");
    if (data.insufficient_evidence) {
      abstentionBanner.classList.remove("hidden");
      if (abstentionMsg) abstentionMsg.textContent = data.answer || "Insufficient evidence.";
    } else {
      abstentionBanner.classList.add("hidden");
    }
  }

  // Synthesized Answer
  renderAnswerPoints(data.answer || "No response generated.");
  const metaBox = document.getElementById("answer-meta");
  metaBox.innerHTML = `
    <span><strong>Mode:</strong> ${data.mode.toUpperCase()}</span>
  `;

  // Audited Atomic Claims
  const claimsList = document.getElementById("claims-list");
  const claimsPanel = document.getElementById("claims-panel");
  if (claimsList) {
    claimsList.innerHTML = "";
    const claims = data.claims || [];
    const countEl = document.getElementById("claim-count");
    if (countEl) countEl.textContent = claims.length;

    if (claims.length > 0) {
      if (claimsPanel) claimsPanel.classList.remove("hidden");
      claims.forEach((claim) => {
        claimsList.appendChild(createClaimCard(claim));
      });
    } else if (claimsPanel) {
      claimsPanel.classList.add("hidden");
    }
  }

  // Evidentiary Bundle
  const evidenceList = document.getElementById("evidence-list");
  evidenceList.innerHTML = "";
  const evidence = data.evidence_bundle || [];
  document.getElementById("evidence-count").textContent = evidence.length;

  evidence.forEach((ev) => {
    const evCard = document.createElement("div");
    evCard.className = "evidence-card";
    evCard.innerHTML = `
      <div class="evidence-card-header">
        <span class="citation-chip" onclick="openProvisionModal('${ev.evidence_id}')">${ev.citation} (${ev.evidence_id})</span>
        <span class="badge">${ev.node_type} • Rank Score: ${Number(ev.reranker_score || 0).toFixed(4)}</span>
      </div>
      <div class="evidence-body">${escapeHtml(ev.text)}</div>
    `;
    evidenceList.appendChild(evCard);
  });

  // Graph Tab
  renderGraphDetails(data);

  // Audit Tab
  document.getElementById("audit-trace-json").textContent = JSON.stringify(data, null, 2);

  // Smooth scroll
  resultsContainer.scrollIntoView({ behavior: "smooth", block: "start" });
}

function renderAnswerPoints(answer) {
  const container = document.getElementById("synthesized-answer");
  container.replaceChildren();

  let points = String(answer)
    .split(/\n+/)
    .map((point) => point.trim().replace(/^(?:[-*•]|\d+[.)])\s*/, ""))
    .filter(Boolean);
  if (points.length === 1) {
    points = points[0].split(/(?<=[.!?])\s+(?=[A-Z0-9])/).map((point) => point.trim()).filter(Boolean);
  }

  const list = document.createElement("ul");
  list.className = "answer-points";
  for (const point of points) {
    const item = document.createElement("li");
    item.textContent = point;
    list.appendChild(item);
  }
  container.appendChild(list);
}

function createClaimCard(claim) {
  const card = document.createElement("div");
  card.className = "claim-card";

  const allowedStatuses = new Set(["SUPPORTED", "CONTRADICTED", "UNSUPPORTED"]);
  const requestedStatus = String(claim.verification_status || "UNSUPPORTED").toUpperCase();
  const status = allowedStatuses.has(requestedStatus) ? requestedStatus : "UNSUPPORTED";
  const statusClass = `status-${status.toLowerCase()}`;
  const score = Math.max(0, Math.min(100, Number(claim.evidence_strength_score) || 0));

  let fillClass = "fill-weak";
  if (score >= 80) fillClass = "fill-strong";
  else if (score >= 65) fillClass = "fill-medium";
  else if (score >= 50) fillClass = "fill-limited";

  const citation = String(claim.citation || "Statute");
  const evId = String(claim.evidence_ids?.[0] || "");

  card.innerHTML = `
    <div class="claim-header">
      <div style="display: flex; align-items: center; gap: 0.5rem;">
        <span class="claim-id-badge">${escapeHtml(String(claim.claim_id || "Claim"))}</span>
        <span class="status-badge ${statusClass}">${status}</span>
        <button class="citation-chip claim-citation" data-evidence-id="${escapeHtml(evId)}">
          ${escapeHtml(citation)}
        </button>
      </div>
      <span class="strength-label">${claim.evidence_label || "Verified"} (${score}/100)</span>
    </div>
    <div class="claim-text">${escapeHtml(claim.text)}</div>
    <p class="claim-reason">${escapeHtml(claim.status_reason || "No verification details were provided.")}</p>
    ${
      claim.supporting_quote
        ? `<div class="quote-box">
             <span class="quote-label">Exact Statutory Excerpt:</span>
             "${escapeHtml(claim.supporting_quote)}"
           </div>`
        : ""
    }
    <div class="strength-container">
      <div class="strength-bar-bg">
        <div class="strength-bar-fill ${fillClass}" style="width: ${score}%;"></div>
      </div>
    </div>
    <button class="breakdown-toggle" onclick="toggleBreakdown(this)">
      <span>▸ Component Scores</span>
    </button>
    <div class="breakdown-box hidden">
      <div class="breakdown-item">
        <strong>Entailment (40%):</strong>
        <span>${claim.component_scores?.entailment || 0}/100</span>
      </div>
      <div class="breakdown-item">
        <strong>Relevance (25%):</strong>
        <span>${claim.component_scores?.relevance || 0}/100</span>
      </div>
      <div class="breakdown-item">
        <strong>Citation (20%):</strong>
        <span>${claim.component_scores?.citation_validity || 0}/100</span>
      </div>
      <div class="breakdown-item">
        <strong>Conditions (15%):</strong>
        <span>${claim.component_scores?.conditions_coverage || 0}/100</span>
      </div>
    </div>
  `;
  const citationButton = card.querySelector(".claim-citation");
  citationButton.addEventListener("click", () => openProvisionModal(citationButton.dataset.evidenceId));
  return card;
}

function toggleBreakdown(btn) {
  const box = btn.nextElementSibling;
  const isHidden = box.classList.contains("hidden");
  if (isHidden) {
    box.classList.remove("hidden");
    btn.querySelector("span").textContent = "▾ Hide Scores";
  } else {
    box.classList.add("hidden");
    btn.querySelector("span").textContent = "▸ Component Scores";
  }
}

function openProvisionModal(evidenceId) {
  if (!activeData) return;
  const ev = activeData.evidence_bundle?.find((e) => e.evidence_id === evidenceId);
  if (!ev) return;

  document.getElementById("modal-citation").textContent = ev.citation || "Statute";
  document.getElementById("modal-chapter").textContent = ev.chapter_title || "Consumer Protection Act, 2019";
  document.getElementById("modal-act-title").textContent = ev.act_title || "Consumer Protection Act, 2019";
  document.getElementById("modal-publisher").textContent = ev.source_publisher || "Government of India";
  document.getElementById("modal-date").textContent = ev.source_publication_date || "2019-08-09";
  document.getElementById("modal-pdf-link").href = ev.source_url || "#";
  document.getElementById("modal-text").textContent = ev.text || "";

  document.getElementById("provision-modal").classList.remove("hidden");
}

function renderGraphDetails(data) {
  const container = document.getElementById("graph-details");
  const graphItems = (data.evidence_bundle || []).filter(
    (e) => e.bridge_entity || (e.expansion_relationships && e.expansion_relationships.length > 0)
  );

  if (graphItems.length === 0) {
    const explanation = data.mode === "graph"
      ? "No graph-expanded provision made it into the final evidence list. The displayed provisions came from the initial similarity search; linked provisions may not have been available or may have ranked below the selected results."
      : `Graph expansion was not used in ${String(data.mode || "this").toUpperCase()} mode. Select Graph Hybrid to follow ontology and statutory citation links.`;
    container.innerHTML = `
      <div class="placeholder-text" style="color: #94a3b8;">
        ${escapeHtml(explanation)}
      </div>
    `;
    return;
  }

  let html = `<div class="evidence-list">`;
  graphItems.forEach((item) => {
    const rels = item.expansion_relationships || [];
    const relNames = rels.map((r) => r.type).join(", ") || "CITES / EXPANDS";
    html += `
      <div class="evidence-card">
        <div class="evidence-card-header">
          <span class="citation-chip">${item.citation}</span>
          <span class="badge badge-source">Bridge: ${item.bridge_entity_name || item.bridge_entity || "Direct Statutory Reference"}</span>
        </div>
        <p style="font-size: 0.8rem; color: #94a3b8; margin-bottom: 0.5rem;">
          <strong>Relationship:</strong> <code>${relNames}</code> •
          <strong>Review Status:</strong> <em>${item.relationship_review_status || "unreviewed"}</em>
        </p>
        <div class="evidence-body">${escapeHtml(item.text)}</div>
      </div>
    `;
  });
  html += `</div>`;
  container.innerHTML = html;
}

let activeCompareEvidence = {};

async function handleCompareSubmit() {
  const queryInput = document.getElementById("query-input");
  const question = queryInput.value.trim();
  if (!question) return;

  const topk = 5;
  const compareBtn = document.getElementById("compare-btn");
  const compareSpinner = document.getElementById("compare-spinner");
  const submitBtn = document.getElementById("submit-btn");

  compareBtn.disabled = true;
  submitBtn.disabled = true;
  compareSpinner.classList.remove("hidden");

  try {
    const response = await fetch("/api/compare", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, top_k: topk }),
    });

    if (!response.ok) {
      const err = await response.json();
      throw new Error(err.detail || "Comparison request failed");
    }

    const data = await response.json();
    renderComparison(data);
  } catch (error) {
    alert(`Failed to compare modes: ${error.message}`);
  } finally {
    compareBtn.disabled = false;
    submitBtn.disabled = false;
    compareSpinner.classList.add("hidden");
  }
}

function renderComparison(data) {
  const compSection = document.getElementById("comparison-section");
  compSection.classList.remove("hidden");

  const resultsSection = document.getElementById("results-container");
  resultsSection.classList.add("hidden");

  const summary = data.summary || {};
  document.getElementById("comparison-best-mode").textContent = `Top Recommended Mode: ${summary.best_mode ? summary.best_mode.toUpperCase() : "N/A"}`;
  document.getElementById("metric-union-citations").textContent = (summary.all_retrieved_citations || []).join(", ") || "None";
  document.getElementById("metric-common-citations").textContent = (summary.common_citations || []).join(", ") || "None (High Variance)";

  const verdictEl = document.getElementById("metric-mode-verdict");
  if (verdictEl) {
    verdictEl.textContent = summary.verdict || "Analysis completed.";
  }

  // Populate each mode column
  ["keyword", "vector", "graph"].forEach((modeKey) => {
    const modeData = data.modes?.[modeKey];
    if (!modeData) return;

    activeCompareEvidence[modeKey] = modeData.evidence_bundle || [];

    // Why This Mode Is Better advantage box
    const advEl = document.getElementById(`advantage-${modeKey}`);
    if (advEl) {
      const advInfo = summary.mode_advantages?.[modeKey];
      let advText = advInfo?.why_better || "";
      if (advInfo?.unique_citations?.length > 0) {
        advText += ` Exclusively surfaced: ${advInfo.unique_citations.join(", ")}`;
      }
      advEl.textContent = advText;
    }

    // Answer
    document.getElementById(`ans-${modeKey}`).textContent = modeData.answer || "No response.";

    // Citations list
    const citesEl = document.getElementById(`cites-${modeKey}`);
    citesEl.innerHTML = "";
    (modeData.evidence_bundle || []).forEach((ev) => {
      const chip = document.createElement("button");
      chip.className = "citation-chip";
      chip.textContent = ev.citation;
      chip.title = ev.chapter_title || "";
      chip.onclick = () => openProvisionModal(ev.evidence_id, modeKey);
      citesEl.appendChild(chip);
    });
  });

  compSection.scrollIntoView({ behavior: "smooth", block: "start" });
}

function openProvisionModal(evidenceId, modeKey) {
  let ev = null;
  if (modeKey && activeCompareEvidence[modeKey]) {
    ev = activeCompareEvidence[modeKey].find((e) => e.evidence_id === evidenceId || e.citation === evidenceId);
  }
  if (!ev && activeData) {
    ev = activeData.evidence_bundle?.find((e) => e.evidence_id === evidenceId || e.citation === evidenceId);
  }
  if (!ev) return;

  document.getElementById("modal-citation").textContent = ev.citation || "Statute";
  document.getElementById("modal-chapter").textContent = ev.chapter_title || "Consumer Protection Act, 2019";
  document.getElementById("modal-act-title").textContent = ev.act_title || "Consumer Protection Act, 2019";
  document.getElementById("modal-publisher").textContent = ev.source_publisher || "Government of India";
  document.getElementById("modal-date").textContent = ev.source_publication_date || "2019-08-09";
  document.getElementById("modal-pdf-link").href = ev.source_url || "#";
  document.getElementById("modal-text").textContent = ev.text || "";

  document.getElementById("provision-modal").classList.remove("hidden");
}

function escapeHtml(str) {
  if (!str) return "";
  return str
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}
