from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
from typing import Any


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def esc(value: Any) -> str:
    return html.escape(str(value if value is not None else ""))


def badge(status: str) -> str:
    palette = {
        "RUN": "#137333",
        "FAILED_AT_RUNTIME": "#b3261e",
        "BLOCKED_BY_RESOURCES": "#8e6c00",
    }
    color = palette.get(status, "#444746")
    return f'<span style="display:inline-block;padding:3px 8px;border-radius:999px;background:{color};color:white;font-size:12px;font-weight:600;">{esc(status)}</span>'


def render_key_value_table(payload: dict[str, Any]) -> str:
    rows = []
    for key, value in payload.items():
        if isinstance(value, (dict, list)):
            value_html = f"<pre>{esc(json.dumps(value, indent=2))}</pre>"
        else:
            value_html = esc(value)
        rows.append(f"<tr><th>{esc(key)}</th><td>{value_html}</td></tr>")
    return "<table>" + "".join(rows) + "</table>"


def render_attack_cards(report: dict[str, Any]) -> str:
    cards: list[str] = []
    for item in report.get("per_attack_results", []):
        attack_name = item.get("attack_name", "<unknown>")
        status = item.get("status", "UNKNOWN")
        params = item.get("attack_parameters", {})
        body_parts = [
            f"<p><strong>Status:</strong> {badge(status)}</p>",
            f"<p><strong>Runtime:</strong> {esc(item.get('runtime_sec'))} seconds</p>",
        ]
        if "clean_transcript" in item:
            body_parts.append(f"<p><strong>Clean transcript:</strong> {esc(item.get('clean_transcript'))}</p>")
        if "adversarial_transcript" in item:
            body_parts.append(f"<p><strong>Adversarial transcript:</strong> {esc(item.get('adversarial_transcript'))}</p>")
        if "transcript_changed" in item:
            body_parts.append(f"<p><strong>Transcript changed:</strong> {esc(item.get('transcript_changed'))}</p>")
        if "target_matched" in item:
            body_parts.append(f"<p><strong>Target matched:</strong> {esc(item.get('target_matched'))}</p>")
        if "perturbation_linf" in item:
            body_parts.append(f"<p><strong>L-inf perturbation:</strong> {esc(item.get('perturbation_linf'))}</p>")
        if "error" in item:
            body_parts.append(f"<p><strong>Error:</strong></p><pre>{esc(item.get('error'))}</pre>")
        body_parts.append(f"<details><summary>Attack parameters</summary><pre>{esc(json.dumps(params, indent=2))}</pre></details>")
        body_parts.append(f"<details><summary>Raw JSON</summary><pre>{esc(json.dumps(item, indent=2))}</pre></details>")
        cards.append("<section class='card'>" f"<h3>{esc(attack_name)}</h3>" + "".join(body_parts) + "</section>")
    return "".join(cards)


