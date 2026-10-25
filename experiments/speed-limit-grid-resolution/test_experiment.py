"""Public, synthetic checks; no private data or solver needed for collection."""
import copy
import importlib.util
from pathlib import Path
import tempfile
import unittest
import csv
from decimal import Decimal
from html.parser import HTMLParser
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
import report

SPEC=importlib.util.spec_from_file_location('grid_experiment',Path(__file__).with_name('experiment.py'))
e=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(e)


def good():
    return dict(status='accepted',solver_exit_code=0,checks={k:'passed' for k in
                ('field','time_steps','policy','input_consistency','monitor_deck')})


class ProtocolTests(unittest.TestCase):
    def test_exact_refinement_not_nominal_15m_rounding(self):
        p=e.protocol()
        self.assertEqual(p['grids']['fine'],[454,906])
        self.assertEqual(13575/906,(13575/453)/2)
        self.assertNotEqual(13575/905,(13575/453)/2)

    def test_only_cap_differs_within_grid(self):
        p=e.protocol();base=e.load(e.ROOT/'release/frozen_baseline_config.json');before=copy.deepcopy(base)
        a=e.config_for(base,'original_100',p);b=e.config_for(base,'original_200',p)
        self.assertEqual(a.pop('numerics'),{'water_speed_limit_m_s':100.})
        self.assertEqual(b.pop('numerics'),{'water_speed_limit_m_s':200.})
        self.assertEqual(a,b);self.assertEqual(base,before)

    def test_finer_case_keeps_physical_settings(self):
        p=e.protocol();base=e.load(e.ROOT/'release/frozen_baseline_config.json')
        fine=e.config_for(base,'fine_050',p)
        fine.pop('numerics');fine['run']['target_cell_size_m']*=2
        self.assertEqual(fine,base)

    def test_no_unplanned_case(self):
        for name in ('original_300','fine_400','cap_200'):
            with self.subTest(name=name),self.assertRaises(ValueError):e.case_parts(name,e.protocol())

    def test_acceptance_requires_all_checks(self):
        self.assertTrue(e.accepted(good()))
        for key in good()['checks']:
            r=good();r['checks'][key]='failed';self.assertFalse(e.accepted(r))
        r=good();r['solver_exit_code']=1;self.assertFalse(e.accepted(r))
        r=good();r['status']='checks_failed';self.assertFalse(e.accepted(r))

    def test_stage_two_requires_passed_pair_and_fine_preflight(self):
        with tempfile.TemporaryDirectory() as t:
            session=Path(t);p=e.protocol()
            with self.assertRaisesRegex(ValueError,'Stage 1'):e.stage_gate(session,'fine_050',p)
            for name in p['stage1']:e.save(session/'cases'/name/'record.json',good())
            with self.assertRaisesRegex(ValueError,'preflight'):e.stage_gate(session,'fine_050',p)
            e.save(session/'preflight_fine.json',{'status':'passed'})
            e.stage_gate(session,'fine_050',p)

    def test_failed_case_stops_expansion(self):
        with tempfile.TemporaryDirectory() as t:
            session=Path(t);p=e.protocol();r=good();r['status']='checks_failed'
            e.save(session/'cases/original_100/record.json',r)
            with self.assertRaisesRegex(ValueError,'Stop expansion'):e.stage_gate(session,'original_200',p)

    def test_policy_preserves_existing_acceptance_threshold(self):
        p=e.protocol()['time_policy']
        self.assertEqual(p['cfl_max'],1.)
        self.assertEqual(p['source_dt_max_s'],.1)
        self.assertEqual(p['cfl_desired'],.5)
        self.assertEqual(p['dt_max_s'],.1)

    def test_global_step_cap_and_formatted_tolerance(self):
        line='AMRCLAW: level 1 CFL = .500E+00 dt = 0.1000E+00 final t = 1.0000E+00'
        self.assertEqual(e.policy_trace(line,.1)['steps'],1)
        e.policy_trace(line.replace('0.1000E','0.1001E'),.1)
        with self.assertRaisesRegex(ValueError,'ceiling'):e.policy_trace(line.replace('0.1000E','0.1010E'),.1)
        with self.assertRaisesRegex(ValueError,'Missing'):e.policy_trace('',.1)

    def test_negative_step_rejected(self):
        with self.assertRaises(ValueError):e.policy_trace('AMRCLAW: level 1 CFL = .5 dt = -1.00 final t = 1.',.1)

    def test_deck_comparison_masks_only_cap(self):
        with tempfile.TemporaryDirectory() as t:
            f=Path(t)/'geoclaw.data'
            f.write_text('50.0 =: speed_limit\n1.0 =: cfl_max\n');first=e.normalized_decks(Path(t))
            f.write_text('200.0 =: speed_limit\n1.0 =: cfl_max\n');self.assertEqual(first,e.normalized_decks(Path(t)))
            f.write_text('200.0 =: speed_limit\n2.0 =: cfl_max\n');self.assertNotEqual(first,e.normalized_decks(Path(t)))


