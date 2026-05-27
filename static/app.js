// ---------------------------------------------------------------------------
// App State Configuration
// ---------------------------------------------------------------------------
const BASE_URL = "/api/v1";
let authToken = sessionStorage.getItem("rag_token") || null;
let activeSessionId = sessionStorage.getItem("rag_session_id") || null;

// ---------------------------------------------------------------------------
// DOM Elements Query Selecctors
// ---------------------------------------------------------------------------
const authLoggedOut = document.getElementById("authLoggedOut");
const authLoggedIn = document.getElementById("authLoggedIn");
const loginBtn = document.getElementById("loginBtn");
const loginSpinner = document.getElementById("loginSpinner");
const usernameInput = document.getElementById("usernameInput");
const passwordInput = document.getElementById("passwordInput");
const authError = document.getElementById("authError");
const authUsername = document.getElementById("authUsername");
const userAvatar = document.getElementById("userAvatar");
const logoutBtn = document.getElementById("logoutBtn");

const deptSelect = document.getElementById("deptSelect");
const uploadZone = document.getElementById("uploadZone");
const fileInput = document.getElementById("fileInput");
const uploadProgressContainer = document.getElementById("uploadProgressContainer");
const uploadFileName = document.getElementById("uploadFileName");
const uploadFileSize = document.getElementById("uploadFileSize");
const uploadProgressFill = document.getElementById("uploadProgressFill");
const uploadStatusText = document.getElementById("uploadStatusText");

const sessionVal = document.getElementById("sessionVal");
const newSessionBtn = document.getElementById("newSessionBtn");
const clearSessionBtn = document.getElementById("clearSessionBtn");

const messagesViewport = document.getElementById("messagesViewport");
const welcomeCard = document.getElementById("welcomeCard");
const chatInput = document.getElementById("chatInput");
const sendBtn = document.getElementById("sendBtn");

// ---------------------------------------------------------------------------
// App Initialization
// ---------------------------------------------------------------------------
function init() {
    setupEventListeners();
    setupTabs();
    if (authToken) {
        setAuthorized(true);
        if (activeSessionId) {
            sessionVal.textContent = activeSessionId;
        } else {
            createNewSession();
        }
    } else {
        setAuthorized(false);
    }
}

// ---------------------------------------------------------------------------
// Event Listeners Registration
// ---------------------------------------------------------------------------
function setupEventListeners() {
    // Auth events
    loginBtn.addEventListener("click", handleLogin);
    logoutBtn.addEventListener("click", handleLogout);
    usernameInput.addEventListener("keydown", (e) => { if (e.key === "Enter") handleLogin(); });
    passwordInput.addEventListener("keydown", (e) => { if (e.key === "Enter") handleLogin(); });

    // Session control events
    newSessionBtn.addEventListener("click", createNewSession);
    clearSessionBtn.addEventListener("click", clearSessionHistory);

    // Ingestion Drag-and-Drop / Browse events
    uploadZone.addEventListener("click", () => fileInput.click());
    fileInput.addEventListener("change", handleFileSelection);

    uploadZone.addEventListener("dragover", (e) => {
        e.preventDefault();
        uploadZone.classList.add("dragover");
    });
    uploadZone.addEventListener("dragleave", () => {
        uploadZone.classList.remove("dragover");
    });
    uploadZone.addEventListener("drop", (e) => {
        e.preventDefault();
        uploadZone.classList.remove("dragover");
        if (e.dataTransfer.files.length > 0) {
            uploadFile(e.dataTransfer.files[0]);
        }
    });

    // Chat interface events
    chatInput.addEventListener("input", adjustTextareaHeight);
    chatInput.addEventListener("keydown", handleChatKeyDown);
    sendBtn.addEventListener("click", submitUserQuery);
}

// ---------------------------------------------------------------------------
// Authentication Handlers
// ---------------------------------------------------------------------------
async function handleLogin() {
    const username = usernameInput.value.trim();
    const password = passwordInput.value.trim();

    if (!username || !password) {
        showAuthError("Please fill out all fields.");
        return;
    }

    showAuthLoading(true);

    try {
        const res = await fetch(`${BASE_URL}/auth/token`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ username, password })
        });

        if (!res.ok) {
            const err = await res.json();
            throw new Error(err.detail || "Authentication failed.");
        }

        const data = await res.json();
        authToken = data.access_token;
        sessionStorage.setItem("rag_token", authToken);

        authUsername.textContent = username;
        userAvatar.textContent = username.charAt(0).toUpperCase();
        setAuthorized(true);

        // Auto-create session on success if none active
        if (!activeSessionId) {
            await createNewSession();
        }
    } catch (e) {
        showAuthError(e.message);
    } finally {
        showAuthLoading(false);
    }
}

function handleLogout() {
    authToken = null;
    activeSessionId = null;
    sessionStorage.removeItem("rag_token");
    sessionStorage.removeItem("rag_session_id");
    sessionVal.textContent = "Not Started";
    setAuthorized(false);
    messagesViewport.innerHTML = "";
    messagesViewport.appendChild(welcomeCard);
    welcomeCard.classList.remove("hidden");
}

