#!/usr/bin/env python3
"""Presentation only: render committed accepted results; never invoke a solver.

From repository root: python -B docs/presentation/experiment_visuals/render.py
Requires the existing Matplotlib environment and Git. --output selects a new
preview location; no original report, figure, record or README is overwritten.
"""
import argparse
import ast
import csv
from decimal import Decimal
import hashlib
from html import escape
import json
from pathlib import Path
import subprocess
import textwrap

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
EXPERIMENT = 'experiments/speed-limit-grid-resolution'
INK, MUTED = '#172e41', '#475761'
COLORS = {'original': '#007c91', 'fine': '#cd6337'}
FIGURE_TITLE = 'Run-up sensitivity to speed limit and grid resolution'
FIGURE_SUBTITLE = 'On each grid, monitored run-up is unchanged when the limit increases from 100 to 200 m/s.'
RUNUP_DEFINITION = 'Highest monitored run-up is the highest sampled natural-land elevation in the expanded monitoring area where water depth reached at least 0.1 m during the simulation. Elevations are relative to model sea level.'
TABLE_TITLE = 'Run-up, flooded area, and water levels'
TABLE_SUBTITLE = 'Comparison across speed limits and grid resolutions, including the earlier 100 m/s simulation.'
TABLE_NOTE = 'Land measurements use the study’s natural-land selection and 0.1 m water-depth threshold. Wetted area includes land reached by water at any time during the simulation. P2, P3, and P5 identify simulation gauge locations; their water levels are elevations relative to model sea level.'
INTERPRETATION = 'The follow-up experiment tested three numerical water-speed limits on two grid resolutions using the same physical setup and matched time-stepping settings. Increasing the limit from 50 to 100 m/s increased highest monitored run-up on both grids. Increasing it further to 200 m/s left this measure unchanged on each grid, although some other outputs differed slightly on the finer grid. Grid refinement increased the run-up values, and the comparison with the earlier 100 m/s simulation also showed sensitivity to time-stepping settings. Together, these results show that the strong response to the 50 m/s limit persists under refinement, while the absolute run-up remains sensitive to other numerical choices.'
SCOPE = 'These comparisons describe sensitivity within the tested model setup and monitoring area. Agreement between the 100 and 200 m/s run-up values does not establish grid convergence or historical accuracy.'
METRICS = [
    ('runup_expanded_m', 'Expanded monitored run-up', 'Highest monitored run-up —\nexpanded area (m)', 2),
    ('runup_legacy_m', 'Original-area monitored run-up', 'Highest monitored run-up —\noriginal area (m)', 2),
    ('wetted_area_km2', 'Eligible land wetted at any time', 'Land area wetted at any time —\nexpanded area (km²)', 6),
    ('max_land_depth_m', 'Maximum water depth on eligible land', 'Maximum water depth on monitored land —\nexpanded area (m)', 3),
    ('P2_eta_m', 'P2 peak water-surface elevation', 'Peak water level at P2 (m)', 3),
    ('P3_eta_m', 'P3 peak water-surface elevation', 'Peak water level at P3 (m)', 3),
    ('P5_eta_m', 'P5 peak water-surface elevation', 'Peak water level at P5 (m)', 3),
]
INPUTS = [EXPERIMENT+'/'+name for name in ('results.csv', 'comparisons.csv', 'results.json', 'protocol.json', 'provenance.json', 'reverification.json')]
INPUTS += ['geoclaw/setrun.py', 'experiments/2026-10-19-speed-caps/plot_figures.py',
           'experiments/2026-10-19-speed-caps/results.json', 'docs/figures/figure_provenance.json']


