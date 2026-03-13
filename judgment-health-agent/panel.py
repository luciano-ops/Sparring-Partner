"""Judgment Health Agent Control Panel — web UI for controlling agent runs.

Usage:
    python3.11 panel.py              # Opens browser to http://localhost:5050
    python3.11 panel.py --port 8080  # Custom port

Provides sliders for Clinical Domain, Patient Sentiment, and Interaction Type
distributions. Runs are streamed with live progress via SSE.
"""

from __future__ import annotations

import argparse
import json
import queue
import sys
import threading
import time
import webbrowser
from pathlib import Path

from flask import Flask, Response, jsonify, request

# Add project to path
sys.path.insert(0, str(Path(__file__).parent))

from models import PatientProfile
from profiles.generator import load_profiles
from profile_classifier import classify_all
from profile_selector import select_profiles, get_achieved_distribution
from instrumentation import tracer

PROFILES_PATH = Path(__file__).parent / "profiles" / "patient_profiles.json"

app = Flask(__name__)

# ── Global state (single-user tool, not production) ──────────────────────────

_state = {
    "running": False,
    "events": queue.Queue(),
    "thread": None,
    "profiles": None,      # loaded once
    "classified": None,    # classified once
}


def _load():
    """Load and classify profiles (cached)."""
    if _state["profiles"] is None:
        _state["profiles"] = load_profiles(PROFILES_PATH)
        _state["classified"] = classify_all(_state["profiles"])
    return _state["profiles"], _state["classified"]


# ── API endpoints ────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return HTML_PAGE


@app.route("/api/stats")
def stats():
    """Return classification counts for all profiles."""
    _, classified = _load()
    return jsonify(classified["counts"])


@app.route("/api/run", methods=["POST"])
def start_run():
    if _state["running"]:
        return jsonify({"error": "A run is already in progress"}), 409

    data = request.json
    distributions = data["distributions"]
    total_count = data["total_count"]
    concurrency = data.get("concurrency", 3)

    _, classified = _load()

    # Select profiles
    selected = select_profiles(classified, distributions, total_count)
    achieved = get_achieved_distribution(selected, classified)

    # Clear event queue
    while not _state["events"].empty():
        try:
            _state["events"].get_nowait()
        except queue.Empty:
            break

    def run_in_background():
        from run import run_batch
        _state["running"] = True

        def on_progress(event):
            _state["events"].put(event)

        try:
            run_batch(
                selected,
                concurrency=concurrency,
                verbose=False,
                progress_callback=on_progress,
            )
        except Exception as e:
            _state["events"].put({"type": "error", "error": str(e)})
        finally:
            # Flush traces (don't shutdown — keeps tracer alive for next batch)
            try:
                tracer.flush(timeout_millis=15000)
            except Exception:
                pass
            _state["running"] = False
            _state["events"].put({"type": "done"})

    _state["thread"] = threading.Thread(target=run_in_background, daemon=True)
    _state["thread"].start()

    return jsonify({
        "status": "started",
        "count": len(selected),
        "achieved": achieved,
    })


@app.route("/api/progress")
def progress_stream():
    """SSE stream of progress events."""
    def generate():
        while True:
            try:
                event = _state["events"].get(timeout=30)
                yield f"data: {json.dumps(event)}\n\n"
                if event.get("type") == "done":
                    break
            except queue.Empty:
                yield f"data: {json.dumps({'type': 'heartbeat'})}\n\n"

    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.route("/api/stop", methods=["POST"])
def stop_run():
    """Signal to stop (best-effort — current conversation will finish)."""
    _state["running"] = False
    return jsonify({"status": "stop_requested"})


# ── HTML ─────────────────────────────────────────────────────────────────────

