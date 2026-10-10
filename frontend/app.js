const form = document.getElementById("upload-form");
const statusBox = document.getElementById("status");
const results = document.getElementById("results");
const aiBox = document.getElementById("use-ai");
const fileInput = document.getElementById("file");
const dropzone = document.getElementById("dropzone");
const fileMeta = document.getElementById("file-meta");
const errorSummary = document.getElementById("error-summary");
const MAX_BYTES = 20 * 1024 * 1024;
const BATCH_MAX_FILES = 5;
const BATCH_MAX_TOTAL = 40 * 1024 * 1024;

fetch("/api/health").then(r => r.json()).then(h => {
  if (h.ai_available) {
    aiBox.disabled = false;
  } else {
    document.getElementById("ai-note").textContent = "AI checks are not configured on this server, rule-based checks only.";
  }
}).catch(() => {});

function link(href, text) {
  const a = document.createElement("a");
  a.href = href;
  a.textContent = text;
  return a;
}

fetch("/api/me").then(r => r.json()).then(me => {
  const bar = document.getElementById("auth-bar");
  if (!me.sso_enabled) return;
  if (me.user) {
    bar.append(" Signed in as " + me.user.email + ". ", link("/auth/logout", "Sign out"));
  } else {
    bar.append(" Sign in required. ", link("/auth/login", "Sign in with Google"));
    document.getElementById("submit").disabled = true;
  }
}).catch(() => {});

function clear(el) {
  while (el.firstChild) el.removeChild(el.firstChild);
}

function formatBytes(bytes) {
  return bytes < 1024 * 1024 ? Math.round(bytes / 1024) + " KB" : (bytes / (1024 * 1024)).toFixed(1) + " MB";
}

function showError(message) {
  errorSummary.textContent = message;
  errorSummary.hidden = false;
  statusBox.textContent = "";
}

function clearError() {
  errorSummary.hidden = true;
  errorSummary.textContent = "";
}

function setFile(file) {
  clearError();
  if (!file) {
    fileMeta.hidden = true;
    return false;
  }
  if (file.type !== "application/pdf" && !file.name.toLowerCase().endsWith(".pdf")) {
    showError("Please choose a PDF file.");
    fileInput.value = "";
    return false;
  }
  if (file.size > MAX_BYTES) {
    showError("This file is larger than 20 MB. Choose a smaller PDF.");
    fileInput.value = "";
    return false;
  }
  const name = document.createElement("strong");
  name.textContent = file.name;
  const size = document.createElement("span");
  size.textContent = formatBytes(file.size);
  clear(fileMeta);
  fileMeta.append(name, size);
  fileMeta.hidden = false;
  return true;
}

fileInput.addEventListener("change", () => setFile(fileInput.files[0]));
["dragenter", "dragover"].forEach(eventName => dropzone.addEventListener(eventName, event => {
  event.preventDefault();
  dropzone.classList.add("dragover");
}));
["dragleave", "drop"].forEach(eventName => dropzone.addEventListener(eventName, event => {
  event.preventDefault();
  dropzone.classList.remove("dragover");
}));
dropzone.addEventListener("drop", event => {
  const file = event.dataTransfer.files[0];
  if (!file) return;
  const transfer = new DataTransfer();
  transfer.items.add(file);
  fileInput.files = transfer.files;
  setFile(file);
});

function statusClass(status) {
  return status.split(" ")[0];
}


// Pager state: which highlighted pages exist and which one is showing
let pageKeys = [];
let pageIndex = 0;

function showPageAt(i) {
  if (!pageKeys.length) return;
  pageIndex = Math.max(0, Math.min(i, pageKeys.length - 1));
  pageKeys.forEach((p, n) => {
    document.getElementById("page-card-" + p).hidden = n !== pageIndex;
  });
  document.getElementById("page-label").textContent =
    "Page " + pageKeys[pageIndex] + " (" + (pageIndex + 1) + "/" + pageKeys.length + ")";
  document.getElementById("page-prev").disabled = pageIndex === 0;
  document.getElementById("page-next").disabled = pageIndex === pageKeys.length - 1;
}

document.getElementById("page-prev").addEventListener("click", () => showPageAt(pageIndex - 1));
document.getElementById("page-next").addEventListener("click", () => showPageAt(pageIndex + 1));

