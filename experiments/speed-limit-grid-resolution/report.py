#!/usr/bin/env python3
"""Generate technical reports from sealed new cases or the published results.json.

--session requires original local outputs; --from-records uses public files only.
No solver is invoked. Plotting uses the existing Matplotlib environment.
"""
import argparse
import base64
import csv
from decimal import Decimal
from html import escape
import json
import importlib.util
import re
from pathlib import Path
import sys

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
import experiment as e

METRICS=[('runup_expanded_m','Expanded monitored run-up','m'),
         ('runup_legacy_m','Original-area monitored run-up','m'),
         ('wetted_area_km2','Eligible land wetted at any time','km²'),
         ('max_land_depth_m','Maximum water depth on eligible land','m'),
         ('P2_eta_m','P2 peak water-surface elevation','m'),
         ('P3_eta_m','P3 peak water-surface elevation','m'),
         ('P5_eta_m','P5 peak water-surface elevation','m')]


def difference(left,right):
    if left is None or right is None:return None,None
    a,b=Decimal(str(left)),Decimal(str(right))
    e.require(a.is_finite() and b.is_finite(),'Nonfinite accepted metric')
    delta=b-a
    return str(delta),str(100*delta/a) if a>0 and b>=0 else None


def audited_baseline():
    """Reuse the checkpoint's public cross-file checks, without altering it."""
    spec=importlib.util.spec_from_file_location('measurement_analysis',e.ROOT/'analysis/measurement_robustness/analyze.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    results,figures,hashes=module.verify_inputs(e.ROOT)
    analysis=module.compare_records(results,figures)
    names=dict(expanded='runup_expanded_m',legacy='runup_legacy_m',area='wetted_area_km2',
               depth='max_land_depth_m',P2='P2_eta_m',P3='P3_eta_m',P5='P5_eta_m')
    return {names[r['metric']]:str(r['value_100']) for r in analysis['comparison']},hashes


def collect(session):
    p=e.protocol();identity=e.load(session/'identity.json')
    e.require(identity['protocol_sha256']==e.sha(HERE/'protocol.json') and
              identity['driver_sha256']==e.sha(HERE/'experiment.py'),'Execution policy/driver mismatch')
    records={};manifests={};preflights={}
    for grid in p['grids']:
        f=session/f'preflight_{grid}.json'
        if f.exists():
            preflights[grid]=e.load(f)
            for name,h in preflights[grid]['prepared_files_sha256'].items():
                e.require(e.sha(session/'inputs'/grid/name)==h,'Prepared-input hash mismatch')
            for case,files in preflights[grid]['generated_cases_sha256'].items():
                for name,h in files.items():
                    e.require(e.sha(session/'cases'/case/name)==h,'Case configuration/deck changed after preflight: '+case+'/'+name)
    for case in p['stage1']+p['stage2']:
        f=session/'cases'/case/'record.json'
        if not f.exists():records[case]={'status':'unattempted','metrics':None,'checks':{},'errors':[]};continue
        r=e.load(f)
        for name,h in r['files_sha256'].items():e.require(e.sha(f.parent/name)==h,'Changed raw output: '+case+'/'+name)
        if r['status']=='accepted':e.require(e.accepted(r),'Incomplete acceptance record')
        else:e.require(r['metrics'] is None,'Failed cases cannot have accepted scientific metrics')
        manifests[case]=dict(record_sha256=e.sha(f),files_sha256=r.pop('files_sha256'))
        v=r.pop('field_validation',{})
        r['field_check_summary']={k:v.get(k) for k in ('status','frames_read','last_time_s','initial_bed_max_error_m','final_bed_change_max_error_m','accepted_small_dry_land_occurrences')}
        r['monitor_diagnostics']=v.get('runup_diagnostics')
        r['bed_timing_check']=v.get('bed_timing_check')
        step=f.parent/'time_step_check.json'
        r['time_step_check']=e.load(step) if step.exists() else None
        policy=f.parent/'policy_check.json'
        r['policy_check']=e.load(policy) if policy.exists() else None
        trace=f.parent/'fort.amr'
        if trace.exists():
            pattern=re.compile(r'AMRCLAW:\s*level\s+\d+\s+CFL\s*=\s*(\S+)\s+dt\s*=\s*(\S+)\s+final t')
            pairs=[tuple(float(v.replace('D','E').replace('d','e')) for v in match.groups())
                   for line in trace.read_text().splitlines() if (match:=pattern.search(line))]
            r['trace_statistics']=dict(maximum_printed_cfl=max(x[0] for x in pairs),
                                       minimum_printed_dt_s=min(x[1] for x in pairs),
                                       maximum_printed_dt_s=max(x[1] for x in pairs)) if pairs else None
        # Retain full errors and limiting-event diagnostics, not private fields.
        records[case]=r
    fig=e.load(e.ROOT/'docs/figures/figure_provenance.json')
    baseline,baseline_hashes=audited_baseline()
    physical=e.load(e.ROOT/'release/frozen_baseline_config.json')
    with (session/'inputs/original/source_history.csv').open() as f:history=list(csv.DictReader(f))
    source_summary=dict(samples=len(history),first_time_s=float(history[0]['time_s']),
                        last_time_s=float(history[-1]['time_s']),
                        first_travel_m=float(history[0]['travel_towards_negative_Y_m']),
                        last_travel_m=float(history[-1]['travel_towards_negative_Y_m']),
                        minimum_represented_volume_m3=min(float(r['represented_volume_m3']) for r in history),
                        maximum_represented_volume_m3=max(float(r['represented_volume_m3']) for r in history))
    result=dict(schema=1,protocol=p,identity=identity,preflights=preflights,cases=records,archived_100_metrics=baseline,
                physical_configuration=physical,source_history_summary=source_summary,
                archived_200_exclusion=fig['excluded_case'],historical_accuracy_established=False,grid_convergence_established=False)
    provenance=dict(checkpoint=p['checkpoint'],runtime_image=p['runtime_image'],solver_sha256=p['solver_sha256'],
                    protocol_sha256=e.sha(HERE/'protocol.json'),driver_sha256=e.sha(HERE/'experiment.py'),
                    frozen_physical_configuration_sha256=e.sha(e.ROOT/'release/frozen_baseline_config.json'),
                    original_code_sha256=identity['code_sha256'],required_inputs_sha256=identity['required_inputs_sha256'],
                    archived_inputs_sha256=identity['archived_prepared_sha256'],case_evidence=manifests,
                    public_baseline_sha256={str(x.relative_to(e.ROOT)):e.sha(x) for x in
                        (e.BASE/'results.json',e.ROOT/'docs/figures/figure_provenance.json')},
                    baseline_cross_file_checks='Passed unchanged checkpoint verification and comparison checks',
                    baseline_checked_files_sha256=baseline_hashes,
                    raw_outputs_location='Lituya_Cap_Comparison/comparison_runs/speed_grid_a205e423 (private; not redistributed)',
                    human_scientific_review='pending',html_visual_review='pending; local-file browser inspection blocked',
                    generated_report_assistance='AI-assisted implementation, testing, numerical analysis and documentation; see root README Research authorship',
                    measurement_checkpoint_csv_note='Git normalized measurement-analysis CSV CRLF line endings to LF. Values are unchanged; that checkpoint provenance records pre-normalization generation hashes.')
    return result,provenance


def tables(data):
    rows=[]
    for name in data['protocol']['stage1']+data['protocol']['stage2']:
        r=data['cases'][name];grid,cap=e.case_parts(name,data['protocol']);nx,ny=data['protocol']['grids'][grid]
        if r['status']=='accepted':e.require(e.accepted(r),'Incomplete acceptance record: '+name)
        row=dict(case=name,grid=grid,speed_limit_m_s=cap,nx=nx,ny=ny,status=r['status'])
        if e.accepted(r):
            for key,_,_ in METRICS:
                v=(r.get('metrics') or {}).get(key)
                e.require(v is not None and not isinstance(v,bool) and Decimal(str(v)).is_finite(),
                          'Accepted case has missing/nonfinite metric: '+name+'/'+key)
        for key,_,_ in METRICS:row[key]=(r.get('metrics') or {}).get(key) if e.accepted(r) else None
        row.update(logged_limiter_events=(r.get('limiter') or {}).get('logged_b4step2_events'),
                   deep_logged_events=(r.get('limiter') or {}).get('events_at_depth_ge_10_m'),
                   maximum_printed_cfl=(r.get('trace_statistics') or {}).get('maximum_printed_cfl'),
                   errors='; '.join(r.get('errors',[])))
        rows.append(row)
    rows.sort(key=lambda row:(row['grid']=='fine',row['speed_limit_m_s']))
    lookup={r['case']:r for r in rows}
    pairs=[(f'{g}_050',f'{g}_100',f'{g}: 50 → 100 m/s') for g in ('original','fine')]
    pairs += [(f'{g}_100',f'{g}_200',f'{g}: 100 → 200 m/s') for g in ('original','fine')]
    pairs += [(f'original_{c:03d}',f'fine_{c:03d}',f'{c} m/s: original → fine grid') for c in (50,100,200)]
    pairs += [('archived_100','original_100','100 m/s: archived → fresh time policy')]
    lookup['archived_100']=dict(status='accepted',**data['archived_100_metrics'])
    comparisons=[]
    for left,right,label in pairs:
        a,b=lookup[left],lookup[right];valid=a['status']==b['status']=='accepted'
        for key,quantity,unit in METRICS:
            x,y=(a.get(key),b.get(key)) if valid else (None,None)
            delta,percent=difference(x,y)
            comparisons.append(dict(comparison=label,from_case=left,to_case=right,quantity=quantity,unit=unit,
                                    from_value=x,to_value=y,difference=delta,percent_difference=percent,
                                    status='accepted comparison' if valid else 'not available: both cases must be accepted'))
    return rows,comparisons


def csv_file(path,rows):
    with path.open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]),lineterminator='\n');w.writeheader();w.writerows(rows)


