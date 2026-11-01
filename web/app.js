const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];
let jobs = [];
let profile = null;
let account = null;
let pendingDeleteJob = null;
let renderedAgentRunId = "";

async function api(path, options = {}) {
  const headers = { ...(options.headers || {}) };
  if (!(options.body instanceof FormData)) headers["Content-Type"] = headers["Content-Type"] || "application/json";
  const response = await fetch(path, {
    ...options,
    headers,
  });
  const data = await response.json().catch(() => ({}));
  if (response.status === 401) { location.replace("/login"); throw new Error("Please sign in again."); }
  if (!response.ok) throw new Error(data.detail || `Request failed (${response.status})`);
  return data;
}

function toast(message, isError = false) {
  const element = $("#toast");
  element.textContent = message;
  element.classList.toggle("error", isError);
  element.classList.add("show");
  window.clearTimeout(toast.timer);
  toast.timer = window.setTimeout(() => element.classList.remove("show"), 3200);
}

function setConnection(online) {
  const pill = $(".connection-pill");
  pill.classList.toggle("online", online);
  pill.classList.toggle("offline", !online);
  $("#connection-label").textContent = online ? "Connected" : "Offline";
}

function setPage(pageName, targetId = "") {
  const profilePage = pageName === "profile";
  $$(".nav-link").forEach((button) => button.classList.toggle("active", button.dataset.page === pageName));
  $$(".page").forEach((section) => section.classList.toggle("active", section.id === (profilePage ? "profile-page" : "dashboard-page")));
  const labels = { overview: "Overview", opportunities: "Opportunities", analysis: "Role analysis", profile: "My profile" };
  $("#breadcrumb-current").textContent = labels[pageName] || "Overview";
  if (profilePage) loadProfile();
  if (targetId && !profilePage) document.getElementById(targetId)?.scrollIntoView({ behavior: "smooth", block: "start" });
  else if (profilePage) window.scrollTo({ top: 0, behavior: "smooth" });
}

function updateProfileBadge() {
  const name = profile?.full_name?.trim() || account?.full_name?.trim();
  const initial = name || account?.email?.split("@")[0] || "?";
  $("#user-avatar").textContent = initial[0].toUpperCase();
  $("#user-avatar").title = name || account?.email || "Your account";
}

