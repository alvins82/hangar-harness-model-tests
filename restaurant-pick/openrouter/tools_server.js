#!/usr/bin/env node
/*
 * Tool backend for the OpenRouter runner.
 *
 * Holds one Chromium context for the whole run, so cookies persist -- which
 * SevenRooms needs: its availability endpoint only answers a request that
 * carries cookies from one of its own pages.
 *
 * Every model in the matrix gets exactly this surface, so runs stay comparable.
 *
 *   POST /fetch    {url, method?, body?, headers?}  -> {status, body}
 *   POST /maps     {query}                          -> {name, rating, address, today, hours}
 *   POST /timeout  {query}                          -> [{title, url}]
 *   GET  /health
 *
 * Usage: node tools_server.js [port]
 */
const http = require('http');
const { chromium } = require('playwright');

const PORT = Number(process.argv[2] || 8791);
const MAX_BODY = 60000;

/*
 * SevenRooms returns ~1.35 MB for one venue-day: 156 slots x 55 fields, mostly
 * photo URLs and marketing copy. Handing that to a model costs ~340k input
 * tokens per call ($3.40 on Astra) and truncating it mid-JSON makes it
 * unparseable. So the shape the prompt documents is preserved --
 * data.availability[date][].times[].type === 'book' -- and the per-slot noise
 * is dropped. Identical for every model, so runs stay comparable.
 */
function reduceSevenRooms(text) {
  let j;
  try { j = JSON.parse(text); } catch { return null; }
  const av = j && j.data && j.data.availability;
  if (!av) return null;
  const out = {};
  for (const [date, shifts] of Object.entries(av)) {
    out[date] = (shifts || []).map(s => ({
      name: s.name,
      shift_category: s.shift_category,
      is_closed: s.is_closed,
      require_credit_card: s.require_credit_card,
      cancellation_policy: s.cancellation_policy,
      duration_minutes_by_party_size: s.duration_minutes_by_party_size,
      times: (s.times || []).map(t => ({ type: t.type, time: t.time, duration: t.duration })),
    }));
  }
  return JSON.stringify({ status: j.status, data: { availability: out },
    _reduced: 'per-slot photo and description fields removed by the tool server' });
}
let ctx, seeded = false;

async function browser() {
  if (!ctx) {
    const b = await chromium.launch({ args: ['--disable-http2'] });
    ctx = await b.newContext({ locale: 'en-AU', timezoneId: 'Australia/Sydney' });
  }
  return ctx;
}

// SevenRooms answers only when the request carries cookies from its own origin.
async function seedSevenRooms(page) {
  if (seeded) return;
  await page.goto('https://www.sevenrooms.com/explore/nomadsydney/reservations/create/search/',
    { waitUntil: 'domcontentloaded', timeout: 60000 }).catch(() => {});
  seeded = true;
}

async function doFetch({ url, method = 'GET', body = null, headers = {} }) {
  const page = await (await browser()).newPage();
  try {
    if (/sevenrooms\.com/.test(url)) await seedSevenRooms(page);
    else await page.goto('about:blank');
    const out = await page.evaluate(async ({ url, method, body, headers }) => {
      try {
        const res = await fetch(url, { method, body: body || undefined, headers });
        return { status: res.status, ct: res.headers.get('content-type') || '', body: await res.text() };
      } catch (e) { return { status: 0, ct: '', body: 'FETCH_ERROR: ' + String(e) }; }
    }, { url, method, body, headers });
    // A page-navigation fallback for hosts that refuse cross-origin fetch.
    if (out.status === 0 && method === 'GET') {
      try {
        const res = await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 30000 });
        const text = await page.evaluate(() => document.body.innerText.replace(/\s+/g, ' '));
        return { status: res ? res.status() : 0, body: text.slice(0, MAX_BODY), via: 'navigate' };
      } catch (e) {
        return { status: 0, body: 'BLOCKED: ' + String(e).split('\n')[0], via: 'navigate' };
      }
    }
    if (/sevenrooms\.com/.test(url)) {
      const reduced = reduceSevenRooms(out.body);
      if (reduced) return { status: out.status, body: reduced, via: 'fetch', reduced: true };
    }
    const truncated = out.body.length > MAX_BODY;
    return {
      status: out.status,
      body: out.body.slice(0, MAX_BODY),
      via: 'fetch',
      ...(truncated && { truncated: true, full_bytes: out.body.length,
        note: `body truncated at ${MAX_BODY} of ${out.body.length} bytes` }),
    };
  } finally { await page.close(); }
}

