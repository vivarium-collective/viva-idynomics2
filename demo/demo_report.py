"""Generate demo/report.html exercising the real IDynoMiCS-2 wrapper.

Runs three configurations sequentially against the upstream JVM, collects
solute/population trajectories, and renders a single self-contained HTML
report (Plotly + Three.js-free since iDynoMiCS-2 here is a 2D biofilm — we
keep the spatial visualization to a heatmap of per-snapshot concentrations
rather than 3D voxels).
"""

from __future__ import annotations

import base64
import json
import os
import time
import webbrowser
from pathlib import Path

import plotly.graph_objects as go
from plotly.io import to_html as plotly_to_html

from process_bigraph import allocate_core

from pbg_idynomics2 import IDynoMiCS2Process
from pbg_idynomics2 import runtime

REPO_ROOT = Path(__file__).resolve().parent.parent
PROTOCOL_DIR = REPO_ROOT / "protocols"
OUT_DIR = Path(__file__).resolve().parent
OUT_DIR.mkdir(exist_ok=True)


CONFIGS = [
    {
        "id": "biofilm-baseline",
        "title": "Biofilm baseline",
        "subtitle": "simple.xml — surface-attached biofilm, fixed boundary feed",
        "description": (
            "30 bacteria seeded on the bottom of a 32x64um 2D domain.  Each step "
            "(3 min) the PDE wrapper diffuses solute + oxygen, agents consume "
            "and grow, then the relaxation pushes them apart.  We track the "
            "compartment-averaged concentrations and the agent population."
        ),
        "protocol": PROTOCOL_DIR / "simple.xml",
        "compartment": "biofilm-compartment",
        "solutes": ["solute", "oxygen"],
        "interval": 180.0,
        "total_time": 7200.0,  # 7200 minutes ≈ 5 days
        "external_drive": None,
        "accent": "#6366f1",
        "track_population": True,
        "collect_spatial": True,
    },
    {
        "id": "chemostat-natural",
        "title": "Chemostat — natural decay",
        "subtitle": "chemostat.xml — dimensionless tank, first-order reaction",
        "description": (
            "Dimensionless tank with two solutes and a first-order reaction "
            "<code>solute1 → 0.5 · solute2</code>.  No agents, no boundary "
            "feed — solute1 decays exponentially, solute2 accumulates.  "
            "iDynoMiCS's <code>ChemostatSolver</code> integrates the ODE."
        ),
        "protocol": PROTOCOL_DIR / "chemostat.xml",
        "compartment": "chemostat",
        "solutes": ["solute1", "solute2"],
        "interval": 1.0,
        "total_time": 50.0,
        "external_drive": None,
        "accent": "#059669",
        "track_population": False,
    },
    {
        "id": "chemostat-pulsed",
        "title": "Chemostat — pulsed external feed",
        "subtitle": "chemostat.xml driven by the PBG input port",
        "description": (
            "Same chemostat compartment, but the bigraph pulses "
            "<code>solute1</code> back up to 2.0 every 10 simulated units "
            "(via the <code>external_concentrations</code> input port).  "
            "iDynoMiCS still integrates the decay between pulses — so the "
            "coupling is bidirectional within the simulator's own step."
        ),
        "protocol": PROTOCOL_DIR / "chemostat.xml",
        "compartment": "chemostat",
        "solutes": ["solute1", "solute2"],
        "interval": 1.0,
        "total_time": 50.0,
        "external_drive": lambda t: (
            {"solute1": 2.0} if int(t) % 10 == 0 and t > 0 else {}
        ),
        "accent": "#d97706",
        "track_population": False,
    },
]