function makeJobCard(job) {
  const row = document.createElement("article");
  row.className = "opportunity-row";
  const main = document.createElement("div");
  main.className = "role-main";
  const title = document.createElement("h3");
  title.className = "job-title";
  title.textContent = job.title;
  const meta = document.createElement("div");
  meta.className = "role-meta";
  const company = document.createElement("span");
  company.textContent = job.company;
  const dot = document.createElement("i");
  const date = document.createElement("span");
  date.textContent = job.created_at ? new Date(job.created_at).toLocaleDateString(undefined, { month: "short", day: "numeric" }) : "Just saved";
  meta.append(company, dot, date);
  main.append(title, meta);
  if (job.url && /^https?:\/\//i.test(job.url)) {
    const link = document.createElement("a");
    link.className = "job-original-link";
    link.href = job.url;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    link.textContent = "Open original posting ↗";
    main.append(link);
  }
  const briefButton = document.createElement("button");
  briefButton.type = "button";
  briefButton.className = "job-brief-button";
  briefButton.dataset.jobBrief = job.id;
  briefButton.setAttribute("aria-label", `Open application brief for ${job.title} at ${job.company}`);
  briefButton.textContent = "Application brief →";
  main.append(briefButton);
  const statusColumn = document.createElement("div");
  statusColumn.className = "role-status-column";
  const statusSelect = document.createElement("select");
  statusSelect.className = "role-status-select";
  statusSelect.dataset.jobStatus = job.id;
  statusSelect.setAttribute("aria-label", `Update status for ${job.title} at ${job.company}`);
  [["saved", "Saved"], ["applied", "Applied"], ["assessment", "Assessment"], ["interview", "Interview"], ["offer", "Offer"], ["rejected", "Closed"]].forEach(([value, label]) => {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = label;
    statusSelect.append(option);
  });
  statusSelect.value = job.status || "saved";
  statusColumn.append(statusSelect);
  const deleteButton = document.createElement("button");
  deleteButton.type = "button";
  deleteButton.className = "delete-job-button";
  deleteButton.dataset.deleteJob = job.id;
  deleteButton.setAttribute("aria-label", `Delete ${job.title} at ${job.company}`);
  deleteButton.title = "Delete this job";
  const trash = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  trash.setAttribute("viewBox", "0 0 20 20");
  trash.setAttribute("aria-hidden", "true");
  const trashPath = document.createElementNS("http://www.w3.org/2000/svg", "path");
  trashPath.setAttribute("d", "M4 6h12M8 6V4h4v2m3 0-.7 10H5.7L5 6m3 3v4m4-4v4");
  trashPath.setAttribute("fill", "none");
  trashPath.setAttribute("stroke", "currentColor");
  trashPath.setAttribute("stroke-width", "1.5");
  trashPath.setAttribute("stroke-linecap", "round");
  trashPath.setAttribute("stroke-linejoin", "round");
  trash.append(trashPath);
  deleteButton.append(trash);
  statusColumn.append(deleteButton);
  row.append(main, statusColumn);
  return row;
}
function renderJobs() {
  const list = $("#jobs-list");
  list.replaceChildren();
  const cutoff = ({ day: 1, week: 7, month: 30 })[$("#date-filter").value];
  const visibleJobs = jobs.filter((job) => {
    const ageDays = job.created_at ? (Date.now() - new Date(job.created_at).getTime()) / 86400000 : Infinity;
    return !cutoff || ageDays <= cutoff;
  });
  $("#jobs-count").textContent = visibleJobs.length === jobs.length ? `${jobs.length} ${jobs.length === 1 ? "role" : "roles"}` : `${visibleJobs.length} of ${jobs.length} roles`;
  $("#saved-count").textContent = jobs.filter((job) => job.status === "saved").length;
  $("#progress-count").textContent = jobs.filter((job) => ["applied", "interview", "assessment"].includes(job.status)).length;

  if (!visibleJobs.length) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.textContent = jobs.length ? "No roles match those filters. Try another search or status." : "No saved roles yet. Add an opportunity to get started.";
    list.append(empty);
  } else {
    visibleJobs.forEach((job) => list.append(makeJobCard(job)));
  }

  const select = $("#analysis-job-id");
  const previous = select.value;
  select.replaceChildren();
  if (!jobs.length) {
    const option = document.createElement("option");
    option.value = "";
    option.textContent = "Save a job first";
    select.append(option);
  } else {
    jobs.forEach((job) => {
      const option = document.createElement("option");
      option.value = job.id;
      option.textContent = `${job.title} · ${job.company}`;
      select.append(option);
    });
    if (jobs.some((job) => String(job.id) === previous)) select.value = previous;
  }
}

async function loadDashboard() {
  try {
    const [session, health, jobData, profileData] = await Promise.all([api("/auth/me"), api("/health"), api("/jobs"), api("/profile")]);
    account = session.user;
    const signoutControl = document.querySelector("#signout-button");
    if (signoutControl) signoutControl.title = session.user.email;
    jobs = jobData;
    profile = profileData;
    setConnection(health.database === "connected");
    renderJobs();
    updateProfileBadge();
    loadLatestAgentRun();
  } catch (error) {
    setConnection(false);
    $("#jobs-list").innerHTML = "<div class='empty-state'>Couldn’t load your workspace. Check that the API and database are running.</div>";
    toast(error.message, true);
  }
}

const signoutButton = document.querySelector("#signout-button");
signoutButton?.addEventListener("click", async () => {
  signoutButton.disabled = true;
  try { await fetch("/auth/logout", { method: "POST" }); }
  finally { location.replace("/"); }
});

async function loadProfile() {
  const form = $("#profile-form");
  try {
    profile = await api("/profile");
    form.elements.full_name.value = profile?.full_name || "";
    form.elements.target_role.value = profile?.target_role || "";
    form.elements.skills.value = profile?.skills || "";
    form.elements.experience_evidence.value = profile?.experience_evidence || "";
    updateProfileBadge();
  } catch (error) {
    toast(error.message, true);
  }
}