function setAuthorized(authorized) {
    const ciqAnalyzeBtn = document.getElementById("ciqAnalyzeBtn");
    const cmpCompareBtn = document.getElementById("cmpCompareBtn");
    const oblExtractBtn = document.getElementById("oblExtractBtn");
    if (authorized) {
        authLoggedOut.classList.add("hidden");
        authLoggedIn.classList.remove("hidden");
        chatInput.disabled = false;
        sendBtn.disabled = false;
        if (ciqAnalyzeBtn) ciqAnalyzeBtn.disabled = false;
        if (cmpCompareBtn) cmpCompareBtn.disabled = false;
        if (oblExtractBtn) oblExtractBtn.disabled = false;
        uploadZone.style.pointerEvents = "auto";
        uploadZone.style.opacity = "1";
    } else {
        authLoggedOut.classList.remove("hidden");
        authLoggedIn.classList.add("hidden");
        chatInput.disabled = true;
        sendBtn.disabled = true;
        if (ciqAnalyzeBtn) ciqAnalyzeBtn.disabled = true;
        if (cmpCompareBtn) cmpCompareBtn.disabled = true;
        if (oblExtractBtn) oblExtractBtn.disabled = true;
        uploadZone.style.pointerEvents = "none";
        uploadZone.style.opacity = "0.5";
    }
}

function showAuthError(msg) {
    authError.textContent = msg;
    authError.classList.remove("hidden");
}

function showAuthLoading(loading) {
    if (loading) {
        loginBtn.disabled = true;
        loginSpinner.classList.remove("hidden");
        authError.classList.add("hidden");
    } else {
        loginBtn.disabled = false;
        loginSpinner.classList.add("hidden");
    }
}

// ---------------------------------------------------------------------------
// Document Ingestion
// ---------------------------------------------------------------------------
function handleFileSelection(e) {
    if (e.target.files.length > 0) {
        uploadFile(e.target.files[0]);
    }
}

async function uploadFile(file) {
    if (!authToken) return;

    // File validation
    const allowedExtensions = /(\.pdf|\.docx|\.txt|\.md)$/i;
    if (!allowedExtensions.exec(file.name)) {
        alert("Only PDF, DOCX, TXT, or MD files are supported.");
        return;
    }

    // Format UI states
    uploadProgressContainer.classList.remove("hidden");
    uploadFileName.textContent = file.name;
    uploadFileSize.textContent = formatBytes(file.size);
    uploadProgressFill.style.width = "10%";
    uploadStatusText.textContent = "Uploading file contents...";

    const formData = new FormData();
    formData.append("file", file);
    formData.append("department", deptSelect.value);

    try {
        uploadProgressFill.style.width = "40%";
        uploadStatusText.textContent = "Parsing and building semantic chunks...";

        const res = await fetch(`${BASE_URL}/ingest`, {
            method: "POST",
            headers: { "Authorization": `Bearer ${authToken}` },
            body: formData
        });

        if (!res.ok) {
            const err = await res.json();
            throw new Error(err.detail || "Upload failed.");
        }

        const data = await res.json();
        uploadProgressFill.style.width = "100%";
        uploadStatusText.innerHTML = `<span style="color: var(--success)">✓ Successfully ingested ${data.chunks_ingested} chunks!</span>`;
    } catch (e) {
        uploadProgressFill.style.width = "100%";
        uploadProgressFill.style.backgroundColor = "var(--danger)";
        uploadStatusText.innerHTML = `<span style="color: var(--danger)">Error: ${e.message}</span>`;
    }
}

// ---------------------------------------------------------------------------
// Session Handlers
// ---------------------------------------------------------------------------
async function createNewSession() {
    if (!authToken) return;
    try {
        const res = await fetch(`${BASE_URL}/session`, {
            method: "POST",
            headers: { "Authorization": `Bearer ${authToken}` }
        });
        res.raise_for_status;
        const data = await res.json();
        activeSessionId = data.session_id;
        sessionStorage.setItem("rag_session_id", activeSessionId);
        sessionVal.textContent = activeSessionId;

        // Reset viewport for new chat
        messagesViewport.innerHTML = "";
        messagesViewport.appendChild(welcomeCard);
        welcomeCard.classList.remove("hidden");
    } catch (e) {
        console.error("Session creation failed", e);
    }
}

async function clearSessionHistory() {
    if (!authToken || !activeSessionId) return;
    if (!confirm("Are you sure you want to clear this session's memory? This deletes conversation history.")) return;

    try {
        const res = await fetch(`${BASE_URL}/session/${activeSessionId}`, {
            method: "DELETE",
            headers: { "Authorization": `Bearer ${authToken}` }
        });
        if (res.ok) {
            messagesViewport.innerHTML = "";
            messagesViewport.appendChild(welcomeCard);
            welcomeCard.classList.remove("hidden");
            alert("Session history cleared successfully.");
        }
    } catch (e) {
        console.error("Error clearing session", e);
    }
}

// ---------------------------------------------------------------------------
// Chat Interface & SSE Streaming
// ---------------------------------------------------------------------------
function handleChatKeyDown(e) {
    if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        submitUserQuery();
    }
}

function adjustTextareaHeight() {
    chatInput.style.height = "auto";
    chatInput.style.height = (chatInput.scrollHeight - 6) + "px";
}