def run_config(cfg):
    """Drive a single IDynoMiCS2Process through a series of intervals, collecting snapshots."""
    print(f"[demo] running {cfg['id']} ...")
    core = allocate_core()
    proc = IDynoMiCS2Process(
        config={
            "protocol_path": str(cfg["protocol"]),
            "compartment": cfg["compartment"],
            "solutes": cfg["solutes"],
        },
        core=core,
    )
    t_wall_start = time.perf_counter()
    init = proc.initial_state()

    snapshots = []
    spatial_frames = []

    spatial_every = cfg.get("spatial_every", 4)  # decimate frames for animation size
    step_idx = [0]

    def _record(t, external):
        snapshots.append({
            "time_min": float(t),
            "concentrations": dict(proc._prev_concns),
            "population": float(proc._prev_pop),
            "external": dict(external),
        })
        if cfg.get("collect_spatial") and (step_idx[0] % spatial_every == 0):
            spatial_frames.append(proc.spatial_snapshot())
        step_idx[0] += 1

    _record(float(init["time"]), {})

    t_cur = float(init["time"])
    interval = float(cfg["interval"])
    end = t_cur + float(cfg["total_time"])
    drive = cfg.get("external_drive")

    while t_cur < end:
        external = drive(t_cur) if drive else {}
        out = proc.update({"external_concentrations": external}, interval=interval)
        t_cur = float(out["time"])
        _record(t_cur, external)

    wall = time.perf_counter() - t_wall_start
    final_pop = proc._prev_pop
    print(f"[demo]   done {cfg['id']} in {wall:.1f}s, {len(snapshots)} snapshots, "
          f"final pop {final_pop}, spatial frames {len(spatial_frames)}")
    return {
        "id": cfg["id"],
        "title": cfg["title"],
        "subtitle": cfg["subtitle"],
        "description": cfg["description"],
        "accent": cfg["accent"],
        "snapshots": snapshots,
        "spatial_frames": spatial_frames,
        "wall_seconds": wall,
        "interval": interval,
        "total_time": float(cfg["total_time"]),
        "solutes": list(cfg["solutes"]),
        "had_external_drive": drive is not None,
        "track_population": cfg.get("track_population", True),
    }


def population_chart(result):
    times = [s["time_min"] for s in result["snapshots"]]
    pops = [s["population"] for s in result["snapshots"]]
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=times, y=pops, mode="lines", name="population",
        line=dict(color=result["accent"], width=3),
    ))
    fig.update_layout(
        title=f"Agent population — {result['title']}",
        xaxis_title="time (min)", yaxis_title="agents",
        template="plotly_white",
        margin=dict(l=50, r=20, t=50, b=50),
        height=320,
    )
    return plotly_to_html(fig, include_plotlyjs=False, full_html=False)


def concentration_chart(result):
    times = [s["time_min"] for s in result["snapshots"]]
    fig = go.Figure()
    palette = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728"]
    for i, solute in enumerate(result["solutes"]):
        ys = [s["concentrations"].get(solute, 0.0) for s in result["snapshots"]]
        fig.add_trace(go.Scatter(
            x=times, y=ys, mode="lines", name=f"{solute} (compartment avg)",
            line=dict(color=palette[i % len(palette)], width=2),
        ))
        if result["had_external_drive"]:
            ext = [s["external"].get(solute) for s in result["snapshots"]]
            if any(e is not None for e in ext):
                fig.add_trace(go.Scatter(
                    x=times, y=ext, mode="lines",
                    name=f"{solute} (external in)",
                    line=dict(color=palette[i % len(palette)], width=1.2, dash="dot"),
                ))
    fig.update_layout(
        title=f"Solute concentrations — {result['title']}",
        xaxis_title="time (min)", yaxis_title="concentration (mg/L)",
        template="plotly_white",
        margin=dict(l=50, r=20, t=50, b=50),
        height=320,
    )
    return plotly_to_html(fig, include_plotlyjs=False, full_html=False)


def _grid_to_2d(grid: list) -> list[list[float]]:
    """Collapse a [Y][X][Z] (or [X][Y][Z]) iDynoMiCS grid to a 2D matrix.

    iDynoMiCS returns ``double[][][]``; for a 2D Rectangle compartment Z=1.
    We pick the only z-slice and return rows × cols floats.
    """
    if not grid or not grid[0]:
        return []
    # Each "plane" is grid[i] = list of rows; each row = list of z-cells.
    rows = []
    for row in grid:
        if not row:
            continue
        rows.append([float(cell[0]) if cell else 0.0 for cell in row])
    return rows


