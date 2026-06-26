#!/usr/bin/env python3
"""Render the multi-persona audit into a single self-contained tabbed HTML file."""
import html
import json
import os
from collections import Counter

from findings_data import FINDINGS

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "audit-report.html")
REPO_URL = "https://github.com/hellodk/kri"

with open(os.path.join(HERE, "issues_map.json")) as fh:
    ISSUES = json.load(fh)

PERSONA_ORDER = [
    "Principal Developer",
    "Principal Architect",
    "Principal SRE",
    "Principal AI/LLM Expert",
    "Principal UI/UX Engineer",
    "Principal Tester",
    "Common User",
]
PERSONA_META = {
    "Principal Developer": ("DEV", "Code quality, bugs, logic & concurrency"),
    "Principal Architect": ("ARC", "Structure, coupling, scalability"),
    "Principal SRE": ("SRE", "Deploy, reliability, observability, sec-ops"),
    "Principal AI/LLM Expert": ("AI", "Agent, prompts, RAG, injection, cost"),
    "Principal UI/UX Engineer": ("UX", "Frontend, accessibility, performance"),
    "Principal Tester": ("TST", "Coverage gaps, flakiness, test quality"),
    "Common User": ("USR", "Onboarding, docs, first-run experience"),
}
SEV_ORDER = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}
SEV_CLASS = {"Critical": "crit", "High": "high", "Medium": "med", "Low": "low"}


def esc(s: str) -> str:
    return html.escape(str(s))


def issue_link(fid: str) -> str:
    info = ISSUES.get(fid)
    if not info:
        return '<span class="noissue">no issue</span>'
    return f'<a class="ilink" href="{info["url"]}" target="_blank" rel="noopener">#{info["number"]}</a>'


def card(f: dict) -> str:
    sev = f["severity"]
    labels = " ".join(f'<span class="lbl">{esc(l)}</span>' for l in f.get("labels", []))
    return f"""
    <article class="card {SEV_CLASS[sev]}" data-sev="{sev}">
      <header class="card-h">
        <span class="sev {SEV_CLASS[sev]}">{esc(sev)}</span>
        <span class="fid">{esc(f['id'])}</span>
        <h3>{esc(f['title'])}</h3>
        <span class="issue">{issue_link(f['id'])}</span>
      </header>
      <div class="loc"><code>{esc(f['location'])}</code></div>
      <pre class="ev">{esc(f['evidence'])}</pre>
      <div class="row"><span class="k">Impact</span><p>{esc(f['impact'])}</p></div>
      <div class="row"><span class="k">Fix</span><p>{esc(f['recommendation'])}</p></div>
      <div class="labels">{labels}</div>
    </article>"""


def persona_section(persona: str) -> str:
    items = sorted(
        [f for f in FINDINGS if f["persona"] == persona],
        key=lambda f: (SEV_ORDER[f["severity"]], f["id"]),
    )
    short, blurb = PERSONA_META[persona]
    counts = Counter(f["severity"] for f in items)
    chips = " ".join(
        f'<span class="chip {SEV_CLASS[s]}">{counts[s]} {s}</span>'
        for s in ["Critical", "High", "Medium", "Low"] if counts[s]
    )
    cards = "\n".join(card(f) for f in items)
    return f"""
  <section class="tab" id="tab-{short}">
    <div class="tab-head">
      <h2>{esc(persona)}</h2>
      <p class="blurb">{esc(blurb)} &middot; {len(items)} findings</p>
      <div class="chips">{chips}</div>
    </div>
    {cards}
  </section>"""


