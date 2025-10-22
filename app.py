# -*- coding: utf-8 -*-
r"""
Self-contained Flask survey app for subjective evaluation of animation-style images.

Features
- Part A (single image): 4 sliders + gated checks (text correctness, no-people).
- Part B (ranking): rank 4 images (one per provider) for the same prompt/seed.
- Part C (diversity): rate diversity of 5 variations (same model, 5 seeds).
- Reads latest manifests from E:\research\<provider>\manifests\run-*\manifest.csv.
- Serves images directly from disk (whitelisted roots).
- Stores responses in SQLite (E:\research\survey_results by default).
- Admin dashboard (login protected) with live tables and CHARTS (Chart.js).
- Full-session flow: /start/full walks A → B → C automatically; optional ?A=12&B=8&C=6 overrides.

Requirements: Flask, python-dotenv, PyYAML
"""

from __future__ import annotations
import base64, csv, json, os, random, sqlite3, string, time, uuid, math
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple, Any

from flask import (
    Flask, render_template, render_template_string, request, redirect,
    url_for, send_file, abort, session, flash, jsonify
)
from dotenv import load_dotenv
import yaml
from functools import wraps
import threading
from collections import defaultdict
from typing import DefaultDict, Set
# ---------------------------- Bootstrapping assets ----------------------------

APP_ROOT = Path(__file__).resolve().parent