def displayed(value,key,unit=None):
    if value is None:return '—'
    if key not in ('from_value','to_value','difference','percent_difference','runup_expanded_m',
                   'maximum_printed_cfl','logged_limiter_events','deep_logged_events'):return str(value)
    digits=6 if unit=='km²' and key!='percent_difference' else 2
    if key=='maximum_printed_cfl':digits=3
    if key in ('logged_limiter_events','deep_logged_events'):digits=0
    number=Decimal(str(value));rounded=f'{number:.{digits}f}'
    if key in ('difference','percent_difference') and number!=0 and Decimal(rounded)==0:
        return f'{number:.3g}'
    return rounded


def plot(rows,path):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig,ax=plt.subplots(figsize=(8.3,5.5))
    for grid,color,marker in [('original','#284b63','o'),('fine','#85613a','s')]:
        bycap={r['speed_limit_m_s']:r for r in rows if r['grid']==grid}
        ys=[bycap[c]['runup_expanded_m'] if bycap[c]['status']=='accepted' else float('nan') for c in (50,100,200)]
        sample=bycap[50]
        label=f"{grid.capitalize()} grid ({sample['nx']} × {sample['ny']} cells)"
        if any(v==v for v in ys):ax.plot([50,100,200],ys,marker=marker,color=color,label=label,linewidth=1.4,markersize=7)
    ax.set(title='Monitored run-up across speed limits and grids',xlabel='Numerical water-speed limit (m/s)',ylabel='Expanded-area monitored run-up (m)')
    ax.set_xticks([50,100,200]);ax.set_ylim(bottom=0);ax.grid(axis='y',color='#e1e4e6');ax.legend(frameon=False)
    fig.text(.08,.025,'Accepted cases only · 0.1 m reporting threshold · 420 s\nTwo grids do not establish convergence; no speed limit is a ground-truth reference.',fontsize=9)
    fig.tight_layout(rect=[0,.1,1,1]);fig.savefig(path,dpi=160);plt.close(fig)