// Used by the "Show page N" buttons in the findings list
function showHighlightedPage(p) {
  const i = pageKeys.indexOf(String(p));
  if (i < 0) return;
  showPageAt(i);
  const card = document.getElementById("page-card-" + p);
  const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  card.scrollIntoView({ behavior: reduce ? "auto" : "smooth", block: "center" });
  card.focus({ preventScroll: true });
  card.classList.add("flash");
  setTimeout(() => card.classList.remove("flash"), 2000);
}

function render(data) {
  document.getElementById("score-value").textContent = data.score + "/100";
  document.getElementById("score-grade").textContent = data.grade + " accessibility profile";
  document.getElementById("pages-value").textContent = data.pages_checked + " / " + data.pages;
  document.getElementById("pages-detail").textContent = data.pages === data.pages_checked ? "Full document reviewed" : "Page limit applied";
  const counts = data.criteria.reduce((out, criterion) => {
    const status = statusClass(criterion.status);
    out[status] = (out[status] || 0) + 1;
    return out;
  }, {});
  document.getElementById("passed-value").textContent = (counts.Passed || 0) + " / " + data.criteria.length;
  document.getElementById("criteria-detail").textContent = (counts.Failed || 0) + " failed, " + (counts.Cannot || 0) + " need review";
  document.getElementById("ai-value").textContent = data.ai_used ? "Used" : "Not used";
  document.getElementById("ai-detail").textContent = data.ai_used ? "Alt text assisted by AI" : "Rule-based checks only";

  const body = document.getElementById("criteria");
  clear(body);
  data.criteria.forEach(c => {
    const item = document.createElement("div");
    item.className = "criterion";
    const name = document.createElement("span");
    name.className = "criterion-name";
    name.textContent = c.label;
    const status = document.createElement("span");
    status.className = "status-pill " + statusClass(c.status);
    status.textContent = c.status;
    item.append(name, status);
    body.appendChild(item);
  });
  document.getElementById("criteria-legend").textContent = (counts.Passed || 0) + " passed";

  const list = document.getElementById("findings");
  clear(list);
  if (!data.findings.length) {
    const li = document.createElement("li");
    li.className = "empty-state";
    li.textContent = "No page-level problems were found in the checks that could be measured.";
    list.appendChild(li);
  }

    const labels = Object.fromEntries(data.criteria.map(c => [c.id, c.label]));

  data.findings.forEach(f => {
    const li = document.createElement("li");
    const where = f.page !== null ? " (page " + (f.page + 1) + ")" : "";
    const head = document.createElement("strong");
    head.textContent = f.status + " / " + f.severity + " / " + (labels[f.criterion] || f.criterion) + where;
    head.className = "finding-head " + statusClass(f.status);
    const message = document.createElement("span");
    message.className = "finding-message";
    message.textContent = f.message;
    li.append(head, message);
    if (f.fix) {
      const fix = document.createElement("span");
      fix.className = "fix";
      fix.textContent = f.fix;
      li.appendChild(fix);
    }
    // Button that jumps to the highlighted page for this finding
    if (f.page !== null && data.highlights[f.page + 1]) {
      const jump = document.createElement("button");
      jump.type = "button";
      jump.className = "text-button";
      jump.textContent = "Show page " + (f.page + 1);
      jump.addEventListener("click", () => showHighlightedPage(f.page + 1));
      li.appendChild(jump);
    }
    list.appendChild(li);
  });

  const box = document.getElementById("highlights");
  clear(box);
  pageKeys = Object.keys(data.highlights);
  pageKeys.forEach(p => {
    const figure = document.createElement("figure");
    figure.className = "highlight-card";
    figure.id = "page-card-" + p;
    figure.tabIndex = -1;
    const img = document.createElement("img");
    img.src = "data:image/png;base64," + data.highlights[p];
    img.alt = "Page " + p + " with problem areas outlined in red";
    const caption = document.createElement("figcaption");
    const issues = data.findings
      .map((f, i) => ({ f, n: i + 1 }))
      .filter(x => x.f.page !== null && String(x.f.page + 1) === p)
      .map(x => "#" + x.n + " " + x.f.message);
    caption.textContent = "Page " + p + " / " + (issues.length ? issues.join("  ") : "problem areas");
    figure.append(img, caption);
    box.appendChild(figure);
  });
  document.getElementById("pager").hidden = pageKeys.length === 0;
  if (pageKeys.length) {
    showPageAt(0);
  } else {
    const empty = document.createElement("p");
    empty.className = "empty-state";
    empty.textContent = "No page-level problem areas to show.";
    box.appendChild(empty);
  }

  results.hidden = false;
  document.getElementById("results-heading").focus();
}

