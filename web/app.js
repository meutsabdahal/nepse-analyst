const STORAGE_KEY = "nepse-analyst-threads-v1";

const state = {
    threads: [],
    activeThreadId: null,
    loading: false,
    abortController: null,
    pendingThreadId: null,
    stopRequested: false,
};

const el = {
    rail: document.getElementById("leftRail"),
    railToggleButton: document.getElementById("railToggleButton"),
    newChatButton: document.getElementById("newChatButton"),
    clearThreadsButton: document.getElementById("clearThreadsButton"),
    threadList: document.getElementById("threadList"),
    messageFeed: document.getElementById("messageFeed"),
    composerForm: document.getElementById("composerForm"),
    composerInput: document.getElementById("composerInput"),
    sendButton: document.getElementById("sendButton"),
    stopButton: document.getElementById("stopButton"),
    typingIndicator: document.getElementById("typingIndicator"),
    exampleStrip: document.getElementById("exampleStrip"),
    messageTemplate: document.getElementById("messageTemplate"),
};

function uid() {
    return Math.random().toString(36).slice(2, 11);
}

function nowIso() {
    return new Date().toISOString();
}

function loadState() {
    try {
        const raw = localStorage.getItem(STORAGE_KEY);
        if (!raw) {
            return;
        }
        const parsed = JSON.parse(raw);
        if (!Array.isArray(parsed.threads)) {
            return;
        }
        state.threads = parsed.threads;
        state.activeThreadId = parsed.activeThreadId;
    } catch {
        state.threads = [];
        state.activeThreadId = null;
    }
}

function saveState() {
    localStorage.setItem(
        STORAGE_KEY,
        JSON.stringify({
            threads: state.threads,
            activeThreadId: state.activeThreadId,
        })
    );
}

function createThread(title = "New chat") {
    const thread = {
        id: uid(),
        title,
        createdAt: nowIso(),
        updatedAt: nowIso(),
        messages: [],
    };
    state.threads.unshift(thread);
    state.activeThreadId = thread.id;
    saveState();
    return thread;
}

function getActiveThread() {
    return state.threads.find((thread) => thread.id === state.activeThreadId) || null;
}

function getThreadById(threadId) {
    return state.threads.find((thread) => thread.id === threadId) || null;
}

function setActiveThread(threadId) {
    state.activeThreadId = threadId;
    saveState();
    render();
}

function stopActiveRequest() {
    if (!state.loading || !state.abortController || state.stopRequested) {
        return;
    }
    state.stopRequested = true;
    el.stopButton.disabled = true;
    el.stopButton.textContent = "Stopping...";
    state.abortController.abort();
}

function deleteThread(threadId) {
    const index = state.threads.findIndex((thread) => thread.id === threadId);
    if (index < 0) {
        return;
    }

    if (state.loading && state.pendingThreadId === threadId) {
        stopActiveRequest();
    }

    state.threads.splice(index, 1);

    if (state.threads.length === 0) {
        createThread();
    } else if (state.activeThreadId === threadId || !getActiveThread()) {
        state.activeThreadId = state.threads[0].id;
        saveState();
    } else {
        saveState();
    }

    render();
}

function clearThreads() {
    if (state.loading) {
        stopActiveRequest();
    }
    state.threads = [];
    state.activeThreadId = null;
    createThread();
    render();
}

function trimTitle(text) {
    const clean = (text || "").replace(/\s+/g, " ").trim();
    if (!clean) {
        return "New chat";
    }
    return clean.length > 56 ? clean.slice(0, 56) + "..." : clean;
}

function formatTime(iso) {
    try {
        return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    } catch {
        return "";
    }
}

function titleCase(role) {
    if (!role) {
        return "Assistant";
    }
    return role.charAt(0).toUpperCase() + role.slice(1);
}

function extractPriceFreshness(dataFreshness) {
    if (!dataFreshness || typeof dataFreshness !== "string") {
        return "";
    }

    const segments = dataFreshness.split("|").map((s) => s.trim());
    const priceSegment = segments.find((s) => s.startsWith("Price data last updated:"));
    return priceSegment || "";
}

function appendMessage(role, content, meta = null) {
    let thread = getActiveThread();
    if (!thread) {
        thread = createThread();
    }

    return appendMessageToThread(thread.id, role, content, meta);
}