function renderAnalysis(result) {
  const container = $("#analysis-result");
  container.replaceChildren();
  container.classList.remove("hidden");
  const summary = document.createElement("div");
  summary.className = "analysis-summary";
  summary.textContent = result.summary;
  container.append(summary);

  const metrics = document.createElement("div");
  metrics.className = "analysis-metrics";
  [["Keyword fit", result.score === null ? "N/A" : `${result.score}%`], ["Supported by experience", result.matched], ["Skills-list only", result.partial], ["Not found in profile", result.gaps]].forEach(([label, value]) => {
    const item = document.createElement("div");
    item.className = "analysis-metric";
    const caption = document.createElement("span");
    caption.textContent = label;
    const strong = document.createElement("strong");
    strong.textContent = value;
    item.append(caption, strong);
    metrics.append(item);
  });
  container.append(metrics);

  if (result.skills.length) {
    const table = document.createElement("table");
    table.className = "skill-table";
    table.innerHTML = "<thead><tr><th>JOB SKILL</th><th>RESULT</th><th>PROFILE EVIDENCE</th></tr></thead>";
    const body = document.createElement("tbody");
    result.skills.forEach((item) => {
      const row = document.createElement("tr");
      const skillCell = document.createElement("td");
      skillCell.textContent = item.skill;
      const matchCell = document.createElement("td");
      const pill = document.createElement("span");
      pill.className = `match-pill ${item.match}`;
      pill.textContent = item.match;
      matchCell.append(pill);
      const evidenceCell = document.createElement("td");
      evidenceCell.textContent = item.evidence.length ? item.evidence.join("; ") : "No supporting evidence found";
      row.append(skillCell, matchCell, evidenceCell);
      body.append(row);
    });
    table.append(body);
    container.append(table);
  }
  if (result.quality_checks) {
    const audit = document.createElement("section");
    audit.className = `analysis-quality ${result.quality_checks.status === "review" ? "needs-review" : "is-checked"}`;
    const heading = document.createElement("strong");
    heading.textContent = result.quality_checks.status === "review" ? "Evidence check needs review" : "Evidence and score checks complete";
    const detail = document.createElement("p");
    detail.textContent = `${result.quality_checks.evidence_quotes_verified} of ${result.quality_checks.evidence_quotes_checked} evidence excerpts matched your saved experience. The fit score is calculated from the requirement labels.`;
    const scope = document.createElement("small");
    scope.textContent = result.quality_checks.scope;
    audit.append(heading, detail, scope);
    (result.quality_checks.warnings || []).forEach((warning) => {
      const item = document.createElement("p");
      item.className = "analysis-quality-warning";
      item.textContent = warning;
      audit.append(item);
    });
    container.append(audit);
  }
  const note = document.createElement("div");
  note.className = "analysis-footnote";
  note.textContent = result.note;
  container.append(note);
}

function setAnalysisView(view) {
  const analysisTab = $("#analysis-view-tab");
  const atsTab = $("#ats-view-tab");
  const showingAnalysis = view === "analysis";
  analysisTab.classList.toggle("active", showingAnalysis);
  atsTab.classList.toggle("active", !showingAnalysis);
  analysisTab.setAttribute("aria-selected", String(showingAnalysis));
  atsTab.setAttribute("aria-selected", String(!showingAnalysis));
  $("#analysis-result").classList.toggle("hidden", !showingAnalysis);
  $("#ats-result").classList.toggle("hidden", showingAnalysis);
}

