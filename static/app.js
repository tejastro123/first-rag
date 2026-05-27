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
    usernameInput.addEventListener("keydown", (e) => { if(e.key === "Enter") handleLogin(); });
    passwordInput.addEventListener("keydown", (e) => { if(e.key === "Enter") handleLogin(); });

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
    if (authorized) {
        authLoggedOut.classList.add("hidden");
        authLoggedIn.classList.remove("hidden");
        chatInput.disabled = false;
        sendBtn.disabled = false;
        uploadZone.style.pointerEvents = "auto";
        uploadZone.style.opacity = "1";
    } else {
        authLoggedOut.classList.remove("hidden");
        authLoggedIn.classList.add("hidden");
        chatInput.disabled = true;
        sendBtn.disabled = true;
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