def spatial_solute_animation(result, solute_name: str):
    """Plotly heatmap animation across time for one solute. Returns HTML or empty string."""
    frames = result.get("spatial_frames") or []
    if not frames:
        return ""
    # Take per-frame 2D grids (skip the t=0 frame if it's all zero — iDynoMiCS
    # zeroes the interior until the first PDE solve).
    times, grids = [], []
    for f in frames:
        sol = f["solutes"].get(solute_name)
        if not sol:
            continue
        g2d = _grid_to_2d(sol["grid"])
        if not g2d:
            continue
        times.append(f["time"])
        grids.append(g2d)
    if not grids:
        return ""

    z0 = grids[0]
    base = go.Heatmap(z=z0, colorscale="Viridis", colorbar=dict(title="mg/L"))
    fig = go.Figure(data=[base])
    frames_anim = [
        go.Frame(data=[go.Heatmap(z=g, colorscale="Viridis")],
                 name=f"{t:.0f}")
        for t, g in zip(times, grids)
    ]
    fig.frames = frames_anim
    fig.update_layout(
        title=f"{solute_name} concentration field (t in min)",
        xaxis_title="x (voxel)", yaxis_title="y (voxel)",
        template="plotly_white",
        height=380, margin=dict(l=50, r=20, t=50, b=50),
        sliders=[{
            "active": 0,
            "currentvalue": {"prefix": "t = "},
            "pad": {"t": 40},
            "steps": [{
                "method": "animate",
                "label": f.name,
                "args": [[f.name], {"mode": "immediate",
                                     "frame": {"duration": 0, "redraw": True},
                                     "transition": {"duration": 0}}]
            } for f in frames_anim]
        }],
        updatemenus=[{
            "type": "buttons", "showactive": False,
            "x": 0, "y": -0.15,
            "buttons": [
                {"label": "Play",
                 "method": "animate",
                 "args": [None, {"frame": {"duration": 200, "redraw": True},
                                  "fromcurrent": True}]},
                {"label": "Pause",
                 "method": "animate",
                 "args": [[None], {"frame": {"duration": 0, "redraw": False},
                                    "mode": "immediate",
                                    "transition": {"duration": 0}}]},
            ]
        }],
    )
    return plotly_to_html(fig, include_plotlyjs=False, full_html=False)


def agents_4d_scatter(result):
    """Agents as a 3D scatter: x, y are simulator positions; z is time.

    Marker color encodes mass (a 4th dimension), so each frame's spatial
    population fans out along the time axis as a 4D snapshot of the biofilm.
    """
    frames = result.get("spatial_frames") or []
    if not frames:
        return ""
    xs, ys, zs, masses, hovers = [], [], [], [], []
    for f in frames:
        for a in f.get("agents", []):
            pos = a.get("position") or []
            if len(pos) < 2:
                continue
            xs.append(pos[0])
            ys.append(pos[1])
            zs.append(f["time"])
            masses.append(a.get("mass") or 0.0)
            hovers.append(
                f"species={a.get('species')}<br>"
                f"mass={a.get('mass'):.3f}<br>"
                f"t={f['time']:.0f}"
                if a.get('mass') is not None else f"t={f['time']:.0f}"
            )
    if not xs:
        return ""
    fig = go.Figure(data=[go.Scatter3d(
        x=xs, y=ys, z=zs,
        mode="markers",
        marker=dict(
            size=3.5,
            color=masses,
            colorscale="Viridis",
            colorbar=dict(title="mass"),
            opacity=0.85,
        ),
        hovertext=hovers,
        hoverinfo="text",
    )])
    fig.update_layout(
        title="Agents in 4D — (x, y, time) coloured by mass",
        scene=dict(
            xaxis_title="x (μm)",
            yaxis_title="y (μm)",
            zaxis_title="time (min)",
            aspectratio=dict(x=1, y=1, z=1.2),
        ),
        height=460,
        margin=dict(l=0, r=0, t=40, b=0),
    )
    return plotly_to_html(fig, include_plotlyjs=False, full_html=False)


