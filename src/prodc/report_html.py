"""Render the board as a single self-contained, interactive HTML viewer — `report --format html`.

A read-only viewer a non-CLI reader can open anywhere and print to PDF: inline CSS, inline
vanilla JS, no external assets, no dependency. It reuses the same resolved model the markdown
report gathers (so it never drifts from `prodc status`), serialises it to an embedded JSON
snapshot, and the JS renders a filterable/searchable/expandable board on top of it. The file only
*views* the board — nothing in it mutates anything.
"""

from __future__ import annotations

import json
from datetime import date

from .config import Config
from .model import Model, NeedResult
from .status import (
    goal_report,
    handoffs,
    recurrence,
    release_report,
    resolve,
    role_report,
    summarize,
)


def _need_payload(r: NeedResult) -> dict[str, object]:
    """One need, flattened to the plain JSON the viewer renders a row and its detail from."""
    need = r.need
    strongest = need.strongest_kind
    return {
        "id": need.id,
        "text": need.text,
        "description": need.description,
        "state": r.state.value,
        "must": need.must,
        "who": need.who or "(unassigned)",
        "label": need.label,
        "client": need.client,
        "opinion": need.is_opinion,
        "warrant": strongest.value if strongest is not None else "opinion",
        "importance": need.importance,
        "goal": need.goal,
        "release": need.release,
        "claim": need.claim,
        "proofs": list(need.proofs),
        "detail": list(r.detail),
        "warnings": list(r.warnings),
        "attestation": (
            {
                "who": need.attestation.who,
                "date": need.attestation.date,
                "kind": need.attestation.kind.value,
                "verdict": need.attestation.verdict,
            }
            if need.attestation
            else None
        ),
        "sources": [
            {
                "kind": s.kind.value,
                "who": s.who,
                "date": s.date,
                "quote": s.quote,
                "locator": s.locator,
            }
            for s in need.sources
        ],
    }


def board_payload(
    cfg: Config, model: Model, *, client: str | None = None, rev: str | None = None
) -> dict[str, object]:
    """Gather the resolved board into a plain-dict snapshot (the data the viewer renders)."""
    needs = list(model.needs)
    results = resolve(needs, cfg.adapters, cfg.source_adapters)
    summary = summarize(results)
    goal_cov, ungoaled = goal_report(results, list(model.goals))
    rel_cov = release_report(results, list(model.releases))
    role_cov, unroled = role_report(results, list(model.roles))

    def _cov(delivered: int, total: int) -> dict[str, object]:
        pct = round(delivered / total * 100) if total else None
        return {"delivered": delivered, "total": total, "pct": pct}

    scope = f" — {client}" if client else ""
    return {
        "title": f"{cfg.root.name}{scope} — product status",
        "project": cfg.root.name,
        "scope": client,
        "stamp": date.today().isoformat() + (f" · {rev}" if rev else ""),
        "summary": {
            "total": summary.total,
            "delivered": summary.delivered,
            "pending": summary.pending,
            "hole": summary.hole,
            "must_hole": summary.must_hole,
            "broken": summary.broken,
            "unresolved": summary.unresolved,
            "opinion": summary.opinion,
            "coverage_pct": round(summary.coverage * 100),
        },
        "needs": [_need_payload(r) for r in results if r.need.product],
        "goals": [{"id": g.id, "text": g.text, **_cov(s.delivered, s.total)} for g, s in goal_cov],
        "ungoaled": [r.need.id for r in ungoaled],
        "releases": [
            {"id": rel.id, "text": rel.text, **_cov(s.delivered, s.total)} for rel, s in rel_cov
        ],
        "roles": [
            {"id": role.id, "text": role.text, **_cov(s.delivered, s.total)} for role, s in role_cov
        ],
        "unroled": [r.need.id for r in unroled],
        "recurrence": [
            {
                "id": rec.baseline.id,
                "text": rec.baseline.text,
                "count": rec.count,
                "clients": list(rec.clients),
            }
            for rec in recurrence(needs)
        ],
        "handoffs": [
            {
                "flow": h.flow.id,
                "from_role": h.from_role,
                "to_role": h.to_role,
                "from_need": h.from_need.id,
                "to_need": h.to_need.id,
            }
            for h in handoffs(needs)
        ],
    }