async function submitUserQuery() {
    const queryText = chatInput.value.trim();
    if (!queryText || !authToken) return;

    // Reset input area
    chatInput.value = "";
    chatInput.style.height = "auto";
    welcomeCard.classList.add("hidden");

    // 1. Render User Message
    appendMessage("user", queryText);

    // 2. Append Empty Assistant Message with loader
    const assistantBubble = appendMessage("assistant", "", true);

    try {
        // Build SSE request using standard Fetch + ReadableStream
        const response = await fetch(`${BASE_URL}/query/stream`, {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                "Authorization": `Bearer ${authToken}`
            },
            body: JSON.stringify({
                query: queryText,
                session_id: activeSessionId,
                filters: { department: deptSelect.value }
            })
        });

        if (!response.ok) {
            const err = await response.json();
            throw new Error(err.detail || "Query execution failed.");
        }

        // Get Stream Reader
        const reader = response.body.getReader();
        const decoder = new TextDecoder("utf-8");

        let done = false;
        let assistantResponseText = "";
        let sources = [];

        // Remove typing indicator before appending text chunks
        assistantBubble.querySelector(".typing-indicator")?.remove();

        let buffer = "";

        while (!done) {
            const { value, done: doneReading } = await reader.read();
            done = doneReading;
            if (value) {
                buffer += decoder.decode(value, { stream: !done });

                // Process lines in buffer
                const lines = buffer.split("\n\n");
                // Keep the last element (could be a partial line) in the buffer
                buffer = lines.pop();

                for (const line of lines) {
                    if (!line.trim()) continue;

                    if (line.startsWith("event: metadata")) {
                        // Parse documents data payload
                        const dataLine = line.split("\n").find(l => l.startsWith("data: "));
                        if (dataLine) {
                            try {
                                sources = JSON.parse(dataLine.substring(6));
                            } catch (err) {
                                console.error("Error parsing sources json", err);
                            }
                        }
                    } else if (line.startsWith("data: [DONE]")) {
                        done = true;
                    } else if (line.startsWith("data: ")) {
                        const chunk = line.substring(6);
                        assistantResponseText += chunk;
                        renderMarkdownLike(assistantBubble, assistantResponseText);
                    }
                }
            }
        }

        // Append Source Cards if available
        if (sources && sources.length > 0) {
            renderSourcesBlock(assistantBubble, sources);
        }

    } catch (e) {
        assistantBubble.innerHTML = `<span style="color: var(--danger)">Error: ${e.message}</span>`;
    }
}

function appendMessage(role, text, showLoader = false) {
    const row = document.createElement("div");
    row.className = `message-row ${role}`;

    const bubble = document.createElement("div");
    bubble.className = "message-bubble";

    if (showLoader) {
        bubble.innerHTML = `
            <div class="typing-indicator">
                <div class="typing-dot"></div>
                <div class="typing-dot"></div>
                <div class="typing-dot"></div>
            </div>
        `;
    } else {
        bubble.textContent = text;
    }

    row.appendChild(bubble);
    messagesViewport.appendChild(row);
    scrollToBottom();
    return bubble;
}