HTML_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Judgment Health Agent</title>
<style>
  :root {
    --bg: #0f1117;
    --surface: #1a1d27;
    --border: #2a2d3a;
    --text: #e4e4e7;
    --muted: #71717a;
    --accent: #f97316;
    --accent-dim: #f9731633;
    --green: #22c55e;
    --red: #ef4444;
  }
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif;
    background: var(--bg); color: var(--text);
    padding: 24px; max-width: 960px; margin: 0 auto;
  }
  h1 { font-size: 22px; font-weight: 600; margin-bottom: 4px; }
  .subtitle { color: var(--muted); font-size: 13px; margin-bottom: 24px; }
  .controls-row {
    display: flex; gap: 16px; margin-bottom: 24px; align-items: center;
  }
  .controls-row label { font-size: 13px; color: var(--muted); }
  .controls-row input[type=number] {
    width: 80px; padding: 8px 12px; border-radius: 8px;
    border: 1px solid var(--border); background: var(--surface);
    color: var(--text); font-size: 15px; font-weight: 600;
  }
  .section {
    background: var(--surface); border: 1px solid var(--border);
    border-radius: 12px; padding: 20px; margin-bottom: 16px;
  }
  .section-header {
    display: flex; justify-content: space-between; align-items: center;
    margin-bottom: 16px;
  }
  .section-title { font-size: 14px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; color: var(--muted); }
  .reset-btn {
    font-size: 11px; color: var(--accent); cursor: pointer;
    background: none; border: 1px solid var(--accent); border-radius: 6px;
    padding: 4px 10px; transition: all 0.15s;
  }
  .reset-btn:hover { background: var(--accent-dim); }
  .slider-row {
    display: grid; grid-template-columns: 160px 1fr 50px 60px;
    align-items: center; gap: 12px; margin-bottom: 10px;
  }
  .slider-label { font-size: 13px; }
  .slider-avail { font-size: 11px; color: var(--muted); text-align: right; }
  .slider-pct { font-size: 14px; font-weight: 600; text-align: right; font-variant-numeric: tabular-nums; }
  input[type=range] {
    -webkit-appearance: none; width: 100%; height: 6px;
    border-radius: 3px; background: var(--border); outline: none;
  }
  input[type=range]::-webkit-slider-thumb {
    -webkit-appearance: none; width: 16px; height: 16px;
    border-radius: 50%; background: var(--accent); cursor: pointer;
    border: 2px solid var(--bg);
  }
  .run-btn {
    width: 100%; padding: 14px; border: none; border-radius: 10px;
    background: var(--accent); color: #000; font-size: 16px;
    font-weight: 700; cursor: pointer; margin-bottom: 16px;
    transition: opacity 0.15s; letter-spacing: 0.3px;
  }
  .run-btn:hover { opacity: 0.9; }
  .run-btn:disabled { opacity: 0.4; cursor: not-allowed; }
  .progress-section { display: none; }
  .progress-section.active { display: block; }
  .progress-bar-outer {
    width: 100%; height: 32px; background: var(--border);
    border-radius: 8px; overflow: hidden; margin-bottom: 12px;
    position: relative;
  }
  .progress-bar-inner {
    height: 100%; background: var(--accent); transition: width 0.3s;
    border-radius: 8px;
  }
  .progress-bar-text {
    position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%);
    font-size: 13px; font-weight: 600; color: var(--text);
    text-shadow: 0 1px 2px rgba(0,0,0,0.5);
  }
  .progress-stats {
    display: flex; gap: 24px; font-size: 13px; color: var(--muted); margin-bottom: 12px;
  }
  .progress-stats span { font-weight: 600; color: var(--text); }
  .log-box {
    background: var(--bg); border: 1px solid var(--border); border-radius: 8px;
    padding: 12px; max-height: 200px; overflow-y: auto; font-family: 'SF Mono', monospace;
    font-size: 12px; line-height: 1.6;
  }
  .log-entry { color: var(--muted); }
  .log-entry .ok { color: var(--green); }
  .log-entry .fail { color: var(--red); }
  .achieved-grid {
    display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 12px;
    margin-bottom: 16px;
  }
  .achieved-col h4 { font-size: 11px; text-transform: uppercase; color: var(--muted); margin-bottom: 6px; letter-spacing: 0.5px; }
  .achieved-item { font-size: 12px; margin-bottom: 2px; }
  .achieved-item span { font-weight: 600; }
