// n8n Code node — Content extraction pipeline
//
// Input: { url, html } — from the HTTP Request node that fetched the URL.
// Output: { url, title, content, extraction_method }
//
// Strategy (chain — first success wins):
//   1. Mozilla Readability on the fetched HTML (best for blog posts / articles)
//   2. Fallback: jina.ai reader proxy (https://r.jina.ai/<url>) — handles
//      JS-rendered SPAs and many paywalls; returns clean Markdown.
//   3. If both fail → throw — the upstream node will catch and emit the
//      graceful "could not extract, paste raw text" message to the user (A6).
//
// Heavy lifting via @mozilla/readability (already bundled with n8n's
// Node.js runtime). For the jina fallback, we use n8n's built-in fetch.

const { Readability } = require('@mozilla/readability');
const { JSDOM } = require('jsdom');

const url = $input.first().json.url;
const html = $input.first().json.html;

if (!url || typeof url !== 'string') {
  throw new Error('extract-content: missing url');
}

// --- Step 1: Mozilla Readability -----------------------------------------
function tryReadability(html, url) {
  try {
    const dom = new JSDOM(html, { url });
    const reader = new Readability(dom.window.document);
    const article = reader.parse();

    if (!article || !article.textContent) return null;

    const content = article.textContent.replace(/\s+/g, ' ').trim();
    // Reject if extraction is suspiciously short — likely paywall / JS gate
    if (content.length < 400) return null;

    return {
      title: (article.title || '').trim() || 'Untitled',
      content,
      extraction_method: 'readability',
    };
  } catch (err) {
    return null;
  }
}

// --- Step 2: jina.ai reader fallback -------------------------------------
async function tryJinaReader(url) {
  try {
    const jinaUrl = `https://r.jina.ai/${url}`;
    const response = await fetch(jinaUrl, {
      method: 'GET',
      headers: { 'Accept': 'text/plain' },
    });

    if (!response.ok) return null;

    const text = await response.text();
    if (!text || text.length < 400) return null;

    // jina returns: "Title: ...\nURL Source: ...\n\nMarkdown Content:\n..."
    const titleMatch = text.match(/^Title:\s*(.+?)$/m);
    const title = (titleMatch && titleMatch[1]) || 'Untitled';

    const contentMatch = text.match(/Markdown Content:\s*\n([\s\S]+)$/);
    const content = (contentMatch ? contentMatch[1] : text)
      .replace(/!\[.*?\]\(.*?\)/g, '')           // strip image syntax
      .replace(/\[.*?\]\(.*?\)/g, (m) => {       // keep link text only
        const t = m.match(/\[(.*?)\]/);
        return t ? t[1] : m;
      })
      .replace(/\s+/g, ' ')
      .trim();

    return {
      title: title.trim(),
      content,
      extraction_method: 'jina',
    };
  } catch (err) {
    return null;
  }
}

// --- Run chain ------------------------------------------------------------
let result = tryReadability(html, url);
if (!result) result = await tryJinaReader(url);

if (!result) {
  // Graceful fallback signal — upstream node catches and prompts for raw text
  throw new Error('EXTRACTION_FAILED: paywall or unreadable content');
}

// Cap content at ~15k chars — keeps Anthropic context cost predictable while
// leaving room for the system prompt + structured output.
if (result.content.length > 15000) {
  result.content = result.content.slice(0, 15000) + '...';
}

return [{ json: { url, ...result } }];