// ---------------------------------------------------------------------------
// Markdown and Source Rendering Helpers
// ---------------------------------------------------------------------------
function renderMarkdownLike(container, text) {
    // Escaping basic HTML to prevent HTML injection
    let clean = text
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;");

    // Format citations like [1], [2] to glowing tags
    clean = clean.replace(/\[([0-9]+)\]/g, '<span class="citation" title="Source Document $1">$1</span>');

    // Code blocks wrapping
    clean = clean.replace(/```([\s\S]*?)```/g, '<pre><code>$1</code></pre>');
    clean = clean.replace(/`([^`\n]+)`/g, '<code>$1</code>');

    // Paragraph formats
    clean = clean.replace(/\n\n/g, '<br><br>');

    container.innerHTML = clean;
    scrollToBottom();
}

function renderSourcesBlock(container, sources) {
    const sourcesCard = document.createElement("div");
    sourcesCard.className = "sources-card";

    const toggle = document.createElement("div");
    toggle.className = "sources-toggle";
    toggle.innerHTML = `
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="9 18 15 12 9 6"></polyline></svg>
        <span>View Reference Context (${sources.length})</span>
    `;

    const list = document.createElement("div");
    list.className = "sources-list hidden";

    sources.forEach((doc, idx) => {
        const item = document.createElement("div");
        item.className = "source-item";

        // Truncate path/name if too long
        const name = doc.metadata.filename || `Chunk ${doc.chunk_id.substring(0, 8)}`;

        item.innerHTML = `
            <div class="source-item-header">
                <span>[${idx + 1}] ${name}</span>
                <span class="source-score">${Math.round(doc.relevance_score * 100)}% Match</span>
            </div>
            <p class="source-text">${escapeHtml(doc.text)}</p>
        `;
        list.appendChild(item);
    });

    toggle.addEventListener("click", () => {
        const isHidden = list.classList.toggle("hidden");
        toggle.classList.toggle("active", !isHidden);
        scrollToBottom();
    });

    sourcesCard.appendChild(toggle);
    sourcesCard.appendChild(list);
    container.appendChild(sourcesCard);
    scrollToBottom();
}

// ---------------------------------------------------------------------------
// General Utilities
// ---------------------------------------------------------------------------
function scrollToBottom() {
    messagesViewport.scrollTop = messagesViewport.scrollHeight;
}

function formatBytes(bytes, decimals = 2) {
    if (bytes === 0) return '0 Bytes';
    const k = 1024;
    const dm = decimals < 0 ? 0 : decimals;
    const sizes = ['Bytes', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(dm)) + ' ' + sizes[i];
}

function escapeHtml(text) {
    return text
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;");
}

// Start app
document.addEventListener("DOMContentLoaded", init);

// ===========================================================================
// ContractIQ — Phase 1: Tab System + Risk Analysis UI
// ===========================================================================

// ---------------------------------------------------------------------------
// Tab Navigation
// ---------------------------------------------------------------------------
function setupTabs() {
    const tabChat = document.getElementById('tabChat');
    const tabContract = document.getElementById('tabContract');
    const panelChat = document.getElementById('panelChat');
    const panelContract = document.getElementById('panelContract');
    const mainTitle = document.getElementById('mainTitle');
    if (!tabChat || !tabContract) return;

    tabChat.addEventListener('click', () => {
        tabChat.classList.add('active', 'active-chat');
        tabContract.classList.remove('active');
        tabContract.classList.add('tab-btn');
        panelChat.classList.add('active');
        panelContract.classList.remove('active');
        if (mainTitle) mainTitle.textContent = 'Interactive Playground';
    });

    tabContract.addEventListener('click', () => {
        tabContract.classList.add('active');
        tabChat.classList.remove('active', 'active-chat');
        panelContract.classList.add('active');
        panelChat.classList.remove('active');
        if (mainTitle) mainTitle.textContent = 'Contract Review';
    });

    // Wire Compare tab
    const tabCompare = document.getElementById('tabCompare');
    const panelCompare = document.getElementById('panelCompare');
    if (tabCompare && panelCompare) {
        tabCompare.addEventListener('click', () => {
            tabCompare.classList.add('active');
            tabChat.classList.remove('active', 'active-chat');
            tabContract.classList.remove('active');
            panelCompare.classList.add('active');
            panelChat.classList.remove('active');
            panelContract.classList.remove('active');
            if (mainTitle) mainTitle.textContent = 'Comparison';
        });

        // Also update tabChat and tabContract to deactivate Compare
        tabChat.addEventListener('click', () => {
            tabCompare.classList.remove('active');
            panelCompare.classList.remove('active');
        });
        tabContract.addEventListener('click', () => {
            tabCompare.classList.remove('active');
            panelCompare.classList.remove('active');
        });
    }

    // Wire up analyze button
    const ciqAnalyzeBtn = document.getElementById('ciqAnalyzeBtn');
    if (ciqAnalyzeBtn) {
        ciqAnalyzeBtn.addEventListener('click', runContractAnalysis);
    }
    // Allow Enter in doc id field
    const ciqDocId = document.getElementById('ciqDocId');
    if (ciqDocId) {
        ciqDocId.addEventListener('keydown', (e) => { if (e.key === 'Enter') runContractAnalysis(); });
    }

    // Wire up compare button
    const cmpCompareBtn = document.getElementById('cmpCompareBtn');
    if (cmpCompareBtn) {
        cmpCompareBtn.addEventListener('click', runContractComparison);
    }
    ['cmpDocA', 'cmpDocB'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.addEventListener('keydown', (e) => { if (e.key === 'Enter') runContractComparison(); });
    });

    // Wire Obligations tab
    const tabObligations   = document.getElementById('tabObligations');
    const panelObligations = document.getElementById('panelObligations');
    if (tabObligations && panelObligations) {
        tabObligations.addEventListener('click', () => {
            [tabChat, tabContract, tabCompare].forEach(t => t?.classList.remove('active','active-chat'));
            [panelChat, panelContract, panelCompare].forEach(p => p?.classList.remove('active'));
            tabObligations.classList.add('active');
            panelObligations.classList.add('active');
            if (mainTitle) mainTitle.textContent = 'Obligations';
        });
        // Deactivate obligations when other tabs clicked
        [tabChat, tabContract, tabCompare].forEach(t => {
            t?.addEventListener('click', () => {
                tabObligations.classList.remove('active');
                panelObligations.classList.remove('active');
            });
        });
    }

    // Wire up extract button
    const oblExtractBtn = document.getElementById('oblExtractBtn');
    if (oblExtractBtn) oblExtractBtn.addEventListener('click', runObligationExtraction);
    const oblDocId = document.getElementById('oblDocId');
    if (oblDocId) oblDocId.addEventListener('keydown', (e) => { if (e.key === 'Enter') runObligationExtraction(); });
}

// ---------------------------------------------------------------------------
// ContractIQ — API Call
// ---------------------------------------------------------------------------
async function runContractAnalysis() {
    if (!authToken) return;

    const docId = document.getElementById('ciqDocId').value.trim();
    const focus = document.getElementById('ciqFocus').value.trim();
    const btn = document.getElementById('ciqAnalyzeBtn');
    const spinner = document.getElementById('ciqSpinner');
    const errEl = document.getElementById('ciqError');
    const resultsEl = document.getElementById('ciqResults');

    if (!docId) {
        errEl.textContent = 'Please enter a document filename.';
        errEl.classList.remove('hidden');
        return;
    }

    // Loading state
    btn.disabled = true;
    spinner.classList.remove('hidden');
    errEl.classList.add('hidden');
    resultsEl.innerHTML = `
        <div class="ciq-loading">
            <div class="ciq-loading-ring"></div>
            <p>Retrieving clauses and running AI risk analysis…</p>
        </div>`;

    try {
        const res = await fetch(`${BASE_URL}/contracts/analyze`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${authToken}`,
            },
            body: JSON.stringify({
                document_id: docId,
                focus_area: focus || null,
            }),
        });

        if (!res.ok) {
            const err = await res.json();
            throw new Error(err.detail || 'Analysis failed.');
        }

        const data = await res.json();
        renderContractAnalysis(data);
    } catch (e) {
        resultsEl.innerHTML = '';
        errEl.textContent = e.message;
        errEl.classList.remove('hidden');
    } finally {
        btn.disabled = false;
        spinner.classList.add('hidden');
    }
}

// ---------------------------------------------------------------------------
// ContractIQ — Render Results
// ---------------------------------------------------------------------------
const RISK_COLORS = {
    low: 'var(--risk-low)',
    medium: 'var(--risk-medium)',
    high: 'var(--risk-high)',
    critical: 'var(--risk-critical)',
};

function riskColor(level) {
    return RISK_COLORS[level] || 'var(--text-muted)';
}