</style>
</head>
<body>

<h1>Judgment Health Agent</h1>
<p class="subtitle">Control panel for agent trace generation</p>

<div class="controls-row">
  <div>
    <label>Total Runs</label><br>
    <input type="number" id="totalRuns" value="50" min="1" max="500">
  </div>
  <div>
    <label>Concurrency</label><br>
    <input type="number" id="concurrency" value="3" min="1" max="10">
  </div>
</div>

<div id="sliderSections"></div>

<button class="run-btn" id="runBtn" onclick="startRun()">
  Run 50 Conversations
</button>

<div class="progress-section" id="progressSection">
  <div class="section">
    <div class="section-header">
      <span class="section-title">Progress</span>
      <span id="progressEta" style="font-size:12px;color:var(--muted)"></span>
    </div>
    <div class="progress-bar-outer">
      <div class="progress-bar-inner" id="progressBar" style="width:0%"></div>
      <div class="progress-bar-text" id="progressText">0 / 0</div>
    </div>
    <div class="progress-stats">
      <div>Tools/conv: <span id="statTools">0</span></div>
      <div>Turns/conv: <span id="statTurns">0</span></div>
      <div>Failed: <span id="statFailed">0</span></div>
    </div>
    <div id="achievedDist"></div>
    <div class="log-box" id="logBox"></div>
  </div>
</div>

<script>
const GROUPS = {
  clinical_domain: {
    title: "Clinical Domain",
    labels: ["Cardiac","Endocrine","General / Preventive","GI","Mental Health","Musculoskeletal","Neurological","Respiratory"],
  },
  patient_sentiment: {
    title: "Patient Sentiment",
    labels: ["Anxious","Frustrated","Reassured","Still Anxious"],
  },
  interaction_type: {
    title: "Interaction Type",
    labels: ["Emergency Escalation","History Collection","Lab Interpretation","Medication Review","Patient Education","Preventive Screening","Symptom Assessment"],
  },
};

let sliderState = {};
let profileStats = {};

// Initialize sliders
function initSliders() {
  const container = document.getElementById('sliderSections');
  container.innerHTML = '';

  for (const [groupKey, group] of Object.entries(GROUPS)) {
    const evenPct = Math.floor(100 / group.labels.length);
    const remainder = 100 - evenPct * group.labels.length;
    sliderState[groupKey] = {};

    group.labels.forEach((label, i) => {
      sliderState[groupKey][label] = evenPct + (i < remainder ? 1 : 0);
    });

    const section = document.createElement('div');
    section.className = 'section';
    section.innerHTML = `
      <div class="section-header">
        <span class="section-title">${group.title}</span>
        <button class="reset-btn" onclick="resetGroup('${groupKey}')">Reset Even</button>
      </div>
      <div id="sliders-${groupKey}"></div>
    `;
    container.appendChild(section);
    renderSliders(groupKey);
  }
}

function renderSliders(groupKey) {
  const container = document.getElementById(`sliders-${groupKey}`);
  const group = GROUPS[groupKey];
  container.innerHTML = '';

  group.labels.forEach(label => {
    const val = sliderState[groupKey][label];
    const avail = (profileStats[groupKey] || {})[label] || 0;
    const row = document.createElement('div');
    row.className = 'slider-row';
    row.innerHTML = `
      <div class="slider-label">${label}</div>
      <input type="range" min="0" max="100" value="${val}"
        oninput="onSlider('${groupKey}','${label}',this.value)">
      <div class="slider-pct" id="pct-${groupKey}-${label}">${val}%</div>
      <div class="slider-avail">${avail}</div>
    `;
    container.appendChild(row);
  });
}