def solute_surface_3d(result, solute_name: str):
    """3D surface of the final solute concentration field — height = concentration."""
    frames = result.get("spatial_frames") or []
    if not frames:
        return ""
    final = frames[-1]
    sol = final["solutes"].get(solute_name)
    if not sol:
        return ""
    g2d = _grid_to_2d(sol["grid"])
    if not g2d:
        return ""
    fig = go.Figure(data=[go.Surface(z=g2d, colorscale="Viridis",
                                     colorbar=dict(title="mg/L"))])
    fig.update_layout(
        title=f"{solute_name} concentration field (final state)",
        scene=dict(
            xaxis_title="x (voxel)", yaxis_title="y (voxel)",
            zaxis_title=f"{solute_name} (mg/L)",
            aspectratio=dict(x=1.2, y=1, z=0.6),
        ),
        height=460,
        margin=dict(l=0, r=0, t=40, b=0),
    )
    return plotly_to_html(fig, include_plotlyjs=False, full_html=False)


def bigraph_diagram() -> str:
    """Render a small bigraph-viz diagram of the wrapper architecture as a data URI."""
    try:
        from bigraph_viz import plot_bigraph
    except Exception as e:
        print(f"[demo] bigraph-viz not available ({e}); skipping diagram")
        return ""

    doc = {
        "idynomics": {
            "_type": "process",
            "address": "local:IDynoMiCS2Process",
            "inputs": {
                "external_concentrations": ["stores", "external_concentrations"],
            },
            "outputs": {
                "average_concentrations": ["stores", "average_concentrations"],
                "population": ["stores", "population"],
                "time": ["stores", "time"],
            },
        },
        "stores": {
            "external_concentrations": {},
            "average_concentrations": {},
            "population": 0.0,
            "time": 0.0,
        },
        "emitter": {
            "_type": "step",
            "address": "local:ram-emitter",
            "inputs": {
                "average_concentrations": ["stores", "average_concentrations"],
                "population": ["stores", "population"],
                "time": ["stores", "time"],
            },
        },
    }
    diagram_dir = OUT_DIR / "_data"
    diagram_dir.mkdir(exist_ok=True)
    try:
        plot_bigraph(
            state=doc,
            out_dir=str(diagram_dir),
            filename="bigraph",
            file_format="png",
            remove_process_place_edges=True,
            rankdir="LR",
            node_fill_colors={
                ("idynomics",): "#6366f1",
                ("emitter",): "#8b5cf6",
                ("stores",): "#e0e7ff",
            },
            node_label_size="16pt",
            port_labels=False,
            dpi="150",
        )
    except Exception as e:
        print(f"[demo] bigraph diagram failed ({e}); skipping")
        return ""
    png_path = diagram_dir / "bigraph.png"
    if not png_path.exists():
        return ""
    with open(png_path, "rb") as f:
        return "data:image/png;base64," + base64.b64encode(f.read()).decode()


def pbg_document_for_viewer() -> dict:
    """Return a representative document shape for the embedded JSON viewer."""
    return {
        "idynomics": {
            "_type": "process",
            "address": "local:IDynoMiCS2Process",
            "config": {
                "protocol_path": "protocols/simple.xml",
                "compartment": "biofilm-compartment",
                "solutes": ["solute", "oxygen"],
            },
            "interval": 180.0,
            "inputs": {
                "external_concentrations": ["stores", "external_concentrations"],
            },
            "outputs": {
                "average_concentrations": ["stores", "average_concentrations"],
                "population": ["stores", "population"],
                "time": ["stores", "time"],
            },
        },
        "stores": {
            "external_concentrations": {},
            "average_concentrations": {},
            "population": 0.0,
            "time": 0.0,
        },
        "emitter": {
            "_type": "step",
            "address": "local:ram-emitter",
            "config": {"emit": {
                "average_concentrations": "map[string,float]",
                "population": "float",
                "time": "float",
            }},
            "inputs": {
                "average_concentrations": ["stores", "average_concentrations"],
                "population": ["stores", "population"],
                "time": ["stores", "time"],
            },
        },
    }