function renderAtsSuggestions(result) {
  const container = $("#ats-result");
  container.replaceChildren();
  container.classList.remove("hidden");

  const heading = document.createElement("div");
  heading.className = "ats-heading";
  const scoreBlock = document.createElement("div");
  const scoreLabel = document.createElement("span");
  scoreLabel.textContent = "Estimated ATS keyword alignment";
  const score = document.createElement("strong");
  score.textContent = result.score === null ? "N/A" : `${result.score}%`;
  scoreBlock.append(scoreLabel, score);
  heading.append(scoreBlock);
  const progress = document.createElement("div");
  progress.className = "ats-progress";
  progress.setAttribute("role", "progressbar");
  progress.setAttribute("aria-label", "Estimated keyword alignment");
  progress.setAttribute("aria-valuemin", "0");
  progress.setAttribute("aria-valuemax", "100");
  progress.setAttribute("aria-valuenow", String(result.score ?? 0));
  const fill = document.createElement("span");
  fill.style.width = `${result.score ?? 0}%`;
  progress.append(fill);
  heading.append(progress);
  container.append(heading);

  const disclaimer = document.createElement("p");
  disclaimer.className = "ats-note";
  disclaimer.textContent = "This is an estimate from the selected job and your saved profile, not a score from a specific employer’s ATS.";
  container.append(disclaimer);

  const groups = [
    { key: "matched", title: "Supported keywords", recommendation: "Keep this keyword close to the relevant experience already in your resume." },
    { key: "partial", title: "Skills listed, proof to add", recommendation: "Your profile lists this skill. Add a concrete project or work example only if you have one." },
    { key: "gap", title: "Job keywords not found in profile", recommendation: "Don’t add this as a skill unless it is true. If you have used it, add the project or experience that proves it." },
  ];
  const keywordSection = document.createElement("section");
  keywordSection.className = "ats-keywords";
  const keywordHeading = document.createElement("h4");
  keywordHeading.textContent = "Suggested keywords from this job";
  keywordSection.append(keywordHeading);
  groups.forEach((group) => {
    const entries = result.skills.filter((item) => item.match === group.key);
    const row = document.createElement("div");
    row.className = "ats-keyword-row";
    const label = document.createElement("span");
    label.textContent = group.title;
    const chips = document.createElement("div");
    chips.className = "ats-keyword-chips";
    if (entries.length) {
      entries.forEach((item) => {
        const chip = document.createElement("span");
        chip.className = `ats-keyword-chip ${group.key}`;
        chip.textContent = item.skill;
        chips.append(chip);
      });
    } else {
      const none = document.createElement("small");
      none.textContent = "None identified";
      chips.append(none);
    }
    row.append(label, chips);
    keywordSection.append(row);
  });
  container.append(keywordSection);

  const changes = document.createElement("section");
  changes.className = "ats-changes";
  const changesHeading = document.createElement("h4");
  changesHeading.textContent = "Resume changes to consider";
  changes.append(changesHeading);
  result.skills.forEach((item) => {
    const group = groups.find((candidate) => candidate.key === item.match);
    if (!group) return;
    const card = document.createElement("article");
    card.className = "ats-change";
    const title = document.createElement("strong");
    title.textContent = item.skill;
    const recommendation = document.createElement("p");
    recommendation.textContent = group.recommendation;
    card.append(title, recommendation);
    if (item.match === "matched" && item.evidence?.length) {
      const evidence = document.createElement("small");
      evidence.textContent = `Existing evidence: ${item.evidence[0]}`;
      card.append(evidence);
    }
    changes.append(card);
  });
  container.append(changes);
}

$("#analysis-view-tabs").addEventListener("click", (event) => {
  const tab = event.target.closest("[data-analysis-view]");
  if (tab) setAnalysisView(tab.dataset.analysisView);
});