function onSlider(groupKey, changedLabel, newVal) {
  newVal = parseInt(newVal);
  const state = sliderState[groupKey];
  const oldVal = state[changedLabel];
  const delta = newVal - oldVal;

  state[changedLabel] = newVal;

  // Redistribute delta among others proportionally
  const others = Object.keys(state).filter(k => k !== changedLabel);
  const othersTotal = others.reduce((s, k) => s + state[k], 0);

  if (othersTotal > 0) {
    others.forEach(k => {
      state[k] = Math.max(0, Math.round(state[k] - (delta * state[k] / othersTotal)));
    });
  }

  // Fix rounding to exactly 100
  const total = Object.values(state).reduce((s, v) => s + v, 0);
  if (total !== 100) {
    const sortedOthers = others.sort((a, b) => state[b] - state[a]);
    if (sortedOthers.length > 0) {
      state[sortedOthers[0]] += (100 - total);
      state[sortedOthers[0]] = Math.max(0, state[sortedOthers[0]]);
    }
  }

  // Update all sliders and labels in this group
  GROUPS[groupKey].labels.forEach(label => {
    const pctEl = document.getElementById(`pct-${groupKey}-${label}`);
    if (pctEl) pctEl.textContent = state[label] + '%';
    const slider = document.querySelector(`#sliders-${groupKey} input[oninput*="'${label}'"]`);
    if (slider) slider.value = state[label];
  });

  updateRunBtn();
}

function resetGroup(groupKey) {
  const labels = GROUPS[groupKey].labels;
  const even = Math.floor(100 / labels.length);
  const rem = 100 - even * labels.length;
  labels.forEach((label, i) => {
    sliderState[groupKey][label] = even + (i < rem ? 1 : 0);
  });
  renderSliders(groupKey);
  updateRunBtn();
}

function updateRunBtn() {
  const n = parseInt(document.getElementById('totalRuns').value) || 50;
  document.getElementById('runBtn').textContent = `Run ${n} Conversations`;
}

document.getElementById('totalRuns').addEventListener('input', updateRunBtn);

// ── Run logic ─────────────────────────────────────────────────

async function startRun() {
  const btn = document.getElementById('runBtn');
  btn.disabled = true;
  btn.textContent = 'Starting...';

  const totalCount = parseInt(document.getElementById('totalRuns').value) || 50;
  const concurrency = parseInt(document.getElementById('concurrency').value) || 3;

  // Filter out 0% categories
  const distributions = {};
  for (const [groupKey, state] of Object.entries(sliderState)) {
    distributions[groupKey] = {};
    for (const [label, pct] of Object.entries(state)) {
      if (pct > 0) distributions[groupKey][label] = pct;
    }
  }

  try {
    const res = await fetch('/api/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ distributions, total_count: totalCount, concurrency }),
    });
    const data = await res.json();

    if (data.error) {
      alert(data.error);
      btn.disabled = false;
      btn.textContent = `Run ${totalCount} Conversations`;
      return;
    }

    // Show achieved distribution
    showAchieved(data.achieved, data.count);

    // Start listening for progress
    const progressSection = document.getElementById('progressSection');
    progressSection.classList.add('active');
    document.getElementById('logBox').innerHTML = '';

    listenProgress(data.count);

  } catch (e) {
    alert('Failed to start: ' + e.message);
    btn.disabled = false;
    updateRunBtn();
  }
}

function showAchieved(achieved, count) {
  const el = document.getElementById('achievedDist');
  let html = '<div class="achieved-grid">';
  for (const [dim, labels] of Object.entries(achieved)) {
    const title = GROUPS[dim]?.title || dim;
    html += `<div class="achieved-col"><h4>${title} (actual)</h4>`;
    for (const [label, cnt] of Object.entries(labels).sort((a, b) => b[1] - a[1])) {
      const pct = (cnt / count * 100).toFixed(0);
      html += `<div class="achieved-item">${label}: <span>${cnt}</span> (${pct}%)</div>`;
    }
    html += '</div>';
  }
  html += '</div>';
  el.innerHTML = html;
}