class ReportTests(unittest.TestCase):
    def fixture(self):
        p=e.protocol();records={}
        for i,name in enumerate(p['stage1']+p['stage2']):
            r=good();r['metrics']={k:10+i for k,_,_ in report.METRICS};r['errors']=[];records[name]=r
        return dict(protocol=p,cases=records,archived_100_metrics={k:8 for k,_,_ in report.METRICS})

    def test_hand_checkable_differences(self):
        self.assertEqual(report.difference(80,100),('20','25'))
        self.assertEqual(report.difference(100,80),('-20','-20'))
        self.assertEqual(report.difference(None,80),(None,None))
        self.assertEqual(report.difference(0,80),('80',None))
        with self.assertRaises(ValueError):report.difference('NaN',80)

    def test_archived_vs_fresh_policy_comparison_is_retained(self):
        rows,comparisons=report.tables(self.fixture())
        policy=[x for x in comparisons if x['from_case']=='archived_100']
        self.assertEqual(len(rows),6);self.assertEqual(len(comparisons),56);self.assertEqual(len(policy),7)
        self.assertEqual(policy[0]['difference'],'2');self.assertEqual(policy[0]['percent_difference'],'25')

    def test_failed_diagnostics_never_enter_comparisons(self):
        data=self.fixture();data['cases']['original_200']['status']='checks_failed'
        data['cases']['original_200']['metrics']['runup_expanded_m']=99999
        rows,comparisons=report.tables(data)
        self.assertIsNone(next(x for x in rows if x['case']=='original_200')['runup_expanded_m'])
        for c in comparisons:
            if 'original_200' in (c['from_case'],c['to_case']):
                self.assertIsNone(c['difference']);self.assertIsNone(c['percent_difference'])

    def test_full_precision_csv(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'table.csv'
            report.csv_file(p,[{'value':'339.72425','missing':None}])
            with p.open() as f:self.assertEqual(list(csv.DictReader(f))[0],{'value':'339.72425','missing':''})

    def test_missing_or_nonfinite_accepted_metric_is_rejected(self):
        for value in (None,'NaN','Infinity'):
            data=self.fixture();data['cases']['original_100']['metrics']['P2_eta_m']=value
            with self.subTest(value=value),self.assertRaises(ValueError):report.tables(data)

    def test_verified_archived_baseline(self):
        baseline,hashes=report.audited_baseline()
        self.assertEqual(set(baseline),{key for key,_,_ in report.METRICS})
        source=e.load(e.BASE/'results.json')
        original=next(r for r in source['summary']['cases'] if r['case']=='cap_100')
        self.assertEqual(Decimal(baseline['runup_expanded_m']),Decimal(str(original['runup_expanded_m'])))
        self.assertIn('simulation/runup_metrics.py',hashes)

    def test_accepted_label_without_complete_checks_is_rejected(self):
        data=self.fixture();data['cases']['original_100']['checks'].pop('field')
        with self.assertRaisesRegex(ValueError,'Incomplete acceptance'):report.tables(data)

    def test_display_does_not_turn_small_nonzero_changes_into_zero(self):
        self.assertEqual(report.displayed('-0.00249','difference','m'),'-0.00249')
        self.assertEqual(report.displayed('0.0023','difference','m'),'0.0023')
        self.assertEqual(report.displayed(0,'difference','m'),'0.00')
        self.assertEqual(report.displayed('41.709','percent_difference','m'),'41.71')


class TableParser(HTMLParser):
    def __init__(self):
        super().__init__();self.rows=[];self.row={};self.cell=None

    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        if tag=='tr':self.row={}
        if tag=='td':
            self.cell=attrs['data-key'];self.row[self.cell]=[attrs['data-value'],'']

    def handle_data(self,text):
        if self.cell:self.row[self.cell][1]+=text

    def handle_endtag(self,tag):
        if tag=='td':self.cell=None
        if tag=='tr' and self.row:self.rows.append(self.row)


class PublishedArtifactTests(unittest.TestCase):
    """The intended public files are required, not silently skipped if missing."""
    def setUp(self):
        self.root=Path(__file__).resolve().parent
        self.data=e.load(self.root/'results.json')

    def test_full_precision_csv_matches_record_calculations(self):
        rows,comparisons=report.tables(self.data)
        for name,expected in [('results.csv',rows),('comparisons.csv',comparisons)]:
            with (self.root/name).open() as f:actual=list(csv.DictReader(f))
            self.assertEqual(actual,[{k:'' if v is None else str(v) for k,v in row.items()} for row in expected])

    def test_html_and_markdown_comparison_values_match_csv(self):
        parser=TableParser();parser.feed((self.root/'report.html').read_text())
        markdown=(self.root/'report.md').read_text()
        with (self.root/'comparisons.csv').open() as f:comparisons=list(csv.DictReader(f))
        html=[r for r in parser.rows if 'from_value' in r]
        self.assertEqual(len(html),len(comparisons))
        expected_order=[r for r in comparisons if r['quantity']=='Expanded monitored run-up']
        expected_order += [r for r in comparisons if r['quantity']!='Expanded monitored run-up']
        for source,row in zip(expected_order,html):
            for key in ('from_value','to_value','difference','percent_difference'):
                self.assertEqual(row[key][0],source[key])
                digits=6 if source['unit']=='km²' and key!='percent_difference' else 2
                displayed='—' if source[key]=='' else f'{Decimal(source[key]):.{digits}f}'
                if source[key] and key in ('difference','percent_difference') and Decimal(source[key])!=0 and Decimal(displayed)==0:
                    displayed=f'{Decimal(source[key]):.3g}'
                self.assertEqual(row[key][1],displayed)
            # The four displayed numbers occur together in a Markdown table row.
            self.assertIn('| '+' | '.join(row[k][1] for k in ('from_value','to_value','difference','percent_difference'))+' |',markdown)

    def test_recorded_acceptance_coverage_and_exclusion(self):
        with (self.root/'case_status.csv').open() as f:statuses={r['case']:r for r in csv.DictReader(f)}
        self.assertEqual(len(statuses),7)
        self.assertEqual(statuses['archived_cap_200']['status'],'excluded')
        for name,case in self.data['cases'].items():
            self.assertEqual(statuses[name]['status'],case['status'])
            if case['status']!='accepted':
                self.assertIsNone(case['metrics']);continue
            self.assertTrue(e.accepted(case))
            self.assertEqual(case['field_check_summary']['last_time_s'],420.)
            self.assertEqual(case['time_step_check']['last_time_s'],420.)
            for monitor in case['monitor_diagnostics']['monitors'].values():
                self.assertTrue(monitor['all_points_observed'])
                self.assertEqual(monitor['observed_points'],monitor['monitor_points'])
                self.assertEqual(monitor['depth_threshold_m'],.1)
            grid=case['grid'];nx,ny=self.data['protocol']['grids'][grid]
            bounds=self.data['preflights'][grid]['domain_xyxy_m']
            area=case['metrics']['wetted_eligible_cells']*(bounds[2]-bounds[0])/nx*(bounds[3]-bounds[1])/ny/1e6
            self.assertAlmostEqual(area,case['metrics']['wetted_area_km2'],places=13)

    def test_generated_file_hashes_and_runtime_identity(self):
        provenance=e.load(self.root/'provenance.json')
        for name,digest in provenance['output_sha256'].items():self.assertEqual(e.sha(self.root/name),digest,name)
        self.assertEqual(e.sha(self.root/'report.py'),provenance['report_script_sha256'])
        self.assertEqual(e.sha(self.root/'experiment.py'),self.data['identity']['driver_sha256'])
        self.assertEqual(e.sha(self.root/'protocol.json'),self.data['identity']['protocol_sha256'])
        self.assertEqual(provenance['runtime_image'],self.data['identity']['runtime_image'])


if __name__=='__main__':unittest.main()