function renderApplicationBrief(brief) {
  const container = $("#application-brief-result");
  container.replaceChildren();
  container.classList.remove("hidden");

  const header = document.createElement("div");
  header.className = "application-brief-header";
  const title = document.createElement("div");
  const eyebrow = document.createElement("div");
  eyebrow.className = "eyebrow";
  eyebrow.textContent = "DRAFT FOR YOUR REVIEW";
  const heading = document.createElement("h3");
  heading.textContent = "Your application brief";
  title.append(eyebrow, heading);
  const copyButton = document.createElement("button");
  copyButton.type = "button";
  copyButton.className = "button brief-copy-button";
  copyButton.textContent = "Copy cover letter";
  header.append(title, copyButton);
  container.append(header);

  const letterSection = document.createElement("section");
  letterSection.className = "brief-section";
  const letterHeading = document.createElement("h4");
  letterHeading.textContent = "Cover letter draft";
  const groundingNote = document.createElement("small");
  groundingNote.className = "brief-grounding-note";
  groundingNote.textContent = "Built from your saved role and profile facts. Review and personalize before using.";
  const letter = document.createElement("p");
  letter.className = "brief-letter";
  letter.textContent = brief.cover_letter;
  letterSection.append(letterHeading, groundingNote, letter);
  container.append(letterSection);

  if (brief.talking_points.length) {
    const pointsSection = document.createElement("section");
    pointsSection.className = "brief-section";
    const pointsHeading = document.createElement("h4");
    pointsHeading.textContent = "Talking points backed by your experience";
    pointsSection.append(pointsHeading);
    brief.talking_points.forEach((item) => {
      const point = document.createElement("article");
      point.className = "brief-point";
      const statement = document.createElement("p");
      statement.textContent = item.point;
      const evidence = document.createElement("small");
      evidence.textContent = `Your evidence: ${item.supporting_evidence}`;
      point.append(statement, evidence);
      pointsSection.append(point);
    });
    container.append(pointsSection);
  }

  if (brief.areas_to_strengthen.length) {
    const gapsSection = document.createElement("section");
    gapsSection.className = "brief-section";
    const gapsHeading = document.createElement("h4");
    gapsHeading.textContent = "Evidence to strengthen";
    const list = document.createElement("ul");
    brief.areas_to_strengthen.forEach((item) => {
      const row = document.createElement("li");
      row.textContent = item;
      list.append(row);
    });
    gapsSection.append(gapsHeading, list);
    container.append(gapsSection);
  }
}

async function loadSavedApplicationBrief(showEmptyState = false) {
  const jobId = $("#analysis-job-id").value;
  const container = $("#application-brief-result");
  if (!jobId) {
    container.replaceChildren();
    container.classList.add("hidden");
    return false;
  }
  container.classList.add("hidden");
  try {
    const saved = await api("/jobs/" + jobId + "/application-brief");
    const panel = $("#agent-run-result");
    const status = $("#agent-run-status");
    const message = $("#agent-run-message");
    panel.classList.remove("hidden");
    $("#analysis-result").classList.add("hidden");
    $("#ats-result").classList.add("hidden");
    $("#analysis-view-tabs").hidden = true;
    if (saved.brief) {
      renderApplicationBrief(saved.brief);
      $("#agent-run-steps").replaceChildren();
      status.textContent = "Saved draft";
      status.dataset.state = "completed";
      message.textContent = "This brief is saved for the selected opportunity. Run the ApplyWise agent to refresh both analysis and draft.";
      setAgentPanelExpanded(true);
      return true;
    }
    container.replaceChildren();
    if (showEmptyState) {
      const message = document.createElement("p");
      message.className = "brief-empty";
      message.textContent = "No brief saved for this job yet. Run the ApplyWise agent to create one.";
      container.append(message);
      container.classList.remove("hidden");
      $("#agent-run-steps").replaceChildren();
      status.textContent = "No saved draft";
      status.dataset.state = "";
      $("#agent-run-message").textContent = "The agent will analyze the role and prepare its brief together.";
      setAgentPanelExpanded(true);
    }
    return false;
  } catch (error) {
    toast(error.message, true);
    return false;
  }
}

function renderEvidenceMatches(matches) {
  const container = $("#evidence-search-results");
  container.replaceChildren();
  if (!matches.length) {
    const empty = document.createElement("p");
    empty.className = "evidence-search-empty";
    empty.textContent = "No profile evidence was found. Add skills or experience to My profile, then try again.";
    container.append(empty);
    return;
  }
  matches.forEach((match) => {
    const card = document.createElement("article");
    card.className = "evidence-match";
    const meta = document.createElement("div");
    meta.className = "evidence-match-meta";
    const source = document.createElement("span");
    source.textContent = match.source;
    const similarity = document.createElement("span");
    similarity.textContent = `Similarity ${Number(match.similarity).toFixed(2)}`;
    meta.append(source, similarity);
    const text = document.createElement("p");
    text.textContent = match.text;
    card.append(meta, text);
    container.append(card);
  });
}