def render_html(
    cfg: Config, model: Model, *, client: str | None = None, rev: str | None = None
) -> str:
    """Render the resolved board as one self-contained interactive HTML document."""
    payload = board_payload(cfg, model, client=client, rev=rev)
    # Escape '<' so an embedded "</script>" or "<!--" in any string can't break out of the tag.
    data = json.dumps(payload, ensure_ascii=False).replace("<", "\\u003c")
    title = str(payload["title"])
    return _TEMPLATE.replace("__TITLE__", _escape(title)).replace("__DATA__", data)


def _escape(text: str) -> str:
    return (
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    )


# The template: inline CSS + inline vanilla JS, no external assets. __TITLE__ and __DATA__ are
# the only substitutions; everything the viewer shows comes from the embedded JSON snapshot.
_TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
:root {
  --bg: #f7f8fa; --panel: #ffffff; --ink: #1a1d23; --muted: #666e7b; --line: #e3e6eb;
  --accent: #3b5bdb; --chip: #eef1f6;
  --delivered: #2f9e44; --pending: #e8a317; --hole: #868e96; --broken: #e03131; --unresolved: #7048e8;
  --shadow: 0 1px 2px rgba(0,0,0,.04), 0 2px 8px rgba(0,0,0,.04);
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --bg: #14161a; --panel: #1c1f26; --ink: #e8eaed; --muted: #9aa3af; --line: #2a2e37;
    --accent: #748ffc; --chip: #242831;
    --delivered: #51cf66; --pending: #ffd43b; --hole: #adb5bd; --broken: #ff6b6b; --unresolved: #b197fc;
    --shadow: none;
  }
}
* { box-sizing: border-box; }
body {
  margin: 0; background: var(--bg); color: var(--ink);
  font: 15px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
}
a { color: var(--accent); }
header {
  position: sticky; top: 0; z-index: 10; background: var(--panel);
  border-bottom: 1px solid var(--line); padding: 14px 16px; box-shadow: var(--shadow);
}
.wrap { max-width: 1040px; margin: 0 auto; padding: 0 16px; }
h1 { font-size: 20px; margin: 0 0 2px; }
.stamp { color: var(--muted); font-size: 13px; }
.bar { height: 10px; border-radius: 6px; background: var(--chip); overflow: hidden; margin: 10px 0 8px; display: flex; }
.bar > span { display: block; height: 100%; }
.seg-delivered { background: var(--delivered); } .seg-pending { background: var(--pending); }
.seg-hole { background: var(--hole); } .seg-broken { background: var(--broken); } .seg-unresolved { background: var(--unresolved); }
.tiles { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 8px; }
.tile {
  border: 1px solid var(--line); background: var(--panel); border-radius: 10px; padding: 7px 11px;
  cursor: pointer; display: flex; align-items: baseline; gap: 7px; font-size: 13px; user-select: none;
}
.tile:hover { border-color: var(--accent); }
.tile.active { border-color: var(--accent); box-shadow: inset 0 0 0 1px var(--accent); }
.tile b { font-size: 17px; }
.dot { width: 9px; height: 9px; border-radius: 50%; display: inline-block; }
.controls { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin-top: 10px; }
input[type=search], select {
  font: inherit; padding: 7px 10px; border: 1px solid var(--line); border-radius: 8px;
  background: var(--panel); color: var(--ink);
}
input[type=search] { flex: 1 1 220px; min-width: 160px; }
label.toggle { display: inline-flex; gap: 6px; align-items: center; font-size: 13px; color: var(--muted); cursor: pointer; }
main { max-width: 1040px; margin: 20px auto; padding: 0 16px; }
.nav { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 16px; }
.nav a { font-size: 13px; text-decoration: none; background: var(--chip); padding: 4px 9px; border-radius: 20px; color: var(--ink); }
.group { margin-bottom: 22px; }
.group > h2 { font-size: 15px; margin: 0 0 8px; display: flex; align-items: baseline; gap: 8px; }
.group > h2 .count { color: var(--muted); font-weight: 400; font-size: 13px; }
.need {
  border: 1px solid var(--line); background: var(--panel); border-radius: 10px; margin-bottom: 7px;
  box-shadow: var(--shadow); overflow: hidden;
}
.need > summary {
  list-style: none; cursor: pointer; padding: 11px 13px; display: grid;
  grid-template-columns: auto 1fr auto; gap: 10px; align-items: center;
}
.need > summary::-webkit-details-marker { display: none; }
.badge {
  font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: .04em;
  padding: 3px 8px; border-radius: 6px; color: #fff; white-space: nowrap;
}
.b-delivered { background: var(--delivered); } .b-pending { background: var(--pending); color: #332701; }
.b-hole { background: var(--hole); } .b-broken { background: var(--broken); } .b-unresolved { background: var(--unresolved); }
.ntext { min-width: 0; }
.nid { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px; color: var(--muted); }
.must { color: var(--broken); font-weight: 700; }
.meta { font-size: 12px; color: var(--muted); white-space: nowrap; }
.detail { padding: 2px 13px 13px; border-top: 1px solid var(--line); font-size: 14px; }
.detail dl { display: grid; grid-template-columns: 110px 1fr; gap: 4px 12px; margin: 10px 0 0; }
.detail dt { color: var(--muted); } .detail dd { margin: 0; }
.src { border-left: 3px solid var(--line); padding: 2px 0 2px 10px; margin: 6px 0; }
.src .q { font-style: italic; }
.tag { font-size: 11px; background: var(--chip); border-radius: 5px; padding: 1px 6px; margin-right: 4px; }
.warn { color: var(--broken); font-size: 13px; }
.empty { color: var(--muted); padding: 30px 0; text-align: center; }
footer { max-width: 1040px; margin: 20px auto 40px; padding: 0 16px; color: var(--muted); font-size: 12px; }
@media print {
  header { position: static; box-shadow: none; }
  .controls, .tile { display: none; } .nav { display: none; }
  .need { break-inside: avoid; } details { } .need[open] summary { }
}
</style>
</head>
<body>
<header><div class="wrap">
  <h1 id="title"></h1>
  <div class="stamp" id="stamp"></div>
  <div class="bar" id="bar"></div>
  <div class="tiles" id="tiles"></div>
  <div class="controls">
    <input type="search" id="q" placeholder="Search needs by id or text…" autocomplete="off">
    <select id="client"></select>
    <select id="group">
      <option value="client">Group by client</option>
      <option value="goal">Group by goal</option>
      <option value="release">Group by release</option>
      <option value="state">Group by state</option>
      <option value="who">Group by who</option>
    </select>
    <label class="toggle"><input type="checkbox" id="must"> must-have only</label>
  </div>
</div></header>
<main>
  <nav class="nav" id="nav"></nav>
  <div id="board"></div>
</main>
<footer id="foot"></footer>
<script id="data" type="application/json">__DATA__</script>
<script>
"use strict";
const DATA = JSON.parse(document.getElementById("data").textContent);
const STATES = ["delivered","pending","hole","broken","unresolved"];
const STATE_LABEL = {delivered:"Delivered",pending:"Pending",hole:"Hole",broken:"Broken",unresolved:"Unresolved"};
const esc = s => String(s==null?"":s).replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const el = (t, cls, html) => { const e = document.createElement(t); if (cls) e.className = cls; if (html!=null) e.innerHTML = html; return e; };

const F = { q:"", client:"", group:"client", must:false, states:new Set() };

function init() {
  document.getElementById("title").textContent = DATA.title;
  document.getElementById("stamp").textContent = DATA.stamp;
  renderBar(); renderTiles(); renderClientFilter();
  document.getElementById("q").addEventListener("input", e => { F.q = e.target.value.toLowerCase(); render(); });
  document.getElementById("client").addEventListener("change", e => { F.client = e.target.value; render(); });
  document.getElementById("group").addEventListener("change", e => { F.group = e.target.value; render(); });
  document.getElementById("must").addEventListener("change", e => { F.must = e.target.checked; render(); });
  const s = DATA.summary;
  document.getElementById("foot").textContent =
    `${s.total} needs · ${s.delivered} delivered · ${s.opinion} opinion${s.opinion===1?"":"s"} · generated by prodc report. A read-only viewer — nothing here changes the board.`;
  render();
}

function renderBar() {
  const s = DATA.summary, bar = document.getElementById("bar"), n = s.total || 1;
  STATES.forEach(st => { const w = (s[st==="hole"?"hole":st]||0)/n*100; if (w>0) { const seg = el("span","seg-"+st); seg.style.width = w+"%"; seg.title = `${STATE_LABEL[st]}: ${s[st]||0}`; bar.appendChild(seg); } });
}

function renderTiles() {
  const s = DATA.summary, box = document.getElementById("tiles");
  const cov = el("div","tile"); cov.innerHTML = `<b>${s.coverage_pct}%</b> coverage`; box.appendChild(cov);
  const tiles = [["delivered",s.delivered],["pending",s.pending],["hole",s.hole],["broken",s.broken],["unresolved",s.unresolved]];
  tiles.forEach(([st,count]) => {
    if (st==="unresolved" && !count) return;
    const t = el("div","tile"); t.dataset.state = st;
    t.innerHTML = `<span class="dot" style="background:var(--${st})"></span><b>${count}</b> ${STATE_LABEL[st]}`;
    t.addEventListener("click", () => { if (F.states.has(st)) F.states.delete(st); else F.states.add(st); t.classList.toggle("active"); render(); });
    box.appendChild(t);
  });
  if (s.must_hole) { const t = el("div","tile"); t.innerHTML = `<span class="must">⚠</span><b>${s.must_hole}</b> must-have gap${s.must_hole===1?"":"s"}`;
    t.addEventListener("click", () => { document.getElementById("must").checked = F.must = true; F.states = new Set(["hole"]); syncTiles(); render(); }); box.appendChild(t); }
}
function syncTiles(){ document.querySelectorAll(".tile[data-state]").forEach(t => t.classList.toggle("active", F.states.has(t.dataset.state))); }

function renderClientFilter() {
  const sel = document.getElementById("client");
  const clients = [...new Set(DATA.needs.map(n => n.client).filter(Boolean))].sort();
  sel.appendChild(new Option("All clients",""));
  clients.forEach(c => sel.appendChild(new Option(c, c)));
  if (!clients.length) sel.style.display = "none";
}

function match(n) {
  if (F.states.size && !F.states.has(n.state)) return false;
  if (F.client && n.client !== F.client) return false;
  if (F.must && !n.must) return false;
  if (F.q && !(n.id.toLowerCase().includes(F.q) || n.text.toLowerCase().includes(F.q))) return false;
  return true;
}

const LABELS = {
  client: n => n.client || "(shared / no client)",
  goal: n => n.goal || "(no goal)",
  release: n => n.release || "(unslotted)",
  who: n => n.who,
  state: n => STATE_LABEL[n.state],
};

function groupKeys(group) {
  // Stable, meaningful order per grouping; declared goals/releases first, in board order.
  if (group === "goal") return DATA.goals.map(g => g.id).concat(["(no goal)"]);
  if (group === "release") return DATA.releases.map(r => r.id).concat(["(unslotted)"]);
  if (group === "state") return STATES.map(s => STATE_LABEL[s]);
  return null;
}

const STATE_RANK = {broken:0,hole:1,unresolved:2,pending:3,delivered:4};
function sortNeeds(a, b) {
  if (a.must !== b.must) return a.must ? -1 : 1;
  if (STATE_RANK[a.state] !== STATE_RANK[b.state]) return STATE_RANK[a.state] - STATE_RANK[b.state];
  return a.id.localeCompare(b.id);
}

function render() {
  syncTiles();
  const board = document.getElementById("board"), nav = document.getElementById("nav");
  board.innerHTML = ""; nav.innerHTML = "";
  const shown = DATA.needs.filter(match);
  const groups = new Map();
  shown.forEach(n => { const k = LABELS[F.group](n); if (!groups.has(k)) groups.set(k, []); groups.get(k).push(n); });
  if (!shown.length) { board.appendChild(el("div","empty","No needs match the current filters.")); return; }

  let order = groupKeys(F.group);
  order = order ? order.filter(k => groups.has(k)) : [...groups.keys()].sort((a,b) => groups.get(b).length - groups.get(a).length || a.localeCompare(b));

  order.forEach((key, i) => {
    const list = groups.get(key).slice().sort(sortNeeds);
    const slug = "g" + i;
    const a = el("a", null, `${esc(key)} <span style="opacity:.6">${list.length}</span>`); a.href = "#" + slug; nav.appendChild(a);
    const g = el("section","group"); g.id = slug;
    const delivered = list.filter(n => n.state==="delivered").length;
    g.appendChild(el("h2", null, `${esc(key)} <span class="count">${delivered}/${list.length} delivered</span>`));
    list.forEach(n => g.appendChild(renderNeed(n)));
    board.appendChild(g);
  });
}

function renderNeed(n) {
  const d = el("details","need");
  const must = n.must ? '<span class="must" title="must-have">● </span>' : "";
  const imp = n.importance!=null ? `<span class="meta">imp ${esc(n.importance)}</span>` : "";
  const sum = el("summary", null,
    `<span class="badge b-${n.state}">${STATE_LABEL[n.state]}</span>` +
    `<span class="ntext">${must}${esc(n.text)} <span class="nid">${esc(n.id)}</span></span>` +
    `<span class="meta">${esc(n.warrant)}${imp?" · "+imp:""}</span>`);
  d.appendChild(sum);
  d.appendChild(renderDetail(n));
  return d;
}

function renderDetail(n) {
  const rows = [];
  const push = (k, v) => { if (v) rows.push(`<dt>${k}</dt><dd>${v}</dd>`); };
  if (n.description) push("detail", esc(n.description));
  push("who", esc(n.who) + (n.label ? ` <span class="meta">(${esc(n.label)})</span>` : ""));
  if (n.client) push("client", esc(n.client));
  if (n.goal) push("goal", esc(n.goal));
  if (n.release) push("release", esc(n.release));
  if (n.claim) push("claim", esc(n.claim));
  if (n.proofs.length) push("proofs", n.proofs.map(p => `<span class="tag">${esc(p)}</span>`).join(" "));
  if (n.detail.length) push("resolution", n.detail.map(esc).join("<br>"));
  if (n.attestation) { const at = n.attestation; push("attested", `${esc(at.who)} (${esc(at.kind)})${at.date?" · "+esc(at.date):""}${at.verdict?" · "+esc(at.verdict):""}`); }

  let srcHtml;
  if (!n.sources.length) srcHtml = '<span class="warn">no source — this need is an opinion</span>';
  else srcHtml = n.sources.map(s => {
    const head = `<span class="tag">${esc(s.kind)}</span>${s.who?" "+esc(s.who):""}${s.date?' <span class="meta">· '+esc(s.date)+'</span>':""}`;
    const q = s.quote ? `<div class="q">“${esc(s.quote)}”</div>` : "";
    const loc = s.locator ? `<div class="meta">${esc(s.locator)}</div>` : "";
    return `<div class="src">${head}${q}${loc}</div>`;
  }).join("");
  push("sources", srcHtml);
  if (n.warnings.length) push("notes", n.warnings.map(w => `<span class="warn">${esc(w)}</span>`).join("<br>"));

  return el("div","detail", `<dl>${rows.join("")}</dl>`);
}

init();
</script>
</body>
</html>
"""