def git(*args):
    return subprocess.check_output(['git', '-c', 'safe.directory='+str(ROOT), *args], cwd=ROOT)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_inputs():
    commit = git('rev-parse', 'HEAD').decode().strip()
    hashes = {}
    for name in INPUTS:
        local = (ROOT/name).read_bytes()
        if local != git('show', commit+':'+name):
            raise ValueError('Source is modified relative to the recorded commit: '+name)
        hashes[name] = hashlib.sha256(local).hexdigest()
    data = json.loads((ROOT/EXPERIMENT/'results.json').read_text())
    with (ROOT/EXPERIMENT/'results.csv').open() as stream:
        rows = list(csv.DictReader(stream))
    with (ROOT/EXPERIMENT/'comparisons.csv').open() as stream:
        comparisons = list(csv.DictReader(stream))
    expected = [f'{g}_{cap:03d}' for g in ('original', 'fine') for cap in (50,100,200)]
    if [r['case'] for r in rows] != expected:
        raise ValueError('Expected exactly the six fresh cases in numerical order')
    for row in rows:
        saved = data['cases'][row['case']]
        if row['status'] != 'accepted' or saved['solver_exit_code'] != 0 or set(saved['checks'].values()) != {'passed'}:
            raise ValueError('Unaccepted or incomplete case: '+row['case'])
        for key, _, _, _ in METRICS:
            if not Decimal(row[key]).is_finite() or Decimal(row[key]) != Decimal(str(saved['metrics'][key])):
                raise ValueError('CSV/record mismatch: '+row['case']+'/'+key)
    archived = dict(case='archived_100', grid='original', speed_limit_m_s='100', status='accepted archived policy')
    control = [r for r in comparisons if r['from_case']=='archived_100' and r['to_case']=='original_100']
    if len(control) != len(METRICS):
        raise ValueError('Missing archived-versus-fresh control')
    for key, quantity, _, _ in METRICS:
        row = next(r for r in control if r['quantity']==quantity)
        archived[key] = row['from_value']
        if Decimal(archived[key]) != Decimal(data['archived_100_metrics'][key]):
            raise ValueError('Archived control mismatch: '+key)
        fresh = next(r for r in rows if r['case']=='original_100')
        if Decimal(row['to_value']) != Decimal(fresh[key]):
            raise ValueError('Fresh control mismatch: '+key)
    # Obtain the original time policy from unchanged tracked setrun code.
    defaults = {}
    for node in ast.walk(ast.parse((ROOT/'geoclaw/setrun.py').read_text())):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant):
            for target in node.targets:
                if isinstance(target, ast.Attribute) and target.attr in ('dt_max', 'cfl_desired', 'cfl_max'):
                    defaults[target.attr] = node.value.value
    if set(defaults) != {'dt_max','cfl_desired','cfl_max'}:
        raise ValueError('Cannot verify archived default time controls')
    source = data['physical_configuration']['source']
    old_policy = dict(cfl_desired=defaults['cfl_desired'], dt_max_s=defaults['dt_max'], cfl_max=defaults['cfl_max'],
                      source_dt_max_s=source['maximum_solver_step_during_motion_s'])
    policy = data['protocol']['time_policy']
    if old_policy['source_dt_max_s'] != policy['source_dt_max_s'] or old_policy['cfl_max'] != policy['cfl_max']:
        raise ValueError('Common time-control premise changed')
    return rows, archived, control, data, old_policy, commit, hashes


def style():
    plt.rcParams.update({'font.family':'DejaVu Sans','font.size':11,'text.color':INK,
        'axes.labelcolor':INK,'axes.edgecolor':'#929da5','xtick.color':INK,'ytick.color':INK,
        'axes.spines.top':False,'axes.spines.right':False,'figure.facecolor':'white','savefig.facecolor':'white'})