$$(".nav-link").forEach((button) => button.addEventListener("click", () => setPage(button.dataset.page, button.dataset.target || "")));
const sidebar = $("#app-shell");
const sidebarToggle = $("#sidebar-toggle");
function setSidebarCollapsed(collapsed) {
  sidebar.classList.toggle("sidebar-collapsed", collapsed);
  sidebarToggle.textContent = collapsed ? "›" : "‹";
  sidebarToggle.setAttribute("aria-label", collapsed ? "Expand sidebar" : "Collapse sidebar");
  sidebarToggle.title = collapsed ? "Expand sidebar" : "Collapse sidebar";
}
setSidebarCollapsed(localStorage.getItem("applywise-sidebar-collapsed") === "true");
sidebarToggle.addEventListener("click", () => {
  const collapsed = !sidebar.classList.contains("sidebar-collapsed");
  setSidebarCollapsed(collapsed);
  localStorage.setItem("applywise-sidebar-collapsed", String(collapsed));
});
$$('[data-jump]').forEach((button) => button.addEventListener("click", () => {
  const target = button.dataset.jump;
  if (target === "profile-page") setPage("profile");
  else setPage(target === "analysis-panel" ? "analysis" : "opportunities", target);
}));
$("#refresh-button").addEventListener("click", loadDashboard);
const addJobDialog = $("#add-job-dialog");
function openAddJobDialog() {
  addJobDialog.showModal();
  window.setTimeout(() => $("#job-form").elements.title.focus(), 0);
}
$("#add-job-button").addEventListener("click", openAddJobDialog);
$("#focus-job-button").addEventListener("click", openAddJobDialog);
$("#job-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const submitButton = form.querySelector("button[type=submit]");
  const payload = Object.fromEntries(new FormData(form).entries());
  submitButton.disabled = true;
  submitButton.textContent = "Saving…";
  try {
    await api("/jobs", { method: "POST", body: JSON.stringify(payload) });
    form.reset();
    addJobDialog.close();
    await loadDashboard();
    toast("Opportunity saved to your tracker.");
  } catch (error) { toast(error.message, true); }
  finally { submitButton.disabled = false; submitButton.innerHTML = 'Save role <span>→</span>'; }
});
$("#date-filter").addEventListener("change", renderJobs);
$("#jobs-list").addEventListener("change", async (event) => {
  const control = event.target.closest("[data-job-status]");
  if (!control) return;
  const job = jobs.find((item) => item.id === control.dataset.jobStatus);
  if (!job) return;
  const previousStatus = job.status;
  control.disabled = true;
  const selectedLabel = control.options[control.selectedIndex].text;
  try {
    const updated = await api(`/jobs/${job.id}`, { method: "PATCH", body: JSON.stringify({ status: control.value }) });
    Object.assign(job, updated);
    toast(`Status updated to ${selectedLabel}.`);
  } catch (error) {
    job.status = previousStatus;
    toast(error.message, true);
  }
  renderJobs();
});
$("#jobs-list").addEventListener("click", async (event) => {
  const briefButton = event.target.closest("[data-job-brief]");
  if (briefButton) {
    const job = jobs.find((item) => item.id === briefButton.dataset.jobBrief);
    if (!job) return;
    $("#analysis-job-id").value = job.id;
    setPage("analysis", "analysis-panel");
    await loadSavedApplicationBrief(true);
    $("#application-brief-result").scrollIntoView({ behavior: "smooth", block: "nearest" });
    return;
  }
  const button = event.target.closest("[data-delete-job]");
  if (!button) return;
  pendingDeleteJob = jobs.find((item) => item.id === button.dataset.deleteJob) || null;
  if (!pendingDeleteJob) return;
  $("#delete-job-message").textContent = `“${pendingDeleteJob.title}” at ${pendingDeleteJob.company} and its saved analysis will be removed from your workspace.`;
  $("#delete-job-dialog").showModal();
});
function closeDeleteDialog() {
  $("#delete-job-dialog").close();
  pendingDeleteJob = null;
}
$("#cancel-delete-job").addEventListener("click", closeDeleteDialog);
$("#close-delete-dialog").addEventListener("click", closeDeleteDialog);
$("#confirm-delete-job").addEventListener("click", async () => {
  if (!pendingDeleteJob) return;
  const job = pendingDeleteJob;
  const confirmButton = $("#confirm-delete-job");
  confirmButton.disabled = true;
  confirmButton.textContent = "Deleting…";
  try {
    await api(`/jobs/${job.id}`, { method: "DELETE" });
    jobs = jobs.filter((item) => item.id !== job.id);
    closeDeleteDialog();
    renderJobs();
    loadSavedApplicationBrief();
    toast("Job deleted from your tracker.");
  } catch (error) {
    toast(error.message, true);
  } finally {
    confirmButton.disabled = false;
    confirmButton.textContent = "Delete job";
    pendingDeleteJob = null;
  }
});
$("#profile-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const payload = Object.fromEntries(new FormData(event.currentTarget).entries());
  try {
    profile = await api("/profile", { method: "PUT", body: JSON.stringify(payload) });
    updateProfileBadge();
    toast("Your profile is saved.");
  } catch (error) { toast(error.message, true); }
});
$("#resume-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const file = $("#resume-file").files[0];
  if (!file) return toast("Choose a PDF or DOCX resume first.", true);
  const button = form.querySelector("button[type=submit]");
  const status = $("#resume-status");
  button.disabled = true;
  status.textContent = "Extracting text from your resume…";
  try {
    const upload = new FormData();
    upload.append("resume", file);
    const result = await api("/profile/resume", { method: "POST", body: upload });
    const evidence = $("#profile-form").elements.experience_evidence;
    const existing = evidence.value.trim();
    evidence.value = existing ? `${existing}\n\n--- Extracted from ${result.filename} ---\n${result.text}` : result.text;
    status.textContent = `Text extracted from ${result.filename}. Review the experience field, then click Save profile.`;
    evidence.focus();
  } catch (error) {
    status.textContent = error.message;
    toast(error.message, true);
  } finally {
    button.disabled = false;
  }
});
$("#analysis-job-id").addEventListener("change", () => {
  loadLatestAgentRun();
});