form.addEventListener("submit", async e => {
  e.preventDefault();
  const button = document.getElementById("submit");
  if (!fileInput.files[0] || !setFile(fileInput.files[0])) return;
  clearError();
  button.disabled = true;
  statusBox.textContent = "Reading document structure and visual content...";
  results.hidden = true;
  try {
    const res = await fetch("/api/audit", { method: "POST", body: new FormData(form) });
    const data = await res.json();
    if (res.status === 401) throw new Error("Please sign in first.");
    if (!res.ok) throw new Error(data.detail || "Audit failed.");
    statusBox.textContent = "Audit complete.";
    render(data);
  } catch (err) {
    showError(err.message);
  } finally {
    button.disabled = false;
  }
});

document.getElementById("new-audit").addEventListener("click", () => {
  results.hidden = true;
  form.reset();
  fileMeta.hidden = true;
  clearError();
  statusBox.textContent = "Ready for another document.";
  document.getElementById("workspace-heading").focus();
});

const batchWorkspace = document.getElementById("batch-workspace");
const batchInput = document.getElementById("batch-files");
const batchMeta = document.getElementById("batch-file-meta");
const batchResults = document.getElementById("batch-results");
const batchStatus = document.getElementById("batch-status");

function setBatchFiles(files) {
  const selected = Array.from(files || []);
  const total = selected.reduce((sum, file) => sum + file.size, 0);
  if (!selected.length) {
    batchMeta.hidden = true;
    return false;
  }
  if (selected.length > BATCH_MAX_FILES) {
    batchStatus.textContent = "Select no more than 5 PDFs.";
    batchInput.value = "";
    batchMeta.hidden = true;
    return false;
  }
  if (total > BATCH_MAX_TOTAL || selected.some(file => file.type !== "application/pdf" && !file.name.toLowerCase().endsWith(".pdf"))) {
    batchStatus.textContent = total > BATCH_MAX_TOTAL ? "The batch is larger than 40 MB." : "Every selected file must be a PDF.";
    batchInput.value = "";
    batchMeta.hidden = true;
    return false;
  }
  const names = document.createElement("strong");
  names.textContent = selected.length + " PDF" + (selected.length === 1 ? "" : "s") + " selected";
  const size = document.createElement("span");
  size.textContent = formatBytes(total) + " total";
  clear(batchMeta);
  batchMeta.append(names, size);
  batchMeta.hidden = false;
  batchStatus.textContent = "";
  return true;
}

batchInput.addEventListener("change", () => setBatchFiles(batchInput.files));
document.getElementById("show-batch").addEventListener("click", () => {
  document.querySelector(".workspace:not(.batch-workspace)").hidden = true;
  batchWorkspace.hidden = false;
  document.getElementById("batch-heading").focus();
});
document.getElementById("show-single").addEventListener("click", () => {
  batchWorkspace.hidden = true;
  document.querySelector(".workspace:not(.batch-workspace)").hidden = false;
  document.getElementById("workspace-heading").focus();
});

const batchForm = document.getElementById("batch-form");
batchForm.addEventListener("submit", async event => {
  event.preventDefault();
  if (!setBatchFiles(batchInput.files)) return;
  const button = document.getElementById("batch-submit");
  button.disabled = true;
  batchStatus.textContent = "Auditing files in parallel...";
  batchResults.hidden = true;
  try {
    const response = await fetch("/api/audit-batch", { method: "POST", body: new FormData(batchForm) });
    const data = await response.json();
    if (response.status === 401) throw new Error("Please sign in first.");
    if (!response.ok) throw new Error(data.detail || "Batch audit failed.");
    clear(batchResults);
    const summary = document.createElement("p");
    summary.className = "batch-summary";
    summary.append(document.createElement("strong"));
    summary.firstChild.textContent = data.files + " files reviewed";
    summary.append(" · " + data.wall_seconds + " seconds · " + data.workers + " workers");
    const list = document.createElement("div");
    list.className = "batch-list";
    data.results.forEach(result => {
      const item = document.createElement("div");
      item.className = "batch-item";
      const name = document.createElement("span");
      name.className = "batch-item-name";
      name.textContent = result.file;
      if (result.error) {
        item.append(name, document.createTextNode(result.error));
      } else {
        const score = document.createElement("strong");
        score.className = "batch-item-score";
        score.textContent = result.score + "/100";
        const detail = document.createElement("span");
        detail.className = "batch-item-finding";
        detail.textContent = result.grade + " · " + result.seconds + "s · " + (result.top_findings[0] || "No findings");
        item.append(name, score, detail);
      }
      list.appendChild(item);
    });
    batchResults.append(summary, list);
    batchResults.hidden = false;
    batchStatus.textContent = "Batch audit complete.";
  } catch (error) {
    batchStatus.textContent = error.message;
  } finally {
    button.disabled = false;
  }
});