function appendMessageToThread(threadId, role, content, meta = null) {
    const thread = getThreadById(threadId);
    if (!thread) {
        return null;
    }

    thread.messages.push({
        id: uid(),
        role,
        content,
        createdAt: nowIso(),
        meta,
    });

    if (role === "user" && thread.messages.filter((m) => m.role === "user").length === 1) {
        thread.title = trimTitle(content);
    }

    thread.updatedAt = nowIso();
    saveState();
    return thread;
}

function formatValue(value) {
    if (value === null || value === undefined || value === "") {
        return "N/A";
    }
    if (typeof value === "number") {
        if (Number.isInteger(value)) {
            return value.toLocaleString();
        }
        return value.toLocaleString(undefined, { maximumFractionDigits: 2 });
    }
    return String(value);
}

function renderThreadList() {
    el.threadList.innerHTML = "";
    el.clearThreadsButton.disabled = state.loading || state.threads.length === 0;

    const sorted = [...state.threads].sort((a, b) => (a.updatedAt < b.updatedAt ? 1 : -1));

    for (const thread of sorted) {
        const li = document.createElement("li");
        li.className = "thread-item" + (thread.id === state.activeThreadId ? " active" : "");
        li.tabIndex = 0;

        const titleRow = document.createElement("div");
        titleRow.className = "thread-title-row";

        const title = document.createElement("p");
        title.className = "thread-title";
        title.textContent = thread.title;

        const remove = document.createElement("button");
        remove.type = "button";
        remove.className = "thread-delete-button";
        remove.title = "Delete chat";
        remove.setAttribute("aria-label", `Delete chat ${thread.title}`);
        remove.textContent = "\u00d7";

        remove.addEventListener("click", (event) => {
            event.stopPropagation();
            deleteThread(thread.id);
        });

        titleRow.append(title, remove);

        const subtitle = document.createElement("p");
        subtitle.className = "thread-subtitle";
        subtitle.textContent = `${thread.messages.length} messages · ${formatTime(thread.updatedAt)}`;

        li.append(titleRow, subtitle);
        li.addEventListener("click", () => setActiveThread(thread.id));
        li.addEventListener("keydown", (event) => {
            if (event.key === "Enter") {
                setActiveThread(thread.id);
            }
        });

        el.threadList.append(li);
    }
}

