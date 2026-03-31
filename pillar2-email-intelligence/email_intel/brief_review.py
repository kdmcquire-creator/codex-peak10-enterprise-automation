"""HTML review surface for Morning Brief items."""

from __future__ import annotations

import json


def build_brief_review_html(*, api_code: str) -> str:
    """Return a lightweight operator UI for Morning Brief review workflows."""
    safe_code = json.dumps(api_code)
    template = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Morning Brief Review</title>
  <style>
    :root {{
      --bg: #f2ebdf;
      --panel: rgba(255, 250, 242, 0.9);
      --panel-strong: rgba(255, 252, 246, 0.97);
      --ink: #17202a;
      --ink-soft: #263241;
      --muted: #6d7480;
      --accent: #1556c9;
      --accent-soft: rgba(21, 86, 201, 0.11);
      --accent-wash: rgba(21, 86, 201, 0.05);
      --line: rgba(23, 32, 42, 0.12);
      --line-strong: rgba(23, 32, 42, 0.2);
      --success: #126348;
      --warn: #9b5d00;
      --danger: #8d2d2d;
      --shadow: 0 30px 80px rgba(24, 29, 38, 0.08);
      --paper-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.75);
      --mono: "IBM Plex Mono", "Cascadia Mono", Consolas, monospace;
      --sans: "Aptos", "Segoe UI", "Helvetica Neue", Arial, sans-serif;
      --serif: "Iowan Old Style", "Palatino Linotype", "Book Antiqua", Georgia, serif;
    }}

    * {{ box-sizing: border-box; }}

    body {{
      margin: 0;
      min-height: 100vh;
      color: var(--ink);
      font-family: var(--sans);
      background:
        radial-gradient(circle at top left, rgba(21, 86, 201, 0.16), transparent 26%),
        radial-gradient(circle at 82% 10%, rgba(23, 32, 42, 0.07), transparent 22%),
        linear-gradient(180deg, #fbf7ef 0%, var(--bg) 46%, #e9dfcf 100%);
      position: relative;
    }}

    body::before {{
      content: "";
      position: fixed;
      inset: 0;
      background:
        linear-gradient(90deg, rgba(255, 255, 255, 0.16) 0, rgba(255, 255, 255, 0.16) 1px, transparent 1px, transparent 120px),
        linear-gradient(rgba(23, 32, 42, 0.025) 1px, transparent 1px);
      background-size: 120px 100%, 100% 28px;
      pointer-events: none;
      opacity: 0.22;
    }}

    .page {{
      width: min(1500px, calc(100vw - 28px));
      margin: 0 auto;
      padding: 24px 0 42px;
      position: relative;
      z-index: 1;
    }}

    .hero {{
      display: grid;
      grid-template-columns: minmax(0, 1.45fr) minmax(330px, 0.92fr);
      gap: 18px;
      align-items: stretch;
    }}

    .poster, .rail, .lane, .queue, .context-panel {{
      background: var(--panel);
      border: 1px solid var(--line);
      box-shadow: var(--shadow);
      backdrop-filter: blur(12px);
      box-shadow: var(--paper-shadow), var(--shadow);
      animation: rise-in 520ms ease both;
    }}

    .poster {{
      border-radius: 32px;
      padding: 34px 34px 28px;
      position: relative;
      overflow: hidden;
      background:
        linear-gradient(135deg, rgba(255, 255, 255, 0.7), transparent 42%),
        linear-gradient(180deg, var(--panel-strong), rgba(255, 248, 240, 0.9));
    }}

    .poster::after {{
      content: "";
      position: absolute;
      inset: auto -64px -70px auto;
      width: 290px;
      height: 290px;
      border-radius: 50%;
      background: radial-gradient(circle, rgba(21, 86, 201, 0.24), rgba(21, 86, 201, 0));
      pointer-events: none;
    }}

    .poster::before {{
      content: "";
      position: absolute;
      inset: 0;
      background:
        linear-gradient(120deg, rgba(255, 255, 255, 0.48), transparent 28%),
        repeating-linear-gradient(0deg, transparent 0, transparent 29px, rgba(23, 32, 42, 0.035) 29px, rgba(23, 32, 42, 0.035) 30px);
      pointer-events: none;
    }}

    .eyebrow {{
      display: inline-flex;
      align-items: center;
      gap: 8px;
      padding: 7px 12px;
      border-radius: 999px;
      color: var(--accent);
      background: var(--accent-soft);
      font-size: 12px;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      font-weight: 700;
    }}

    h1 {{
      margin: 18px 0 10px;
      font-family: var(--serif);
      font-size: clamp(2.7rem, 4.5vw, 5.3rem);
      line-height: 0.9;
      letter-spacing: -0.05em;
      max-width: 11ch;
      color: var(--ink-soft);
    }}

    .lede {{
      max-width: 54ch;
      color: var(--muted);
      font-size: 1.02rem;
      line-height: 1.7;
      margin: 0 0 26px;
    }}

    .stat-strip {{
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 12px;
      margin-top: 24px;
    }}

    .stat {{
      padding: 16px 16px 14px;
      border-top: 1px solid var(--line);
      background: linear-gradient(180deg, rgba(255, 255, 255, 0.38), transparent);
      border-radius: 18px;
    }}

    .stat strong {{
      display: block;
      font-size: 1.85rem;
      line-height: 1;
      margin-bottom: 6px;
      color: var(--ink-soft);
    }}

    .stat span {{
      color: var(--muted);
      font-size: 0.9rem;
    }}

    .rail {{
      border-radius: 28px;
      padding: 24px;
      display: flex;
      flex-direction: column;
      gap: 18px;
      background:
        linear-gradient(180deg, rgba(255, 255, 255, 0.82), rgba(255, 249, 241, 0.88)),
        var(--panel);
    }}

    .rail-head, .section-head {{
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: baseline;
    }}

    .rail-head h2,
    .section-head h2 {{
      margin: 0;
      font-size: 0.92rem;
      text-transform: uppercase;
      letter-spacing: 0.12em;
      color: var(--muted);
    }}

    .section-head p {{
      margin: 6px 0 0;
      color: var(--muted);
      font-size: 0.95rem;
    }}

    .section-head {{
      padding-bottom: 14px;
      margin-bottom: 4px;
      border-bottom: 1px solid rgba(23, 32, 42, 0.08);
    }}

    .actions,
    .filters {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
    }}

    button {{
      border: 0;
      border-radius: 999px;
      padding: 11px 16px;
      font: inherit;
      cursor: pointer;
      transition: transform 140ms ease, background 140ms ease, color 140ms ease, opacity 140ms ease, border-color 140ms ease, box-shadow 140ms ease;
    }}

    button:hover {{ transform: translateY(-1px); }}
    button.primary {{
      background: linear-gradient(135deg, var(--accent), #0d448f);
      color: white;
      box-shadow: 0 12px 24px rgba(21, 86, 201, 0.2);
    }}
    button.secondary {{ background: rgba(23, 32, 42, 0.07); color: var(--ink); }}
    button.ghost {{
      background: rgba(255, 255, 255, 0.58);
      border: 1px solid var(--line);
      color: var(--muted);
    }}
    button.active {{
      background: var(--ink);
      color: white;
      box-shadow: 0 12px 24px rgba(23, 32, 42, 0.18);
    }}

    .mono {{
      font-family: var(--mono);
      font-size: 0.82rem;
      color: var(--muted);
    }}

    .status {{
      min-height: 42px;
      padding: 13px 15px;
      border-radius: 18px;
      background: rgba(23, 32, 42, 0.05);
      color: var(--muted);
      line-height: 1.5;
      border: 1px solid rgba(23, 32, 42, 0.08);
    }}

    .status.success {{ color: var(--success); background: rgba(18, 99, 72, 0.10); }}
    .status.error {{ color: var(--danger); background: rgba(141, 45, 45, 0.10); }}

    .layout {{
      display: grid;
      grid-template-columns: minmax(0, 1.35fr) minmax(340px, 0.9fr) minmax(340px, 0.95fr);
      gap: 18px;
      margin-top: 18px;
      align-items: start;
    }}

    .lane-stack,
    .queue-stack,
    .context-stack {{
      display: grid;
      gap: 18px;
    }}

    .lane, .queue, .context-panel {{
      border-radius: 28px;
      padding: 24px;
      background:
        linear-gradient(180deg, rgba(255, 255, 255, 0.82), rgba(255, 249, 241, 0.88)),
        var(--panel);
    }}

    .context-panel {{
      position: sticky;
      top: 18px;
    }}

    .item-list {{
      display: grid;
      gap: 12px;
    }}

    .item {{
      padding: 18px 0 0;
      border-top: 1px solid var(--line);
      position: relative;
    }}

    .item:first-child {{ border-top: 0; padding-top: 0; }}

    .item::before {{
      content: "";
      position: absolute;
      left: -10px;
      top: 18px;
      width: 3px;
      height: calc(100% - 18px);
      border-radius: 999px;
      background: rgba(21, 86, 201, 0.18);
    }}

    .item:first-child::before {{
      top: 2px;
      height: calc(100% - 2px);
    }}

    .item-top {{
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: flex-start;
    }}

    .item h3 {{
      margin: 0 0 8px;
      font-size: 1.08rem;
      line-height: 1.25;
      color: var(--ink-soft);
    }}

    .item p {{
      margin: 0 0 10px;
      color: var(--muted);
      line-height: 1.55;
    }}

    .chip-row {{
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      margin-bottom: 10px;
    }}

    .chip {{
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 6px 10px;
      border-radius: 999px;
      font-size: 0.8rem;
      background: rgba(23, 32, 42, 0.06);
      color: var(--muted);
      border: 1px solid rgba(23, 32, 42, 0.04);
    }}

    .chip.priority-high {{ color: white; background: #1d2430; }}
    .chip.priority-medium {{ color: var(--warn); background: rgba(155, 93, 0, 0.10); }}
    .chip.priority-low {{ color: var(--muted); }}
    .chip.state-resolved {{ color: var(--success); background: rgba(18, 99, 72, 0.10); }}
    .chip.state-dismissed {{ color: var(--danger); background: rgba(141, 45, 45, 0.10); }}
    .chip.state-open {{ color: var(--accent); background: var(--accent-soft); }}
    .chip.carry-over {{
      color: white;
      background: linear-gradient(135deg, #0e5bd7 0%, #1d2430 100%);
      font-weight: 700;
    }}

    .meta {{
      display: grid;
      gap: 6px;
      margin: 0 0 12px;
      font-size: 0.88rem;
      color: var(--muted);
      grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
    }}

    .meta strong {{
      color: var(--ink);
      font-weight: 600;
    }}

    .item-actions {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-top: 12px;
    }}

    .item-actions button {{
      padding: 9px 13px;
      font-size: 0.92rem;
    }}

    .item-note {{
      margin-top: 12px;
      display: grid;
      gap: 8px;
    }}

    .item-note label {{
      font-size: 0.8rem;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      color: var(--muted);
      font-weight: 700;
    }}

    .item-note textarea,
    .item-note input {{
      width: 100%;
      border-radius: 16px;
      border: 1px solid var(--line);
      background: rgba(255, 255, 255, 0.78);
      padding: 12px 14px;
      color: var(--ink);
      font: inherit;
      line-height: 1.45;
      box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.68);
    }}

    .item-note textarea {{
      min-height: 74px;
      resize: vertical;
    }}

    .empty {{
      color: var(--muted);
      border-top: 1px solid var(--line);
      padding-top: 16px;
    }}

    .loading {{
      opacity: 0.6;
      pointer-events: none;
    }}

    .context-empty {{
      color: var(--muted);
      line-height: 1.6;
    }}

    .context-summary {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 10px;
      margin-bottom: 16px;
    }}

    .context-stat {{
      padding: 12px 14px;
      border-radius: 18px;
      background: linear-gradient(180deg, rgba(255, 255, 255, 0.66), rgba(23, 32, 42, 0.03));
      border: 1px solid rgba(23, 32, 42, 0.06);
    }}

    .context-stat strong {{
      display: block;
      font-size: 1.35rem;
      line-height: 1;
      margin-bottom: 5px;
    }}

    .context-stat span {{
      color: var(--muted);
      font-size: 0.82rem;
    }}

    .subhead {{
      margin: 18px 0 8px;
      font-size: 0.82rem;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      color: var(--muted);
    }}

    .context-card {{
      padding: 16px 0 0;
      border-top: 1px solid var(--line);
    }}

    .context-card:first-of-type {{
      padding-top: 0;
      border-top: 0;
    }}

    .context-card h4 {{
      margin: 0 0 6px;
      font-size: 1rem;
      line-height: 1.35;
      color: var(--ink-soft);
    }}

    .context-card p {{
      margin: 0 0 8px;
      color: var(--muted);
      line-height: 1.55;
    }}

    .context-card a {{
      color: var(--accent);
      text-decoration: none;
      border-bottom: 1px solid rgba(21, 86, 201, 0.22);
    }}

    .context-card a:hover {{
      border-bottom-color: var(--accent);
    }}

    @keyframes rise-in {{
      from {{
        opacity: 0;
        transform: translateY(12px);
      }}
      to {{
        opacity: 1;
        transform: translateY(0);
      }}
    }}

    @media (max-width: 1260px) {{
      .layout {{ grid-template-columns: 1fr; }}
      .hero {{ grid-template-columns: 1fr; }}
      .stat-strip {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
      .context-panel {{ position: static; }}
    }}

    @media (max-width: 720px) {{
      .page {{ width: min(100vw - 18px, 1460px); padding-top: 18px; }}
      .poster, .rail, .lane, .queue, .context-panel {{ border-radius: 20px; padding: 18px; }}
      .stat-strip, .context-summary {{ grid-template-columns: 1fr 1fr; }}
      h1 {{ max-width: none; }}
      .meta {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <div class="page" id="app">
    <section class="hero">
      <div class="poster">
        <span class="eyebrow">Morning Brief Review</span>
        <h1>Clear today without losing yesterday.</h1>
        <p class="lede">
          Review open Follow-Ups and Watchlist items, clear what is done, reopen anything worth another pass,
          and pull the underlying message context before you decide.
        </p>
        <div class="stat-strip" id="overviewStats">
          <div class="stat"><strong>--</strong><span>Follow-Ups</span></div>
          <div class="stat"><strong>--</strong><span>Watchlist</span></div>
          <div class="stat"><strong>--</strong><span>Carry-over</span></div>
          <div class="stat"><strong>--</strong><span>Meetings</span></div>
        </div>
      </div>

      <aside class="rail">
        <div class="rail-head">
          <div>
            <h2>Operator Rail</h2>
            <div class="mono">Live tenant review flow</div>
          </div>
          <div class="actions">
            <button class="secondary" id="refreshBtn" type="button">Refresh</button>
          </div>
        </div>

        <div class="filters" id="stateFilters">
          <button class="active" data-state="open" type="button">Open</button>
          <button class="ghost" data-state="resolved" type="button">Resolved</button>
          <button class="ghost" data-state="dismissed" type="button">Dismissed</button>
          <button class="ghost" data-state="open,resolved,dismissed" type="button">All recent</button>
        </div>

        <div class="status" id="statusBox">Loading the latest Morning Brief and review queue...</div>

        <div class="mono" id="summaryMeta">Waiting on live data...</div>
      </aside>
    </section>

    <section class="layout">
      <div class="lane-stack">
        <article class="lane">
          <div class="section-head">
            <div>
              <h2>Follow-Ups</h2>
              <p>Items that likely need a concrete next move today.</p>
            </div>
          </div>
          <div class="item-list" id="followUpsList"></div>
        </article>

        <article class="lane">
          <div class="section-head">
            <div>
              <h2>Watchlist</h2>
              <p>Signals worth judgment before they turn into drift.</p>
            </div>
          </div>
          <div class="item-list" id="watchlistList"></div>
        </article>
      </div>

      <div class="queue-stack">
        <aside class="queue">
          <div class="section-head">
            <div>
              <h2>Review Queue</h2>
              <p>The active filter controls what shows up here.</p>
            </div>
          </div>
          <div class="item-list" id="queueList"></div>
        </aside>

        <aside class="queue">
          <div class="section-head">
            <div>
              <h2>Recently Cleared</h2>
              <p>Quick reassurance on what was resolved or dismissed recently.</p>
            </div>
          </div>
          <div class="item-list" id="recentlyClearedList"></div>
        </aside>
      </div>

      <div class="context-stack">
        <aside class="context-panel">
          <div class="section-head">
            <div>
              <h2>Context</h2>
              <p>Open the underlying messages and drafts before you decide.</p>
            </div>
          </div>
          <div id="contextPanel" class="context-empty">Choose "View context" on any brief item to load the underlying thread signals here.</div>
        </aside>
      </div>
    </section>
  </div>

  <script>
    const functionCode = __API_CODE__;
    const apiBase = '/api';
    const state = {{
      queueFilter: 'open',
      morningBrief: null,
      queueItems: [],
      contextItem: null,
      contextData: null,
      lastQuickAction: null,
      loading: false,
    }};

    const appEl = document.getElementById('app');
    const overviewStatsEl = document.getElementById('overviewStats');
    const followUpsListEl = document.getElementById('followUpsList');
    const watchlistListEl = document.getElementById('watchlistList');
    const queueListEl = document.getElementById('queueList');
    const recentlyClearedListEl = document.getElementById('recentlyClearedList');
    const contextPanelEl = document.getElementById('contextPanel');
    const statusBoxEl = document.getElementById('statusBox');
    const summaryMetaEl = document.getElementById('summaryMeta');
    const refreshBtn = document.getElementById('refreshBtn');
    const stateFiltersEl = document.getElementById('stateFilters');

    async function apiFetch(path, options = {{}}) {{
      const url = new URL(path, window.location.origin);
      url.searchParams.set('code', functionCode);
      const response = await fetch(url.toString(), {{
        headers: {{ 'Content-Type': 'application/json' }},
        ...options,
      }});
      if (!response.ok) {{
        const text = await response.text();
        throw new Error(text || `Request failed with status ${{response.status}}`);
      }}
      const contentType = response.headers.get('content-type') || '';
      return contentType.includes('application/json') ? response.json() : response.text();
    }}

    function setLoading(loading) {{
      state.loading = loading;
      appEl.classList.toggle('loading', loading);
      refreshBtn.disabled = loading;
    }}

    function setStatus(message, tone = '') {{
      statusBoxEl.textContent = message;
      statusBoxEl.className = tone ? `status ${{tone}}` : 'status';
    }}

    function setFilterButtons() {{
      for (const el of stateFiltersEl.querySelectorAll('button')) {{
        el.className = el.dataset.state === state.queueFilter ? 'active' : 'ghost';
      }}
    }}

    function renderOverview() {{
      const overview = state.morningBrief?.overview || {{}};
      const carryOver = (overview.carried_over_follow_up_count || 0) + (overview.carried_over_watchlist_count || 0);
      overviewStatsEl.innerHTML = `
        <div class="stat"><strong>${{overview.follow_up_count ?? 0}}</strong><span>Follow-Ups</span></div>
        <div class="stat"><strong>${{overview.watchlist_count ?? 0}}</strong><span>Watchlist</span></div>
        <div class="stat"><strong>${{carryOver}}</strong><span>Carry-over</span></div>
        <div class="stat"><strong>${{overview.meeting_count ?? 0}}</strong><span>Meetings</span></div>
      `;

      const byState = summarizeByState();
      summaryMetaEl.textContent = [
        `Queue filter: ${{state.queueFilter}}`,
        `Brief date: ${{state.morningBrief?.brief_date || 'n/a'}}`,
        `Open: ${{byState.open || 0}}`,
        `Resolved: ${{byState.resolved || 0}}`,
        `Dismissed: ${{byState.dismissed || 0}}`,
      ].join(' | ');
    }}

    function summarizeByState() {{
      return state.queueItems.reduce((acc, item) => {{
        const next = {{ ...acc }};
        next[item.state] = (next[item.state] || 0) + 1;
        return next;
      }}, {{}});
    }}

    function formatTimestamp(raw) {{
      if (!raw) return '';
      const parsed = new Date(raw);
      if (Number.isNaN(parsed.getTime())) return raw;
      return parsed.toLocaleString([], {{
        month: 'short',
        day: 'numeric',
        hour: 'numeric',
        minute: '2-digit',
      }});
    }}

    function formatDatetimeLocalValue(raw) {{
      if (!raw) return '';
      const parsed = new Date(raw);
      if (Number.isNaN(parsed.getTime())) return '';
      const offsetMs = parsed.getTimezoneOffset() * 60000;
      return new Date(parsed.getTime() - offsetMs).toISOString().slice(0, 16);
    }}

    function isoFromDatetimeLocal(value) {{
      if (!value) return '';
      const parsed = new Date(value);
      if (Number.isNaN(parsed.getTime())) return '';
      return parsed.toISOString();
    }}

    function timestampForItem(item) {{
      const raw = item.activity_at || item.state_changed_at || item.updated_at || item.last_seen_at || item.first_seen_at || '';
      if (!raw) return 0;
      const parsed = new Date(raw);
      return Number.isNaN(parsed.getTime()) ? 0 : parsed.getTime();
    }}

    function sortItemsByRecency(items) {{
      return [...(items || [])].sort((left, right) => timestampForItem(right) - timestampForItem(left));
    }}

    function renderItem(item, {{ includeContextButton = true }} = {{}}) {{
      const chips = [
        `<span class="chip priority-${{item.priority || 'low'}}">${{item.priority || 'low'}} priority</span>`,
        `<span class="chip state-${{item.state}}">${{item.state_label || item.state}}</span>`,
      ];
      if (item.carried_over && item.carry_over_label) {{
        chips.push(`<span class="chip carry-over">${{item.carry_over_label}}</span>`);
      }}
      if (item.ui_section === 'watchlist') chips.push('<span class="chip">Watchlist</span>');
      if (item.ui_section === 'follow_ups') chips.push('<span class="chip">Follow-Up</span>');

      const metaRows = [];
      if (item.contact) metaRows.push(`<div><strong>Contact:</strong> ${{item.contact}}</div>`);
      if (item.recipient) metaRows.push(`<div><strong>Recipient:</strong> ${{item.recipient}}</div>`);
      if (item.source_subject) metaRows.push(`<div><strong>Source:</strong> ${{item.source_subject}}</div>`);
      if (item.activity_at) metaRows.push(`<div><strong>${{item.activity_label || 'Latest activity'}}:</strong> ${{formatTimestamp(item.activity_at)}}</div>`);
      if (item.state !== 'open' && item.reason_label) chips.push(`<span class="chip">${{item.reason_label}}</span>`);

      const stateActions = (item.available_actions || []).map((action) => `
        <button
          class="${{action.action === 'dismiss' ? 'ghost' : (action.action === 'resolve' ? 'primary' : 'secondary')}}"
          type="button"
          data-item-id="${{item.item_id}}"
          data-action="${{action.action}}"
          data-intent="state"
        >${{action.label}}</button>
      `).join('');

      const quickActions = (item.available_quick_actions || []).map((action) => `
        <button
          class="ghost"
          type="button"
          data-item-id="${{item.item_id}}"
          data-action="${{action.action}}"
          data-intent="quick-action"
        >${{action.label}}</button>
      `).join('');

      const contextAction = includeContextButton && item.has_context ? `
        <button
          class="ghost"
          type="button"
          data-item-id="${{item.item_id}}"
          data-intent="context"
        >View context</button>
      ` : '';

      const noteComposer = item.state === 'open' ? `
        <div class="item-note">
          <label for="note-${item.item_id}">Operator note</label>
          <textarea id="note-${item.item_id}" data-note-for="${item.item_id}" placeholder="Optional note for resolve, dismiss, reopen, or quick actions.">${item.reason_detail || ''}</textarea>
        </div>
      ` : '';

      return `
        <article class="item" data-item-shell="${item.item_id}">
          <div class="item-top">
            <div>
              <h3>${{item.title}}</h3>
              <div class="chip-row">${{chips.join('')}}</div>
            </div>
          </div>
          ${{metaRows.length ? `<div class="meta">${{metaRows.join('')}}</div>` : ''}}
          <p>${{item.message || ''}}</p>
          ${item.state !== 'open' && item.status_summary ? `<p><strong>Status:</strong> ${{item.status_summary}}</p>` : ''}
          ${item.could_mean ? `<p><strong>Could mean:</strong> ${{item.could_mean}}</p>` : ''}
          ${item.suggested_action ? `<p><strong>Suggested next step:</strong> ${{item.suggested_action}}</p>` : ''}
          ${item.reason_label ? `<p><strong>Resolution note:</strong> ${{item.reason_label}}${{item.reason_detail ? ` - ${{item.reason_detail}}` : ''}}</p>` : ''}
          ${noteComposer}
          <div class="item-actions">${{stateActions}}${{quickActions}}${{contextAction}}</div>
        </article>
      `;
    }}

    function renderItemList(targetEl, items, emptyMessage, options = {{}}) {{
      if (!items || !items.length) {{
        targetEl.innerHTML = `<div class="empty">${{emptyMessage}}</div>`;
        return;
      }}
      targetEl.innerHTML = items.map((item) => renderItem(item, options)).join('');
    }}

    function renderQueue() {{
      const filtered = sortItemsByRecency(state.queueItems.filter((item) => {{
        if (state.queueFilter === 'open,resolved,dismissed') return true;
        return item.state === state.queueFilter;
      }}));
      const cleared = sortItemsByRecency(state.queueItems
        .filter((item) => item.state === 'resolved' || item.state === 'dismissed')
      ).slice(0, 6);

      renderItemList(queueListEl, filtered, 'No items match this review filter right now.');
      renderItemList(
        recentlyClearedListEl,
        cleared,
        'Nothing has been cleared recently.',
        {{ includeContextButton: true }},
      );
    }}

    function renderMorningBrief() {{
      const brief = state.morningBrief || {{}};
      renderItemList(followUpsListEl, brief.follow_ups || [], 'No active Follow-Ups in the latest brief.');
      renderItemList(watchlistListEl, brief.watchlist || [], 'No active Watchlist items in the latest brief.');
      renderOverview();
    }}

    function renderContextPanel() {{
      if (!state.contextItem || !state.contextData) {{
        contextPanelEl.className = 'context-empty';
        contextPanelEl.textContent = 'Choose "View context" on any brief item to load the underlying thread signals here.';
        return;
      }}

      const data = state.contextData;
      const latestAction = state.lastQuickAction && state.lastQuickAction.itemId === state.contextItem.item_id
        ? state.lastQuickAction
        : null;
      const messageCards = (data.messages || []).map((message) => `
        <article class="context-card">
          <h4>${{message.subject || 'Recent message'}}</h4>
          <div class="chip-row">
            <span class="chip">${{message.matched_on}}</span>
            <span class="chip">${{message.category || 'unknown'}}</span>
            ${message.urgency ? `<span class="chip">Urgency ${{message.urgency}}</span>` : ''}
          </div>
          <div class="meta">
            ${message.sender ? `<div><strong>Sender:</strong> ${{message.sender}}</div>` : ''}
            ${(message.received_at || message.saved_at) ? `<div><strong>When:</strong> ${{formatTimestamp(message.received_at || message.saved_at)}}</div>` : ''}
          </div>
          <p>${{message.summary || 'No summary captured for this item yet.'}}</p>
        </article>
      `).join('');

      const draftCards = (data.drafts || []).map((draft) => `
        <article class="context-card">
          <h4>${{draft.subject || 'Draft reply'}}</h4>
          <div class="chip-row">
            <span class="chip">${{draft.matched_on}}</span>
            <span class="chip">${{draft.sent ? 'Sent draft' : (draft.approved ? 'Approved draft' : 'Saved draft')}}</span>
            ${draft.status ? `<span class="chip">${{draft.status}}</span>` : ''}
            ${draft.tone ? `<span class="chip">${{draft.tone}}</span>` : ''}
          </div>
          <div class="meta">
            ${draft.to_recipients?.length ? `<div><strong>Recipients:</strong> ${{draft.to_recipients.join(', ')}}</div>` : ''}
            ${draft.cc_recipients?.length ? `<div><strong>CC:</strong> ${{draft.cc_recipients.join(', ')}}</div>` : ''}
            ${draft.approved_by ? `<div><strong>Approved by:</strong> ${{draft.approved_by}}</div>` : ''}
            ${(draft.sent_at || draft.approved_at || draft.saved_at) ? `<div><strong>When:</strong> ${{formatTimestamp(draft.sent_at || draft.approved_at || draft.saved_at)}}</div>` : ''}
          </div>
          ${draft.body ? `<p>${{draft.body}}</p>` : ''}
          ${draft.approval_note ? `<p><strong>Approval note:</strong> ${{draft.approval_note}}</p>` : ''}
          ${draft.send_block_reason ? `<p><strong>Send blocked:</strong> ${{draft.send_block_reason}}</p>` : ''}
          ${!draft.sent ? `
            <div class="item-note">
              <label for="draft-body-${draft.draft_id}">Draft body</label>
              <textarea id="draft-body-${draft.draft_id}" data-draft-body-for="${draft.draft_id}" placeholder="Edit the reply before approval or send.">${draft.body || ''}</textarea>
            </div>
            <div class="item-note">
              <label for="draft-note-${draft.draft_id}">Approval note</label>
              <textarea id="draft-note-${draft.draft_id}" data-draft-note-for="${draft.draft_id}" placeholder="Optional note for approval history or send context.">${draft.approval_note || ''}</textarea>
            </div>
          ` : ''}
          <div class="item-actions">
            ${(draft.available_actions || []).map((action) => `
              <button
                class="${action.action === 'send' ? 'primary' : 'ghost'}"
                type="button"
                data-draft-id="${draft.draft_id}"
                data-message-id="${draft.message_id || ''}"
                data-action="${action.action}"
                data-intent="draft-action"
              >${action.label}</button>
            `).join('')}
          </div>
        </article>
      `).join('');
      const eventDraftCards = (data.event_drafts || []).map((draft) => `
        <article class="context-card">
          <h4>${{draft.title || 'Draft event'}}</h4>
          <div class="chip-row">
            <span class="chip">${{draft.matched_on}}</span>
            <span class="chip">${{draft.created_event ? 'Created event' : (draft.approved ? 'Approved draft' : 'Saved event draft')}}</span>
            ${draft.meeting_format ? `<span class="chip">${{draft.meeting_format}}</span>` : ''}
            ${draft.status ? `<span class="chip">${{draft.status}}</span>` : ''}
          </div>
          <div class="meta">
            ${draft.candidate_time_phrases?.length ? `<div><strong>Candidate times:</strong> ${{draft.candidate_time_phrases.join(', ')}}</div>` : ''}
            ${draft.attendees?.length ? `<div><strong>Attendees:</strong> ${{draft.attendees.join(', ')}}</div>` : ''}
            ${draft.location_hint ? `<div><strong>Location:</strong> ${{draft.location_hint}}</div>` : ''}
            ${draft.scheduled_start_at ? `<div><strong>Scheduled:</strong> ${{formatTimestamp(draft.scheduled_start_at)}}</div>` : ''}
            ${draft.approved_by ? `<div><strong>Approved by:</strong> ${{draft.approved_by}}</div>` : ''}
            ${(draft.created_event_at || draft.approved_at || draft.saved_at) ? `<div><strong>When:</strong> ${{formatTimestamp(draft.created_event_at || draft.approved_at || draft.saved_at)}}</div>` : ''}
          </div>
          ${draft.summary ? `<p>${{draft.summary}}</p>` : ''}
          ${draft.created_event_web_link ? `<p><a href="${{draft.created_event_web_link}}" target="_blank" rel="noreferrer">Open created event</a></p>` : ''}
          ${(!draft.created_event && (draft.available_actions || []).some((action) => action.action === 'create_event')) ? `
            <div class="item-note">
              <label for="event-start-${draft.event_draft_id}">Event start</label>
              <input
                id="event-start-${draft.event_draft_id}"
                type="datetime-local"
                data-event-start-for="${draft.event_draft_id}"
                value="${formatDatetimeLocalValue(draft.scheduled_start_at)}"
              />
            </div>
          ` : ''}
          ${!draft.created_event ? `
            <div class="item-note">
              <label for="event-review-${draft.event_draft_id}">Review notes</label>
              <textarea id="event-review-${draft.event_draft_id}" data-event-review-for="${draft.event_draft_id}" placeholder="Optional note for approval or scheduling context.">${draft.review_notes || ''}</textarea>
            </div>
          ` : (draft.review_notes ? `<p><strong>Review notes:</strong> ${{draft.review_notes}}</p>` : '')}
          <div class="item-actions">
            ${(draft.available_actions || []).map((action) => `
              <button
                class="${action.action === 'create_event' ? 'primary' : 'ghost'}"
                type="button"
                data-event-draft-id="${draft.event_draft_id}"
                data-source-message-id="${draft.source_message_id || ''}"
                data-action="${action.action}"
                data-intent="event-draft-action"
              >${action.label}</button>
            `).join('')}
          </div>
        </article>
      `).join('');
      const latestActionCards = [];
      if (latestAction?.response?.event_draft) {{
        const eventDraft = latestAction.response.event_draft;
        latestActionCards.push(`
          <article class="context-card">
            <h4>Event draft preview</h4>
            <div class="chip-row">
              <span class="chip">Draft event</span>
              <span class="chip">${{eventDraft.meeting_format || 'meeting'}}</span>
              <span class="chip">${{eventDraft.duration_minutes || 0}} min</span>
            </div>
            <div class="meta">
              ${eventDraft.candidate_time_phrases?.length ? `<div><strong>Candidate times:</strong> ${{eventDraft.candidate_time_phrases.join(', ')}}</div>` : ''}
              ${eventDraft.attendees?.length ? `<div><strong>Attendees:</strong> ${{eventDraft.attendees.join(', ')}}</div>` : ''}
              ${eventDraft.location_hint ? `<div><strong>Location hint:</strong> ${{eventDraft.location_hint}}</div>` : ''}
            </div>
            <p><strong>${{eventDraft.title || 'Untitled meeting'}}</strong></p>
            ${eventDraft.summary ? `<p>${{eventDraft.summary}}</p>` : ''}
            ${eventDraft.review_notes ? `<p><strong>Review notes:</strong> ${{eventDraft.review_notes}}</p>` : ''}
            ${eventDraft.created_event_web_link ? `<p><a href="${{eventDraft.created_event_web_link}}" target="_blank" rel="noreferrer">Open created event</a></p>` : ''}
          </article>
        `);
      }}
      if (latestAction?.response?.created_event) {{
        const createdEvent = latestAction.response.created_event;
        latestActionCards.push(`
          <article class="context-card">
            <h4>Created event</h4>
            <div class="chip-row">
              <span class="chip">Calendar event</span>
              ${createdEvent.start_at ? `<span class="chip">${{formatTimestamp(createdEvent.start_at)}}</span>` : ''}
            </div>
            <div class="meta">
              ${createdEvent.attendees?.length ? `<div><strong>Attendees:</strong> ${{createdEvent.attendees.join(', ')}}</div>` : ''}
              ${createdEvent.id ? `<div><strong>Event id:</strong> ${{createdEvent.id}}</div>` : ''}
            </div>
            ${createdEvent.web_link ? `<p><a href="${{createdEvent.web_link}}" target="_blank" rel="noreferrer">Open created event</a></p>` : ''}
          </article>
        `);
      }}
      if (latestAction?.response?.resolved_item) {{
        const resolvedItem = latestAction.response.resolved_item;
        latestActionCards.push(`
          <article class="context-card">
            <h4>Queue update</h4>
            <div class="chip-row">
              <span class="chip">${{resolvedItem.state_label || resolvedItem.state || 'Updated'}}</span>
              ${resolvedItem.reason_label ? `<span class="chip">${{resolvedItem.reason_label}}</span>` : ''}
            </div>
            <p>${{resolvedItem.title || 'The linked brief item was updated.'}}</p>
          </article>
        `);
      }}
      if (latestAction?.response?.draft) {{
        const draft = latestAction.response.draft;
        latestActionCards.push(`
          <article class="context-card">
            <h4>Draft reply preview</h4>
            <div class="chip-row">
              <span class="chip">Draft reply</span>
              <span class="chip">${{draft.needs_review ? 'Needs review' : 'Ready'}}</span>
            </div>
            <div class="meta">
              ${draft.to_recipients?.length ? `<div><strong>Recipients:</strong> ${{draft.to_recipients.join(', ')}}</div>` : ''}
              ${draft.tone ? `<div><strong>Tone:</strong> ${{draft.tone}}</div>` : ''}
            </div>
            <p><strong>${{draft.subject || 'Draft reply'}}</strong></p>
            ${draft.body ? `<p>${{draft.body}}</p>` : ''}
          </article>
        `);
      }}
      if (latestAction?.response?.warnings?.length) {{
        latestActionCards.push(`
          <article class="context-card">
            <h4>Latest action warnings</h4>
            <p>${{latestAction.response.warnings.join(' | ')}}</p>
          </article>
        `);
      }}
      if (latestAction?.response?.fallback?.applied) {{
        latestActionCards.push(`
          <article class="context-card">
            <h4>Fallback applied</h4>
            <p>${{latestAction.response.fallback.mode || 'fallback'}}</p>
            ${latestAction.response.fallback.warning ? `<p><strong>Why:</strong> ${{latestAction.response.fallback.warning}}</p>` : ''}
          </article>
        `);
      }}

      contextPanelEl.className = '';
      const contextNoteComposer = state.contextItem.state === 'open' ? `
        <div class="item-note">
          <label for="context-note-${state.contextItem.item_id}">Operator note</label>
          <textarea id="context-note-${state.contextItem.item_id}" data-note-for="${state.contextItem.item_id}" placeholder="Optional note for resolve, dismiss, reopen, or quick actions.">${state.contextItem.reason_detail || ''}</textarea>
        </div>
      ` : '';

      contextPanelEl.innerHTML = `
        <div class="chip-row">
          <span class="chip state-${{state.contextItem.state}}">${{state.contextItem.state_label || state.contextItem.state}}</span>
          ${state.contextItem.carry_over_label ? `<span class="chip carry-over">${{state.contextItem.carry_over_label}}</span>` : ''}
        </div>
        <h3>${{state.contextItem.title}}</h3>
        <p>${{state.contextItem.message || ''}}</p>
        ${state.contextItem.reason_label ? `<p><strong>Resolution note:</strong> ${{state.contextItem.reason_label}}${{state.contextItem.reason_detail ? ` - ${{state.contextItem.reason_detail}}` : ''}}</p>` : ''}
        ${contextNoteComposer}
        <div class="context-summary">
          <div class="context-stat"><strong>${{data.summary?.message_count ?? 0}}</strong><span>Matched messages</span></div>
          <div class="context-stat"><strong>${{data.summary?.draft_count ?? 0}}</strong><span>Matched drafts</span></div>
          <div class="context-stat"><strong>${{data.summary?.event_draft_count ?? 0}}</strong><span>Event drafts</span></div>
          <div class="context-stat"><strong>${{data.summary?.latest_activity_at ? formatTimestamp(data.summary.latest_activity_at) : 'n/a'}}</strong><span>Latest activity</span></div>
        </div>
        <div class="item-actions">
          ${(state.contextItem.available_quick_actions || []).map((action) => `
            <button
              class="ghost"
              type="button"
              data-item-id="${state.contextItem.item_id}"
              data-action="${action.action}"
              data-intent="quick-action"
            >${action.label}</button>
          `).join('')}
        </div>
        ${latestActionCards.length ? `<div class="subhead">Latest action</div>${latestActionCards.join('')}` : ''}
        <div class="subhead">Messages</div>
        ${messageCards || '<div class="context-empty">No matching messages were found for this brief item.</div>'}
        <div class="subhead">Drafts</div>
        ${draftCards || '<div class="context-empty">No matching draft activity was found for this brief item.</div>'}
        <div class="subhead">Event drafts</div>
        ${eventDraftCards || '<div class="context-empty">No matching event drafts were found for this brief item.</div>'}
      `;
    }}

    function noteForItem(itemId) {{
      const candidates = document.querySelectorAll(`[data-note-for="${itemId}"]`);
      for (const candidate of candidates) {{
        const value = (candidate.value || '').trim();
        if (value) return value;
      }}
      return '';
    }}

    function startAtForEventDraft(eventDraftId) {{
      const candidate = document.querySelector(`[data-event-start-for="${eventDraftId}"]`);
      return isoFromDatetimeLocal(candidate?.value || '');
    }}

    function bodyForDraft(draftId) {{
      const candidate = document.querySelector(`[data-draft-body-for="${draftId}"]`);
      return (candidate?.value || '').trim();
    }}

    function noteForDraft(draftId) {{
      const candidate = document.querySelector(`[data-draft-note-for="${draftId}"]`);
      return (candidate?.value || '').trim();
    }}

    function reviewNoteForEventDraft(eventDraftId) {{
      const candidate = document.querySelector(`[data-event-review-for="${eventDraftId}"]`);
      return (candidate?.value || '').trim();
    }}

    async function updateEventDraft(eventDraftId, sourceMessageId, body) {{
      return apiFetch(`${apiBase}/email/event-drafts/${eventDraftId}`, {{
        method: 'PUT',
        body: JSON.stringify({{
          source_message_id: sourceMessageId,
          ...body,
        }}),
      }});
    }}

    async function updateDraft(draftId, messageId, body) {{
      return apiFetch(`${apiBase}/email/drafts/${draftId}`, {{
        method: 'PUT',
        body: JSON.stringify({{
          message_id: messageId,
          ...body,
        }}),
      }});
    }}

    async function sendDraft(draftId, messageId, body) {{
      return apiFetch(`${apiBase}/email/drafts/${draftId}/send`, {{
        method: 'POST',
        body: JSON.stringify({{
          message_id: messageId,
          ...body,
        }}),
      }});
    }}

    async function createEventFromDraft(eventDraftId, sourceMessageId, body) {{
      return apiFetch(`${apiBase}/email/event-drafts/${eventDraftId}/create-event`, {{
        method: 'POST',
        body: JSON.stringify({{
          source_message_id: sourceMessageId,
          ...body,
        }}),
      }});
    }}

    async function loadMorningBrief() {{
      state.morningBrief = await apiFetch(`${{apiBase}}/email/brief/morning`, {{
        method: 'POST',
        body: JSON.stringify({{ days: 30 }}),
      }});
    }}

    async function loadQueue() {{
      const params = new URLSearchParams({{
        state: 'open,resolved,dismissed',
        days: '30',
        limit: '60',
      }});
      state.queueItems = (await apiFetch(`${{apiBase}}/email/brief/items?${{params.toString()}}`)).items || [];
    }}

    async function loadContext(itemId) {{
      if (!state.contextItem || state.contextItem.item_id !== itemId) {{
        state.lastQuickAction = null;
      }}
      state.contextData = await apiFetch(`${{apiBase}}/email/brief/items/${{itemId}}/context?days=30&limit=8`);
      state.contextItem = state.contextData.item;
      renderContextPanel();
    }}

    async function refreshAll(message = 'Morning Brief refreshed.', tone = 'success') {{
      setLoading(true);
      try {{
        await Promise.all([loadMorningBrief(), loadQueue()]);
        renderMorningBrief();
        renderQueue();
        renderContextPanel();
        setStatus(message, tone);
      }} catch (error) {{
        setStatus(error.message || 'Something went wrong while loading the review surface.', 'error');
      }} finally {{
        setLoading(false);
      }}
    }}

    async function updateItemState(itemId, nextState) {{
      setLoading(true);
      try {{
        await apiFetch(`${{apiBase}}/email/brief/items/${{itemId}}/state`, {{
          method: 'POST',
          body: JSON.stringify({{
            state: nextState,
            updated_by: 'brief-review-ui',
            notes: noteForItem(itemId),
          }}),
        }});
        if (state.lastQuickAction && state.lastQuickAction.itemId === itemId) {{
          state.lastQuickAction = null;
        }}
        if (state.contextItem && state.contextItem.item_id === itemId) {{
          state.contextData = null;
        }}
        await refreshAll(`Item updated to ${{nextState}}.`, 'success');
      }} catch (error) {{
        setStatus(error.message || 'Unable to update item state.', 'error');
        setLoading(false);
      }}
    }}

    async function runQuickAction(itemId, action) {{
      setLoading(true);
      try {{
        const response = await apiFetch(`${{apiBase}}/email/brief/items/${{itemId}}/actions`, {{
          method: 'POST',
          body: JSON.stringify({{
            action,
            requested_by: 'brief-review-ui',
            notes: noteForItem(itemId),
          }}),
        }});
        state.lastQuickAction = {{ itemId, action, response }};
        if (action === 'generate_reply_draft') {{
          setStatus('Draft reply created from the selected brief item.', 'success');
        }} else if (action === 'generate_event_draft') {{
          setStatus('Draft event created from the selected brief item.', 'success');
        }} else {{
          setStatus(`Action ${action} completed.`, 'success');
        }}
        if (state.contextItem && state.contextItem.item_id === itemId) {{
          state.contextData = null;
          await loadContext(itemId);
        }}
        await refreshAll('', '');
        return response;
      }} catch (error) {{
        setStatus(error.message || 'Unable to run the brief item action.', 'error');
      }} finally {{
        setLoading(false);
      }}
      return null;
    }}

    async function runEventDraftAction(eventDraftId, sourceMessageId, action) {{
      setLoading(true);
      try {{
        let response = null;
        const reviewNotes = reviewNoteForEventDraft(eventDraftId);
        if (action === 'approve') {{
          response = await updateEventDraft(eventDraftId, sourceMessageId, {{
            approved: true,
            approved_by: 'brief-review-ui',
            ...(reviewNotes ? {{ review_notes: reviewNotes }} : {{}}),
          }});
          setStatus('Event draft approved.', 'success');
        }} else if (action === 'unapprove') {{
          response = await updateEventDraft(eventDraftId, sourceMessageId, {{
            approved: false,
            review_notes: reviewNotes,
          }});
          setStatus('Event draft marked unapproved.', 'success');
        }} else if (action === 'create_event') {{
          const startAt = startAtForEventDraft(eventDraftId);
          if (reviewNotes) {{
            await updateEventDraft(eventDraftId, sourceMessageId, {{
              review_notes: reviewNotes,
            }});
          }}
          response = await createEventFromDraft(eventDraftId, sourceMessageId, {{
            requested_by: 'brief-review-ui',
            brief_item_id: state.contextItem?.item_id || '',
            ...(startAt ? {{ start_at: startAt }} : {{}}),
          }});
          setStatus('Calendar event created from the approved draft.', 'success');
        }}
        if (response && state.contextItem) {{
          state.lastQuickAction = {{
            itemId: state.contextItem.item_id,
            action: `event_draft_${{action}}`,
            response,
          }};
          state.contextData = null;
          await loadContext(state.contextItem.item_id);
        }}
        await refreshAll('', '');
        return response;
      }} catch (error) {{
        setStatus(error.message || 'Unable to run the event-draft action.', 'error');
      }} finally {{
        setLoading(false);
      }}
      return null;
    }}

    async function runDraftAction(draftId, messageId, action) {{
      setLoading(true);
      try {{
        const draftBody = bodyForDraft(draftId);
        const approvalNote = noteForDraft(draftId);
        let response = null;
        if (action === 'approve') {{
          response = await updateDraft(draftId, messageId, {{
            approved: true,
            approved_by: 'brief-review-ui',
            ...(draftBody ? {{ body: draftBody }} : {{}}),
            ...(approvalNote ? {{ approval_note: approvalNote }} : {{}}),
          }});
          setStatus('Reply draft approved.', 'success');
        }} else if (action === 'unapprove') {{
          response = await updateDraft(draftId, messageId, {{
            approved: false,
            ...(draftBody ? {{ body: draftBody }} : {{}}),
            approval_note: approvalNote,
          }});
          setStatus('Reply draft marked unapproved.', 'success');
        }} else if (action === 'send') {{
          response = await sendDraft(draftId, messageId, {{
            requested_by: 'brief-review-ui',
            approved_by: 'brief-review-ui',
            brief_item_id: state.contextItem?.item_id || '',
            ...(draftBody ? {{ body: draftBody }} : {{}}),
            ...(approvalNote ? {{ approval_note: approvalNote }} : {{}}),
          }});
          setStatus(
            response?.sent
              ? 'Reply draft sent.'
              : `Reply draft processed in ${response?.delivery_mode || 'current'} mode.`,
            'success',
          );
        }}
        if (response && state.contextItem) {{
          state.lastQuickAction = {{
            itemId: state.contextItem.item_id,
            action: `draft_${{action}}`,
            response,
          }};
          state.contextData = null;
          await loadContext(state.contextItem.item_id);
        }}
        await refreshAll('', '');
        return response;
      }} catch (error) {{
        setStatus(error.message || 'Unable to run the draft action.', 'error');
      }} finally {{
        setLoading(false);
      }}
      return null;
    }}

    stateFiltersEl.addEventListener('click', async (event) => {{
      const button = event.target.closest('button[data-state]');
      if (!button || state.loading) return;
      state.queueFilter = button.dataset.state;
      setFilterButtons();
      renderQueue();
      renderOverview();
      setStatus(`Showing ${{state.queueFilter}} items.`, '');
    }});

    document.addEventListener('click', async (event) => {{
      const eventDraftButton = event.target.closest('button[data-event-draft-id][data-intent="event-draft-action"]');
      if (eventDraftButton && !state.loading) {{
        await runEventDraftAction(
          eventDraftButton.dataset.eventDraftId,
          eventDraftButton.dataset.sourceMessageId || '',
          eventDraftButton.dataset.action,
        );
        return;
      }}

      const draftButton = event.target.closest('button[data-draft-id][data-intent="draft-action"]');
      if (draftButton && !state.loading) {{
        await runDraftAction(
          draftButton.dataset.draftId,
          draftButton.dataset.messageId || '',
          draftButton.dataset.action,
        );
        return;
      }}

      const button = event.target.closest('button[data-item-id][data-intent]');
      if (!button || state.loading) return;
      const itemId = button.dataset.itemId;
      if (button.dataset.intent === 'context') {{
        setLoading(true);
        try {{
          await loadContext(itemId);
          setStatus('Context loaded.', '');
        }} catch (error) {{
          setStatus(error.message || 'Unable to load brief item context.', 'error');
        }} finally {{
          setLoading(false);
        }}
        return;
      }}
      if (button.dataset.intent === 'quick-action') {{
        await runQuickAction(itemId, button.dataset.action);
        return;
      }}
      await updateItemState(itemId, button.dataset.action);
    }});

    refreshBtn.addEventListener('click', () => refreshAll());

    setFilterButtons();
    refreshAll('Review surface ready.', '');
  </script>
</body>
</html>
"""
    return template.replace("__API_CODE__", safe_code)