def render_html(results, bigraph_uri, report_path):
    sections = []
    nav_items = []
    metric_cards = []
    total_wall = 0.0
    total_steps = 0
    for r in results:
        sec_id = r["id"]
        nav_items.append(
            f'<a class="nav-link" href="#{sec_id}">{r["title"]}</a>'
        )
        pop_html = population_chart(r)
        concn_html = concentration_chart(r)
        snaps = len(r["snapshots"])
        final_pop = r["snapshots"][-1]["population"]
        if r.get("track_population", True):
            pop_metric = (
                f'<div class="metric-row"><span>final pop</span>'
                f'<b>{final_pop:.0f}</b></div>'
            )
            charts_block = (
                f'<div class="chart">{pop_html}</div>'
                f'<div class="chart">{concn_html}</div>'
            )
        else:
            final_concs = r["snapshots"][-1]["concentrations"]
            pop_metric = (
                f'<div class="metric-row"><span>final '
                f'{r["solutes"][0]}</span>'
                f'<b>{final_concs.get(r["solutes"][0], 0.0):.3f}</b></div>'
            )
            charts_block = f'<div class="chart" style="grid-column:1/-1;">{concn_html}</div>'
        metric_cards.append(
            f'<div class="metric" style="border-left-color:{r["accent"]};">'
            f'<div class="metric-title">{r["title"]}</div>'
            f'{pop_metric}'
            f'<div class="metric-row"><span>snapshots</span><b>{snaps}</b></div>'
            f'<div class="metric-row"><span>wall</span><b>{r["wall_seconds"]:.1f}s</b></div>'
            f'</div>'
        )
        spatial_block = ""
        if r.get("spatial_frames"):
            anim_html = ""
            surf_html = ""
            primary_solute = r["solutes"][0] if r["solutes"] else None
            if primary_solute:
                anim_html = spatial_solute_animation(r, primary_solute)
                surf_html = solute_surface_3d(r, primary_solute)
            scatter_html = agents_4d_scatter(r)
            if anim_html or scatter_html or surf_html:
                spatial_block = (
                    '<div class="spatial">'
                    '<h3>Full simulator state — 3D / 4D views</h3>'
                    '<p class="sub2">Read straight from the JVM after each '
                    'step. The 2D solute grid animates over time (3D '
                    'x-y-t view); the final solute field is also rendered '
                    'as a 3D surface where height encodes concentration; '
                    'and the agents are shown as a 4D scatter '
                    '(positions × time × mass).</p>'
                    f'<div class="chart">{anim_html}</div>'
                    f'<div class="chart">{surf_html}</div>'
                    f'<div class="chart">{scatter_html}</div>'
                    '</div>'
                )
        sections.append(f"""
        <section id="{sec_id}" class="config" style="--accent:{r['accent']};">
          <h2>{r['title']}</h2>
          <p class="subtitle">{r['subtitle']}</p>
          <p>{r['description']}</p>
          <div class="charts">
            {charts_block}
          </div>
          {spatial_block}
          <div class="meta">
            <span>protocol: <code>{r['id']}</code></span>
            <span>interval: {r['interval']:.0f} min</span>
            <span>total: {r['total_time']:.0f} min</span>
            <span>wall: {r['wall_seconds']:.2f} s</span>
            <span>snapshots: {snaps}</span>
          </div>
        </section>
        """)
        total_wall += r["wall_seconds"]
        total_steps += snaps

    bigraph_html = ""
    if bigraph_uri:
        bigraph_html = (
            '<section id="architecture"><h2>Architecture</h2>'
            '<p>The wrapper exposes a single <code>Process</code> that drives '
            'the upstream <code>idynomics.Simulator</code> via JPype.  Inputs '
            'push absolute external concentrations down into iDynoMiCS; '
            'outputs come back as composable deltas (so a sibling kinetic '
            'process can also write to the same store).</p>'
            f'<img class="bigraph" src="{bigraph_uri}" alt="bigraph">'
            '</section>'
        )

    doc_json = json.dumps(pbg_document_for_viewer(), indent=2)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>pbg-idynomics2 — demo report</title>