function renderSourceMeta(container, meta) {
    if (!meta) {
        return;
    }

    const priceFreshness = extractPriceFreshness(meta.data_freshness);
    if (priceFreshness) {
        const row = document.createElement("div");
        row.className = "meta-row";

        const chip = document.createElement("span");
        chip.className = "chip";
        chip.textContent = priceFreshness;
        row.append(chip);

        container.append(row);
    }

    if (meta.quick_facts && meta.quick_facts.symbol) {
        const factsWrap = document.createElement("section");
        factsWrap.className = "quick-facts";

        const heading = document.createElement("h4");
        heading.textContent = `Quick facts: ${meta.quick_facts.symbol} - ${meta.quick_facts.name || ""}`;

        const grid = document.createElement("div");
        grid.className = "facts-grid";

        const pairs = [
            ["Sector", meta.quick_facts.sector],
            ["Close", meta.quick_facts.close_price],
            ["P/E", meta.quick_facts.pe_ratio],
            ["EPS", meta.quick_facts.eps],
            ["Book Value", meta.quick_facts.book_value],
            ["ROE", meta.quick_facts.roe],
            ["Cash Dividend", meta.quick_facts.cash_dividend],
            ["Bonus Shares", meta.quick_facts.bonus_shares],
            ["52W Low", meta.quick_facts.low_52w],
            ["52W High", meta.quick_facts.high_52w],
        ];

        for (const [label, value] of pairs) {
            const tile = document.createElement("div");
            tile.className = "fact";
            const labelEl = document.createElement("p");
            labelEl.className = "fact-label";
            labelEl.textContent = label;
            const valueEl = document.createElement("p");
            valueEl.className = "fact-value";
            valueEl.textContent = formatValue(value);
            tile.append(labelEl, valueEl);
            grid.append(tile);
        }

        factsWrap.append(heading, grid);
        container.append(factsWrap);
    }

    if (meta.error) {
        const errorChip = document.createElement("span");
        errorChip.className = "chip";
        errorChip.textContent = `Error detail: ${meta.error}`;
        container.append(errorChip);
    }

    const hasSources =
        meta.sources &&
        (meta.sources.sql ||
            (Array.isArray(meta.sources.sql_rows_preview) && meta.sources.sql_rows_preview.length > 0) ||
            (Array.isArray(meta.sources.passages) && meta.sources.passages.length > 0));

    if (!hasSources) {
        return;
    }

    const details = document.createElement("details");
    details.className = "source-disclosure";

    const summary = document.createElement("summary");
    summary.textContent = "Source transparency";
    details.append(summary);

    if (meta.sources.sql) {
        const sql = document.createElement("pre");
        sql.className = "sql-block";
        sql.textContent = meta.sources.sql;
        details.append(sql);
    }

    if (Array.isArray(meta.sources.sql_rows_preview) && meta.sources.sql_rows_preview.length > 0) {
        const table = document.createElement("table");
        table.className = "source-table";

        const columns = Object.keys(meta.sources.sql_rows_preview[0]);
        const thead = document.createElement("thead");
        const trHead = document.createElement("tr");
        for (const col of columns) {
            const th = document.createElement("th");
            th.textContent = col;
            trHead.append(th);
        }
        thead.append(trHead);

        const tbody = document.createElement("tbody");
        for (const rowData of meta.sources.sql_rows_preview.slice(0, 12)) {
            const tr = document.createElement("tr");
            for (const col of columns) {
                const td = document.createElement("td");
                td.textContent = formatValue(rowData[col]);
                tr.append(td);
            }
            tbody.append(tr);
        }

        table.append(thead, tbody);
        details.append(table);
    }

    if (Array.isArray(meta.sources.passages)) {
        for (const passage of meta.sources.passages) {
            const card = document.createElement("article");
            card.className = "passage";

            const title = document.createElement("p");
            title.className = "passage-title";
            title.textContent = passage.title || "Untitled";

            const detailsLine = document.createElement("p");
            detailsLine.className = "passage-meta";
            detailsLine.textContent = `Source: ${passage.source || "unknown"} | Date: ${passage.published_at || "unknown"} | Score: ${formatValue(passage.relevance_score)}`;

            const content = document.createElement("p");
            content.className = "passage-content";
            content.textContent = passage.content_preview || "";

            card.append(title, detailsLine, content);
            details.append(card);
        }
    }

    container.append(details);
}

function renderMessages() {
    const thread = getActiveThread();
    el.messageFeed.innerHTML = "";

    if (!thread || thread.messages.length === 0) {
        const empty = document.createElement("article");
        empty.className = "message assistant";

        const role = document.createElement("p");
        role.className = "message-role";
        role.textContent = "Assistant";

        const body = document.createElement("div");
        body.className = "message-body";
        body.textContent =
            "Ask anything about NEPSE fundamentals, dividends, sectors, prices, and recent news.";

        empty.append(role, body);
        el.messageFeed.append(empty);
        return;
    }

    for (const message of thread.messages) {
        const clone = el.messageTemplate.content.firstElementChild.cloneNode(true);
        clone.classList.add(message.role === "user" ? "user" : "assistant");

        const role = clone.querySelector(".message-role");
        const body = clone.querySelector(".message-body");
        const meta = clone.querySelector(".message-meta");

        role.textContent = titleCase(message.role);
        body.textContent = message.content;

        if (message.role === "assistant") {
            renderSourceMeta(meta, message.meta);
        }

        el.messageFeed.append(clone);
    }

    el.messageFeed.scrollTop = el.messageFeed.scrollHeight;
}

function renderExamples(examples) {
    el.exampleStrip.innerHTML = "";
    for (const text of examples.slice(0, 8)) {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "example-chip";
        button.textContent = text;
        button.addEventListener("click", () => {
            sendMessage(text);
        });
        el.exampleStrip.append(button);
    }
}

function updateExampleStripVisibility() {
    const thread = getActiveThread();
    const shouldShow = !thread || thread.messages.length === 0;
    el.exampleStrip.classList.toggle("hidden", !shouldShow);
}