// ---------------------------------------------------------------
// Platform status view (security posture and instance metrics)
// ---------------------------------------------------------------
const platformStatus = document.getElementById("platform-status");

function cell(tag, text, cls) {
  const c = document.createElement(tag);
  c.textContent = text;
  if (cls) c.className = cls;
  return c;
}

const CLASS = { Pass: "Passed", Warn: "Cannot", Fail: "Failed" };
const FEATURED_METRICS = [
  ["instance", "Serving instance"],
  ["cpu_percent", "CPU utilization", "%"],
  ["process_memory_mb", "Process memory", " MB"],
  ["audit_latency_p95_seconds", "Audit p95 latency", " s"],
];

async function load() {
  platformStatus.textContent = "Loading.";
  try {
    const [pr, mr] = await Promise.all([fetch("/api/posture"), fetch("/api/metrics")]);
    if (pr.status === 401 || mr.status === 401) throw new Error("Please sign in first from the main page.");
    const posture = await pr.json();
    const metrics = await mr.json();

    document.getElementById("posture-score").textContent = posture.score + "/100 · " + posture.passed + " of " + posture.total + " passed";
    const postureSummary = document.getElementById("posture-summary");
    clear(postureSummary);
    const postureState = cell("strong", posture.score >= 80 ? "Healthy baseline" : "Review recommended", posture.score >= 80 ? "Passed" : "Cannot");
    const postureNote = cell("span", "Application-level checks are evaluated on every refresh.");
    postureSummary.append(postureState, postureNote);
    const body = document.getElementById("posture");
    clear(body);
    posture.checks.forEach(c => {
      const tr = document.createElement("tr");
      const detail = c.detail + (c.fix ? " Fix: " + c.fix : "");
      tr.append(cell("td", c.category), cell("th", c.title), cell("td", c.status, CLASS[c.status]), cell("td", detail));
      tr.children[1].scope = "row";
      body.appendChild(tr);
    });

    const mbody = document.getElementById("metrics");
    clear(mbody);
    const cards = document.getElementById("metric-cards");
    clear(cards);
    FEATURED_METRICS.forEach(([key, label, suffix = ""]) => {
      const card = document.createElement("div");
      card.className = "metric-card";
      card.append(cell("span", label, "card-label"));
      const value = metrics[key] === null || metrics[key] === undefined ? "n/a" : String(metrics[key]) + suffix;
      card.append(cell("strong", value));
      cards.appendChild(card);
    });
    Object.keys(metrics).forEach(k => {
      const tr = document.createElement("tr");
      const value = metrics[k] === null ? "n/a" : Array.isArray(metrics[k]) ? metrics[k].join(", ") : String(metrics[k]);
      tr.append(cell("th", k.replace(/_/g, " ")), cell("td", value));
      tr.children[0].scope = "row";
      mbody.appendChild(tr);
    });
    platformStatus.textContent = "Updated.";
  } catch (err) {
    platformStatus.textContent = "Error: " + err.message;
  }
}

document.getElementById("refresh").addEventListener("click", load);

// Status view: open and close, refresh every 10 seconds while it is visible.
const statusView = document.getElementById("status-view");
const auditViews = () => [document.querySelector(".workspace:not(.batch-workspace)"), batchWorkspace, results];
document.getElementById("show-status").addEventListener("click", () => {
  auditViews().forEach(el => { el.hidden = true; });
  statusView.hidden = false;
  document.getElementById("status-heading").focus();
  load();
});
document.getElementById("hide-status").addEventListener("click", () => {
  statusView.hidden = true;
  document.querySelector(".workspace:not(.batch-workspace)").hidden = false;
  document.getElementById("workspace-heading").focus();
});
setInterval(() => { if (!statusView.hidden) load(); }, 10000);