def overview() -> str:
    sev_counts = Counter(f["severity"] for f in FINDINGS)
    rows = ""
    for p in PERSONA_ORDER:
        items = [f for f in FINDINGS if f["persona"] == p]
        c = Counter(f["severity"] for f in items)
        short = PERSONA_META[p][0]
        rows += (
            f'<tr><td><a href="#" data-go="{short}">{esc(p)}</a></td>'
            f'<td class="num">{len(items)}</td>'
            f'<td class="num crit-t">{c["Critical"] or ""}</td>'
            f'<td class="num high-t">{c["High"] or ""}</td>'
            f'<td class="num med-t">{c["Medium"] or ""}</td>'
            f'<td class="num low-t">{c["Low"] or ""}</td></tr>'
        )
    crit_list = "\n".join(
        f'<li><span class="sev crit">Critical</span> '
        f'<code>{esc(f["id"])}</code> {esc(f["title"])} {issue_link(f["id"])}</li>'
        for f in FINDINGS if f["severity"] == "Critical"
    )
    return f"""
  <section class="tab active" id="tab-OVERVIEW">
    <div class="tab-head">
      <h2>Audit Overview</h2>
      <p class="blurb">External multi-persona audit of the <b>kri</b> Fleet Platform &middot;
      {len(FINDINGS)} findings &middot; filed as GitHub issues
      <a href="{REPO_URL}/issues?q=is%3Aissue+label%3Aaudit" target="_blank" rel="noopener">label:audit</a>.
      Nothing has been fixed — these are for review.</p>
      <div class="chips">
        <span class="chip crit">{sev_counts['Critical']} Critical</span>
        <span class="chip high">{sev_counts['High']} High</span>
        <span class="chip med">{sev_counts['Medium']} Medium</span>
        <span class="chip low">{sev_counts['Low']} Low</span>
      </div>
    </div>
    <table class="summary">
      <thead><tr><th>Auditor</th><th>Total</th><th>Crit</th><th>High</th><th>Med</th><th>Low</th></tr></thead>
      <tbody>{rows}</tbody>
    </table>
    <h3 class="crit-head">All Critical findings</h3>
    <ul class="critlist">{crit_list}</ul>
  </section>"""


def tab_buttons() -> str:
    btns = ['<button class="tb active" data-tab="OVERVIEW">Overview</button>']
    for p in PERSONA_ORDER:
        short = PERSONA_META[p][0]
        n = sum(1 for f in FINDINGS if f["persona"] == p)
        btns.append(f'<button class="tb" data-tab="{short}">{esc(p)} <span class="b">{n}</span></button>')
    return "\n".join(btns)