function setAgentPanelExpanded(expanded) {
  const panel = $("#agent-run-result");
  const toggle = $("#agent-run-toggle");
  panel.classList.toggle("is-collapsed", !expanded);
  toggle.setAttribute("aria-expanded", String(expanded));
  toggle.setAttribute("aria-label", expanded ? "Collapse agent details" : "Expand agent details");
  toggle.textContent = expanded ? "⌃" : "⌄";
}

$("#agent-run-toggle").addEventListener("click", () => {
  setAgentPanelExpanded($("#agent-run-toggle").getAttribute("aria-expanded") !== "true");
});

function renderAgentRun(run, expand = false) {
  const panel = $("#agent-run-result");
  const status = $("#agent-run-status");
  const steps = $("#agent-run-steps");
  const message = $("#agent-run-message");
  panel.classList.remove("hidden");
  setAgentPanelExpanded(expand);
  status.textContent = run.status === "completed" ? "Complete" : run.status === "failed" ? "Needs attention" : "In progress";
  status.dataset.state = run.status;
  steps.replaceChildren();
  (run.steps || []).forEach((step) => {
    const row = document.createElement("li");
    row.dataset.state = step.status;
    const mark = document.createElement("span");
    mark.className = "agent-step-mark";
    mark.textContent = step.status === "completed" ? "✓" : step.status === "running" ? "·" : "○";
    const copy = document.createElement("div");
    const name = document.createElement("strong");
    name.textContent = step.name;
    const detail = document.createElement("small");
    detail.textContent = step.detail || (step.status === "pending" ? "Waiting" : "Working");
    copy.append(name, detail);
    row.append(mark, copy);
    steps.append(row);
  });
  if (run.result?.analysis && renderedAgentRunId !== run.id) {
    renderAnalysis(run.result.analysis);
    renderAtsSuggestions(run.result.analysis);
    $("#analysis-view-tabs").hidden = false;
    setAnalysisView("analysis");
    renderedAgentRunId = run.id;
  }
  if (run.result?.brief) renderApplicationBrief(run.result.brief);

  if (run.status === "completed") {
    message.textContent = "Finished. Review the analysis and saved draft below; ApplyWise has not submitted anything.";
  } else if (run.status === "failed") {
    message.textContent = run.error || "The workflow could not finish. Please try again.";
  } else if (run.result?.analysis) {
    message.textContent = "Role analysis and ATS tips are ready. The application brief is still being prepared.";
  } else {
    message.textContent = "The agent is working through these steps. You can keep this page open.";
  }
}