function renderContractAnalysis(data) {
    const resultsEl = document.getElementById('ciqResults');
    resultsEl.innerHTML = '';

    const wrap = document.createElement('div');
    wrap.className = 'ciq-results';

    // 1 — Overview card
    wrap.appendChild(buildOverviewCard(data));

    // 2 — Category heatmap
    if (data.flagged_clauses && data.flagged_clauses.length > 0) {
        wrap.appendChild(buildHeatmapCard(data.flagged_clauses));
        wrap.appendChild(buildClausesSection(data.flagged_clauses));
    }

    resultsEl.appendChild(wrap);
}

// --- Overview card with animated score ring ---
function buildOverviewCard(data) {
    const score = data.overall_risk_score;
    const level = data.overall_risk_level;
    const color = riskColor(level);
    const pct = Math.round(score * 100);
    // circle circumference = 2π × 40 ≈ 251.2
    const dashOffset = 251.2 - (251.2 * score);

    const card = document.createElement('div');
    card.className = 'risk-overview-card';
    card.innerHTML = `
        <div class="risk-ring-wrap">
            <div class="risk-ring">
                <svg viewBox="0 0 100 100">
                    <circle class="track" cx="50" cy="50" r="40"/>
                    <circle class="fill" id="riskRingFill" cx="50" cy="50" r="40"
                        stroke="${color}"
                        style="stroke-dashoffset:251.2"/>
                </svg>
                <div class="risk-ring-label">
                    <span class="risk-ring-score color-${level}" style="color:${color}">${pct}</span>
                    <span class="risk-ring-pct">/ 100</span>
                </div>
            </div>
            <span class="risk-level-badge-large risk-badge ${level}">${level.toUpperCase()}</span>
        </div>
        <div class="risk-overview-info">
            <p class="risk-doc-name">Document: <span>${escapeHtml(data.document_id)}</span></p>
            <p class="risk-summary-text">${escapeHtml(data.executive_summary)}</p>
            <div class="risk-stats-row">
                <div class="risk-stat">
                    <span class="risk-stat-val">${data.clause_count}</span>
                    <span class="risk-stat-label">Total Clauses</span>
                </div>
                <div class="risk-stat">
                    <span class="risk-stat-val">${data.flagged_clauses.length}</span>
                    <span class="risk-stat-label">Flagged</span>
                </div>
                <div class="risk-stat">
                    <span class="risk-stat-val">${data.flagged_clauses.filter(c => c.risk_level === 'critical' || c.risk_level === 'high').length}</span>
                    <span class="risk-stat-label">High+Critical</span>
                </div>
                <div class="risk-stat">
                    <span class="latency-chip">${Math.round(data.latency_ms / 1000)}s</span>
                    <span class="risk-stat-label">Analysis Time</span>
                </div>
            </div>
        </div>`;

    // Animate ring after element inserted
    requestAnimationFrame(() => {
        setTimeout(() => {
            const fill = card.querySelector('#riskRingFill');
            if (fill) fill.style.strokeDashoffset = dashOffset;
        }, 80);
    });

    return card;
}

// --- Category heatmap ---
function buildHeatmapCard(clauses) {
    // Aggregate max score per category
    const catMap = {};
    clauses.forEach(c => {
        if (!catMap[c.category] || c.risk_score > catMap[c.category].max) {
            catMap[c.category] = { max: c.risk_score, count: 0 };
        }
        catMap[c.category].count++;
    });
    const entries = Object.entries(catMap).sort((a, b) => b[1].max - a[1].max);
    const maxScore = entries[0]?.[1].max || 1;

    const card = document.createElement('div');
    card.className = 'risk-heatmap-card';
    card.innerHTML = `<p class="ciq-section-title">Risk by Category</p><div class="heatmap-bars"></div>`;
    const barsEl = card.querySelector('.heatmap-bars');

    entries.forEach(([cat, { max, count }]) => {
        const level = scoreToLevel(max);
        const color = riskColor(level);
        const widthPct = Math.round((max / maxScore) * 100);
        const row = document.createElement('div');
        row.className = 'heatmap-row';
        row.innerHTML = `
            <span class="heatmap-label">${cat.replace(/_/g, ' ')}</span>
            <div class="heatmap-bar-track">
                <div class="heatmap-bar-fill" style="width:0%;background:${color}" data-w="${widthPct}"></div>
            </div>
            <span class="heatmap-count">${count}</span>`;
        barsEl.appendChild(row);
    });

    // Animate bars
    requestAnimationFrame(() => {
        setTimeout(() => {
            card.querySelectorAll('.heatmap-bar-fill').forEach(el => {
                el.style.width = el.dataset.w + '%';
            });
        }, 120);
    });

    return card;
}

// --- Clause cards ---
function buildClausesSection(clauses) {
    const section = document.createElement('div');
    section.className = 'clauses-section';
    section.innerHTML = `<p class="ciq-section-title">Flagged Clauses (${clauses.length})</p><div class="clause-cards"></div>`;
    const cardsEl = section.querySelector('.clause-cards');

    clauses.forEach(clause => {
        const card = document.createElement('div');
        card.className = 'clause-card';
        card.setAttribute('data-level', clause.risk_level);
        const scoreDisplay = Math.round(clause.risk_score * 100);
        card.innerHTML = `
            <div class="clause-header">
                <span class="clause-category">${escapeHtml(clause.category.replace(/_/g, ' '))}</span>
                <div class="clause-badges">
                    <span class="risk-badge ${clause.risk_level}">${clause.risk_level.toUpperCase()}</span>
                    <span class="clause-score" style="color:${riskColor(clause.risk_level)}">${scoreDisplay}/100</span>
                </div>
            </div>
            <blockquote class="clause-text">${escapeHtml(clause.clause_text)}</blockquote>
            <div>
                <p class="clause-explain-label">Why this is risky</p>
                <p class="clause-explain">${escapeHtml(clause.explanation)}</p>
            </div>
            <div class="clause-recommend-wrap">
                <p class="recommend-icon">⚡ Recommendation</p>
                <p class="clause-recommend">${escapeHtml(clause.recommendation)}</p>
            </div>`;
        cardsEl.appendChild(card);
    });

    return section;
}