def runup_figure(rows, data, path):
    fig = plt.figure(figsize=(12.8,8.4))
    fig.text(.065,.95,FIGURE_TITLE,fontsize=24,weight='bold')
    fig.text(.065,.907,FIGURE_SUBTITLE,fontsize=13)
    ax = fig.add_axes([.12,.25,.815,.53])
    plotted = []
    for grid, marker, offset in [('original','o',-22),('fine','s',19)]:
        selected = [r for r in rows if r['grid']==grid]
        caps = [int(r['speed_limit_m_s']) for r in selected]
        values = [float(r['runup_expanded_m']) for r in selected]
        spacing = data['preflights'][grid]['dx_m']
        label = f'{"Original" if grid=="original" else "Finer"} grid · approximately {spacing:g} m cells'
        ax.plot(caps,values,color=COLORS[grid],marker=marker,ms=8,lw=2,label=label,zorder=3)
        for cap,value in zip(caps,values):
            ax.annotate(f'{value:.2f}',(cap,value),xytext=(0,offset),textcoords='offset points',
                        ha='center',fontsize=12,weight='semibold',color=COLORS[grid])
        plotted.append(dict(grid=grid,x_m_s=caps,y_m=[r['runup_expanded_m'] for r in selected]))
    ax.set(xlim=(40,211),ylim=(0,550),xticks=[50,100,200],yticks=range(0,551,100),
           xlabel='Numerical water-speed limit (m/s)',ylabel='Highest monitored run-up (m)')
    ax.set_xlabel(ax.get_xlabel(),labelpad=14);ax.set_ylabel(ax.get_ylabel(),labelpad=12)
    ax.grid(axis='y',color='#e3e8eb',linewidth=.8);ax.set_axisbelow(True)
    ax.legend(loc='lower left',bbox_to_anchor=(0,1.04),ncol=2,frameon=False,fontsize=11,borderaxespad=0)
    fig.text(.065,.065,textwrap.fill(RUNUP_DEFINITION,112),fontsize=11.5,color=MUTED,va='bottom',linespacing=1.55)
    # Assert the plot uses real numerical spacing and the unrounded source heights.
    for line, source in zip(ax.lines,plotted):
        assert list(line.get_xdata()) == source['x_m_s']
        assert list(line.get_ydata()) == [float(v) for v in source['y_m']]
    fig.savefig(path,dpi=170);plt.close(fig)
    return plotted


def table_content(rows, archived, control, data, old_policy):
    columns = [archived]+rows
    values = [[format(Decimal(r[key]),f'.{places}f') for r in columns] for key,_,_,places in METRICS]
    new = data['protocol']['time_policy']
    notes = [f'The earlier simulation used a target CFL of {old_policy["cfl_desired"]:g} and a maximum allowed time step of {old_policy["dt_max_s"]:g} s. '
             f'The follow-up simulations used a target CFL of {new["cfl_desired"]:g} and a maximum allowed time step of {new["dt_max_s"]:g} s. Actual time steps were adaptive.',
             f'Shared numerical controls: initial step {new["dt_initial_s"]:g} s; moving-source maximum step {new["source_dt_max_s"]:g} s; CFL acceptance ceiling {new["cfl_max"]:.1f}; maximum {new["steps_max"]:,} steps. The existing formatted-log acceptance tolerance is unchanged.']
    c = next(r for r in control if r['quantity']=='Expanded monitored run-up')
    control_note = f'On the original grid, the revised time-stepping settings reduced highest monitored run-up from {Decimal(c["from_value"]):.2f} to {Decimal(c["to_value"]):.2f} m—a decrease of {abs(Decimal(c["difference"])):.2f} m ({abs(Decimal(c["percent_difference"])):.2f}%).'
    captions = [TABLE_NOTE]
    return columns, values, notes, control_note, captions