function listenProgress(total) {
  const evtSource = new EventSource('/api/progress');
  const logBox = document.getElementById('logBox');
  const bar = document.getElementById('progressBar');
  const barText = document.getElementById('progressText');
  const eta = document.getElementById('progressEta');

  evtSource.onmessage = function(e) {
    const data = JSON.parse(e.data);

    if (data.type === 'heartbeat') return;

    if (data.type === 'progress' || data.type === 'error') {
      const done = data.completed + data.failed;
      const pct = (done / data.total * 100).toFixed(1);
      bar.style.width = pct + '%';
      barText.textContent = `${done} / ${data.total}`;

      document.getElementById('statTools').textContent = (data.avg_tools || 0).toFixed(1);
      document.getElementById('statTurns').textContent = (data.avg_turns || 0).toFixed(1);
      document.getElementById('statFailed').textContent = data.failed || 0;

      // ETA
      if (done > 0 && done < data.total) {
        const remaining = (data.elapsed / done) * (data.total - done);
        eta.textContent = `${formatTime(data.elapsed)} elapsed, ~${formatTime(remaining)} remaining`;
      } else {
        eta.textContent = formatTime(data.elapsed) + ' elapsed';
      }

      // Log entry
      const cls = data.type === 'error' ? 'fail' : 'ok';
      const msg = data.type === 'error'
        ? `${data.profile_id} FAILED: ${data.error}`
        : `${data.profile_id} - ${data.turn_count} turns, ${data.tool_count} tools`;
      logBox.innerHTML += `<div class="log-entry"><span class="${cls}">\\u25cf</span> ${msg}</div>`;
      logBox.scrollTop = logBox.scrollHeight;
    }

    if (data.type === 'done') {
      evtSource.close();
      const btn = document.getElementById('runBtn');
      btn.disabled = false;
      updateRunBtn();
      barText.textContent += ' - Done!';
      eta.textContent = 'Complete. Check your Judgment dashboard.';
    }
  };

  evtSource.onerror = function() {
    evtSource.close();
    document.getElementById('runBtn').disabled = false;
    updateRunBtn();
  };
}

function formatTime(s) {
  if (s < 60) return Math.round(s) + 's';
  const m = Math.floor(s / 60);
  const sec = Math.round(s % 60);
  return m + 'm' + String(sec).padStart(2, '0') + 's';
}

// ── Init ─────────────────────────────────────────────────────

async function init() {
  try {
    const res = await fetch('/api/stats');
    profileStats = await res.json();
  } catch (e) {
    console.error('Failed to load stats:', e);
  }
  initSliders();
  updateRunBtn();
}

init();
</script>
</body>
</html>"""


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Judgment Health Agent Control Panel")
    parser.add_argument("--port", type=int, default=5050, help="Port (default: 5050)")
    parser.add_argument("--no-browser", action="store_true", help="Don't auto-open browser")
    args = parser.parse_args()

    # Pre-load profiles
    print("Loading and classifying profiles...")
    profiles, classified = _load()
    print(f"  {len(profiles)} profiles classified across 3 dimensions")

    for dim, labels in classified["counts"].items():
        top = sorted(labels.items(), key=lambda x: -x[1])[:3]
        top_str = ", ".join(f"{l}: {c}" for l, c in top)
        print(f"  {dim}: {top_str}, ...")

    print(f"\nStarting panel at http://localhost:{args.port}")

    if not args.no_browser:
        threading.Timer(1.0, lambda: webbrowser.open(f"http://localhost:{args.port}")).start()

    app.run(host="0.0.0.0", port=args.port, debug=False, threaded=True)


if __name__ == "__main__":
    main()