// --- Score → level helper (mirrors backend) ---
function scoreToLevel(score) {
    if (score <= 0.25) return 'low';
    if (score <= 0.50) return 'medium';
    if (score <= 0.75) return 'high';
    return 'critical';
}

// ===========================================================================
// ContractIQ — Phase 2: Contract Comparison UI
// ===========================================================================

// ---------------------------------------------------------------------------
// Comparison API call
// ---------------------------------------------------------------------------
async function runContractComparison() {
    if (!authToken) return;

    const docA     = document.getElementById('cmpDocA').value.trim();
    const docB     = document.getElementById('cmpDocB').value.trim();
    const focus    = document.getElementById('cmpFocus').value.trim();
    const btn      = document.getElementById('cmpCompareBtn');
    const spinner  = document.getElementById('cmpSpinner');
    const errEl    = document.getElementById('cmpError');
    const resultsEl = document.getElementById('cmpResults');

    if (!docA || !docB) {
        errEl.textContent = 'Please enter both contract filenames.';
        errEl.classList.remove('hidden');
        return;
    }
    if (docA === docB) {
        errEl.textContent = 'Contract A and Contract B must be different files.';
        errEl.classList.remove('hidden');
        return;
    }

    btn.disabled = true;
    spinner.classList.remove('hidden');
    errEl.classList.add('hidden');
    resultsEl.innerHTML = `
        <div class="ciq-loading">
            <div class="ciq-loading-ring" style="border-top-color:var(--primary);"></div>
            <p>Running dual retrieval and AI clause-diff analysis…</p>
        </div>`;

    try {
        const res = await fetch(`${BASE_URL}/contracts/compare`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${authToken}`,
            },
            body: JSON.stringify({
                document_a: docA,
                document_b: docB,
                focus_area: focus || null,
            }),
        });

        if (!res.ok) {
            const err = await res.json();
            throw new Error(err.detail || 'Comparison failed.');
        }

        const data = await res.json();
        renderComparisonResult(data);
    } catch (e) {
        resultsEl.innerHTML = '';
        errEl.textContent = e.message;
        errEl.classList.remove('hidden');
    } finally {
        btn.disabled = false;
        spinner.classList.add('hidden');
    }
}

// ---------------------------------------------------------------------------
// Render comparison results
// ---------------------------------------------------------------------------
const SHIFT_CONFIG = {
    improved:  { arrow: '↓', color: 'var(--risk-low)',      cls: 'shift-improved', label: 'Risk Improved' },
    worsened:  { arrow: '↑', color: 'var(--risk-critical)', cls: 'shift-worsened', label: 'Risk Worsened' },
    neutral:   { arrow: '↔', color: 'var(--text-muted)',    cls: 'shift-neutral',  label: 'Risk Neutral'  },
};

function renderComparisonResult(data) {
    const resultsEl = document.getElementById('cmpResults');
    resultsEl.innerHTML = '';

    const wrap = document.createElement('div');
    wrap.className = 'ciq-results';

    // 1 — Risk shift banner
    wrap.appendChild(buildShiftBanner(data));

    // 2 — Delta sections (modified first as most important, then added, then removed)
    if (data.modified_clauses?.length) wrap.appendChild(buildDeltaSection('modified', data.modified_clauses));
    if (data.added_clauses?.length)    wrap.appendChild(buildDeltaSection('added',    data.added_clauses));
    if (data.removed_clauses?.length)  wrap.appendChild(buildDeltaSection('removed',  data.removed_clauses));

    resultsEl.appendChild(wrap);
}

function buildShiftBanner(data) {
    const cfg       = SHIFT_CONFIG[data.risk_shift_direction] || SHIFT_CONFIG.neutral;
    const shiftPct  = Math.round(Math.abs(data.overall_risk_shift) * 100);
    const latencySec = Math.round(data.latency_ms / 1000);

    const banner = document.createElement('div');
    banner.className = 'risk-shift-banner';
    banner.innerHTML = `
        <div class="shift-arrow-wrap">
            <span class="shift-arrow" style="color:${cfg.color}">${cfg.arrow}</span>
            <span class="shift-score ${cfg.cls}">${shiftPct}%</span>
            <span class="shift-label ${cfg.cls}">${cfg.label}</span>
        </div>
        <div class="shift-info">
            <div class="shift-docs">
                <span class="shift-doc-tag doc-a" title="${escapeHtml(data.document_a)}">${escapeHtml(data.document_a)}</span>
                <span class="shift-arrow-icon">→</span>
                <span class="shift-doc-tag doc-b" title="${escapeHtml(data.document_b)}">${escapeHtml(data.document_b)}</span>
            </div>
            <p class="shift-executive">${escapeHtml(data.executive_delta)}</p>
            <div class="shift-stats-row">
                <div class="shift-stat">
                    <span class="shift-stat-val">${data.total_deltas}</span>
                    <span class="shift-stat-label">Total Deltas</span>
                </div>
                <div class="shift-stat">
                    <span class="shift-stat-val" style="color:var(--risk-medium)">${data.modified_clauses.length}</span>
                    <span class="shift-stat-label">Modified</span>
                </div>
                <div class="shift-stat">
                    <span class="shift-stat-val" style="color:var(--risk-low)">${data.added_clauses.length}</span>
                    <span class="shift-stat-label">Added</span>
                </div>
                <div class="shift-stat">
                    <span class="shift-stat-val" style="color:var(--risk-critical)">${data.removed_clauses.length}</span>
                    <span class="shift-stat-label">Removed</span>
                </div>
                <div class="shift-stat">
                    <span class="latency-chip">${latencySec}s</span>
                    <span class="shift-stat-label">Analysis Time</span>
                </div>
            </div>
        </div>`;
    return banner;
}

const DELTA_SECTION_META = {
    added:    { label: '⊕ Added Clauses',    cls: 'added'    },
    removed:  { label: '⊖ Removed Clauses',  cls: 'removed'  },
    modified: { label: '⇔ Modified Clauses', cls: 'modified' },
};

function buildDeltaSection(type, deltas) {
    const meta    = DELTA_SECTION_META[type];
    const section = document.createElement('div');
    section.className = 'delta-section';
    section.innerHTML = `
        <div class="delta-section-header">
            <span class="delta-type-badge ${meta.cls}">${meta.label}</span>
            <span class="delta-count">${deltas.length} clause${deltas.length !== 1 ? 's' : ''}</span>
        </div>`;

    deltas.forEach(delta => section.appendChild(buildDeltaCard(delta, type)));
    return section;
}

function buildDeltaCard(delta, type) {
    const card = document.createElement('div');
    card.className = `delta-card ${type}`;

    const favoursLabel = delta.favours.replace(/_/g, ' ');

    // Build diff blocks based on type
    let diffHtml = '';
    if (type === 'modified' && delta.text_a && delta.text_b) {
        diffHtml = `
            <div class="diff-blocks">
                <div class="diff-block">
                    <span class="diff-block-label label-a">Contract A (before)</span>
                    <p class="diff-text text-a">${escapeHtml(delta.text_a)}</p>
                </div>
                <div class="diff-block">
                    <span class="diff-block-label label-b">Contract B (after)</span>
                    <p class="diff-text text-b">${escapeHtml(delta.text_b)}</p>
                </div>
            </div>`;
    } else if (type === 'removed' && delta.text_a) {
        diffHtml = `
            <div class="diff-block">
                <span class="diff-block-label label-a">Removed from Contract A</span>
                <p class="diff-text text-removed">${escapeHtml(delta.text_a)}</p>
            </div>`;
    } else if (type === 'added' && delta.text_b) {
        diffHtml = `
            <div class="diff-block">
                <span class="diff-block-label label-b">Added in Contract B</span>
                <p class="diff-text text-added">${escapeHtml(delta.text_b)}</p>
            </div>`;
    }

    card.innerHTML = `
        <div class="delta-card-header">
            <div class="delta-card-meta">
                <span class="delta-category">${escapeHtml(delta.category.replace(/_/g,' '))}</span>
                <span class="significance-badge ${delta.significance}">${delta.significance.toUpperCase()}</span>
            </div>
            <span class="favours-tag">Favours: ${escapeHtml(favoursLabel)}</span>
        </div>
        ${diffHtml}
        <p class="delta-explanation">${escapeHtml(delta.explanation)}</p>`;

    return card;
}

// ===========================================================================
// ContractIQ \u2014 Phase 3: Obligation Extraction UI
// ===========================================================================

const PRIORITY_COLORS = {
    critical: 'var(--risk-critical)',
    high:     'var(--risk-high)',
    medium:   'var(--risk-medium)',
    low:      'var(--risk-low)',
};

// ---------------------------------------------------------------------------
// API call
// ---------------------------------------------------------------------------
async function runObligationExtraction() {
    if (!authToken) return;

    const docId   = document.getElementById('oblDocId').value.trim();
    const partyA  = document.getElementById('oblPartyA').value.trim() || 'Party A';
    const partyB  = document.getElementById('oblPartyB').value.trim() || 'Party B';
    const btn     = document.getElementById('oblExtractBtn');
    const spinner = document.getElementById('oblSpinner');
    const errEl   = document.getElementById('oblError');
    const resEl   = document.getElementById('oblResults');

    if (!docId) {
        errEl.textContent = 'Please enter a document filename.';
        errEl.classList.remove('hidden');
        return;
    }

    btn.disabled = true;
    spinner.classList.remove('hidden');
    errEl.classList.add('hidden');
    resEl.innerHTML = `
        <div class="ciq-loading">
            <div class="ciq-loading-ring" style="border-top-color:var(--obl-teal);"></div>
            <p>Retrieving clauses and extracting obligation registry\u2026</p>
        </div>`;

    try {
        const res = await fetch(`${BASE_URL}/contracts/obligations`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${authToken}`,
            },
            body: JSON.stringify({
                document_id: docId,
                party_a_name: partyA,
                party_b_name: partyB,
            }),
        });

        if (!res.ok) {
            const err = await res.json();
            throw new Error(err.detail || 'Extraction failed.');
        }

        const data = await res.json();
        renderObligationRegistry(data, partyA, partyB);
    } catch (e) {
        resEl.innerHTML = '';
        errEl.textContent = e.message;
        errEl.classList.remove('hidden');
    } finally {
        btn.disabled = false;
        spinner.classList.add('hidden');
    }
}