def build_html(report: dict[str, Any]) -> str:
    environment = report.get("environment", {})
    model = report.get("model", {})
    input_block = report.get("input", {})
    clean = report.get("clean_result", {})
    inventory = report.get("attack_inventory", [])
    skipped = report.get("skipped_attacks", [])

    run_count = sum(1 for row in report.get("per_attack_results", []) if row.get("status") == "RUN")
    failure_count = sum(1 for row in report.get("per_attack_results", []) if row.get("status") != "RUN")

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Sentinel ART Audio Report</title>
  <style>
    :root {{
      --bg: #07111f;
      --ink: #eef7ff;
      --card: rgba(11, 23, 39, 0.94);
      --line: rgba(112, 170, 221, 0.18);
      --accent: #2fb6ff;
      --muted: #a9bfd6;
    }}
    body {{
      margin: 0;
      padding: 32px;
      background: radial-gradient(circle at top left, rgba(47, 182, 255, 0.16), transparent 24%), linear-gradient(180deg, #040a14 0%, #081323 46%, #0a1729 100%);
      color: var(--ink);
      font-family: "Avenir Next", "Segoe UI", sans-serif;
      line-height: 1.5;
    }}
    h1, h2, h3 {{
      margin-top: 0;
      font-family: "Avenir Next", "Segoe UI", sans-serif;
      letter-spacing: 0.01em;
    }}
    .wrap {{
      max-width: 1100px;
      margin: 0 auto;
    }}
    .hero {{
      background: linear-gradient(135deg, #071323 0%, #0d233e 38%, #103157 72%, #0a6db3 100%);
      color: white;
      padding: 28px;
      border-radius: 20px;
      box-shadow: 0 24px 72px rgba(0,0,0,0.32);
      margin-bottom: 24px;
    }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
      gap: 16px;
      margin-bottom: 24px;
    }}
    .card {{
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 18px;
      padding: 20px;
      box-shadow: 0 22px 54px rgba(2,7,15,0.34);
      margin-bottom: 18px;
    }}
    table {{
      width: 100%;
      table-layout: fixed;
      border-collapse: collapse;
      background: rgba(8, 18, 31, 0.34);
    }}
    th, td {{
      border: 1px solid var(--line);
      text-align: left;
      vertical-align: top;
      padding: 10px;
      font-size: 14px;
      overflow-wrap: anywhere;
      word-break: break-word;
    }}
    th {{
      background: rgba(16, 35, 58, 0.92);
      width: 240px;
      font-family: "Avenir Next", "Segoe UI", sans-serif;
    }}
    pre {{
      overflow-x: auto;
      white-space: pre-wrap;
      word-break: break-word;
      background: rgba(4, 11, 21, 0.96);
      border: 1px solid var(--line);
      border-radius: 12px;
      padding: 12px;
      font-size: 12px;
      color: #d8f3dc;
    }}
    .muted {{
      color: var(--muted);
    }}
    ul {{
      margin: 0;
      padding-left: 20px;
    }}
  </style>
</head>
<body>
  <div class="wrap">
    <section class="hero">
      <h1>Sentinel ART Audio Report</h1>
      <p>Standalone ART evidence rendered in the Sentinel report style for quick operator review.</p>
      <p class="muted">Completed attacks: {run_count} | Non-successful attack executions: {failure_count} | Inventory entries: {len(inventory)}</p>
    </section>

    <div class="grid">
      <section class="card">
        <h2>Model</h2>
        {render_key_value_table(model)}
      </section>
      <section class="card">
        <h2>Environment</h2>
        {render_key_value_table(environment)}
      </section>
      <section class="card">
        <h2>Input</h2>
        {render_key_value_table(input_block)}
      </section>
      <section class="card">
        <h2>Clean Result</h2>
        {render_key_value_table(clean)}
      </section>
    </div>

    <section class="card">
      <h2>Attack Inventory</h2>
      <table>
        <thead>
          <tr>
            <th>Attack</th>
            <th>Decision</th>
            <th>Reason</th>
          </tr>
        </thead>
        <tbody>
          {''.join(f"<tr><td>{esc(row.get('attack_name'))}</td><td>{badge(str(row.get('decision', '')))}</td><td>{esc(row.get('reason'))}</td></tr>" for row in inventory)}
        </tbody>
      </table>
    </section>

    <section class="card">
      <h2>Per-Attack Results</h2>
      {render_attack_cards(report)}
    </section>

    <section class="card">
      <h2>Skipped / Blocked Attacks</h2>
      {("<ul>" + "".join(f"<li><strong>{esc(item.get('attack_name'))}</strong>: {esc(item.get('reason'))}</li>" for item in skipped) + "</ul>") if skipped else "<p>None.</p>"}
    </section>

    <section class="card">
      <h2>Embedded JSON Snapshot</h2>
      <pre>{esc(json.dumps(report, indent=2))}</pre>
    </section>
  </div>
</body>
</html>
"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Convert the vendored Whisper ART demo JSON result into a standalone HTML report.")
    parser.add_argument("--input", default="vendored_art_demo_output/reports/results.json", help="Path to the JSON results file.")
    parser.add_argument("--output", default="vendored_art_demo_output/reports/report.html", help="Path to the output HTML file.")
    args = parser.parse_args()

    input_path = Path(args.input)
    output_path = Path(args.output)
    report = load_json(input_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(build_html(report), encoding="utf-8")
    print(str(output_path.resolve()))


if __name__ == "__main__":
    main()