TEMPLATES: Dict[str, str] = {
"base.html": r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <title>{{ title or "Animation Image Survey" }}</title>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <link rel="stylesheet" href="{{ url_for('static', filename='style.css') }}">
  <script defer src="{{ url_for('static', filename='client.js') }}"></script>
</head>
<body>
  <header>
    <div class="container">
      <h1>{{ heading or "Animation Image Survey" }}</h1>
    </div>
  </header>
  <main class="container">
    {% with messages = get_flashed_messages() %}
      {% if messages %}
        <div class="flash">
          {% for m in messages %}<div>{{ m }}</div>{% endfor %}
        </div>
      {% endif %}
    {% endwith %}
    {% block content %}{% endblock %}
  </main>
  <footer>
    <div class="container small">
      <span>Local survey • Your responses are anonymous.</span>
    </div>
  </footer>
</body>
</html>
""",

"home.html": r"""{% extends "base.html" %}
{% block content %}
<section class="card">
  <h2>Welcome</h2>
  <p>Help us evaluate AI models for <strong>animation-style images</strong>. Choose one quick module:</p>
  <ul>
    <li><strong>Part A</strong> – Rate single images.</li>
    <li><strong>Part B</strong> – Rank 4 images for the same prompt.</li>
    <li><strong>Part C</strong> – Judge diversity of 5 variations.</li>
  </ul>
  <div class="buttons">
    <a class="btn" href="{{ url_for('onboarding') }}">Onboarding</a>
    <a class="btn" href="{{ url_for('admin_login') }}">Admin</a>
  </div>
</section>

<section class="grid-3">
  <a class="card btn-card" href="{{ url_for('start_module','A') }}">
    <h3>Start Part A</h3>
    <p>~10–12 minutes</p>
  </a>
  <a class="card btn-card" href="{{ url_for('start_module','B') }}">
    <h3>Start Part B</h3>
    <p>~10–12 minutes</p>
  </a>
  <a class="card btn-card" href="{{ url_for('start_module','C') }}">
    <h3>Start Part C</h3>
    <p>~8–10 minutes</p>
  </a>
</section>

<section class="card">
  <h3>Do everything in one go?</h3>
  <p>Run a full session: <strong>A → B → C</strong> with the default number of items.</p>
  <div class="buttons">
    <a class="btn" href="{{ url_for('start_full_session') }}">Start Full Session</a>
    <a class="btn" href="{{ url_for('start_full_session') }}?A=12&B=8&C=6">Short Full Session</a>
  </div>
</section>
{% endblock %}
""",

"onboarding.html": r"""{% extends "base.html" %}
{% block content %}
<section class="card">
  <h2>How to rate</h2>
  <ol>
    <li><strong>Prompt Adherence</strong>: Did the image follow the instructions?</li>
    <li><strong>Aesthetic Quality</strong>: Is it visually pleasing and well-composed?</li>
    <li><strong>Creativity</strong>: Is it fresh/interesting while still on-brief?</li>
    <li><strong>Animation-Style Look</strong>: Does it look like an illustration/cartoon?</li>
  </ol>
  <p>If a prompt asks for specific <strong>text</strong>, mark whether it’s correct/legible. If a prompt says <strong>no people</strong>, flag any people that appear.</p>
  <p>For rankings, you’ll see 4 images for one prompt—choose a unique rank 1 (best) to 4 (worst) for each.</p>
  <div class="buttons">
    <a class="btn" href="{{ url_for('start_module','A') }}">Start Part A</a>
    <a class="btn" href="{{ url_for('start_module','B') }}">Start Part B</a>
    <a class="btn" href="{{ url_for('start_module','C') }}">Start Part C</a>
    <a class="btn" href="{{ url_for('start_full_session') }}">Start Full Session (A → B → C)</a>
  </div>
</section>
{% endblock %}
""",

"module_a.html": r"""{% extends "base.html" %}
{% block content %}
<form class="card" method="post" action="{{ url_for('submit_a') }}" onsubmit="return beforeSubmit('elapsed_ms_a')">
  <div class="headrow">
    <div>Part A — Image {{ idx }} of {{ total }}</div>
  </div>
  <p class="prompt"><strong>Prompt:</strong> {{ item.prompt_text }}</p>
  <div class="img-wrap">
    <img src="{{ url_for('serve_img') }}?p={{ img_b64 }}" alt="image"/>
  </div>

  <div class="field">
    <label>Prompt Adherence (1–7)</label>
    <input type="range" name="adherence" min="1" max="7" value="4" step="1" oninput="showVal(this)">
    <span class="bubble">4</span>
  </div>
  <div class="field">
    <label>Aesthetic Quality (1–7)</label>
    <input type="range" name="aesthetic" min="1" max="7" value="4" step="1" oninput="showVal(this)">
    <span class="bubble">4</span>
  </div>
  <div class="field">
    <label>Creativity (1–7)</label>
    <input type="range" name="creativity" min="1" max="7" value="4" step="1" oninput="showVal(this)">
    <span class="bubble">4</span>
  </div>
  <div class="field">
    <label>Animation-Style Look (1–7)</label>
    <input type="range" name="style" min="1" max="7" value="4" step="1" oninput="showVal(this)">
    <span class="bubble">4</span>
  </div>

  {% if item.has_text %}
  <div class="field">
    <label>Text correctness</label>
    <select name="text_correctness" required>
      <option value="">Choose…</option>
      <option value="correct">Correct</option>
      <option value="partial">Partially correct</option>
      <option value="incorrect">Incorrect / Illegible</option>
    </select>
  </div>
  {% else %}
  <input type="hidden" name="text_correctness" value="">
  {% endif %}

  {% if item.no_people %}
  <div class="field">
    <label>Does the image wrongly include people?</label>
    <select name="people_violation" required>
      <option value="0">No</option>
      <option value="1">Yes</option>
    </select>
  </div>
  {% else %}
  <input type="hidden" name="people_violation" value="0">
  {% endif %}

  <!-- Hidden payload -->
  <input type="hidden" name="provider" value="{{ item.provider }}">
  <input type="hidden" name="model" value="{{ item.model }}">
  <input type="hidden" name="category_id" value="{{ item.category_id }}">
  <input type="hidden" name="prompt_id" value="{{ item.prompt_id }}">
  <input type="hidden" name="seed_label" value="{{ item.seed_label }}">
  <input type="hidden" name="image_path" value="{{ item.image_path }}">
  <input type="hidden" name="prompt_text" value="{{ item.prompt_text }}">
  <input type="hidden" name="has_text" value="{{ item.has_text }}">
  <input type="hidden" name="no_people" value="{{ item.no_people }}">
  <input type="hidden" id="elapsed_ms_a" name="elapsed_ms" value="0">

  <div class="buttons">
    <button class="btn" type="submit">Submit & Next</button>
  </div>
</form>
{% endblock %}
""",

"module_b.html": r"""{% extends "base.html" %}
{% block content %}
<form class="card" method="post" action="{{ url_for('submit_b') }}" onsubmit="return beforeSubmit('elapsed_ms_b')">
  <div class="headrow">
    <div>Part B — Set {{ idx }} of {{ total }}</div>
  </div>
  <p><strong>Prompt ID:</strong> {{ prompt }} &nbsp; <strong>Category:</strong> {{ cat }} &nbsp; <strong>Seed:</strong> {{ seed }}</p>

  <div class="grid-2">
    {% for tile in display %}
    <div class="tile">
      <img src="{{ url_for('serve_img') }}?p={{ tile.img_b64 }}" alt="candidate">
      <div class="rank-field">
        <label>Rank (1=best, 4=worst)</label>
        <select class="rank-select" name="rank_{{ tile.provider }}" required onchange="enforceUniqueRanks(this)">
          <option value="">Choose…</option>
          <option>1</option><option>2</option><option>3</option><option>4</option>
        </select>
      </div>
      <input type="hidden" name="image_{{ tile.provider }}" value="{{ tile.image_path }}">
    </div>
    {% endfor %}
  </div>

  <!-- Hidden payload -->
  <input type="hidden" name="category_id" value="{{ cat }}">
  <input type="hidden" name="prompt_id" value="{{ prompt }}">
  <input type="hidden" name="seed_label" value="{{ seed }}">
  <input type="hidden" id="elapsed_ms_b" name="elapsed_ms" value="0">

  <div class="buttons">
    <button class="btn" type="submit">Submit & Next</button>
  </div>
</form>
{% endblock %}
""",

"module_c.html": r"""{% extends "base.html" %}
{% block content %}
<form class="card" method="post" action="{{ url_for('submit_c') }}" onsubmit="return beforeSubmit('elapsed_ms_c')">
  <div class="headrow">
    <div>Part C — Set {{ idx }} of {{ total }}</div>
  </div>
  <p><strong>Provider:</strong> {{ provider }} &nbsp; <strong>Category:</strong> {{ cat }} &nbsp; <strong>Prompt:</strong> {{ prompt }}</p>

  <div class="grid-5">
    {% for im in images %}
      <div class="tile">
        <img src="{{ url_for('serve_img') }}?p={{ im.img_b64 }}" alt="variant">
        <div class="seedlabel">seed {{ im.seed_label }}</div>
      </div>
    {% endfor %}
  </div>

  <div class="field">
    <label>Diversity (1–7): How different are these while still matching the prompt?</label>
    <input type="range" name="diversity" min="1" max="7" value="4" step="1" oninput="showVal(this)">
    <span class="bubble">4</span>
  </div>

  <!-- Hidden payload -->
  <input type="hidden" name="provider" value="{{ provider }}">
  <input type="hidden" name="category_id" value="{{ cat }}">
  <input type="hidden" name="prompt_id" value="{{ prompt }}">
  <input type="hidden" id="elapsed_ms_c" name="elapsed_ms" value="0">
  <input type="hidden" name="image_paths_json" value='{{ images | tojson }}'>

  <div class="buttons">
    <button class="btn" type="submit">Submit & Next</button>
  </div>
</form>
{% endblock %}
""",

"thanks.html": r"""{% extends "base.html" %}
{% block content %}
<section class="card">
  <h2>Thanks!</h2>
  <p>Your responses were recorded. You can choose another part or close this window.</p>
  <div class="buttons">
    <a class="btn" href="{{ url_for('home') }}">Home</a>
  </div>
</section>
{% endblock %}
""",

"admin_login.html": r"""{% extends "base.html" %}
{% block content %}
<form class="card" method="post" action="{{ url_for('admin_login', next=request.args.get('next')) }}">
  <h2>Admin Login</h2>
  <p>Enter the admin token.</p>
  <div class="field">
    <label>Token</label>
    <input name="token" type="password" required autocomplete="current-password" />
  </div>
  <div class="buttons">
    <button class="btn" type="submit">Login</button>
    <a class="btn" href="{{ url_for('home') }}">Cancel</a>
  </div>
</form>
{% endblock %}
""",

"admin.html": r"""{% extends "base.html" %}
{% block content %}

<!-- Load Chart.js via CDN -->
<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>

<section class="card">
  <div class="headrow">
    <h2>Overview</h2>
    <div>
      <button class="btn" onclick="reloadPools()">Reload Pools</button>
      <a class="btn" href="{{ url_for('admin_export') }}">Export CSVs</a>
      <a class="btn" href="{{ url_for('admin_logout') }}">Logout</a>
    </div>
  </div>

  <div id="overview" class="grid-3 smallcards">
    <div class="mini card-lite"><div class="k">—</div><div class="t">Raters</div></div>
    <div class="mini card-lite"><div class="k">—</div><div class="t">Responses A</div></div>
    <div class="mini card-lite"><div class="k">—</div><div class="t">Responses B</div></div>
    <div class="mini card-lite"><div class="k">—</div><div class="t">Responses C</div></div>
    <div class="mini card-lite"><div class="k">—</div><div class="t">Pool A</div></div>
    <div class="mini card-lite"><div class="k">—</div><div class="t">Pool B</div></div>
    <div class="mini card-lite"><div class="k">—</div><div class="t">Pool C</div></div>
  </div>
</section>

<section class="card">
  <h3>Module A — MOS per provider</h3>
  <div class="charts">
    <canvas id="chartA_MOS"></canvas>
    <canvas id="chartA_Text"></canvas>
    <canvas id="chartA_People"></canvas>
  </div>
  <table id="tableA" class="table">
    <thead><tr>
      <th>Provider</th><th>N</th>
      <th>Adherence</th><th>Aesthetic</th><th>Creativity</th><th>Style</th>
    </tr></thead>
    <tbody></tbody>
  </table>

  <div class="grid-2">
    <div>
      <h4>Text correctness (has_text prompts)</h4>
      <table id="tableAText" class="table">
        <thead><tr><th>Provider</th><th>Correct</th><th>Partial</th><th>Incorrect</th></tr></thead>
        <tbody></tbody>
      </table>
    </div>
    <div>
      <h4>No-people compliance</h4>
      <table id="tableAPeople" class="table">
        <thead><tr><th>Provider</th><th>With rule</th><th>Violations</th><th>Violation rate</th></tr></thead>
        <tbody></tbody>
      </table>
    </div>
  </div>
</section>

<section class="card">
  <h3>Module B — Rankings</h3>
  <div class="charts">
    <canvas id="chartB_AvgRank"></canvas>
    <canvas id="chartB_Wins"></canvas>
  </div>
  <table id="tableB" class="table">
    <thead><tr>
      <th>Provider</th><th>N</th><th>Avg rank ↓</th><th>#1 Wins</th>
    </tr></thead>
    <tbody></tbody>
  </table>
</section>

<section class="card">
  <h3>Module C — Diversity</h3>
  <div class="charts">
    <canvas id="chartC_Diversity"></canvas>
  </div>
  <table id="tableC" class="table">
    <thead><tr>
      <th>Provider</th><th>N</th><th>Avg diversity</th>
    </tr></thead>
    <tbody></tbody>
  </table>
</section>

<section class="card">
  <h3>Recent submissions</h3>
  <div class="grid-3 smallcards" id="recent">
    <div>
      <h4>Part A</h4>
      <ul id="recentA" class="list"></ul>
    </div>
    <div>
      <h4>Part B</h4>
      <ul id="recentB" class="list"></ul>
    </div>
    <div>
      <h4>Part C</h4>
      <ul id="recentC" class="list"></ul>
    </div>
  </div>
</section>

<script>
let timer = null;

// Chart handles
let chA_MOS = null, chA_Text = null, chA_People = null;
let chB_Avg = null, chB_Wins = null;
let chC_Div = null;

function makeBar(canvasId, labels, datasets, stacked=false, suggestedMin=null, suggestedMax=null) {
  const ctx = document.getElementById(canvasId).getContext('2d');
  const opt = {
    responsive: true,
    animation: false,
    interaction: { mode: 'index', intersect: false },
    scales: {
      x: { stacked: stacked },
      y: { stacked: stacked, beginAtZero: true }
    },
    plugins: { legend: { position: 'top' } }
  };
  if (suggestedMin !== null || suggestedMax !== null) {
    opt.scales.y.suggestedMin = suggestedMin;
    opt.scales.y.suggestedMax = suggestedMax;
  }
  return new Chart(ctx, {
    type: 'bar',
    data: { labels, datasets },
    options: opt
  });
}

function toLabels(arr, key="provider") {
  return (arr||[]).map(x => x[key]);
}

function fetchStats() {
  return fetch("{{ url_for('admin_stats') }}").then(r => r.json());
}

function pct(num, den) {
  if (!den) return 0;
  return Math.round((100 * num / den) * 10) / 10;
}

function initCharts(data) {
  // Module A MOS
  const A_mos = data.A.mos || [];
  const labelsA = toLabels(A_mos);
  const dsA = [
    { label: 'Adherence',  data: A_mos.map(x => x.adherence),  borderWidth: 1 },
    { label: 'Aesthetic',  data: A_mos.map(x => x.aesthetic),  borderWidth: 1 },
    { label: 'Creativity', data: A_mos.map(x => x.creativity), borderWidth: 1 },
    { label: 'Style',      data: A_mos.map(x => x.style),      borderWidth: 1 }
  ];
  chA_MOS = makeBar('chartA_MOS', labelsA, dsA, false, 1, 7);

  // Text correctness (stacked counts)
  const A_text = data.A.text || [];
  const labelsAT = toLabels(A_text);
  const dsAT = [
    { label: 'Correct',   data: A_text.map(x => x.correct || 0) },
    { label: 'Partial',   data: A_text.map(x => x.partial || 0) },
    { label: 'Incorrect', data: A_text.map(x => x.incorrect || 0) }
  ];
  chA_Text = makeBar('chartA_Text', labelsAT, dsAT, true);

  // People violation rate
  const A_people = data.A.people || [];
  const labelsAP = toLabels(A_people);
  const rates = A_people.map(x => {
    const rule = x.with_rule || 0, viol = x.violations || 0;
    return rule ? +(100 * viol / rule).toFixed(1) : 0;
  });
  chA_People = makeBar('chartA_People', labelsAP, [{ label: 'Violation %', data: rates }]);

  // Module B Avg Rank + Wins
  const B = data.B.ranking || [];
  const labelsB = toLabels(B, "provider");
  chB_Avg = makeBar('chartB_AvgRank', labelsB, [{ label: 'Avg Rank (lower better)', data: B.map(x => x.avg_rank) }], false, 1, 4);
  chB_Wins = makeBar('chartB_Wins', labelsB, [{ label: '#1 Wins', data: B.map(x => x.wins) }]);

  // Module C Diversity
  const C = data.C.diversity || [];
  const labelsC = toLabels(C, "provider");
  chC_Div = makeBar('chartC_Diversity', labelsC, [{ label: 'Avg Diversity', data: C.map(x => x.avg_diversity) }], false, 1, 7);
}

function updateCharts(data) {
  function upd(ch, labels, datasets) {
    if (!ch) return;
    ch.data.labels = labels;
    ch.data.datasets = datasets;
    ch.update();
  }

  const A_mos = data.A.mos || [];
  upd(chA_MOS, toLabels(A_mos), [
    { label: 'Adherence',  data: A_mos.map(x => x.adherence) },
    { label: 'Aesthetic',  data: A_mos.map(x => x.aesthetic) },
    { label: 'Creativity', data: A_mos.map(x => x.creativity) },
    { label: 'Style',      data: A_mos.map(x => x.style) }
  ]);

  const A_text = data.A.text || [];
  upd(chA_Text, toLabels(A_text), [
    { label: 'Correct',   data: A_text.map(x => x.correct || 0) },
    { label: 'Partial',   data: A_text.map(x => x.partial || 0) },
    { label: 'Incorrect', data: A_text.map(x => x.incorrect || 0) }
  ]);

  const A_people = data.A.people || [];
  const labelsAP = toLabels(A_people);
  const rates = A_people.map(x => {
    const rule = x.with_rule || 0, viol = x.violations || 0;
    return rule ? +(100 * viol / rule).toFixed(1) : 0;
  });
  upd(chA_People, labelsAP, [{ label: 'Violation %', data: rates }]);

  const B = data.B.ranking || [];
  upd(chB_Avg, toLabels(B, "provider"), [{ label: 'Avg Rank (lower better)', data: B.map(x => x.avg_rank) }]);
  upd(chB_Wins, toLabels(B, "provider"), [{ label: '#1 Wins', data: B.map(x => x.wins) }]);

  const C = data.C.diversity || [];
  upd(chC_Div, toLabels(C, "provider"), [{ label: 'Avg Diversity', data: C.map(x => x.avg_diversity) }]);
}

function fmt(n) { return n === null || n === undefined ? "—" : String(n); }

async function refreshAll() {
  const r = await fetch("{{ url_for('admin_stats') }}");
  const js = await r.json();
  if (!js.ok) return;

  const d = js.data;

  // Overview counters
  const ov = document.querySelectorAll("#overview .k");
  const t = d.totals, p = d.pools;
  const vals = [t.raters, t.A, t.B, t.C, p.pool_A, p.pool_B, p.pool_C];
  ov.forEach((el, i) => el.textContent = fmt(vals[i]));

  // Tables
  const tbA = document.querySelector("#tableA tbody");
  tbA.innerHTML = "";
  (d.A.mos || []).forEach(row => {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td>${row.provider}</td><td>${row.n}</td>
                    <td>${row.adherence}</td><td>${row.aesthetic}</td>
                    <td>${row.creativity}</td><td>${row.style}</td>`;
    tbA.appendChild(tr);
  });

  const tbAT = document.querySelector("#tableAText tbody");
  tbAT.innerHTML = "";
  (d.A.text || []).forEach(row => {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td>${row.provider}</td>
                    <td>${row.correct||0}</td><td>${row.partial||0}</td><td>${row.incorrect||0}</td>`;
    tbAT.appendChild(tr);
  });

  const tbAP = document.querySelector("#tableAPeople tbody");
  tbAP.innerHTML = "";
  (d.A.people || []).forEach(row => {
    const withRule = row.with_rule || 0;
    const viol = row.violations || 0;
    const rate = withRule ? ((100*viol/withRule).toFixed(1)+"%") : "—";
    const tr = document.createElement("tr");
    tr.innerHTML = `<td>${row.provider}</td>
                    <td>${withRule}</td><td>${viol}</td><td>${rate}</td>`;
    tbAP.appendChild(tr);
  });

  const tbB = document.querySelector("#tableB tbody");
  tbB.innerHTML = "";
  (d.B.ranking || []).forEach(row => {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td>${row.provider}</td><td>${row.n}</td>
                    <td>${row.avg_rank}</td><td>${row.wins}</td>`;
    tbB.appendChild(tr);
  });

  const tbC = document.querySelector("#tableC tbody");
  tbC.innerHTML = "";
  (d.C.diversity || []).forEach(row => {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td>${row.provider}</td><td>${row.n}</td><td>${row.avg_diversity}</td>`;
    tbC.appendChild(tr);
  });

  // Charts (first call creates, later calls update)
  if (!chA_MOS) {
    initCharts(d);
  } else {
    updateCharts(d);
  }
}

function startPolling() {
  if (timer) clearInterval(timer);
  refreshAll();
  timer = setInterval(refreshAll, 5000);
}

async function reloadPools() {
  const r = await fetch("{{ url_for('admin_reload') }}", { method: "POST" });
  const js = await r.json();
  if (js.ok) {
    refreshAll();
    alert("Task pools rebuilt from latest manifests.");
  } else {
    alert("Reload failed: " + (js.error || "Unknown error"));
  }
}

startPolling();
</script>

{% endblock %}
"""
}

STATIC_FILES: Dict[str, str] = {
"style.css": r""":root {
  --bg: #0f1115; --fg: #e7e9ee; --muted: #aab2c0; --accent: #5aa0ff; --card: #151923;
  --border: #242a36; --btn: #1e2633; --btn-hover: #263142;
}
* { box-sizing: border-box; }
body { margin: 0; font-family: system-ui, Segoe UI, Roboto, Helvetica, Arial, sans-serif;
       background: var(--bg); color: var(--fg); }
header, footer { background: #0c0f14; border-bottom: 1px solid var(--border); }
footer { border-top: 1px solid var(--border); border-bottom: none; margin-top: 24px; }
.container { max-width: 1100px; margin: 0 auto; padding: 16px; }
.small { color: var(--muted); font-size: 14px; }
h1, h2, h3 { margin: 0 0 12px; }
.card { background: var(--card); border: 1px solid var(--border); border-radius: 10px; padding: 16px; margin: 16px 0; }
.grid-3 { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; }
.grid-2 { display: grid; grid-template-columns: repeat(2, 1fr); gap: 12px; }
.grid-5 { display: grid; grid-template-columns: repeat(5, 1fr); gap: 8px; }
.btn-card { text-decoration: none; color: var(--fg); text-align: center; }
.btn { background: var(--btn); color: var(--fg); border: 1px solid var(--border); padding: 10px 16px;
       border-radius: 8px; text-decoration: none; cursor: pointer; }
.btn:hover { background: var(--btn-hover); }
.img-wrap, .tile img { width: 100%; background: #0c0f14; border: 1px solid var(--border); border-radius: 8px; }
.tile { background: #121722; border: 1px solid var(--border); border-radius: 8px; padding: 8px; }
.field { margin: 12px 0; }
.field label { display: block; margin-bottom: 6px; color: var(--muted); }
input[type=range] { width: 100%; }
.bubble { margin-left: 8px; color: var(--muted); }
.buttons { margin-top: 12px; display: flex; gap: 8px; flex-wrap: wrap; }
.prompt { white-space: pre-wrap; }
.headrow { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; color: var(--muted); }
.flash { background: #3a1e1e; border: 1px solid #5a2a2a; padding: 8px; border-radius: 8px; margin-bottom: 8px; }
.seedlabel { margin-top: 6px; color: var(--muted); font-size: 12px; text-align: center; }

.table { width: 100%; border-collapse: collapse; margin-top: 8px; }
.table th, .table td { border: 1px solid var(--border); padding: 6px 8px; text-align: left; }
.table th { background: #0f1420; color: var(--muted); }
.smallcards { gap: 8px; }
.card-lite { background: #121722; border: 1px dashed var(--border); border-radius: 8px; padding: 10px; }
.card-lite .k { font-size: 20px; font-weight: 600; }
.card-lite .t { color: var(--muted); }
.list { list-style: none; padding-left: 0; margin: 0; }
.list li { padding: 4px 0; border-bottom: 1px dashed var(--border); }

.charts { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; margin: 12px 0; }
@media (max-width: 1100px) { .charts { grid-template-columns: 1fr; } }
""",

"client.js": r"""function showVal(slider) {
  const bubble = slider.nextElementSibling;
  if (bubble) bubble.textContent = slider.value;
}
function beforeSubmit(hiddenId) {
  const h = document.getElementById(hiddenId);
  if (h) {
    const started = window.__start_ts || Date.now();
    h.value = Date.now() - started;
  }
  return true;
}
window.addEventListener("load", () => {
  window.__start_ts = Date.now();
  document.querySelectorAll("input[type=range]").forEach(s => showVal(s));
});
function enforceUniqueRanks(sel) {
  const selects = Array.from(document.querySelectorAll(".rank-select"));
  const values = selects.map(s => s.value).filter(v => v);
  const duplicates = values.filter((v, i, a) => a.indexOf(v) !== i);
  if (duplicates.length > 0) {
    selects.forEach(s => { if (s !== sel && s.value === sel.value) s.value = ""; });
  }
}
"""
}

DEFAULT_CONFIG_YAML = r"""# Auto-created if missing; edit paths if yours differ
providers:
  chatgpt: "E:\\research\\chatgpt"
  google: "E:\\research\\google"
  stability: "E:\\research\\stability"
  bfl: "E:\\research\\flux"

seed_labels: [11, 23, 37, 53, 71]

module_items:
  A: 24
  B: 12
  C: 12

filter:
  status_ok_only: true
  # require_1k_square: true

storage:
  root: "E:\\research\\survey_results"
  fallback_root: "C:\\Users\\ulugbek-pc\\Documents\\research\\survey_results"
"""

def ensure_assets():
    """Write templates/static if missing; create default config.yaml if missing."""
    tpl_dir = APP_ROOT / "templates"
    st_dir = APP_ROOT / "static"
    tpl_dir.mkdir(parents=True, exist_ok=True)
    st_dir.mkdir(parents=True, exist_ok=True)
    for name, content in TEMPLATES.items():
        path = tpl_dir / name
        if not path.exists():
            path.write_text(content, encoding="utf-8")
    for name, content in STATIC_FILES.items():
        path = st_dir / name
        if not path.exists():
            path.write_text(content, encoding="utf-8")
    cfg_path = APP_ROOT / "config.yaml"
    if not cfg_path.exists():
        cfg_path.write_text(DEFAULT_CONFIG_YAML, encoding="utf-8")

_seen_lock = threading.Lock()
# Per-rater sets of keys for each module (lives only in RAM; cleared on restart)
SEEN_A: DefaultDict[str, Set[tuple]] = defaultdict(set)  # (provider, category_id, prompt_id, seed_label)
SEEN_B: DefaultDict[str, Set[tuple]] = defaultdict(set)  # (category_id, prompt_id, seed_label)
SEEN_C: DefaultDict[str, Set[tuple]] = defaultdict(set)  # (provider, category_id, prompt_id)

def mark_seen_a(rater_id: str, item: dict):
    key = (item["provider"], item["category_id"], item["prompt_id"], int(item["seed_label"]))
    with _seen_lock:
        SEEN_A[rater_id].add(key)

def mark_seen_b(rater_id: str, cat: str, prompt: str, seed: int):
    key = (cat, prompt, int(seed))
    with _seen_lock:
        SEEN_B[rater_id].add(key)

def mark_seen_c(rater_id: str, provider: str, cat: str, prompt: str):
    key = (provider, cat, prompt)
    with _seen_lock:
        SEEN_C[rater_id].add(key)


# ---------------------------- Config & storage ----------------------------

load_dotenv(APP_ROOT / ".env")
ensure_assets()

def read_yaml(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}

CFG = read_yaml(APP_ROOT / "config.yaml")

PROVIDER_DIRS: Dict[str, Path] = {k: Path(v) for k, v in CFG.get("providers", {}).items()}
SEED_LABELS: List[int] = list(CFG.get("seed_labels", [11, 23, 37, 53, 71]))
MODULE_ITEMS = CFG.get("module_items", {"A": 24, "B": 12, "C": 12})
FILTERS = CFG.get("filter", {})
REQUIRE_1K_SQUARE = FILTERS.get("require_1k_square", False)
STATUS_OK_ONLY = FILTERS.get("status_ok_only", True)

# ---- Prompt prepend (hidden by default in UI) ----
PREPEND_TEXT = (
    "2D animation / anime style, cel-shaded, clean bold outlines, SFW, family-friendly, "
    "vibrant but not neon, avoid photorealistic textures. Unless specified, do not add "
    "on-image text or watermarks. Emphasize clarity and readability. When a phrase appears "
    "in quotes below, render the phrase in the image without quotation marks. Render all "
    "on-image text in UPPERCASE ASCII (no curly punctuation). Do not reference or imitate "
    "the style of any living artist or copyrighted characters. "
)

def split_prompt(full: str) -> tuple[str, str]:
    """Return (prepend, core). If full doesn't start with prepend, core==full."""
    full = full or ""
    prep = PREPEND_TEXT
    if full.startswith(prep):
        return prep, full[len(prep):].lstrip()
    return prep, full

STORAGE_ROOT = Path(os.getenv("SURVEY_STORAGE", CFG.get("storage", {}).get("root", "E:/research/survey_results")))
FALLBACK_STORAGE_ROOT = Path(os.getenv("SURVEY_STORAGE_FALLBACK", CFG.get("storage", {}).get("fallback_root", "C:/Users/ulugbek-pc/Documents/research/survey_results")))
if not STORAGE_ROOT.exists():
    try:
        STORAGE_ROOT.mkdir(parents=True, exist_ok=True)
    except Exception:
        FALLBACK_STORAGE_ROOT.mkdir(parents=True, exist_ok=True)
        STORAGE_ROOT = FALLBACK_STORAGE_ROOT

DB_PATH = STORAGE_ROOT / "db" / "survey.sqlite"
EXPORT_DIR = STORAGE_ROOT / "exports"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)
EXPORT_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------- Flask app ----------------------------

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET", "".join(random.choices(string.ascii_letters + string.digits, k=32)))

# ---------------------------- Data structures ----------------------------

@dataclass
class ManifestRow:
    provider: str
    model: str
    run_id: str
    category_id: str
    prompt_id: str
    seed_label: int
    image_path: Path
    prompt_text: str
    has_text: bool
    expected_texts: str
    no_people: bool
    status: str
    w: int | None
    h: int | None
    completed_utc: str

ALL_A_IMAGES: List[ManifestRow] = []
B_SETS: Dict[Tuple[str, str, int], Dict[str, ManifestRow]] = {}
C_SETS: List[Tuple[str, str, str, List[ManifestRow]]] = []
ALLOWED_IMAGE_BASES: List[Path] = []

# ---------------------------- DB helpers ----------------------------

def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = db(); cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS raters(
      rater_id TEXT PRIMARY KEY,
      created_utc TEXT,
      user_agent TEXT
    );""")
    cur.execute("""
    CREATE TABLE IF NOT EXISTS responses_a(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      rater_id TEXT,
      provider TEXT, model TEXT,
      category_id TEXT, prompt_id TEXT, seed_label INTEGER,
      image_path TEXT, prompt_text TEXT,
      has_text INTEGER, no_people INTEGER,
      adherence INTEGER, aesthetic INTEGER, creativity INTEGER, style INTEGER,
      text_correctness TEXT, people_violation INTEGER,
      elapsed_ms INTEGER, submitted_utc TEXT
    );""")
    cur.execute("""
    CREATE TABLE IF NOT EXISTS responses_b(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      rater_id TEXT,
      category_id TEXT, prompt_id TEXT, seed_label INTEGER,
      rank_chatgpt INTEGER, rank_google INTEGER, rank_stability INTEGER, rank_bfl INTEGER,
      image_chatgpt TEXT, image_google TEXT, image_stability TEXT, image_bfl TEXT,
      elapsed_ms INTEGER, submitted_utc TEXT
    );""")
    cur.execute("""
    CREATE TABLE IF NOT EXISTS responses_c(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      rater_id TEXT,
      provider TEXT, category_id TEXT, prompt_id TEXT,
      diversity INTEGER,
      image_paths_json TEXT,
      elapsed_ms INTEGER, submitted_utc TEXT
    );""")
    conn.commit(); conn.close()

# ---------------------------- Manifest loading ----------------------------

def _normalize_image_path(path_str: str, provider_root: Path) -> Path:
    """
    Convert Windows-style absolute paths in manifests to the correct provider_root on Linux.
    Rules:
      - if we find '/<provider>/' (or '\<provider>\'), take the subpath after provider and join it to provider_root
      - else, if we find '/images/' (or '\images\'), join that trailing segment to provider_root
      - else, if path is relative, join to provider_root
      - else, as a last resort use basename under provider_root/images
    """
    s = str(path_str or "").strip().replace("\\", "/")
    prov = provider_root.name.lower()
    # /chatgpt/... or /flux/... etc.
    m1 = s.lower().find("/" + prov + "/")
    if m1 != -1:
        return provider_root / s[m1 + len(prov) + 2:]  # skip '/<prov>/'
    # /images/...
    m2 = s.lower().find("/images/")
    if m2 != -1:
        return provider_root / s[m2+1:]  # drop leading slash
    # relative path
    if not s.startswith("/"):
        return provider_root / s
    # fallback to basename in images/
    from pathlib import PurePath
    return provider_root / "images" / PurePath(s).name


def parse_bool(x: Any) -> bool:
    return str(x).strip().lower() in ("1","true","t","yes","y")

def try_int(x: str) -> int | None:
    try: return int(x)
    except Exception: return None

def read_latest_manifest(provider: str, base_dir: Path) -> List[ManifestRow]:
    man_dir = base_dir / "manifests"
    if not man_dir.exists(): return []
    runs = sorted((p for p in man_dir.glob("run-*") if p.is_dir()), key=lambda p: p.name, reverse=True)
    if not runs: return []
    latest = runs[0]
    csv_path = latest / "manifest.csv"
    if not csv_path.exists(): return []
    rows: List[ManifestRow] = []
    with open(csv_path, "r", encoding="utf-8", newline="") as f:
        rd = csv.DictReader(f)
        for r in rd:
            if STATUS_OK_ONLY and r.get("status","") != "ok": continue
            w = try_int(r.get("full_w","") or "")
            h = try_int(r.get("full_h","") or "")
            if REQUIRE_1K_SQUARE and not (w == 1024 and h == 1024): continue
            seed_label = try_int(r.get("seed","") or "") or 0
            img_path = _normalize_image_path(r.get("image_path",""), base_dir)
            rows.append(ManifestRow(
                provider=provider,
                model=r.get("model",""),
                run_id=r.get("run_id",""),
                category_id=str(r.get("category_id","")).strip(),
                prompt_id=str(r.get("prompt_id","")).strip(),
                seed_label=seed_label,
                image_path=img_path,
                prompt_text=r.get("prompt_text",""),
                has_text=parse_bool(r.get("has_text","false")),
                expected_texts=r.get("expected_texts",""),
                no_people=parse_bool(r.get("no_people","false")),
                status=r.get("status",""),
                w=w, h=h,
                completed_utc=r.get("request_completed_utc","")
            ))
    return [r for r in rows if r.image_path.exists()]

def build_tasks():
    global ALL_A_IMAGES, B_SETS, C_SETS, ALLOWED_IMAGE_BASES
    ALL_A_IMAGES = []
    per_provider: Dict[str, List[ManifestRow]] = {}
    ALLOWED_IMAGE_BASES = []
    for prov, root in PROVIDER_DIRS.items():
        rows = read_latest_manifest(prov, root)
        per_provider[prov] = rows
        ALL_A_IMAGES.extend(rows)
        ALLOWED_IMAGE_BASES.append(root.resolve())

    # Build B sets: keys present across all providers
    B_SETS = {}
    providers = list(PROVIDER_DIRS.keys())
    idx: Dict[str, Dict[Tuple[str,str,int], ManifestRow]] = {}
    for prov, rows in per_provider.items():
        d: Dict[Tuple[str,str,int], ManifestRow] = {}
        for r in rows:
            key = (r.category_id, r.prompt_id, r.seed_label)
            keep = d.get(key)
            if not keep or (r.completed_utc > keep.completed_utc):
                d[key] = r
        idx[prov] = d
    keys_all = None
    for prov in providers:
        keys = set(idx[prov].keys())
        keys_all = keys if keys_all is None else keys_all & keys
    if keys_all:
        for key in keys_all:
            B_SETS[key] = {prov: idx[prov][key] for prov in providers}

    # Build C sets: per provider, for each (cat,prompt) need all seed labels
    C_SETS = []
    for prov, rows in per_provider.items():
        group: Dict[Tuple[str,str], Dict[int, ManifestRow]] = {}
        for r in rows:
            gp = (r.category_id, r.prompt_id)
            group.setdefault(gp, {})[r.seed_label] = r
        for (cat,prompt), m in group.items():
            if all(s in m for s in SEED_LABELS):
                ordered = [m[s] for s in SEED_LABELS]
                C_SETS.append((prov, cat, prompt, ordered))

# ---------------------------- Image serving ----------------------------

def encode_path(p: Path) -> str:
    return base64.urlsafe_b64encode(str(p).encode("utf-8")).decode("ascii")

def decode_path(s: str) -> Path:
    return Path(base64.urlsafe_b64decode(s.encode("ascii")).decode("utf-8"))

def is_under_allowed_bases(p: Path) -> bool:
    try:
        rp = p.resolve(strict=False)
        for base in ALLOWED_IMAGE_BASES:
            try:
                rp.relative_to(base)
                return True
            except Exception:
                continue
        return False
    except Exception:
        return False

@app.get("/img")
def serve_img():
    b64 = request.args.get("p","").strip()
    if not b64: abort(400)
    p = decode_path(b64)
    if not is_under_allowed_bases(p): abort(403)
    if not p.exists(): abort(404)
    # Heuristic: default to PNG, but let Flask sniff if needed
    return send_file(p, mimetype="image/png")

# ---------------------------- Rater & plans ----------------------------

def get_or_create_rater() -> str:
    rid = session.get("rater_id")
    if not rid:
        rid = str(uuid.uuid4())
        session["rater_id"] = rid
        conn = db()
        conn.execute("INSERT OR IGNORE INTO raters(rater_id, created_utc, user_agent) VALUES(?,?,?)",
                     (rid, datetime.utcnow().isoformat()+"Z", request.headers.get("User-Agent","")))
        conn.commit(); conn.close()
    return rid

def slim_asdict_mr(m: ManifestRow) -> dict:
    d = asdict_mr(m)
    # drop heavy fields so the cookie stays < 4 KB
    d["prompt_text"] = ""         # template will rehydrate when rendering
    return d


def asdict_mr(m: ManifestRow) -> dict:
    return {
        "provider": m.provider, "model": m.model, "run_id": m.run_id,
        "category_id": m.category_id, "prompt_id": m.prompt_id, "seed_label": m.seed_label,
        "image_path": str(m.image_path), "prompt_text": m.prompt_text,
        "has_text": int(m.has_text), "expected_texts": m.expected_texts,
        "no_people": int(m.no_people), "status": m.status,
        "w": m.w or "", "h": m.h or "", "completed_utc": m.completed_utc
    }

def sample_plan_for_rater(rater_id: str, overrides: dict | None = None) -> dict:
    random.seed()
    plan: Dict[str, Any] = {"A": [], "B": [], "C": []}

    tgtA = int(MODULE_ITEMS.get("A", 24))
    tgtB = int(MODULE_ITEMS.get("B", 12))
    tgtC = int(MODULE_ITEMS.get("C", 12))

    # ---- filter A by unseen ----
    seen_a = SEEN_A.get(rater_id, set())
    pool_a = [m for m in ALL_A_IMAGES
              if (m.provider, m.category_id, m.prompt_id, m.seed_label) not in seen_a]
    kA = min(tgtA, len(pool_a))
    plan["A"] = random.sample(pool_a, kA) if kA > 0 and len(pool_a) >= kA else pool_a[:kA]

    # ---- filter B by unseen ----
    seen_b = SEEN_B.get(rater_id, set())
    pool_b_keys = [key for key in B_SETS.keys() if key not in seen_b]
    random.shuffle(pool_b_keys)
    kB = min(tgtB, len(pool_b_keys))
    plan["B"] = pool_b_keys[:kB]

    # ---- filter C by unseen ----
    seen_c = SEEN_C.get(rater_id, set())
    pool_c = [(prov, cat, prompt, rows)
              for (prov, cat, prompt, rows) in C_SETS
              if (prov, cat, prompt) not in seen_c]
    kC = min(tgtC, len(pool_c))
    plan["C"] = random.sample(pool_c, kC) if kC > 0 and len(pool_c) >= kC else pool_c[:kC]

    # store slim plan (unchanged)
    session["plan_idx"] = {"A": 0, "B": 0, "C": 0}
    session["plan_sizes"] = {"A": len(plan["A"]), "B": len(plan["B"]), "C": len(plan["C"])}
    session["plan"] = {
        "A": [slim_asdict_mr(m) for m in plan["A"]],
        "B": plan["B"],
        "C": [(prov, cat, prompt, [slim_asdict_mr(x) for x in rows]) for (prov,cat,prompt,rows) in plan["C"]]
    }
    return session["plan"]

def hydrate_prompt_text(item: dict) -> dict:
    # find original in ALL_A_IMAGES by keys; fill prompt_text if blank
    if item.get("prompt_text"):
        return item
    for r in ALL_A_IMAGES:
        if (r.provider == item["provider"] and
            r.category_id == item["category_id"] and
            r.prompt_id == item["prompt_id"] and
            r.seed_label == item["seed_label"]):
            item["prompt_text"] = r.prompt_text
            break
    return item


# ---------------------------- Admin auth & stats ----------------------------

def is_admin() -> bool:
    return bool(session.get("is_admin") is True)

def require_admin(view_func):
    @wraps(view_func)
    def wrapper(*args, **kwargs):
        if not is_admin():
            return redirect(url_for("admin_login", next=request.path))
        return view_func(*args, **kwargs)
    return wrapper

def _fetchone_val(conn, sql, params=()):
    cur = conn.execute(sql, params); row = cur.fetchone()
    return (row[0] if row and len(row) else 0)

def _fetchall_dicts(conn, sql, params=()):
    cur = conn.execute(sql, params)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]

def get_stats() -> dict:
    pools = {"pool_A": len(ALL_A_IMAGES), "pool_B": len(B_SETS), "pool_C": len(C_SETS)}
    conn = db()
    total_raters = _fetchone_val(conn, "SELECT COUNT(*) FROM raters")
    A_total = _fetchone_val(conn, "SELECT COUNT(*) FROM responses_a")
    B_total = _fetchone_val(conn, "SELECT COUNT(*) FROM responses_b")
    C_total = _fetchone_val(conn, "SELECT COUNT(*) FROM responses_c")

    A_mos = _fetchall_dicts(conn, """
      SELECT provider,
             COUNT(*) AS n,
             ROUND(AVG(adherence),2) AS adherence,
             ROUND(AVG(aesthetic),2) AS aesthetic,
             ROUND(AVG(creativity),2) AS creativity,
             ROUND(AVG(style),2) AS style
      FROM responses_a
      GROUP BY provider
      ORDER BY provider
    """)
    A_text = _fetchall_dicts(conn, """
      SELECT provider,
             SUM(CASE WHEN text_correctness='correct' THEN 1 ELSE 0 END) AS correct,
             SUM(CASE WHEN text_correctness='partial' THEN 1 ELSE 0 END) AS partial,
             SUM(CASE WHEN text_correctness='incorrect' THEN 1 ELSE 0 END) AS incorrect
      FROM responses_a
      WHERE text_correctness IS NOT NULL AND text_correctness <> ''
      GROUP BY provider
      ORDER BY provider
    """)
    A_people = _fetchall_dicts(conn, """
      SELECT provider,
             SUM(CASE WHEN no_people=1 THEN 1 ELSE 0 END) AS with_rule,
             SUM(CASE WHEN no_people=1 AND people_violation=1 THEN 1 ELSE 0 END) AS violations
      FROM responses_a
      GROUP BY provider
      ORDER BY provider
    """)
    B_rank = _fetchall_dicts(conn, """
      SELECT 'chatgpt' AS provider, COUNT(*) AS n,
             ROUND(AVG(rank_chatgpt),2) AS avg_rank,
             SUM(CASE WHEN rank_chatgpt=1 THEN 1 ELSE 0 END) AS wins
      FROM responses_b
      UNION ALL
      SELECT 'google', COUNT(*), ROUND(AVG(rank_google),2),
             SUM(CASE WHEN rank_google=1 THEN 1 ELSE 0 END)
      FROM responses_b
      UNION ALL
      SELECT 'stability', COUNT(*), ROUND(AVG(rank_stability),2),
             SUM(CASE WHEN rank_stability=1 THEN 1 ELSE 0 END)
      FROM responses_b
      UNION ALL
      SELECT 'bfl', COUNT(*), ROUND(AVG(rank_bfl),2),
             SUM(CASE WHEN rank_bfl=1 THEN 1 ELSE 0 END)
      FROM responses_b
    """)
    C_div = _fetchall_dicts(conn, """
      SELECT provider,
             COUNT(*) AS n,
             ROUND(AVG(diversity),2) AS avg_diversity
      FROM responses_c
      GROUP BY provider
      ORDER BY provider
    """)
    recent_a = _fetchall_dicts(conn, """
      SELECT submitted_utc, rater_id, provider, category_id, prompt_id, seed_label
      FROM responses_a ORDER BY id DESC LIMIT 10
    """)
    recent_b = _fetchall_dicts(conn, """
      SELECT submitted_utc, rater_id, category_id, prompt_id, seed_label
      FROM responses_b ORDER BY id DESC LIMIT 10
    """)
    recent_c = _fetchall_dicts(conn, """
      SELECT submitted_utc, rater_id, provider, category_id, prompt_id, diversity
      FROM responses_c ORDER BY id DESC LIMIT 10
    """)
    conn.close()
    return {
        "pools": pools,
        "totals": {"raters": total_raters, "A": A_total, "B": B_total, "C": C_total},
        "A": {"mos": A_mos, "text": A_text, "people": A_people},
        "B": {"ranking": B_rank},
        "C": {"diversity": C_div},
        "recent": {"A": recent_a, "B": recent_b, "C": recent_c}
    }

# ---------------------------- Routes ----------------------------

_init_lock = threading.Lock()
_initialized = False

def _init_once():
    global _initialized
    with _init_lock:
        if _initialized:
            return
        # whatever you previously did in before_first_request:
        init_db()
        build_tasks()
        _initialized = True

@app.before_request
def _ensure_init():
    _init_once()

@app.get("/")
def home():
    rid = get_or_create_rater()

    # counts
    a_images = len(ALL_A_IMAGES)
    a_sets = len({(m.category_id, m.prompt_id, m.seed_label) for m in ALL_A_IMAGES})
    b_sets = len(B_SETS)
    c_grids = len(C_SETS)

    sizes = {
        "A_sets": a_sets,
        "A_images": a_images,
        "B_sets": b_sets,
        "C_grids": c_grids,
    }

    plan = session.get("plan") or sample_plan_for_rater(rid)
    plan_sizes = session.get("plan_sizes", {"A":0,"B":0,"C":0})
    plan_idx   = session.get("plan_idx",   {"A":0,"B":0,"C":0})
    remaining  = {m: max(0, plan_sizes.get(m,0) - plan_idx.get(m,0)) for m in "ABC"}

    return render_template("home.html", sizes=sizes, remaining=remaining, seed_labels=SEED_LABELS)


@app.get("/onboarding")
def onboarding():
    from flask import redirect, url_for
    return redirect(url_for("home"), code=301)

@app.get("/start/<module_id>")
def start_module(module_id: str):
    rid = get_or_create_rater()
    session.pop("full_mode", None)  # solo module, don't chain

    if "plan" not in session:
        sample_plan_for_rater(rid)

    idx   = session.get("plan_idx",   {"A":0,"B":0,"C":0})
    sizes = session.get("plan_sizes", {"A":0,"B":0,"C":0})

    # Only restart the module if it's already finished; otherwise resume
    if idx.get(module_id, 0) >= sizes.get(module_id, 0):
        idx[module_id] = 0

    session["plan_idx"] = idx
    return redirect(url_for(f"mod_{module_id.lower()}"))


# Full session flow
@app.get("/start/full")
def start_full_session():
    rid = get_or_create_rater()
    # Always use default module sizes from config.yaml (no quick/short overrides)
    sample_plan_for_rater(rid, overrides=None)
    session["full_mode"] = True
    return redirect(url_for("full_next"))


@app.get("/full/next")
def full_next():
    rid = get_or_create_rater()
    plan_sizes = session.get("plan_sizes")
    plan_idx   = session.get("plan_idx")
    # If plan missing or zero-sized, build a fresh one
    if not plan_sizes or sum(plan_sizes.values()) == 0:
        sample_plan_for_rater(rid)
        plan_sizes = session.get("plan_sizes", {"A":0,"B":0,"C":0})
        session["plan_idx"] = {"A":0,"B":0,"C":0}

    idx = session.get("plan_idx", {"A":0,"B":0,"C":0})
    for m, route in (("A","mod_a"),("B","mod_b"),("C","mod_c")):
        if idx.get(m,0) < plan_sizes.get(m,0):
            return redirect(url_for(route))
    session.pop("full_mode", None)
    return redirect(url_for("thanks"))

# --- Module A (single image) ---
@app.get("/a")
def mod_a():
    rid = get_or_create_rater()
    plan = session.get("plan") or sample_plan_for_rater(rid)
    idx = session.get("plan_idx", {}).get("A", 0)
    total = session.get("plan_sizes", {}).get("A", 0)
    if idx >= total:
        if session.get("full_mode"): return redirect(url_for("full_next"))
        return redirect(url_for("thanks"))

    item = plan["A"][idx]
    if hasattr(item, "__dict__") and not isinstance(item, dict):
        item = asdict_mr(item)
    item = hydrate_prompt_text(item)

    prepend, core = split_prompt(item["prompt_text"])
    img_b64 = encode_path(Path(item["image_path"]))
    return render_template(
        "module_a.html",
        item=item,
        img_b64=img_b64,
        idx=idx + 1,
        total=total,
        prompt_core=core,
        prompt_prepend=prepend
    )


@app.post("/submit/a")
def submit_a():
    rid = get_or_create_rater()
    form = request.form
    mark_seen_a(rid, {
        "provider": form["provider"],
        "category_id": form["category_id"],
        "prompt_id": form["prompt_id"],
        "seed_label": int(form["seed_label"])
    })
    conn = db()
    conn.execute("""
        INSERT INTO responses_a(
          rater_id, provider, model, category_id, prompt_id, seed_label,
          image_path, prompt_text, has_text, no_people,
          adherence, aesthetic, creativity, style,
          text_correctness, people_violation, elapsed_ms, submitted_utc
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        rid, form["provider"], form["model"], form["category_id"], form["prompt_id"], int(form["seed_label"]),
        form["image_path"], form["prompt_text"], int(form.get("has_text",0)), int(form.get("no_people",0)),
        int(form["adherence"]), int(form["aesthetic"]), int(form["creativity"]), int(form["style"]),
        form.get("text_correctness",""), int(form.get("people_violation","0")),
        int(form.get("elapsed_ms","0")), datetime.utcnow().isoformat()+"Z"
    ))
    conn.commit(); conn.close()
    idx_all = session.get("plan_idx", {"A":0,"B":0,"C":0}); idx_all["A"] = idx_all.get("A",0) + 1
    session["plan_idx"] = idx_all
    return redirect(url_for("full_next") if session.get("full_mode") else url_for("mod_a"))

# --- Module B (ranking) ---
@app.get("/b")
def mod_b():
    rid = get_or_create_rater()
    plan = session.get("plan") or sample_plan_for_rater(rid)
    idx = session.get("plan_idx", {}).get("B", 0)
    total = session.get("plan_sizes", {}).get("B", 0)
    if total <= 0:
        return render_template("no_data.html", title="Part B is unavailable",
                               message="No matching 4-model sets were found across providers. "
                                       "Check manifests and try Reload Pools in admin.")
    if idx >= total:
        if session.get("full_mode"): return redirect(url_for("full_next"))
        return redirect(url_for("thanks"))

    cat, pid, seed = plan["B"][idx]  # pid = prompt_id
    rows_by_provider = B_SETS.get((cat, pid, seed), {})

    # Build display cards
    display = []
    any_row = None
    for prov in ("chatgpt","google","stability","bfl"):
        r = rows_by_provider.get(prov)
        if r:
            any_row = any_row or r
            display.append({
                "provider": prov,
                "model": r.model,
                "image_path": str(r.image_path),
                "img_b64": encode_path(r.image_path),
            })

    # Split the REAL text prompt; fall back to prompt_id if missing
    full_text = any_row.prompt_text if any_row else pid
    prepend, core = split_prompt(full_text)

    return render_template(
        "module_b.html",
        cat=cat, prompt_id=pid, seed=seed,               # keep IDs for hidden inputs
        display=display, idx=idx+1, total=total,
        prompt_core=core, prompt_prepend=prepend         # <-- use these in the template
    )


@app.post("/submit/b")
def submit_b():
    rid = get_or_create_rater()
    form = request.form
    ranks = {
        "chatgpt": int(form["rank_chatgpt"]),
        "google": int(form["rank_google"]),
        "stability": int(form["rank_stability"]),
        "bfl": int(form["rank_bfl"])
    }
    # ensure these hidden inputs exist in module_b.html: category_id, prompt_id, seed_label
    mark_seen_b(rid, form["category_id"], form["prompt_id"], int(form["seed_label"]))
    if len(set(ranks.values())) != 4:
        flash("Please assign unique ranks 1–4."); return redirect(url_for("mod_b"))
    conn = db()
    conn.execute("""
        INSERT INTO responses_b(
          rater_id, category_id, prompt_id, seed_label,
          rank_chatgpt, rank_google, rank_stability, rank_bfl,
          image_chatgpt, image_google, image_stability, image_bfl,
          elapsed_ms, submitted_utc
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        rid, form["category_id"], form["prompt_id"], int(form["seed_label"]),
        ranks["chatgpt"], ranks["google"], ranks["stability"], ranks["bfl"],
        form["image_chatgpt"], form["image_google"], form["image_stability"], form["image_bfl"],
        int(form.get("elapsed_ms","0")), datetime.utcnow().isoformat()+"Z"
    ))
    conn.commit(); conn.close()
    idx_all = session.get("plan_idx", {"A":0,"B":0,"C":0}); idx_all["B"] = idx_all.get("B",0) + 1
    session["plan_idx"] = idx_all
    return redirect(url_for("full_next") if session.get("full_mode") else url_for("mod_b"))

# --- Module C (diversity) ---
@app.get("/c")
def mod_c():
    rid = get_or_create_rater()
    plan = session.get("plan") or sample_plan_for_rater(rid)

    idx = session.get("plan_idx", {}).get("C", 0)
    total = session.get("plan_sizes", {}).get("C", 0)
    if idx >= total:
        if session.get("full_mode"):
            return redirect(url_for("full_next"))
        return redirect(url_for("thanks"))

    # plan["C"][i] = (provider, category_id, prompt_id, [5 rows])
    prov, cat, pid, row_objs = plan["C"][idx]

    # Normalize rows to dicts and hydrate prompt text
    norm_rows = []
    for r in row_objs:
        if hasattr(r, "__dict__") and not isinstance(r, dict):
            r = asdict_mr(r)
        r = hydrate_prompt_text(r)
        norm_rows.append(r)

    # For the visible grid (b64 URLs) and hidden payload (raw paths)
    images = [str(r["image_path"]) for r in norm_rows]                       # hidden JSON
    img_b64_list = [encode_path(Path(r["image_path"])) for r in norm_rows]   # <img src=...>

    # Use real text from any of the 5 rows; fall back to the prompt_id if missing
    full_text = (norm_rows[0].get("prompt_text") if norm_rows else "") or pid
    prepend, core = split_prompt(full_text)

    return render_template(
        "module_c.html",
        provider=prov,
        cat=cat,
        prompt_id=pid,              # keep ID for hidden field
        prompt_core=core,
        prompt_prepend=prepend,
        img_b64_list=img_b64_list,  # used by template loop
        images=images,              # used by hidden input: image_paths_json
        idx=idx + 1,
        total=total,
    )



@app.post("/submit/c")
def submit_c():
    rid = get_or_create_rater()
    form = request.form
    # mark the grid (provider,cat,prompt) as seen
    mark_seen_c(rid, form["provider"], form["category_id"], form["prompt_id"])
    conn = db()
    conn.execute("""
        INSERT INTO responses_c(
          rater_id, provider, category_id, prompt_id, diversity,
          image_paths_json, elapsed_ms, submitted_utc
        ) VALUES (?,?,?,?,?,?,?,?)
    """, (
        rid, form["provider"], form["category_id"], form["prompt_id"], int(form["diversity"]),
        form["image_paths_json"], int(form.get("elapsed_ms","0")), datetime.utcnow().isoformat()+"Z"
    ))
    conn.commit(); conn.close()
    idx_all = session.get("plan_idx", {"A":0,"B":0,"C":0}); idx_all["C"] = idx_all.get("C",0) + 1
    session["plan_idx"] = idx_all
    return redirect(url_for("full_next") if session.get("full_mode") else url_for("mod_c"))

@app.get("/thanks")
def thanks():
    return render_template("thanks.html")

# --- Admin: login, dashboard, stats, reload, export ---
@app.get("/admin/login")
def admin_login():
    return render_template("admin_login.html", title="Admin Login", heading="Admin Login")

@app.post("/admin/login")
def admin_login_post():
    token = request.form.get("token","").strip()
    correct = os.getenv("ADMIN_TOKEN","")
    if token and correct and token == correct:
        session["is_admin"] = True
        next_url = request.args.get("next") or url_for("admin_home")
        return redirect(next_url)
    flash("Invalid admin token."); return redirect(url_for("admin_login"))

@app.get("/admin/logout")
def admin_logout():
    session.pop("is_admin", None); return redirect(url_for("home"))

@app.get("/admin")
@require_admin
def admin_home():
    return render_template("admin.html", title="Admin Dashboard", heading="Admin Dashboard")

@app.get("/admin/stats")
@require_admin
def admin_stats():
    try:
        stats = get_stats()
        return jsonify({"ok": True, "data": stats})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@app.post("/admin/reload")
@require_admin
def admin_reload():
    try:
        build_tasks()
        stats = get_stats()
        return jsonify({"ok": True, "message": "Task pools rebuilt from latest manifests.", "data": stats})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@app.get("/admin/export")
@require_admin
def admin_export():
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    out_a = EXPORT_DIR / f"responses_a_{ts}.csv"
    out_b = EXPORT_DIR / f"responses_b_{ts}.csv"
    out_c = EXPORT_DIR / f"responses_c_{ts}.csv"
    conn = db()
    for table, path in [("responses_a", out_a), ("responses_b", out_b), ("responses_c", out_c)]:
        rows = conn.execute(f"SELECT * FROM {table}").fetchall()
        if rows:
            with open(path, "w", encoding="utf-8", newline="") as f:
                w = csv.writer(f); w.writerow(rows[0].keys())
                for r in rows: w.writerow([r[k] for k in r.keys()])
    conn.close()
    return jsonify({"exported": True, "files": [str(out_a), str(out_b), str(out_c)]})

# --- Clear in-memory "seen" caches ---

@app.post("/admin/clear_seen_me")
@require_admin
def admin_clear_seen_me():
    rid = session.get("rater_id", "")
    with _seen_lock:
        SEEN_A.pop(rid, None)
        SEEN_B.pop(rid, None)
        SEEN_C.pop(rid, None)
    # optional: also reset this rater's current plan/progress
    session.pop("plan", None)
    session.pop("plan_idx", None)
    session.pop("plan_sizes", None)
    return jsonify({"ok": True, "cleared_for": rid})

@app.post("/admin/clear_seen_all")
@require_admin
def admin_clear_seen_all():
    with _seen_lock:
        SEEN_A.clear()
        SEEN_B.clear()
        SEEN_C.clear()
    # optional: does not touch user sessions
    return jsonify({"ok": True})


# ---------------------------- Main ----------------------------
if __name__ == "__main__":
    with app.app_context():
        _init_once()
    import os
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")), debug=False)
