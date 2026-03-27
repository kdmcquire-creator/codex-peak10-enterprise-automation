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
      --bg: #f4efe6;
      --panel: rgba(255, 251, 245, 0.94);
      --panel-strong: rgba(255, 251, 245, 0.98);
      --ink: #1d2430;
      --muted: #697282;
      --accent: #0e5bd7;
      --accent-soft: rgba(14, 91, 215, 0.12);
      --line: rgba(29, 36, 48, 0.11);
      --success: #126348;
      --warn: #9b5d00;
      --danger: #8d2d2d;
      --shadow: 0 22px 60px rgba(24, 29, 38, 0.08);
      --mono: "IBM Plex Mono", "Cascadia Mono", Consolas, monospace;
      --sans: "Segoe UI", "Aptos", "Helvetica Neue", Arial, sans-serif;
    }}

    * {{ box-sizing: border-box; }}

    body {{
      margin: 0;
      min-height: 100vh;
      color: var(--ink);
      font-family: var(--sans);
      background:
        radial-gradient(circle at top left, rgba(14, 91, 215, 0.12), transparent 28%),
        linear-gradient(180deg, #fbf7f0 0%, var(--bg) 52%, #efe7da 100%);
    }}

    .page {{
      width: min(1460px, calc(100vw - 32px));
      margin: 0 auto;
      padding: 28px 0 40px;
    }}

    .hero {{
      display: grid;
      grid-template-columns: minmax(0, 1.35fr) minmax(330px, 0.95fr);
      gap: 22px;
      align-items: stretch;
    }}

    .poster, .rail, .lane, .queue, .context-panel {{
      background: var(--panel);
      border: 1px solid var(--line);
      box-shadow: var(--shadow);
      backdrop-filter: blur(12px);
    }}

    .poster {{
      border-radius: 28px;
      padding: 28px;
      position: relative;
      overflow: hidden;
    }}

    .poster::after {{
      content: "";
      position: absolute;
      inset: auto -40px -40px auto;
      width: 240px;
      height: 240px;
      border-radius: 50%;
      background: radial-gradient(circle, rgba(14, 91, 215, 0.20), rgba(14, 91, 215, 0));
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
      font-size: clamp(2.3rem, 4vw, 4.6rem);
      line-height: 0.94;
      letter-spacing: -0.05em;
      max-width: 10ch;
    }}

    .lede {{
      max-width: 58ch;
      color: var(--muted);
      font-size: 1rem;
      line-height: 1.65;
      margin: 0 0 22px;
    }}

    .stat-strip {{
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 12px;
      margin-top: 22px;
    }}

    .stat {{
      padding: 14px 16px;
      border-top: 1px solid var(--line);
    }}

    .stat strong {{
      display: block;
      font-size: 1.7rem;
      line-height: 1;
      margin-bottom: 6px;
    }}

    .stat span {{
      color: var(--muted);
      font-size: 0.9rem;
    }}

    .rail {{
      border-radius: 24px;
      padding: 22px;
      display: flex;
      flex-direction: column;
      gap: 18px;
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
      font-size: 1rem;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      color: var(--muted);
    }}

    .section-head p {{
      margin: 6px 0 0;
      color: var(--muted);
      font-size: 0.95rem;
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
      transition: transform 140ms ease, background 140ms ease, color 140ms ease, opacity 140ms ease;
    }}

    button:hover {{ transform: translateY(-1px); }}
    button.primary {{ background: var(--accent); color: white; }}
    button.secondary {{ background: rgba(29, 36, 48, 0.06); color: var(--ink); }}
    button.ghost {{ background: transparent; border: 1px solid var(--line); color: var(--muted); }}
    button.active {{ background: var(--ink); color: white; }}

    .mono {{
      font-family: var(--mono);
      font-size: 0.82rem;
      color: var(--muted);
    }}

    .status {{
      min-height: 42px;
      padding: 12px 14px;
      border-radius: 18px;
      background: rgba(29, 36, 48, 0.05);
      color: var(--muted);
      line-height: 1.5;
    }}

    .status.success {{ color: var(--success); background: rgba(18, 99, 72, 0.10); }}
    .status.error {{ color: var(--danger); background: rgba(141, 45, 45, 0.10); }}

    .layout {{
      display: grid;
      grid-template-columns: minmax(0, 1.35fr) minmax(340px, 0.9fr) minmax(340px, 0.95fr);
      gap: 22px;
      margin-top: 22px;
      align-items: start;
    }}

    .lane-stack,
    .queue-stack,
    .context-stack {{
      display: grid;
      gap: 18px;
    }}

    .lane, .queue, .context-panel {{
      border-radius: 24px;
      padding: 22px;
    }}

    .item-list {{
      display: grid;
      gap: 12px;
    }}

    .item {{
      padding: 16px 0 0;
      border-top: 1px solid var(--line);
    }}

    .item:first-child {{ border-top: 0; padding-top: 0; }}

    .item-top {{
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: flex-start;
    }}

    .item h3 {{
      margin: 0 0 8px;
      font-size: 1.05rem;
      line-height: 1.25;
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
      background: rgba(29, 36, 48, 0.06);
      color: var(--muted);
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

    .item-note textarea {{
      width: 100%;
      min-height: 74px;
      resize: vertical;
      border-radius: 16px;
      border: 1px solid var(--line);
      background: rgba(255, 255, 255, 0.72);
      padding: 12px 14px;
      color: var(--ink);
      font: inherit;
      line-height: 1.45;
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
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 10px;
      margin-bottom: 16px;
    }}

    .context-stat {{
      padding: 12px 14px;
      border-radius: 18px;
      background: rgba(29, 36, 48, 0.05);
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
      padding: 14px 0 0;
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
    }}

    .context-card p {{
      margin: 0 0 8px;
      color: var(--muted);
      line-height: 1.55;
    }}

    @media (max-width: 1260px) {{
      .layout {{ grid-template-columns: 1fr; }}
      .hero {{ grid-template-columns: 1fr; }}
      .stat-strip {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
    }}

    @media (max-width: 720px) {{
      .page {{ width: min(100vw - 18px, 1460px); padding-top: 18px; }}
      .poster, .rail, .lane, .queue, .context-panel {{ border-radius: 20px; padding: 18px; }}
      .stat-strip, .context-summary {{ grid-template-columns: 1fr 1fr; }}
      h1 {{ max-width: none; }}
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
          <div id="contextPanel" class="context-empty">Choose “View context” on any brief item to load the underlying thread signals here.</div>
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
      const filtered = state.queueItems.filter((item) => {{
        if (state.queueFilter === 'open,resolved,dismissed') return true;
        return item.state === state.queueFilter;
      }});
      const cleared = state.queueItems
        .filter((item) => item.state === 'resolved' || item.state === 'dismissed')
        .slice(0, 6);

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
        contextPanelEl.textContent = 'Choose “View context” on any brief item to load the underlying thread signals here.';
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
            <span class="chip">${{draft.sent ? 'Sent draft' : 'Saved draft'}}</span>
          </div>
          <div class="meta">
            ${draft.to_recipients?.length ? `<div><strong>Recipients:</strong> ${{draft.to_recipients.join(', ')}}</div>` : ''}
            ${(draft.sent_at || draft.saved_at) ? `<div><strong>When:</strong> ${{formatTimestamp(draft.sent_at || draft.saved_at)}}</div>` : ''}
          </div>
        </article>
      `).join('');
      const eventDraftCards = (data.event_drafts || []).map((draft) => `
        <article class="context-card">
          <h4>${{draft.title || 'Draft event'}}</h4>
          <div class="chip-row">
            <span class="chip">${{draft.matched_on}}</span>
            <span class="chip">${{draft.approved ? 'Approved draft' : 'Saved event draft'}}</span>
            ${draft.meeting_format ? `<span class="chip">${{draft.meeting_format}}</span>` : ''}
          </div>
          <div class="meta">
            ${draft.candidate_time_phrases?.length ? `<div><strong>Candidate times:</strong> ${{draft.candidate_time_phrases.join(', ')}}</div>` : ''}
            ${draft.attendees?.length ? `<div><strong>Attendees:</strong> ${{draft.attendees.join(', ')}}</div>` : ''}
            ${(draft.approved_at || draft.saved_at) ? `<div><strong>When:</strong> ${{formatTimestamp(draft.approved_at || draft.saved_at)}}</div>` : ''}
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