HTML = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>kri Fleet Platform — External Audit</title>
<style>
  :root {{
    --bg:#0d1117; --panel:#161b22; --panel2:#1c2230; --border:#30363d;
    --txt:#e6edf3; --muted:#9198a1; --acc:#58a6ff;
    --crit:#f85149; --high:#fb8500; --med:#d29922; --low:#3fb950;
  }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--bg); color:var(--txt);
    font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif; }}
  header.top {{ padding:24px 28px 8px; border-bottom:1px solid var(--border); background:var(--panel); }}
  header.top h1 {{ margin:0; font-size:22px; letter-spacing:.3px; }}
  header.top p {{ margin:6px 0 0; color:var(--muted); font-size:13.5px; }}
  nav.tabs {{ position:sticky; top:0; z-index:10; display:flex; flex-wrap:wrap; gap:6px;
    padding:12px 20px; background:var(--panel); border-bottom:1px solid var(--border); }}
  .tb {{ background:var(--panel2); color:var(--txt); border:1px solid var(--border);
    padding:7px 12px; border-radius:8px; cursor:pointer; font-size:13px; transition:.15s; }}
  .tb:hover {{ border-color:var(--acc); }}
  .tb.active {{ background:var(--acc); color:#04101f; border-color:var(--acc); font-weight:600; }}
  .tb .b {{ display:inline-block; background:rgba(255,255,255,.15); border-radius:10px;
    padding:0 6px; margin-left:4px; font-size:11px; }}
  .tb.active .b {{ background:rgba(0,0,0,.2); }}
  main {{ max-width:1080px; margin:0 auto; padding:22px 20px 80px; }}
  .tab {{ display:none; }} .tab.active {{ display:block; }}
  .tab-head h2 {{ margin:6px 0 2px; font-size:20px; }}
  .blurb {{ color:var(--muted); margin:2px 0 12px; font-size:13.5px; }}
  .chips, .chip {{ display:inline-flex; }} .chips {{ gap:8px; flex-wrap:wrap; margin-bottom:14px; }}
  .chip {{ align-items:center; gap:6px; padding:3px 10px; border-radius:20px; font-size:12px;
    border:1px solid var(--border); background:var(--panel2); }}
  .chip.crit{{color:var(--crit);}} .chip.high{{color:var(--high);}}
  .chip.med{{color:var(--med);}} .chip.low{{color:var(--low);}}
  .card {{ background:var(--panel); border:1px solid var(--border); border-left:4px solid var(--border);
    border-radius:10px; padding:14px 16px; margin:12px 0; }}
  .card.crit {{ border-left-color:var(--crit); }} .card.high {{ border-left-color:var(--high); }}
  .card.med {{ border-left-color:var(--med); }} .card.low {{ border-left-color:var(--low); }}
  .card-h {{ display:flex; align-items:center; gap:10px; flex-wrap:wrap; }}
  .card-h h3 {{ margin:0; font-size:15.5px; flex:1 1 320px; }}
  .sev {{ font-size:11px; font-weight:700; padding:2px 8px; border-radius:6px; text-transform:uppercase; letter-spacing:.4px; }}
  .sev.crit {{ background:rgba(248,81,73,.15); color:var(--crit); }}
  .sev.high {{ background:rgba(251,133,0,.15); color:var(--high); }}
  .sev.med {{ background:rgba(210,153,34,.15); color:var(--med); }}
  .sev.low {{ background:rgba(63,185,80,.15); color:var(--low); }}
  .fid {{ font:600 11.5px ui-monospace,SFMono-Regular,Menlo,monospace; color:var(--muted); }}
  .issue {{ margin-left:auto; }}
  .ilink {{ color:var(--acc); text-decoration:none; font:600 13px ui-monospace,monospace;
    border:1px solid var(--border); border-radius:6px; padding:2px 8px; }}
  .ilink:hover {{ border-color:var(--acc); }}
  .noissue {{ color:var(--muted); font-size:12px; }}
  .loc {{ margin:8px 0 6px; }}
  .loc code {{ color:var(--acc); font:12px ui-monospace,monospace; word-break:break-all; }}
  pre.ev {{ background:#0b0f14; border:1px solid var(--border); border-radius:8px;
    padding:10px 12px; overflow-x:auto; font:12.5px ui-monospace,monospace; color:#c9d1d9; margin:6px 0 10px; }}
  .row {{ display:flex; gap:10px; margin:6px 0; }}
  .row .k {{ flex:0 0 54px; color:var(--muted); font-size:12px; font-weight:600; text-transform:uppercase;
    letter-spacing:.4px; padding-top:2px; }}
  .row p {{ margin:0; }}
  .labels {{ margin-top:10px; display:flex; gap:6px; flex-wrap:wrap; }}
  .lbl {{ font-size:11px; color:var(--muted); border:1px solid var(--border); border-radius:12px; padding:1px 8px; }}
  table.summary {{ border-collapse:collapse; width:100%; margin:8px 0 22px; }}
  table.summary th, table.summary td {{ border:1px solid var(--border); padding:8px 10px; text-align:left; }}
  table.summary th {{ background:var(--panel2); font-size:12px; text-transform:uppercase; letter-spacing:.4px; color:var(--muted); }}
  table.summary td.num {{ text-align:center; font-variant-numeric:tabular-nums; }}
  .crit-t {{ color:var(--crit); font-weight:700; }} .high-t {{ color:var(--high); font-weight:700; }}
  .med-t {{ color:var(--med); }} .low-t {{ color:var(--low); }}
  table.summary a {{ color:var(--acc); text-decoration:none; }}
  .crit-head {{ margin-top:6px; }}
  ul.critlist {{ list-style:none; padding:0; }}
  ul.critlist li {{ padding:7px 0; border-bottom:1px solid var(--border); }}
  ul.critlist code {{ color:var(--muted); font-size:12px; }}
  footer {{ text-align:center; color:var(--muted); font-size:12px; padding:20px; }}
</style>
</head>
<body>
<header class="top">
  <h1>kri Fleet Platform — External Audit</h1>
  <p>Seven reviewers: Principal Developer, Architect, SRE, AI/LLM Expert, UI/UX Engineer, Tester, and a Common User.
     {len(FINDINGS)} findings &middot; one GitHub issue each &middot; <b>none fixed</b> (review first).</p>
</header>
<nav class="tabs">
{tab_buttons()}
</nav>
<main>
{overview()}
{''.join(persona_section(p) for p in PERSONA_ORDER)}
</main>
<footer>Generated from <code>audit/findings_data.py</code> &middot; issues labelled
  <a href="{REPO_URL}/issues?q=is%3Aissue+label%3Aaudit" target="_blank" rel="noopener" style="color:var(--acc)">audit</a>.</footer>
<script>
  const tabs = document.querySelectorAll('.tab');
  const btns = document.querySelectorAll('.tb');
  function show(id) {{
    tabs.forEach(t => t.classList.toggle('active', t.id === 'tab-' + id));
    btns.forEach(b => b.classList.toggle('active', b.dataset.tab === id));
    window.scrollTo({{top:0, behavior:'instant'}});
  }}
  btns.forEach(b => b.addEventListener('click', () => show(b.dataset.tab)));
  document.querySelectorAll('[data-go]').forEach(a =>
    a.addEventListener('click', e => {{ e.preventDefault(); show(a.dataset.go); }}));
</script>
</body>
</html>"""

with open(OUT, "w") as fh:
    fh.write(HTML)
print(f"Wrote {OUT} ({len(HTML):,} bytes)")