def render(data,output):
    rows,comparisons=tables(data)
    csv_file(output/'results.csv',rows);csv_file(output/'comparisons.csv',comparisons)
    status=[{k:r[k] for k in ('case','grid','speed_limit_m_s','status','errors')} for r in rows]
    status.append(dict(case='archived_cap_200',grid='original (archived policy)',speed_limit_m_s=200,status='excluded',errors=data['archived_200_exclusion']['reason']))
    csv_file(output/'case_status.csv',status)
    plot(rows,output/'runup_vs_speed_limit.png')
    title='Speed-limit × grid-resolution experiment'
    note='Generated technical analysis report. Produced with AI-assisted implementation, testing, numerical analysis and documentation. It is not an independently written PhD application writing sample. Scientific review is pending; no claim is made that the researcher reviewed every calculation or conclusion.'
    primary=[r for r in comparisons if r['quantity']=='Expanded monitored run-up']
    findings=[]
    for r in primary:
        if r['difference'] is None:continue
        findings.append(f"{r['comparison']}: {Decimal(str(r['from_value'])):.2f} → {Decimal(str(r['to_value'])):.2f} m; "
                        f"difference {Decimal(r['difference']):+.2f} m ({Decimal(r['percent_difference']):+.2f}%).")
    primary_lookup={r['comparison']:r for r in primary}
    if all(primary_lookup[f'{g}: 50 → 100 m/s']['difference'] is not None for g in ('original','fine')):
        rises=[Decimal(primary_lookup[f'{g}: 50 → 100 m/s']['difference']) for g in ('original','fine')]
        findings.append('The 50→100 m/s run-up increase persists on both grids.' if min(rises)>0 else
                        'The 50→100 m/s run-up increase does not persist with the same sign on both grids.')
        for grid in ('original','fine'):
            r=primary_lookup[f'{grid}: 100 → 200 m/s']
            if r['difference'] is not None:
                small=abs(Decimal(r['difference']))<abs(Decimal(primary_lookup[f'{grid}: 50 → 100 m/s']['difference']))
                findings.append(f"On the {grid} grid the absolute 100→200 m/s change is {'smaller' if small else 'not smaller'} than the 50→100 m/s change. "
                                'This comparison alone does not establish a plateau beyond 200 m/s or numerical convergence.')
    for grid in ('original','fine'):
        for caps in ('50 → 100','100 → 200'):
            selected=[r for r in comparisons if r['comparison']==f'{grid}: {caps} m/s']
            if not all(r['difference'] is not None for r in selected):continue
            flat=[r['quantity'] for r in selected if Decimal(r['difference'])==0]
            falling=[r['quantity'] for r in selected if Decimal(r['difference'])<0]
            if len(flat)==len(METRICS):
                findings.append(f'At {grid} resolution, all seven reported maxima/area metrics are equal for {caps} m/s at the saved precision; this does not establish identical fields or time series.')
            else:
                if flat:findings.append(f'{grid.capitalize()} grid, {caps} m/s — unchanged reported quantities: '+', '.join(flat)+'.')
                if falling:findings.append(f'{grid.capitalize()} grid, {caps} m/s — decreasing reported quantities: '+', '.join(falling)+'.')
    sections=[('Question and declared controls',[
        'Does the large run-up sensitivity to the numerical water-speed limit persist under grid refinement, and do the results become less sensitive to further increases in the limit?',
        'Fresh cases share desired CFL 0.5, global dt_max 0.1 s, source-motion dt cap 0.1 s and initial dt 0.02 s. CFL acceptance remains 1.0 with the existing formatted-log tolerance. The policy was declared before launching Stage 1 and is not adjusted to obtain preferred outcomes.',
        'The original grid is 227 × 453 (30 × 29.96688741721854 m); the planned fine grid is 454 × 906 (15 × 14.98344370860927 m), over the identical physical domain. All existing physical-source, water, friction and measurement settings are retained.']),
        ('Numerical acceptance and case status',[
        'Acceptance requires solver completion and unchanged field, CFL/time-step, monitoring-coverage and input-consistency checks, plus enforcement of the declared global step ceiling. Reaching 420 s alone is insufficient. Failed and unattempted cases contribute no accepted comparison values; the archived failed 200 m/s case remains excluded.']),
        ('Primary run-up comparisons',[
        'Run-up is the highest eligible ground elevation reached by at least 0.1 m of water in the expanded monitoring area, relative to model sea level. Land metrics use per-time-step fgmax monitoring, not the 49 saved visualization frames. These are monitor-specific maxima, not historical observations or established bay-wide maxima.',
        'Differences are the second case minus the first, with percentages relative to the first. Tables round values for display; small nonzero differences use three significant digits so they are not shown as zero. CSVs retain the saved precision. Missing entries mean the comparison cannot be made from two accepted cases; they are not zero results. No after-the-fact “close enough” tolerance is applied.']),
        ('Secondary quantities and limiter diagnostics',[
        'The full-precision comparison table also contains original-area run-up, eligible land wetted at any time, maximum land-water depth, and P2/P3/P5 peak water-surface elevations. Wetted area is eligible wet-cell count × actual dx × dy / 1,000,000. Depth maxima are measured above local ground; gauge elevations are relative to model sea level, not peak-to-trough wave heights. Different maxima need not occur together. Equal gauge peaks do not establish identical time series. Percentage differences describe sensitivity; they are not errors relative to reality or statistical uncertainty.',
        'Counts refer to logged b4step2 events; printed event attributes are rounded. They do not represent every limiting operation or unique affected cells, and do not quantify momentum or energy changes. Small or zero logged counts do not by themselves establish accuracy.']),
        ('Refinement and physical setup',[
        f"The preserved prescribed source has volume {data['physical_configuration']['source']['volume_m3']:.8f} m³, travels {data['physical_configuration']['source']['travel_negative_y_m']:g} m towards negative Y over {data['physical_configuration']['source']['travel_duration_s']:g} s, and retains its {data['physical_configuration']['source']['history_interval_s']:g} s source-history interval. This is the existing uncalibrated source specification. The compact records include its unchanged physical configuration and sampled-volume range.",
        ('Fine-grid preflight passed. Identical terrain.tt3, slide.dtt3, source_arrays.npz and source_history.csv hashes preserve the nodal terrain and source volume/motion history. The native 15 m geometry and four-node (60 m) source padding remain unchanged. Cell averages are reintegrated onto exactly doubled grid dimensions; recombining each four fine cells reproduces its coarse-cell average within the declared numerical preflight tolerance. Monitoring bounds remain fixed in metres. Cell eligibility counts, sampled bed elevations and boundary representations can change through discretization.'
         if 'fine' in data['preflights'] else 'Fine-grid preflight has not completed; no preservation claim is made for unexecuted refinement. Expansion is conditional on an accepted Stage 1 pair and a passed physical preflight.')]),
        ('Interpretation and limitations',findings+[
        'Compare fresh 100 m/s against archived 100 m/s separately: this isolates the changed time-stepping policy at the original grid, and must be reported even when the difference is large. The within-grid comparisons use identical policies and measurement definitions.',
        'Two grids are not proof of convergence. The 200 m/s setting is not ground truth, and no accepted cap has been established as physically correct or optimal. Historical accuracy is not established. Artificial boundaries can influence the water even when their cells are excluded from measurement. This is a bounded preliminary numerical experiment, not source calibration.',
        'HTML visual review remains pending because browser policy blocked local-file inspection. Structural/table-data checks are recorded separately. See verification.json and README.md for commands, actual test counts and prerequisites.'])]
    md=['# '+title,'',note,'',
        'Generated by [report.py](report.py) from [results.json](results.json), [protocol.json](protocol.json), sealed private execution records and the archived baseline. See the repository [research-authorship and AI-assistance statement](../../README.md#research-authorship).','']
    html=['<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">',
          '<title>'+title+'</title><style>body{font:16px/1.55 system-ui,sans-serif;color:#26333c;background:#f1f3f4;margin:0}main{max-width:1120px;margin:30px auto;padding:32px;background:white}h1{font-size:29px}h2{font-size:21px;margin-top:30px}table{border-collapse:collapse;width:100%;font-size:14px}th,td{padding:9px;border-bottom:1px solid #ccd1d5;text-align:left}td.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}th{background:#edf0f2}caption{text-align:left;font-weight:600;margin:12px 0}.wrap{overflow:auto}img{width:100%;max-width:850px}a{color:#284b63}@media print{@page{size:A4 landscape;margin:14mm}body{background:white;font-size:10pt}main{margin:0;padding:0;max-width:none}table{font-size:9pt}tr{break-inside:avoid}h2{break-after:avoid}thead{display:table-header-group}.wrap{overflow:visible}}@media(max-width:650px){main{margin:0;padding:16px}}</style><main><h1>'+title+'</h1><p>'+escape(note)+'</p>',
          '<p>Generated by <a href="report.py">report.py</a> from <a href="results.json">results.json</a>, <a href="protocol.json">protocol.json</a>, sealed private execution records and the archived baseline. See the repository <a href="../../README.md#research-authorship">research-authorship and AI-assistance statement</a>.</p>']
    def table(title,records,columns):
        md.extend(['**'+title+'**','','| '+' | '.join(label for _,label in columns)+' |','| '+' | '.join('---' for _ in columns)+' |'])
        html.append('<div class="wrap"><table><caption>'+escape(title)+'</caption><thead><tr>'+''.join('<th>'+escape(label)+'</th>' for _,label in columns)+'</tr></thead><tbody>')
        for row in records:
            cells=[];html.append('<tr>')
            for key,_ in columns:
                v=row.get(key);numeric=key in ('from_value','to_value','difference','percent_difference','runup_expanded_m',
                                               'maximum_printed_cfl','logged_limiter_events','deep_logged_events')
                text=displayed(v,key,row.get('unit'))
                cells.append(text)
                html.append('<td class="'+('num' if numeric else '')+'" data-key="'+key+'" data-value="'+escape('' if v is None else str(v),quote=True)+'">'+escape(text)+'</td>')
            html.append('</tr>');md.append('| '+' | '.join(cells)+' |')
        md.append('');html.append('</tbody></table></div>')
    for heading,paragraphs in sections:
        md.extend(['## '+heading,'']);html.append('<h2>'+heading+'</h2>')
        for paragraph in paragraphs:md.extend([paragraph,'']);html.append('<p>'+escape(paragraph)+'</p>')
        if heading=='Numerical acceptance and case status':table('Complete planned case status',status,[('case','Case'),('grid','Grid'),('status','Status'),('errors','Reason / diagnostic')])
        if heading=='Primary run-up comparisons':
            table('Expanded-area monitored run-up (m)',[r for r in comparisons if r['quantity']=='Expanded monitored run-up'],[('comparison','Comparison'),('from_value','First (m)'),('to_value','Second (m)'),('difference','Difference (m)'),('percent_difference','Difference (%)')])
            md.extend(['![Accepted monitored run-up against numerical water-speed limit](runup_vs_speed_limit.png)',''])
            html.append('<img alt="Accepted monitored run-up against numerical water-speed limit" src="data:image/png;base64,'+base64.b64encode((output/'runup_vs_speed_limit.png').read_bytes()).decode()+'">')
        if heading=='Secondary quantities and limiter diagnostics':
            table('Numerical diagnostics and logged limiter events',rows,[('case','Case'),('status','Status'),('maximum_printed_cfl','Maximum printed CFL'),('logged_limiter_events','Logged events'),('deep_logged_events','Events at printed depth ≥10 m')])
            for label in dict.fromkeys(r['comparison'] for r in comparisons):
                table(label+' — secondary quantities',[r for r in comparisons if r['comparison']==label and r['quantity']!='Expanded monitored run-up'],[('quantity','Quantity'),('unit','Unit'),('from_value','First'),('to_value','Second'),('difference','Difference'),('percent_difference','Change (%)')])
    md.extend(['[Full-precision results](results.csv) · [Comparisons](comparisons.csv) · [Provenance](provenance.json)',''])
    html.append('<p><a href="results.csv">Full-precision results</a> · <a href="comparisons.csv">Comparisons</a> · <a href="provenance.json">Provenance</a></p></main></html>')
    (output/'report.md').write_text('\n'.join(md));(output/'report.html').write_text('\n'.join(html))


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--session',type=Path);p.add_argument('--from-records',action='store_true');p.add_argument('--output',type=Path,default=HERE)
    a=p.parse_args();a.output.mkdir(parents=True,exist_ok=True)
    if a.from_records:
        data=e.load(a.output/'results.json');provenance=e.load(a.output/'provenance.json')
        baseline,_=audited_baseline()
        e.require(data['archived_100_metrics']==baseline,'Published baseline metrics differ from verified archive')
        e.require(data['protocol']==e.protocol(),'Published execution protocol differs')
        e.require(data['identity']['driver_sha256']==e.sha(HERE/'experiment.py'),'Published execution driver differs')
        e.require(data['physical_configuration']==e.load(e.ROOT/'release/frozen_baseline_config.json'),
                  'Published physical configuration differs')
    else:
        if not a.session:p.error('--session or --from-records is required')
        data,provenance=collect(a.session);e.save(a.output/'results.json',data)
    render(data,a.output)
    provenance['report_script_sha256']=e.sha(__file__)
    provenance['output_sha256']={name:e.sha(a.output/name) for name in
        ('results.json','results.csv','comparisons.csv','case_status.csv','report.md','report.html','runup_vs_speed_limit.png')}
    e.save(a.output/'provenance.json',provenance)
    print('Generated reports and figure; no simulation executed.')


if __name__=='__main__':main()