function toggleLoading(value) {
    state.loading = value;
    el.newChatButton.disabled = value;
    el.sendButton.disabled = value;
    el.sendButton.classList.toggle("hidden", value);
    el.stopButton.classList.toggle("hidden", !value);
    if (value) {
        state.stopRequested = false;
        el.stopButton.disabled = false;
        el.stopButton.textContent = "Stop";
    } else {
        state.stopRequested = false;
        el.stopButton.disabled = true;
        el.stopButton.textContent = "Stop";
    }
    el.clearThreadsButton.disabled = value || state.threads.length === 0;
    el.typingIndicator.classList.toggle("hidden", !value);
}

function autoResizeComposer() {
    el.composerInput.style.height = "auto";
    el.composerInput.style.height = Math.min(el.composerInput.scrollHeight, 220) + "px";
}

async function sendMessage(message) {
    const text = (message || "").trim();
    if (!text || state.loading) {
        return;
    }

    let thread = getActiveThread();
    if (!thread) {
        thread = createThread();
    }
    const requestThreadId = thread.id;

    appendMessageToThread(requestThreadId, "user", text);
    render();
    toggleLoading(true);

    state.abortController = new AbortController();
    state.pendingThreadId = requestThreadId;

    try {
        const response = await fetch("/api/chat", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ message: text }),
            signal: state.abortController.signal,
        });

        if (!response.ok) {
            throw new Error(`Request failed with status ${response.status}`);
        }

        const payload = await response.json();
        appendMessageToThread(
            requestThreadId,
            "assistant",
            payload.answer || "No response.",
            {
                success: payload.success,
                route: payload.route,
                guardrail_type: payload.guardrail_type,
                query_language: payload.query_language,
                data_freshness: payload.data_freshness,
                quick_facts: payload.quick_facts,
                sources: payload.sources,
                error: payload.error,
            }
        );
    } catch (error) {
        const isAborted = error instanceof DOMException && error.name === "AbortError";
        if (isAborted) {
            appendMessageToThread(requestThreadId, "assistant", "Stopped processing this query.", {
                success: false,
                route: "SYSTEM",
                query_language: "en",
                error: "Request stopped by user",
            });
        } else {
            appendMessageToThread(
                requestThreadId,
                "assistant",
                "I could not process your request right now. Please retry in a moment.",
                {
                    success: false,
                    route: "SYSTEM",
                    query_language: "en",
                    error: error instanceof Error ? error.message : String(error),
                }
            );
        }
    } finally {
        state.abortController = null;
        state.pendingThreadId = null;
        toggleLoading(false);
        render();
    }
}

function render() {
    renderThreadList();
    renderMessages();
    updateExampleStripVisibility();
}

async function hydrateExamples() {
    const fallback = [
        "Which commercial bank has the highest EPS in the latest fiscal year?",
        "What recent news is there about NABIL?",
        "Should I buy HIDCL right now?",
    ];

    try {
        const response = await fetch("/api/example-questions");
        if (!response.ok) {
            throw new Error("Unable to load examples");
        }
        const payload = await response.json();
        renderExamples(Array.isArray(payload.examples) ? payload.examples : fallback);
    } catch {
        renderExamples(fallback);
    }
}

function bootstrapState() {
    loadState();
    if (state.threads.length === 0) {
        createThread();
    }
    if (!getActiveThread()) {
        state.activeThreadId = state.threads[0].id;
    }
    saveState();
}

function bindEvents() {
    el.newChatButton.addEventListener("click", () => {
        createThread();
        render();
    });

    el.clearThreadsButton.addEventListener("click", () => {
        clearThreads();
    });

    el.railToggleButton.addEventListener("click", () => {
        el.rail.classList.toggle("open");
    });

    el.stopButton.addEventListener("click", () => {
        stopActiveRequest();
    });

    el.composerForm.addEventListener("submit", async (event) => {
        event.preventDefault();
        const text = el.composerInput.value;
        el.composerInput.value = "";
        autoResizeComposer();
        await sendMessage(text);
    });

    el.composerInput.addEventListener("input", autoResizeComposer);

    el.composerInput.addEventListener("keydown", async (event) => {
        if (event.key === "Enter" && !event.shiftKey) {
            event.preventDefault();
            const text = el.composerInput.value;
            el.composerInput.value = "";
            autoResizeComposer();
            await sendMessage(text);
        }
    });
}

async function init() {
    bootstrapState();
    bindEvents();
    autoResizeComposer();
    render();
    await hydrateExamples();
}

init();