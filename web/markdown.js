// A small, safe Markdown subset for answers: paragraphs, **bold**, bullet and
// numbered lists, [text](https://…) links, # headings (shown as bold lines) and
// [n] citations. Text is parsed into plain objects and turned into DOM nodes;
// nothing is ever assigned to innerHTML, so model output cannot inject markup.

const MD_BULLET = /^\s{0,3}[-*+•]\s+(.*)$/;
const MD_NUMBERED = /^\s{0,3}(\d{1,3})[.)]\s+(.*)$/;
const MD_HEADING = /^\s{0,3}#{1,6}\s+(.*?)(?:\s+#+)?\s*$/;
const MD_CONTINUATION = /^\s{2,}\S/;
const MD_INLINE = /\*\*(?=\S)([\s\S]*?\S)\*\*|\[([^\]\n]+)\]\((https?:\/\/[^\s)]+)\)|\[(\d+)\]/g;

function parseMarkdownBlocks(text) {
    const blocks = [];
    let paragraph = null;
    let list = null;
    let blankSinceItem = false;

    const closeParagraph = () => {
        if (paragraph) {
            blocks.push({ type: "paragraph", text: paragraph.join("\n") });
            paragraph = null;
        }
    };
    const closeList = () => {
        if (list) {
            blocks.push(list);
            list = null;
        }
    };

    for (const line of String(text ?? "").replace(/\r\n?/g, "\n").split("\n")) {
        if (!line.trim()) {
            closeParagraph();
            blankSinceItem = true;
            continue;
        }

        const bullet = line.match(MD_BULLET);
        const numbered = bullet ? null : line.match(MD_NUMBERED);
        if (bullet || numbered) {
            const ordered = Boolean(numbered);
            closeParagraph();
            if (list && list.ordered !== ordered) {
                closeList();
            }
            if (!list) {
                list = { type: "list", ordered, start: ordered ? Number(numbered[1]) : 1, items: [] };
            }
            list.items.push((bullet ? bullet[1] : numbered[2]).trim());
            blankSinceItem = false;
            continue;
        }

        if (list && !blankSinceItem && MD_CONTINUATION.test(line)) {
            list.items[list.items.length - 1] += ` ${line.trim()}`;
            continue;
        }
        closeList();

        const heading = line.match(MD_HEADING);
        if (heading) {
            closeParagraph();
            blocks.push({ type: "heading", text: heading[1] });
            continue;
        }

        paragraph = paragraph || [];
        paragraph.push(line);
    }
    closeParagraph();
    closeList();
    return blocks;
}

function safeHttpUrl(value) {
    try {
        const url = new URL(value);
        return url.protocol === "http:" || url.protocol === "https:" ? url.href : null;
    } catch {
        return null;
    }
}

function parseMarkdownInline(text) {
    const nodes = [];
    let last = 0;
    const pushText = (value) => {
        if (!value) {
            return;
        }
        const previous = nodes[nodes.length - 1];
        if (previous && previous.type === "text") {
            previous.text += value;
        } else {
            nodes.push({ type: "text", text: value });
        }
    };

    for (const match of String(text ?? "").matchAll(MD_INLINE)) {
        pushText(text.slice(last, match.index));
        last = match.index + match[0].length;
        if (match[1] !== undefined) {
            nodes.push({ type: "strong", children: parseMarkdownInline(match[1]) });
        } else if (match[2] !== undefined) {
            const href = safeHttpUrl(match[3]);
            if (href) {
                nodes.push({ type: "link", text: match[2], href });
            } else {
                pushText(match[0]);
            }
        } else {
            nodes.push({ type: "citation", number: Number(match[4]), text: match[0] });
        }
    }
    pushText(String(text ?? "").slice(last));
    return nodes;
}

// citation(number, text) returns a node for an [n] marker, or null to keep it as text.
function appendMarkdownInline(parent, text, citation) {
    for (const node of parseMarkdownInline(text)) {
        appendMarkdownInlineNode(parent, node, citation);
    }
}

function appendMarkdownInlineNode(parent, node, citation) {
    if (node.type === "text") {
        parent.append(node.text);
    } else if (node.type === "strong") {
        const strong = document.createElement("strong");
        for (const child of node.children) {
            appendMarkdownInlineNode(strong, child, citation);
        }
        parent.append(strong);
    } else if (node.type === "link") {
        const link = document.createElement("a");
        link.href = node.href;
        link.textContent = node.text;
        link.target = "_blank";
        link.rel = "noopener noreferrer";
        parent.append(link);
    } else if (node.type === "citation") {
        parent.append((citation && citation(node.number, node.text)) || node.text);
    }
}

function renderMarkdown(container, text, citation) {
    container.replaceChildren();
    for (const block of parseMarkdownBlocks(text)) {
        if (block.type === "list") {
            const list = document.createElement(block.ordered ? "ol" : "ul");
            if (block.ordered && block.start !== 1) {
                list.start = block.start;
            }
            for (const item of block.items) {
                const li = document.createElement("li");
                appendMarkdownInline(li, item, citation);
                list.append(li);
            }
            container.append(list);
        } else {
            const p = document.createElement("p");
            if (block.type === "heading") {
                p.className = "answer-heading";
                const strong = document.createElement("strong");
                appendMarkdownInline(strong, block.text, citation);
                p.append(strong);
            } else {
                appendMarkdownInline(p, block.text, citation);
            }
            container.append(p);
        }
    }
}

if (typeof module === "object" && module.exports) {
    module.exports = { parseMarkdownBlocks, parseMarkdownInline, safeHttpUrl };
}