// ---------------------------------------------------------------------------
// Render registry
// ---------------------------------------------------------------------------
function renderObligationRegistry(data, partyA, partyB) {
    const resEl = document.getElementById('oblResults');
    resEl.innerHTML = '';

    const wrap = document.createElement('div');
    wrap.className = 'ciq-results';

    // 1 \u2014 Summary banner
    wrap.appendChild(buildOblBanner(data));

    // 2 \u2014 Two-column party grid (party_a | party_b)
    if (data.party_a_obligations.length || data.party_b_obligations.length) {
        wrap.appendChild(buildPartyColumns(data, partyA, partyB));
    }

    // 3 \u2014 Shared / unknown obligations full-width
    if (data.shared_obligations.length) {
        const section = document.createElement('div');
        section.className = 'obl-shared-section';
        const hdr = document.createElement('div');
        hdr.className = 'obl-column-header shared';
        hdr.innerHTML = `\u2194 Shared Obligations <span class="obl-col-count">${data.shared_obligations.length}</span>`;
        section.appendChild(hdr);
        data.shared_obligations.forEach(o => section.appendChild(buildOblCard(o)));
        wrap.appendChild(section);
    }

    resEl.appendChild(wrap);
}

function buildOblBanner(data) {
    const latencySec = Math.round(data.latency_ms / 1000);
    const banner = document.createElement('div');
    banner.className = 'obl-banner';
    banner.innerHTML = `
        <div class="obl-banner-top">
            <p class="obl-doc-label">Document: <span>${escapeHtml(data.document_id)}</span></p>
            ${data.earliest_deadline ? `<span class="obl-deadline-chip">\ud83d\udcc5 Earliest: ${escapeHtml(data.earliest_deadline)}</span>` : ''}
        </div>
        <p class="obl-executive">${escapeHtml(data.executive_summary)}</p>
        <div class="obl-priority-bar">
            ${data.critical_count ? `<span class="obl-priority-chip critical">\u25cf ${data.critical_count} Critical</span>` : ''}
            ${data.high_count     ? `<span class="obl-priority-chip high">\u25cf ${data.high_count} High</span>`         : ''}
            ${data.medium_count   ? `<span class="obl-priority-chip medium">\u25cf ${data.medium_count} Medium</span>`   : ''}
            ${data.low_count      ? `<span class="obl-priority-chip low">\u25cf ${data.low_count} Low</span>`            : ''}
            <span class="latency-chip">${data.total_obligations} obligations \u2022 ${latencySec}s</span>
        </div>`;
    return banner;
}

