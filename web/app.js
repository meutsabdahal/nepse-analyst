const STORAGE_KEY = "nepse-analyst-threads-v1";

const state = {
    threads: [],
    activeThreadId: null,
    loading: false,
    abortController: null,
    pendingThreadId: null,
    progressTimer: null,
    progressStartedAt: 0,
    stopRequested: false,
    coverage: null,
    freshness: null,
};

const el = {
    rail: document.getElementById("leftRail"),
    railToggleButton: document.getElementById("railToggleButton"),
    railBackdrop: document.getElementById("railBackdrop"),
    chatStage: document.getElementById("chatStage"),
    newChatButton: document.getElementById("newChatButton"),
    clearThreadsButton: document.getElementById("clearThreadsButton"),
    threadList: document.getElementById("threadList"),
    chatTitle: document.getElementById("chatTitle"),
    dataStatus: document.getElementById("dataStatus"),
    messageFeed: document.getElementById("messageFeed"),
    composerForm: document.getElementById("composerForm"),
    composerInput: document.getElementById("composerInput"),
    sendButton: document.getElementById("sendButton"),
    stopButton: document.getElementById("stopButton"),
    typingIndicator: document.getElementById("typingIndicator"),
    progressStage: document.getElementById("progressStage"),
    progressElapsed: document.getElementById("progressElapsed"),
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

// Below this width the chat list is a drawer over the chat (see styles.css).
const narrowScreen = window.matchMedia("(max-width: 980px)");

// Opens or closes the chat list drawer on narrow screens. While open, the chat
// behind it is inert and a backdrop covers it; while closed, the off-screen
// list is inert so Tab cannot reach it. On wide screens the list is always
// shown and nothing is made inert.
function setRailOpen(open, { restoreFocus = false } = {}) {
    const drawer = narrowScreen.matches;
    const isOpen = drawer && open;
    el.rail.classList.toggle("open", isOpen);
    el.railBackdrop.classList.toggle("visible", isOpen);
    el.railToggleButton.setAttribute("aria-expanded", String(isOpen));
    el.rail.inert = drawer && !isOpen;
    el.chatStage.inert = isOpen;
    if (isOpen) {
        const current = el.rail.querySelector(".thread-open[aria-current]");
        (current || el.newChatButton).focus();
    } else if (drawer && restoreFocus) {
        el.railToggleButton.focus();
    }
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

// Fallback for conversations saved before answers carried `freshness`.
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
    // The list is rebuilt, so put keyboard focus back on the same button after.
    const focused = el.threadList.contains(document.activeElement) ? document.activeElement : null;
    const focusedThread = focused ? focused.dataset.threadId : null;
    const focusedClass = focused ? focused.className : null;
    el.threadList.innerHTML = "";
    el.clearThreadsButton.disabled = state.loading || state.threads.length === 0;

    const sorted = [...state.threads].sort((a, b) => (a.updatedAt < b.updatedAt ? 1 : -1));

    for (const thread of sorted) {
        const active = thread.id === state.activeThreadId;
        const li = document.createElement("li");
        li.className = "thread-item" + (active ? " active" : "");

        // Opening and deleting are sibling buttons: a button cannot contain another.
        const open = document.createElement("button");
        open.type = "button";
        open.className = "thread-open";
        open.dataset.threadId = thread.id;
        if (active) {
            open.setAttribute("aria-current", "true");
        }
        open.addEventListener("click", () => {
            setActiveThread(thread.id);
            setRailOpen(false, { restoreFocus: true });
        });

        const title = document.createElement("span");
        title.className = "thread-title";
        title.textContent = thread.title;
        setLang(title, threadLang(thread));

        const remove = document.createElement("button");
        remove.type = "button";
        remove.className = "thread-delete-button";
        remove.dataset.threadId = thread.id;
        remove.title = "Delete chat";
        remove.setAttribute("aria-label", `Delete chat ${thread.title}`);
        remove.textContent = "\u00d7";

        remove.addEventListener("click", () => deleteThread(thread.id));

        const subtitle = document.createElement("span");
        subtitle.className = "thread-subtitle";
        subtitle.textContent = `${thread.messages.length} messages · ${formatTime(thread.updatedAt)}`;

        open.append(title, subtitle);
        li.append(open, remove);
        el.threadList.append(li);
    }

    if (focused) {
        // A deleted chat's button is gone: focus the open chat instead.
        const same = [...el.threadList.querySelectorAll(`.${focusedClass}`)].find(
            (button) => button.dataset.threadId === focusedThread
        );
        const fallback = el.threadList.querySelector(".thread-open[aria-current]");
        (same || fallback || el.newChatButton).focus();
    }
}

// What each answer_basis kind means, shown on hover.
const BASIS_HINTS = {
    database: "Computed from the NEPSE database.",
    news: "Summarised from the news articles listed under Sources.",
    database_and_news: "Combines the NEPSE database with the news articles listed under Sources.",
    general_knowledge: "Written by the language model alone. No database or news was checked, so verify it.",
    declined: "Outside what NEPSE Analyst answers (predictions or investment advice).",
};

function renderSourceMeta(container, meta, messageId) {
    if (!meta) {
        return;
    }

    const basis = meta.answer_basis;
    const freshness = meta.freshness;
    const priceFreshness = freshness ? "" : extractPriceFreshness(meta.data_freshness);
    if ((basis && basis.label) || (freshness && freshness.label) || priceFreshness) {
        const row = document.createElement("div");
        row.className = "meta-row";

        if (basis && basis.label) {
            const basisChip = document.createElement("span");
            basisChip.className = `chip basis-chip basis-${basis.kind}`;
            basisChip.textContent = basis.label;
            basisChip.title = BASIS_HINTS[basis.kind] || "";
            row.append(basisChip);
        }

        if (freshness && freshness.label) {
            // Price and news dates; a warning style (and marker, not colour alone) when either is old.
            const chip = document.createElement("span");
            const stale = freshness.prices_stale || freshness.news_stale;
            chip.className = stale ? "chip freshness-chip stale" : "chip freshness-chip";
            chip.textContent = stale ? `⚠ ${freshness.label}` : freshness.label;
            chip.title = freshness.warning || "Prices and news are up to date.";
            row.append(chip);
        } else if (priceFreshness) {
            const chip = document.createElement("span");
            chip.className = "chip";
            chip.textContent = priceFreshness;
            row.append(chip);
        }

        container.append(row);
    }

    if (meta.quick_facts && meta.quick_facts.symbol) {
        const factsWrap = document.createElement("section");
        factsWrap.className = "quick-facts";

        const heading = document.createElement("h4");
        heading.textContent = `Quick facts: ${meta.quick_facts.symbol} - ${meta.quick_facts.name || ""}`;

        const grid = document.createElement("div");
        grid.className = "facts-grid";

        // Formatted rows (units, as-of dates, empty facts left out) from the API;
        // the raw fields for answers saved before rows existed.
        const rows = Array.isArray(meta.quick_facts.rows)
            ? meta.quick_facts.rows
            : null;
        const pairs = rows ? [] : [
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

        for (const row of rows || []) {
            const tile = document.createElement("div");
            tile.className = "fact";
            const labelEl = document.createElement("p");
            labelEl.className = "fact-label";
            labelEl.textContent = row.label;
            const valueEl = document.createElement("p");
            valueEl.className = "fact-value";
            valueEl.textContent = row.value;
            tile.append(labelEl, valueEl);
            if (row.as_of) {
                const asOf = document.createElement("p");
                asOf.className = "fact-as-of";
                asOf.textContent = row.as_of;
                tile.append(asOf);
            }
            grid.append(tile);
        }

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

    if (isRetryable(meta)) {
        // The answer text is the plain explanation; raw error detail is never shown.
        const row = document.createElement("div");
        row.className = "retry-row";
        const retry = document.createElement("button");
        retry.type = "button";
        retry.className = "retry-button";
        retry.textContent = "Retry";
        retry.title = "Ask this question again";
        retry.disabled = state.loading;
        retry.addEventListener("click", () => retryMessage(messageId));
        row.append(retry);
        if (meta.request_id) {
            // Server-side detail is logged under this ID; it is never sent to the browser.
            const refChip = document.createElement("span");
            refChip.className = "chip";
            refChip.textContent = `Reference: ${meta.request_id}`;
            row.append(refChip);
        }
        container.append(row);
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
    summary.textContent = "Sources";
    details.append(summary);

    if (meta.sources.sql) {
        const sql = document.createElement("pre");
        sql.className = "sql-block";
        sql.textContent = meta.sources.sql;
        details.append(sql);
    }

    const rows = meta.sources.sql_rows_preview;
    if (Array.isArray(rows) && rows.length > 0) {
        const table = document.createElement("table");
        table.className = "source-table";

        // Readable labels and units from the API; raw names for older saved answers.
        const columns = Array.isArray(meta.sources.columns) && meta.sources.columns.length > 0
            ? meta.sources.columns
            : Object.keys(rows[0]).map((key) => ({ key, label: key, unit: null, description: null }));
        const thead = document.createElement("thead");
        const trHead = document.createElement("tr");
        for (const col of columns) {
            const th = document.createElement("th");
            th.textContent = col.label;
            if (col.unit) {
                const unit = document.createElement("span");
                unit.className = "column-unit";
                unit.textContent = ` (${col.unit})`;
                th.append(unit);
            }
            if (col.description) {
                th.title = col.description;
            }
            trHead.append(th);
        }
        thead.append(trHead);

        const tbody = document.createElement("tbody");
        for (const rowData of rows.slice(0, 12)) {
            const tr = document.createElement("tr");
            for (const col of columns) {
                const td = document.createElement("td");
                const value = rowData[col.key];
                td.textContent = col.format === "year" && typeof value === "number" ? String(value) : formatValue(value);
                tr.append(td);
            }
            tbody.append(tr);
        }

        table.append(thead, tbody);
        details.append(table);
    }

    if (Array.isArray(meta.sources.passages)) {
        meta.sources.passages.forEach((passage, index) => {
            const number = passage.number || index + 1;
            const card = document.createElement("article");
            card.className = "passage";
            card.id = sourceCardId(messageId, number);

            const title = document.createElement("p");
            title.className = "passage-title";
            const badge = document.createElement("span");
            badge.className = "passage-number";
            badge.textContent = `[${number}] `;
            title.append(badge);
            if (passage.url) {
                const link = document.createElement("a");
                link.href = passage.url;
                link.target = "_blank";
                link.rel = "noopener noreferrer";
                link.textContent = passage.title || "Untitled";
                title.append(link);
            } else {
                title.append(passage.title || "Untitled");
            }

            const detailsLine = document.createElement("p");
            detailsLine.className = "passage-meta";
            const sourceName = passage.source_name || passage.source || "Unknown source";
            detailsLine.textContent = `${sourceName} · ${passage.published_at || "date unknown"}`;

            const content = document.createElement("p");
            content.className = "passage-content";
            content.textContent = passage.content_preview || "";

            card.append(title, detailsLine, content);
            details.append(card);
        });
    }

    container.append(details);
}

function sourceCardId(messageId, number) {
    return `source-${messageId}-${number}`;
}

// Answer text with each [n] that matches a news card turned into a link to it.
function renderAnswerText(body, text, messageId, passages) {
    const count = Array.isArray(passages) ? passages.length : 0;
    renderMarkdown(body, text, (number, label) => {
        if (number < 1 || number > count) {
            return null;
        }
        const link = document.createElement("a");
        link.className = "citation";
        link.href = `#${sourceCardId(messageId, number)}`;
        link.textContent = label;
        link.title = passages[number - 1].title || `Source ${number}`;
        link.addEventListener("click", (event) => {
            event.preventDefault();
            showSourceCard(messageId, number);
        });
        return link;
    });
}

// A failed answer (not a decline or an empty result) can be asked again.
function isRetryable(meta) {
    return Boolean(meta && meta.success === false && meta.error);
}

function retryMessage(messageId) {
    const thread = getActiveThread();
    if (!thread || state.loading) {
        return;
    }
    const index = thread.messages.findIndex((m) => m.id === messageId);
    if (index < 0) {
        return;
    }
    const failed = thread.messages[index];
    const previous = index > 0 ? thread.messages[index - 1] : null;
    const askedBefore = previous && previous.role === "user" ? previous : null;
    const question = (failed.meta && failed.meta.question) || (askedBefore && askedBefore.content);
    if (!question) {
        return;
    }
    // Replace the failed exchange instead of repeating it in the thread.
    thread.messages.splice(askedBefore ? index - 1 : index, askedBefore ? 2 : 1);
    saveState();
    sendMessage(question);
}

function showSourceCard(messageId, number) {
    const card = document.getElementById(sourceCardId(messageId, number));
    if (!card) {
        return;
    }
    const panel = card.closest("details");
    if (panel) {
        panel.open = true;
    }
    // Scroll only the message feed: scrollIntoView would also scroll clipped
    // ancestors sideways and shift the whole layout.
    const feed = el.messageFeed;
    const offset = card.getBoundingClientRect().top - feed.getBoundingClientRect().top;
    const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    feed.scrollTo({
        top: feed.scrollTop + offset - (feed.clientHeight - card.offsetHeight) / 2,
        behavior: reduceMotion ? "auto" : "smooth",
    });
    card.classList.remove("passage-highlight");
    void card.offsetWidth; // restart the highlight animation on repeat clicks
    card.classList.add("passage-highlight");
}

// "ne" for Nepali text, from the query_language the server sent with the answer,
// so screen readers pick a Nepali voice and lines break by Nepali rules. Only the
// body is marked: role labels, sources and tables stay English.
// A question is Nepali when it is "ne" or "mixed" (it contains Devanagari); an
// answer only when "ne", as "mixed" questions are answered in English.
function messageLang(messages, index) {
    const message = messages[index];
    if (message.role === "assistant") {
        return message.meta && message.meta.query_language === "ne" ? "ne" : null;
    }
    const reply = messages[index + 1];
    const language = reply && reply.role === "assistant" && reply.meta ? reply.meta.query_language : null;
    return language === "ne" || language === "mixed" ? "ne" : null;
}

// Removes the attribute rather than setting lang="", which means "unknown
// language" instead of inheriting the page's English.
function setLang(element, lang) {
    if (lang) {
        element.lang = lang;
    } else {
        element.removeAttribute("lang");
    }
}

// The title is the first question, so it is Nepali when that question was.
function threadLang(thread) {
    return thread && thread.messages.length > 0 ? messageLang(thread.messages, 0) : null;
}

// Pixels from the bottom that still count as "at the bottom", so a reader who
// has scrolled up is not pulled down when an answer arrives.
const STICK_TO_BOTTOM_PX = 48;

function buildMessageNode(messages, index) {
    const message = messages[index];
    const clone = el.messageTemplate.content.firstElementChild.cloneNode(true);
    clone.classList.add(message.role === "user" ? "user" : "assistant");
    clone.dataset.messageId = message.id;

    const role = clone.querySelector(".message-role");
    const body = clone.querySelector(".message-body");
    const meta = clone.querySelector(".message-meta");

    role.textContent = titleCase(message.role);
    if (message.role === "assistant") {
        const passages = message.meta && message.meta.sources ? message.meta.sources.passages : null;
        renderAnswerText(body, message.content, message.id, passages);
        renderSourceMeta(meta, message.meta, message.id);
    } else {
        body.textContent = message.content;
    }
    setLang(body, messageLang(messages, index));
    return clone;
}

function buildEmptyState() {
    const empty = document.createElement("article");
    empty.className = "message assistant";
    empty.dataset.emptyState = "true";

    const role = document.createElement("p");
    role.className = "message-role";
    role.textContent = "Assistant";

    const body = document.createElement("div");
    body.className = "message-body";
    const intro = document.createElement("p");
    intro.textContent = "Ask about NEPSE companies, sectors, dividends and prices.";
    body.append(intro);
    renderCoverage(body, state.coverage);

    empty.append(role, body);
    return empty;
}

// Draws a thread from scratch, for opening a chat. The feed element is
// replaced rather than emptied: the feed is a live region, and a screen reader
// does not read the content a live region starts with, so opening a chat does
// not read the whole conversation out. Messages drawn here skip the entry
// animation; only new ones rise in.
function rebuildFeed(thread) {
    const feed = el.messageFeed.cloneNode(false);
    feed.dataset.threadId = thread ? thread.id : "";
    if (!thread || thread.messages.length === 0) {
        feed.append(buildEmptyState());
    } else {
        thread.messages.forEach((_, index) => {
            const node = buildMessageNode(thread.messages, index);
            node.classList.add("settled");
            feed.append(node);
        });
    }
    el.messageFeed.replaceWith(feed);
    el.messageFeed = feed;
    feed.scrollTop = feed.scrollHeight;
}

// Brings the open chat's feed up to date without redrawing it: messages that
// are gone (a retried exchange) are removed and new ones appended, so open
// Sources panels stay open, nothing replays its animation, and the live region
// announces only what was added. Scrolls to the bottom for the reader's own
// question, and for an answer only when they were already at the bottom.
function updateFeed(thread) {
    const feed = el.messageFeed;
    const atBottom = feed.scrollHeight - feed.scrollTop - feed.clientHeight <= STICK_TO_BOTTOM_PX;
    const ids = new Set(thread.messages.map((m) => m.id));
    const rendered = new Map();
    for (const node of [...feed.children]) {
        const id = node.dataset.messageId;
        if (id && ids.has(id)) {
            rendered.set(id, node);
        } else {
            node.remove();
        }
    }

    let askedQuestion = false;
    thread.messages.forEach((message, index) => {
        const node = rendered.get(message.id);
        if (node) {
            // A question's language is known once its answer arrives.
            setLang(node.querySelector(".message-body"), messageLang(thread.messages, index));
            return;
        }
        feed.append(buildMessageNode(thread.messages, index));
        askedQuestion = askedQuestion || message.role === "user";
    });

    if (askedQuestion || atBottom) {
        feed.scrollTop = feed.scrollHeight;
    }
}

function renderMessages() {
    const thread = getActiveThread();
    const sameThread = thread && el.messageFeed.dataset.threadId === thread.id;
    if (sameThread && thread.messages.length > 0) {
        updateFeed(thread);
    } else {
        rebuildFeed(thread);
    }
}

// What each dataset covers, with dates, so the first screen promises no more
// than is loaded. Nothing is listed until /api/coverage answers.
function renderCoverage(container, items) {
    if (!Array.isArray(items) || items.length === 0) {
        return;
    }
    const heading = document.createElement("p");
    heading.textContent = "The data covers:";
    const list = document.createElement("ul");
    list.className = "coverage-list";
    for (const item of items) {
        const row = document.createElement("li");
        const label = document.createElement("strong");
        label.textContent = item.label;
        row.append(label, ` ${item.detail}`);
        if (item.stale) {
            const tag = document.createElement("span");
            tag.className = "coverage-stale";
            tag.textContent = "Out of date";
            if (typeof item.age_days === "number") {
                tag.title = `Last updated ${item.age_days} days ago.`;
            }
            row.append(" ", tag);
        }
        list.append(row);
    }
    container.append(heading, list);
}

// Every group is shown in full; the server keeps the list short.
function renderExamples(groups) {
    el.exampleStrip.replaceChildren();
    for (const group of groups) {
        const section = document.createElement("div");
        section.className = "example-group";
        const label = document.createElement("p");
        label.className = "example-group-label";
        label.textContent = group.group;
        section.append(label);
        for (const text of group.questions) {
            const button = document.createElement("button");
            button.type = "button";
            button.className = "example-chip";
            button.textContent = text;
            button.addEventListener("click", () => {
                sendMessage(text);
            });
            section.append(button);
        }
        el.exampleStrip.append(section);
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
    for (const button of document.querySelectorAll(".retry-button")) {
        button.disabled = value;
    }
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
    if (value) {
        startProgress();
    } else {
        stopProgress();
    }
}

function autoResizeComposer() {
    el.composerInput.style.height = "auto";
    el.composerInput.style.height = Math.min(el.composerInput.scrollHeight, 220) + "px";
}

// The stream is newline-delimited JSON: stage events, then one answer event.
async function readChatStream(response, onStage) {
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let answer = null;
    const handle = (line) => {
        if (!line.trim()) {
            return;
        }
        const event = JSON.parse(line);
        if (event.type === "stage") {
            onStage(event);
        } else if (event.type === "answer") {
            answer = event.data;
        }
    };
    for (;;) {
        const { value, done } = await reader.read();
        if (done) {
            break;
        }
        buffer += decoder.decode(value, { stream: true });
        let newline;
        while ((newline = buffer.indexOf("\n")) >= 0) {
            handle(buffer.slice(0, newline));
            buffer = buffer.slice(newline + 1);
        }
    }
    handle(buffer + decoder.decode());
    if (!answer) {
        throw new Error("The answer stream ended before the answer arrived");
    }
    return answer;
}

function formatElapsed(ms) {
    const seconds = Math.floor(ms / 1000);
    if (seconds < 60) {
        return `${seconds} s`;
    }
    return `${Math.floor(seconds / 60)} min ${String(seconds % 60).padStart(2, "0")} s`;
}

function setProgressStage(label) {
    if (label) {
        el.progressStage.textContent = label;
    }
}

function tickProgress() {
    el.progressElapsed.textContent = `· ${formatElapsed(performance.now() - state.progressStartedAt)}`;
}

function startProgress() {
    stopProgress();
    state.progressStartedAt = performance.now();
    setProgressStage("Sending your question");
    tickProgress();
    state.progressTimer = setInterval(tickProgress, 1000);
}

function stopProgress() {
    if (state.progressTimer !== null) {
        clearInterval(state.progressTimer);
        state.progressTimer = null;
    }
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
    // Loading first: the typing indicator shortens the feed, and the scroll to
    // the new question has to account for it.
    toggleLoading(true);
    render();

    state.abortController = new AbortController();
    state.pendingThreadId = requestThreadId;

    try {
        const response = await fetch("/api/chat/stream", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ message: text }),
            signal: state.abortController.signal,
        });

        if (response.status === 429) {
            const seconds = Number(response.headers.get("Retry-After"));
            let wait = "";
            if (seconds > 0) {
                const amount = seconds < 120 ? `${seconds} seconds`
                    : seconds < 7200 ? `${Math.ceil(seconds / 60)} minutes`
                    : `${Math.ceil(seconds / 3600)} hours`;
                wait = ` Try again in about ${amount}.`;
            }
            appendMessageToThread(
                requestThreadId,
                "assistant",
                `You have asked a lot of questions in a short time.${wait}`,
                { success: false, route: "SYSTEM", query_language: "en", error: "rate_limited", question: text }
            );
            return;
        }

        if (!response.ok) {
            throw new Error(`Request failed with status ${response.status}`);
        }

        const payload = await readChatStream(response, (event) => setProgressStage(event.label));
        if (payload.freshness) {
            state.freshness = payload.freshness;
        }
        appendMessageToThread(
            requestThreadId,
            "assistant",
            payload.answer || "No response.",
            {
                success: payload.success,
                route: payload.route,
                answer_basis: payload.answer_basis,
                guardrail_type: payload.guardrail_type,
                query_language: payload.query_language,
                data_freshness: payload.data_freshness,
                freshness: payload.freshness,
                quick_facts: payload.quick_facts,
                sources: payload.sources,
                request_id: payload.request_id,
                error: payload.error || null,
                question: text,
            }
        );
    } catch (error) {
        const isAborted = error instanceof DOMException && error.name === "AbortError";
        if (isAborted) {
            appendMessageToThread(requestThreadId, "assistant", "Stopped before an answer was ready.", {
                success: false,
                route: "SYSTEM",
                query_language: "en",
                error: "stopped",
                question: text,
            });
        } else {
            // The detail goes to the console for debugging, not into the chat.
            console.error("chat request failed", error);
            const offline = typeof navigator !== "undefined" && navigator.onLine === false;
            appendMessageToThread(
                requestThreadId,
                "assistant",
                offline
                    ? "You appear to be offline, so the question was not sent."
                    : "Something went wrong while answering this question.",
                {
                    success: false,
                    route: "SYSTEM",
                    query_language: "en",
                    error: offline ? "offline" : "request_failed",
                    question: text,
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

// The header shows the open chat's title and how current the data is; the
// app's name is already in the sidebar.
function renderHeader() {
    const thread = getActiveThread();
    el.chatTitle.textContent = thread ? thread.title : "New chat";
    setLang(el.chatTitle, threadLang(thread));

    const freshness = state.freshness;
    const status = el.dataStatus;
    status.classList.toggle("hidden", !(freshness && freshness.label));
    if (!freshness || !freshness.label) {
        return;
    }
    const stale = freshness.prices_stale || freshness.news_stale;
    status.classList.toggle("stale", Boolean(stale));
    status.textContent = stale ? `⚠ ${freshness.label}` : freshness.label;
    status.title = freshness.warning || "Prices and news are up to date.";
}

function render() {
    renderHeader();
    renderThreadList();
    renderMessages();
    updateExampleStripVisibility();
}

async function hydrateExamples() {
    const fallback = [
        { group: "Companies", questions: ["What is NICA's P/E ratio?"] },
        { group: "Concepts", questions: ["What does a P/E ratio tell an investor?"] },
    ];

    try {
        const response = await fetch("/api/example-questions");
        if (!response.ok) {
            throw new Error("Unable to load examples");
        }
        const payload = await response.json();
        renderExamples(Array.isArray(payload.groups) ? payload.groups : fallback);
    } catch {
        renderExamples(fallback);
    }
}

async function hydrateCoverage() {
    try {
        const response = await fetch("/api/coverage");
        if (!response.ok) {
            return;
        }
        const payload = await response.json();
        state.coverage = Array.isArray(payload.items) ? payload.items : null;
        state.freshness = payload.freshness || state.freshness;
    } catch {
        return;
    }
    renderHeader();
    const thread = getActiveThread();
    if (!thread || thread.messages.length === 0) {
        renderMessages();
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
        setRailOpen(false, { restoreFocus: true });
    });

    el.clearThreadsButton.addEventListener("click", () => {
        clearThreads();
    });

    el.railToggleButton.addEventListener("click", () => {
        setRailOpen(!el.rail.classList.contains("open"));
    });

    el.railBackdrop.addEventListener("click", () => {
        setRailOpen(false, { restoreFocus: true });
    });

    document.addEventListener("keydown", (event) => {
        if (event.key === "Escape" && el.rail.classList.contains("open")) {
            setRailOpen(false, { restoreFocus: true });
        }
    });

    // Crossing the breakpoint switches between drawer and sidebar.
    narrowScreen.addEventListener("change", () => setRailOpen(false));

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
        // Enter that accepts an input-method suggestion (Nepali, etc.) must not send.
        // Safari reports that keydown after composition ends, with keyCode 229.
        if (event.isComposing || event.keyCode === 229) {
            return;
        }
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
    setRailOpen(false);
    await Promise.all([hydrateExamples(), hydrateCoverage()]);
}

init();