def table_figure(columns, values, notes, control_note, captions, path):
    fig = plt.figure(figsize=(16,9.8))
    fig.text(.05,.95,TABLE_TITLE,fontsize=24,weight='bold')
    fig.text(.05,.907,TABLE_SUBTITLE,fontsize=13)
    left, width, first = .05,.90,.31
    cell = (1-first)/7
    centers = [left+width*(first+cell*(i+.5)) for i in range(7)]
    for start,end,label,color in [(0,1,'Earlier study ·\noriginal grid',MUTED),(1,4,'Follow-up study ·\noriginal grid',COLORS['original']),(4,7,'Follow-up study ·\nfiner grid',COLORS['fine'])]:
        center=(centers[start]+centers[end-1])/2
        fig.text(center,.79,label,ha='center',fontsize=11.5,weight='bold',color=color,linespacing=1.5)
    fig.text(left,.738,'Quantity and units',fontsize=11.5,weight='bold')
    for x,column in zip(centers,columns):fig.text(x,.738,column['speed_limit_m_s']+' m/s',ha='center',fontsize=11.5,weight='bold')
    ax=fig.add_axes([left,.38,width,.34]);ax.set_axis_off()
    table=ax.table(cellText=[[label]+row for (_,_,label,_),row in zip(METRICS,values)],
                   colWidths=[first]+[cell]*7,cellLoc='right',bbox=[0,0,1,1])
    table.auto_set_font_size(False);table.set_fontsize(11.5)
    for (i,j), c in table.get_celld().items():
        c.set_edgecolor('#e3e8eb');c.set_linewidth(.6);c.set_text_props(color=INK)
        c.set_facecolor('#f3f6f7' if i%2==0 else 'white');c.PAD=.08
        if j==1:c.set_facecolor('#eaf0f3')
        if j==0:c.get_text().set_ha('left');c.set_text_props(fontsize=11)
    # Visually separate the earlier policy without adding a data category.
    boundary=left+width*(first+cell)
    fig.add_artist(plt.Line2D([boundary,boundary],[.38,.84],transform=fig.transFigure,color='#929da5',lw=1.5))
    fig.text(left,.318,'Time-step comparison at 100 m/s',fontsize=13,weight='semibold')
    fig.text(left,.274,textwrap.fill(control_note,145),fontsize=11.5,va='top',linespacing=1.55)
    fig.text(left,.096,textwrap.fill(TABLE_NOTE,155),fontsize=11,color=MUTED,va='bottom',linespacing=1.55)
    fig.savefig(path,dpi=170);plt.close(fig)


def table_html(columns, values, notes, control_note, captions, path):
    text=['<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">',
          '<title>'+TABLE_TITLE+'</title><style>body{font:16px/1.5 system-ui,sans-serif;color:#172e41;margin:0;background:#f3f6f7}main{max-width:1400px;margin:auto;padding:32px;background:white}h1{font-size:28px}h2{font-size:21px;margin-top:30px}table{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}th,td{padding:12px;border-bottom:1px solid #d9e1e5}th{text-align:left}td{text-align:right;white-space:nowrap}thead th{text-align:center}thead th:first-child{text-align:left}tbody tr:nth-child(odd){background:#f3f6f7}.original{color:#007c91}.fine{color:#b9572f}.earlier,td[data-case="archived_100"]{background:#eaf0f3;border-right:2px solid #929da5}.wrap{overflow:auto}p.note{color:#475761}a{color:#007c91}@media print{@page{size:A4 landscape;margin:12mm}main{padding:0}body{font-size:10pt}th,td{padding:8px}tr{break-inside:avoid}.wrap{overflow:visible}}</style><main>',
          '<h1 id="table-title">'+TABLE_TITLE+'</h1><p>'+TABLE_SUBTITLE+'</p>',
          '<div class="wrap"><table aria-labelledby="table-title"><thead><tr><th rowspan="2">Quantity and units</th><th class="earlier">Earlier study · original grid</th><th colspan="3" class="original">Follow-up study · original grid</th><th colspan="3" class="fine">Follow-up study · finer grid</th></tr><tr>']
    text += ['<th'+(' class="earlier"' if c['case']=='archived_100' else '')+'>'+escape(c['speed_limit_m_s'])+' m/s</th>' for c in columns]
    text.append('</tr></thead><tbody>')
    for (key,_,label,_), row in zip(METRICS,values):
        text.append('<tr><th scope="row">'+escape(label).replace('\n','<br>')+'</th>')
        for c,shown in zip(columns,row):
            text.append(f'<td data-case="{c["case"]}" data-metric="{key}" data-value="{c[key]}" title="Recorded value: {c[key]}">{shown}</td>')
        text.append('</tr>')
    text.append('</tbody></table></div>')
    text.append('<h2>Time-step comparison at 100 m/s</h2><p>'+escape(control_note)+'</p>')
    text += ['<p class="note">'+escape(n)+'</p>' for n in captions]
    text.append('<h2>Methods note</h2>')
    text += ['<p class="note">'+escape(n)+'</p>' for n in notes]
    text.append('<h2>Proposed interpretation for review</h2><p>'+escape(INTERPRETATION)+'</p><p>'+escape(SCOPE)+'</p>')
    text.append('<p>Figure definition: '+escape(RUNUP_DEFINITION)+'</p><p>See <a href="presentation_notes.md">captions, methods and the separate interpretation proposal</a>, including source filenames and full settings.</p>')
    text += ['<p>Display rounding: run-up 2 decimals; depth and gauges 3; area 6. Exact recorded values remain in table attributes and <a href="provenance.json">provenance</a>.</p>',
             '<p>Generated presentation table, with AI-assisted code and formatting. See the <a href="../../../README.md#research-authorship">research-authorship statement</a> and <a href="../../../experiments/speed-limit-grid-resolution/report.html">unchanged technical report</a>.</p></main></html>']
    path.write_text('\n'.join(text)+'\n')