function buildPartyColumns(data, partyA, partyB) {
    const grid = document.createElement('div');
    grid.className = 'obl-columns';

    // Party A column
    const colA = document.createElement('div');
    colA.className = 'obl-column';
    colA.innerHTML = `<div class="obl-column-header party-a">${escapeHtml(partyA)} Obligations <span class="obl-col-count">${data.party_a_obligations.length}</span></div>`;
    if (data.party_a_obligations.length) {
        data.party_a_obligations.forEach(o => colA.appendChild(buildOblCard(o)));
    } else {
        colA.innerHTML += `<p style="font-size:0.76rem;color:var(--text-muted);padding:8px 0">No obligations found.</p>`;
    }

    // Party B column
    const colB = document.createElement('div');
    colB.className = 'obl-column';
    colB.innerHTML = `<div class="obl-column-header party-b">${escapeHtml(partyB)} Obligations <span class="obl-col-count">${data.party_b_obligations.length}</span></div>`;
    if (data.party_b_obligations.length) {
        data.party_b_obligations.forEach(o => colB.appendChild(buildOblCard(o)));
    } else {
        colB.innerHTML += `<p style="font-size:0.76rem;color:var(--text-muted);padding:8px 0">No obligations found.</p>`;
    }

    grid.appendChild(colA);
    grid.appendChild(colB);
    return grid;
}

function buildOblCard(obl) {
    const card = document.createElement('div');
    card.className = 'obl-card';
    card.setAttribute('data-priority', obl.priority);

    const priorityColor = PRIORITY_COLORS[obl.priority] || 'var(--text-muted)';

    // Meta chips row
    const metaChips = [];
    if (obl.due_date) {
        metaChips.push(`<span class="obl-meta-chip deadline">\ud83d\udcc5 ${escapeHtml(obl.due_date)}</span>`);
    }
    if (obl.is_recurring && obl.recurrence_schedule) {
        metaChips.push(`<span class="obl-meta-chip recurring">\ud83d\udd04 ${escapeHtml(obl.recurrence_schedule)}</span>`);
    } else if (obl.is_recurring) {
        metaChips.push(`<span class="obl-meta-chip recurring">\ud83d\udd04 Recurring</span>`);
    }
    if (obl.conditions) {
        metaChips.push(`<span class="obl-meta-chip conditions">\u26a0 Conditional</span>`);
    }
    if (obl.status && obl.status !== 'pending') {
        metaChips.push(`<span class="obl-meta-chip">${escapeHtml(obl.status)}</span>`);
    }

    const penaltyHtml = obl.penalty_clause
        ? `<div class="obl-penalty">
               <span class="obl-penalty-label">\u26a0 Penalty / Consequence</span>
               <p class="obl-penalty-text">${escapeHtml(obl.penalty_clause)}</p>
           </div>`
        : '';

    card.innerHTML = `
        <div class="obl-card-header">
            <div class="obl-badges">
                <span class="obl-card-id">${escapeHtml(obl.obligation_id)}</span>
                <span class="obl-type-pill">${escapeHtml(obl.obligation_type.replace(/_/g,' '))}</span>
            </div>
            <span style="font-size:0.68rem;font-weight:700;color:${priorityColor};text-transform:uppercase;letter-spacing:0.06em;">
                <span class="obl-priority-dot" style="background:${priorityColor};display:inline-block;"></span>
                ${obl.priority}
            </span>
        </div>
        <p class="obl-desc">${escapeHtml(obl.description)}</p>
        <blockquote class="obl-verbatim">${escapeHtml(obl.verbatim_text)}</blockquote>
        ${metaChips.length ? `<div class="obl-meta-row">${metaChips.join('')}</div>` : ''}
        ${penaltyHtml}`;

    return card;
}