<script src="https://cdn.plot.ly/plotly-2.27.0.min.js"></script>
<style>
  body {{ margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; color: #1f2937; background: #f9fafb; }}
  header {{ background: #ffffff; border-bottom: 1px solid #e5e7eb; padding: 24px 48px; }}
  header h1 {{ margin: 0 0 4px 0; font-size: 22px; }}
  header .lead {{ color: #6b7280; font-size: 14px; }}
  nav {{ position: sticky; top: 0; z-index: 10; background: #ffffff; border-bottom: 1px solid #e5e7eb; padding: 12px 48px; }}
  nav .nav-inner {{ display: flex; gap: 20px; font-size: 14px; }}
  nav a {{ color: #4b5563; text-decoration: none; }}
  nav a:hover {{ color: #111827; }}
  main {{ padding: 24px 48px; max-width: 1200px; }}
  section {{ background: #ffffff; border: 1px solid #e5e7eb; border-radius: 8px; padding: 20px 24px; margin-bottom: 24px; border-left: 4px solid var(--accent, #6366f1); }}
  section h2 {{ margin-top: 0; font-size: 18px; }}
  .subtitle {{ color: #6b7280; margin-top: -8px; }}
  .charts {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }}
  @media (max-width: 900px) {{ .charts {{ grid-template-columns: 1fr; }} }}
  .meta {{ margin-top: 12px; font-size: 12px; color: #6b7280; display: flex; flex-wrap: wrap; gap: 16px; }}
  .meta code {{ background: #f3f4f6; padding: 2px 6px; border-radius: 4px; }}
  .metrics {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px; margin-bottom: 24px; }}
  .metric {{ background: #ffffff; border: 1px solid #e5e7eb; border-left: 4px solid #6366f1; border-radius: 6px; padding: 12px 16px; }}
  .metric-title {{ font-weight: 600; margin-bottom: 6px; }}
  .metric-row {{ display: flex; justify-content: space-between; font-size: 13px; color: #4b5563; }}
  .metric-row b {{ color: #111827; }}
  img.bigraph {{ max-width: 100%; height: auto; border: 1px solid #e5e7eb; border-radius: 6px; background: #ffffff; }}
  pre.doc {{ background: #0f172a; color: #e0e7ff; padding: 16px; border-radius: 6px; font-size: 12px; overflow: auto; max-height: 360px; }}
  pre.doc .k {{ color: #c4b5fd; }}
  pre.doc .s {{ color: #6ee7b7; }}
  pre.doc .n {{ color: #93c5fd; }}
  pre.doc .b {{ color: #fbbf24; }}
  .summary {{ font-size: 13px; color: #6b7280; }}
  .spatial {{ margin-top: 18px; padding-top: 14px; border-top: 1px dashed #e5e7eb; }}
  .spatial h3 {{ margin: 0 0 6px 0; font-size: 15px; }}
  .sub2 {{ color: #6b7280; font-size: 13px; margin-top: 0; }}
</style>
</head>
<body>
<header>
  <h1>pbg-idynomics2 — IDynoMiCS 2.0 via process-bigraph</h1>
  <div class="lead">Three real-simulator runs against the upstream
  <code>idynomics.Simulator</code>, driven through JPype, with PBG input
  ports closing the loop on external solute concentrations.</div>
</header>
<nav><div class="nav-inner">
  {' '.join(nav_items)}
  <a class="nav-link" href="#architecture">Architecture</a>
  <a class="nav-link" href="#document">Document</a>
</div></nav>
<main>
  <div class="summary">total wall {total_wall:.1f}s across {len(results)} configurations, {total_steps} snapshots collected.</div>
  <div class="metrics">
    {''.join(metric_cards)}
  </div>
  {''.join(sections)}
  {bigraph_html}
  <section id="document">
    <h2>Composite document (representative)</h2>
    <p>This is the shape of the PBG document constructed for each run —
    the bridge connects to four stores (<code>external_concentrations</code>,
    <code>average_concentrations</code>, <code>population</code>, <code>time</code>),
    and a <code>RAMEmitter</code> records the outputs.</p>
    <pre class="doc">{html_escape(doc_json)}</pre>
  </section>
</main>
</body></html>
"""
    report_path.write_text(html, encoding="utf-8")


def html_escape(s: str) -> str:
    return (s.replace("&", "&amp;")
             .replace("<", "&lt;")
             .replace(">", "&gt;"))


def main():
    # Pre-warm: make sure the JAR is in cache before the first config (so the
    # very first run's wall-clock isn't dominated by the download).
    runtime.ensure_release(verbose=True)

    results = []
    for cfg in CONFIGS:
        results.append(run_config(cfg))

    bigraph_uri = bigraph_diagram()
    out = OUT_DIR / "report.html"
    render_html(results, bigraph_uri, out)
    print(f"[demo] report written to {out}")
    webbrowser.open("file://" + str(out.resolve()))


if __name__ == "__main__":
    main()