async function doMaps({ query }) {
  const page = await (await browser()).newPage();
  try {
    await page.goto('https://www.google.com/maps/search/' + encodeURIComponent(query) + '?hl=en&gl=au',
      { waitUntil: 'domcontentloaded', timeout: 45000 });
    await page.waitForTimeout(3500);
    // Expand the collapsed hours row if it is there.
    await page.evaluate(() => {
      const c = [...document.querySelectorAll('span,div,button')].find(e => {
        const t = (e.innerText || '').trim();
        return /^(Open|Clos)/.test(t) && t.length < 60 && e.getBoundingClientRect().height > 0;
      });
      if (c) c.click();
    }).catch(() => {});
    await page.waitForTimeout(1500);
    return await page.evaluate(() => {
      const txt = document.body.innerText.replace(/\s+/g, ' ');
      const stars = [...document.querySelectorAll('[aria-label]')]
        .map(e => e.getAttribute('aria-label'))
        .find(a => a && /^[\d.]+ stars?/.test(a.trim()));
      const rows = [...new Set([...document.querySelectorAll('tr')]
        .map(r => r.innerText.replace(/\s+/g, ' ').trim())
        .filter(r => /^(Mon|Tue|Wed|Thu|Fri|Sat|Sun)/i.test(r)))];
      const addr = txt.match(/([\w\/\- ]*\d+[A-Za-z]?\s+[A-Z][\w' ]+(?:St|Street|Rd|Road|Ave|Avenue|Pde|Parade)[^,]*,\s*[A-Z][\w ]+\s+(?:NSW|VIC|QLD)\s*\d{4})/);
      return {
        rating: stars ? stars.trim().split(' ')[0] : null,
        rating_raw: stars || null,
        address: addr ? addr[1].trim() : null,
        hours: rows,
        // Review counts are not exposed on this panel; say so rather than guess.
        review_count: null,
        note: 'review_count is not available from this surface',
        snippet: txt.slice(0, 500),
      };
    });
  } finally { await page.close(); }
}

async function doTimeout({ query }) {
  const page = await (await browser()).newPage();
  try {
    await page.goto('https://www.timeout.com/search?q=' + encodeURIComponent(query),
      { waitUntil: 'domcontentloaded', timeout: 30000 });
    await page.waitForTimeout(2500);
    return await page.evaluate(() => [...document.querySelectorAll('a')]
      .map(a => ({ title: (a.innerText || '').replace(/\s+/g, ' ').trim(), url: a.href }))
      .filter(r => r.title.length > 8 && /timeout\.com\/(sydney|.*restaurant)/.test(r.url))
      .slice(0, 25));
  } finally { await page.close(); }
}

const ROUTES = { '/fetch': doFetch, '/maps': doMaps, '/timeout': doTimeout };

http.createServer((req, res) => {
  if (req.url === '/health') { res.writeHead(200).end('ok'); return; }
  const handler = ROUTES[req.url];
  if (!handler || req.method !== 'POST') { res.writeHead(404).end('no route'); return; }
  let raw = '';
  req.on('data', d => raw += d);
  req.on('end', async () => {
    let out;
    try { out = await handler(JSON.parse(raw || '{}')); }
    catch (e) { out = { error: String(e).split('\n')[0] }; }
    res.writeHead(200, { 'content-type': 'application/json' });
    res.end(JSON.stringify(out));
  });
}).listen(PORT, '127.0.0.1', () => console.error(`tools server on 127.0.0.1:${PORT}`));

process.on('SIGTERM', () => process.exit(0));