def presentation_notes(data, notes, control_note, path):
    """Generate the accompanying captions/methods and user-supplied proposal."""
    descriptions=[]
    for grid, label in [('original','Original'),('fine','Finer')]:
        nx,ny=data['protocol']['grids'][grid]
        west,south,east,north=data['preflights'][grid]['domain_xyxy_m']
        descriptions.append(f'{label} grid: {nx} × {ny} cells; spacing {(east-west)/nx:g} × {(north-south)/ny:.8f} m.')
    methods=notes+[f'GeoClaw 5.14.0; simulation duration {data["physical_configuration"]["run"]["duration_s"]:g} s. '+' '.join(descriptions),
        'Physical source, terrain, domain, friction, wet/dry settings, monitoring boundaries and measurement definitions are unchanged. Actual adaptive time steps may differ across cases and grids. The 100 m/s time-step comparison changes both the target CFL and the maximum allowed time step; it does not isolate either control individually.',
        'Different maxima need not occur at the same time or location. Equal gauge peaks do not establish identical time series. Run-up is the sampled natural-land ground elevation, not water depth or gauge water-surface elevation.']
    parts=['# Presentation captions, methods and proposed interpretation',
           'Generated from `render.py` and the recorded inputs. The figure and comparison table were approved for inclusion in the root README; these notes retain the detailed methods and interpretation proposal.',
           '## Run-up figure',f'**{FIGURE_TITLE}**',FIGURE_SUBTITLE,RUNUP_DEFINITION,
           'Connecting lines join the three tested speed limits; they do not imply simulations at intermediate limits. Exact plotted values and source hashes remain in [provenance.json](provenance.json).',
           '## Comparison table',f'**{TABLE_TITLE}**',TABLE_SUBTITLE,TABLE_NOTE,
           'Run-up is displayed to two decimals, water depth/gauge levels to three and wetted area to six. This retains the small differences between the finer-grid 100 and 200 m/s cases. Exact recorded values remain in the HTML table attributes and provenance.',
           '## Time-step comparison at 100 m/s',control_note,'## Methods note',*methods,
           '## Proposed interpretation for review',INTERPRETATION,SCOPE,
           '## Sources and supporting records',
           'Source values: [`results.csv`](../../../experiments/speed-limit-grid-resolution/results.csv), [`comparisons.csv`](../../../experiments/speed-limit-grid-resolution/comparisons.csv) and [`results.json`](../../../experiments/speed-limit-grid-resolution/results.json). Controls and identity: [`protocol.json`](../../../experiments/speed-limit-grid-resolution/protocol.json) and the linked experiment provenance. The presentation provenance records the exact source commit and input hashes.',
           'Detailed acceptance checks, verification and excluded-case information remain in the [technical report](../../../experiments/speed-limit-grid-resolution/report.html) and [verification record](../../../experiments/speed-limit-grid-resolution/REVERIFICATION.md). These original research documents are unchanged.']
    path.write_text('\n\n'.join(parts)+'\n')
    return methods


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,default=HERE)
    args=parser.parse_args();output=args.output.resolve();output.mkdir(parents=True,exist_ok=True)
    if output != HERE and (output==ROOT or output.is_relative_to(ROOT/'experiments') or output.is_relative_to(ROOT/'docs/figures')):
        raise ValueError('Refusing an original research/figure destination')
    rows,archived,control,data,old_policy,commit,hashes=load_inputs();style()
    plotted=runup_figure(rows,data,output/'runup_grid_comparison.png')
    columns,values,notes,control_note,captions=table_content(rows,archived,control,data,old_policy)
    table_figure(columns,values,notes,control_note,captions,output/'secondary_comparison.png')
    methods=presentation_notes(data,notes,control_note,output/'presentation_notes.md')
    table_html(columns,values,methods,control_note,captions,output/'secondary_comparison.html')
    provenance=dict(source_commit=commit,source_bytes_match_commit=True,source_sha256=hashes,
        script_sha256=sha(Path(__file__)),matplotlib_version=matplotlib.__version__,
        plotted_data=plotted,table_cases=columns,table_display_values=values,
        fresh_time_policy=data['protocol']['time_policy'],archived_time_policy=old_policy,
        control_comparisons=control,grid_dimensions=data['protocol']['grids'],
        domain_xyxy_m=data['preflights']['original']['domain_xyxy_m'],
        runup_definition='Highest eligible natural-land ground elevation reached by at least 0.1 m of water, within the named monitoring area; relative to model sea level.',
        presentation=dict(colors_represent='grid, not accuracy or preference',x_axis='linear; actual values 50, 100, 200 m/s',
            figure_title=FIGURE_TITLE,figure_subtitle=FIGURE_SUBTITLE,figure_note=RUNUP_DEFINITION,
            table_title=TABLE_TITLE,table_subtitle=TABLE_SUBTITLE,table_note=TABLE_NOTE,
            methods=methods,proposed_interpretation=INTERPRETATION,scope=SCOPE,
            plotted_heights='unrounded source values; only text labels rounded',
            connecting_lines='join discrete case results; do not imply simulated intermediate caps',
            table_rounding='run-up 2 decimals; depth/gauges 3; area 6',smoothing=False,new_metrics=False),
        archived_200='excluded; failed recorded CFL/time-step checks; never substituted for a fresh case',
        code_checks='Six accepted cases; numeric CSV/JSON and archived-control cross-checks; plotted x/y arrays checked against source; source bytes checked against Git commit.',
        limitations=['Tested setup and monitored area only','No established historical accuracy or grid convergence','Neither speed limit nor grid is a ground-truth reference'],
        review_status='Figure and comparison table approved by the user for root README inclusion; original research reports unchanged',
        authorship_reference='../../../README.md#research-authorship',
        output_sha256={f:sha(output/f) for f in ('runup_grid_comparison.png','secondary_comparison.png','secondary_comparison.html','presentation_notes.md')})
    (output/'provenance.json').write_text(json.dumps(provenance,indent=2,ensure_ascii=False,allow_nan=False)+'\n')
    print('Rendered figure and comparison table from committed results; no simulation or existing-file changes.')


if __name__=='__main__':main()
