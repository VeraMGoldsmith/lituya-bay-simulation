"""Mocked Docker routing plus real standard-library collection on synthetic files."""
from pathlib import Path
import json
import os
import shutil
import subprocess
import zipfile

import pytest
from simulation.common import ROOT, save
from test_launcher import shell_fixture


@pytest.fixture
def comparison_shell(shell_fixture):
    root,calls,run=shell_fixture
    # Reuse the established fake Docker/OS fixture with the NEW launcher's content.
    shutil.copy2(ROOT/'run_comparison.sh',root/'run.sh')
    shutil.copy2(ROOT/'collect_comparison.py',root/'collect_comparison.py')
    return root,calls,run


def test_default_only_preflight_native_arm64(comparison_shell):
    root,calls,run=comparison_shell
    r=run();assert r.returncode==0,r.stderr+r.stdout
    text=calls.read_text()
    assert '/workspace/comparison.py preflight' in text
    assert '/workspace/workflow.py' not in text
    assert '--platform linux/arm64' in text
    assert '-e LITUYA_RUN_IMAGE_ID=sha256:' in text
    assert '--network none' in text and '--cap-drop ALL' in text
    assert str(root)+':/workspace' in text


def test_run_routes_only_to_bounded_runner(comparison_shell):
    _,calls,run=comparison_shell
    assert run(['run']).returncode==0
    assert '/workspace/comparison.py run' in calls.read_text()


@pytest.mark.parametrize('args',[['all'],['baseline'],['run','--grid','15'],['preflight','--cap','400'],['run','--duration-s','30']])
def test_reject_legacy_and_parameter_overrides_before_docker(comparison_shell,args):
    _,calls,run=comparison_shell
    assert run(args).returncode==2
    assert not calls.exists()


@pytest.mark.parametrize('env,expected',[
    ({'MOCK_RUN_EXIT':'3'},3),({'MOCK_BUILD_EXIT':'12'},12),
    ({'MOCK_WRITE_IID':'no'},1),({'MOCK_IMAGE_ID':'stale'},1),
    ({'MOCK_ENDPOINT':'tcp://remote:2375'},1),({'MOCK_INFO_EXIT':'1'},1),
])
def test_errors_propagate_without_silent_fallback(comparison_shell,env,expected):
    _,calls,run=comparison_shell
    assert run(**env).returncode==expected
    if expected!=3:assert not any(' run ' in s for s in calls.read_text().splitlines())


def test_read_only_status_and_collection_do_not_need_docker(comparison_shell):
    root,calls,run=comparison_shell
    session=root/'comparison_runs/mock_session';session.mkdir(parents=True)
    save(session/'preflight.json',{'status':'failed','scope':'synthetic collector test'})
    save(root/'comparison_results/latest_attempt.json',{'session':'comparison_runs/mock_session'})
    (session/'fort.q0000').write_text('omit raw field')
    (session/'fort.t0000').write_text('0 time')
    assert run(['status']).returncode==0
    r=run(['collect']);assert r.returncode==0,r.stderr+r.stdout
    assert not calls.exists()
    zpath=next(root.glob('lituya-comparison-diagnostics-*.zip'))
    with zipfile.ZipFile(zpath) as z:
        assert 'experiment/fort.q0000' not in z.namelist()
        assert 'experiment/fort.t0000' in z.namelist()
        assert any('host_logs/' in s for s in z.namelist())


def test_collector_rejects_unsafe_path_and_missing_attempt(comparison_shell):
    root,calls,run=comparison_shell
    assert run(['collect']).returncode!=0
    save(root/'comparison_results/latest_attempt.json',{'session':'../../outside'})
    assert run(['collect']).returncode!=0
    assert not calls.exists()


def test_collector_symlink_refusal(comparison_shell):
    root,_,run=comparison_shell
    session=root/'comparison_runs/mock';session.mkdir(parents=True)
    outside=root/'outside.txt';outside.write_text('not part of run')
    (session/'solver.log').symlink_to(outside)
    save(root/'comparison_results/latest_attempt.json',{'session':'comparison_runs/mock'})
    assert run(['collect']).returncode!=0


def test_new_launcher_help_and_legacy_disabled_in_release_package():
    subprocess.run(['bash','-n',str(ROOT/'run_comparison.sh')],check=True)
    r=subprocess.run(['bash',str(ROOT/'run_comparison.sh'),'--help'],capture_output=True,text=True)
    assert r.returncode==0 and 'Default: preflight' in r.stdout
    r=subprocess.run(['bash',str(ROOT/'run.sh')],capture_output=True,text=True)
    assert r.returncode==2 and 'run_comparison.sh preflight' in r.stderr


def test_source_does_not_call_legacy_or_calibration():
    text=(ROOT/'simulation/cap_comparison.py').read_text()
    assert 'from calibration' not in text and 'import workflow' not in text
    assert 'run_cases(' not in text and 'seal_control(' not in text