async function loadLatestAgentRun() {
  const jobId = $("#analysis-job-id").value;
  const panel = $("#agent-run-result");
  renderedAgentRunId = "";
  if (!jobId) { panel.classList.add("hidden"); return; }
  panel.classList.add("hidden");
  try {
    const result = await api(`/jobs/${jobId}/agent-runs/latest`);
    let run = result.run;
    if (!run || $("#analysis-job-id").value !== jobId) return;
    renderAgentRun(run, run.status === "running");
    while (run.status === "running") {
      await new Promise((resolve) => window.setTimeout(resolve, 900));
      if ($("#analysis-job-id").value !== jobId) return;
      run = await api(`/agent-runs/${run.id}`);
      renderAgentRun(run, true);
    }
  } catch (error) {
    toast(error.message, true);
  }
}

$("#run-agent-button").addEventListener("click", async () => {
  const jobId = $("#analysis-job-id").value;
  if (!jobId) return toast("Save and select a job before running the ApplyWise agent.", true);
  const button = $("#run-agent-button");
  const panel = $("#agent-run-result");
  const steps = $("#agent-run-steps");
  const message = $("#agent-run-message");
  renderedAgentRunId = "";
  button.disabled = true;
  button.textContent = "Starting agent…";
  panel.classList.remove("hidden");
  setAgentPanelExpanded(true);
  $("#analysis-result").replaceChildren();
  $("#analysis-result").classList.add("hidden");
  $("#ats-result").replaceChildren();
  $("#ats-result").classList.add("hidden");
  $("#analysis-view-tabs").hidden = true;
  $("#application-brief-result").replaceChildren();
  $("#application-brief-result").classList.add("hidden");
  steps.replaceChildren();
  message.textContent = "Starting the application workflow…";
  panel.scrollIntoView({ behavior: "smooth", block: "nearest" });
  try {
    const started = await api(`/jobs/${jobId}/agent-run`, { method: "POST" });
    let run;
    do {
      run = await api(`/agent-runs/${started.id}`);
      renderAgentRun(run, true);
      if (run.status === "running") await new Promise((resolve) => window.setTimeout(resolve, 900));
    } while (run.status === "running");
    if (run.status === "completed") {
      $("#analysis-panel").scrollIntoView({ behavior: "smooth", block: "start" });
      toast("ApplyWise finished the workflow. Review your draft.");
    } else {
      toast(run.error || "The agent could not finish this run.", true);
    }
  } catch (error) {
    message.textContent = error.message;
    toast(error.message, true);
  } finally {
    button.disabled = false;
    button.innerHTML = 'Analyze + draft with ApplyWise <span>✦</span>';
  }
});

$("#application-brief-result").addEventListener("click", async (event) => {
  if (!event.target.closest(".brief-copy-button")) return;
  const letter = $("#application-brief-result .brief-letter")?.textContent || "";
  try {
    await navigator.clipboard.writeText(letter);
    toast("Cover letter copied.");
  } catch {
    toast("Copy failed. Select the cover letter text and copy it manually.", true);
  }
});

$("#evidence-search-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const query = form.elements.query.value.trim();
  const button = $("#evidence-search-button");
  const results = $("#evidence-search-results");
  button.disabled = true;
  button.textContent = "Searching…";
  results.textContent = "Finding the closest evidence in your profile…";
  try {
    const result = await api("/profile/search", { method: "POST", body: JSON.stringify({ query }) });
    renderEvidenceMatches(result.matches);
  } catch (error) {
    results.textContent = error.message;
    toast(error.message, true);
  } finally {
    button.disabled = false;
    button.innerHTML = 'Search evidence <span>→</span>';
  }
});
loadDashboard();
