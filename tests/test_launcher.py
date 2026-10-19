from pathlib import Path
import os
import shutil
import subprocess

import pytest

from simulation.common import ROOT


def test_shell_syntax_and_help():
    subprocess.run(['bash','-n',str(ROOT/'run.sh')],check=True)
    run=subprocess.run(['bash',str(ROOT/'run.sh'),'--help'],text=True,capture_output=True)
    assert run.returncode==0 and 'nine source candidates' in run.stdout
    run=subprocess.run(['bash',str(ROOT/'run.sh'),'invalid'],text=True,capture_output=True)
    assert run.returncode==2


@pytest.fixture
def shell_fixture(tmp_path):
    root=tmp_path/'Project With Spaces';root.mkdir();shutil.copy2(ROOT/'run.sh',root/'run.sh')
    shutil.copy2(ROOT/'Dockerfile',root/'Dockerfile')
    bin_path=tmp_path/'bin';bin_path.mkdir();calls=tmp_path/'calls'
    commands={
        'uname':'#!/bin/sh\n[ "$1" = -s ] && echo "${MOCK_OS:-Darwin}" || echo "${MOCK_ARCH:-arm64}"\n',
        'sysctl':'#!/bin/sh\necho "${MOCK_TRANSLATED:-0}"\n',
        'open':'#!/bin/sh\nexit 0\n',
        'docker':'''#!/bin/sh
printf '%s\\n' "$*" >> "$CALLS"
[ "$1" = --context ] && shift 2
case "$1" in
 context)
   case "$*" in *--format*) echo "${MOCK_ENDPOINT:-unix:///unit/docker.sock}";; *) [ "${MOCK_DESKTOP:-yes}" = yes ] || exit 1;; esac ;;
 info) exit "${MOCK_INFO_EXIT:-0}";;
 image)
   [ "${MOCK_IMAGE:-yes}" = yes ] || exit 1
   case "$*" in
     *'{{.Id}}'*) printf '%s\\n' "${MOCK_IMAGE_ID:-sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa}";;
     *) echo "${MOCK_IMAGE_ARCH:-arm64}";;
   esac ;;
 build)
   [ "${MOCK_BUILD_EXIT:-0}" = 0 ] || exit "$MOCK_BUILD_EXIT"
   iidfile=
   while [ "$#" -gt 0 ]; do
     if [ "$1" = --iidfile ]; then iidfile="$2"; shift 2; else shift; fi
   done
   if [ "${MOCK_WRITE_IID:-yes}" = yes ] && [ -n "$iidfile" ]; then
     printf '%s\\n' "${MOCK_IMAGE_ID:-sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa}" > "$iidfile"
   fi
   exit 0 ;;

 run) exit "${MOCK_RUN_EXIT:-0}";;
 *) exit 99;;
esac
'''}
    for name,text in commands.items():
        path=bin_path/name;path.write_text(text);path.chmod(0o755)
    env=dict(os.environ,PATH=str(bin_path)+':'+os.environ['PATH'],CALLS=str(calls))
    # Avoid inheriting an image override from a developer machine.
    env.pop('LITUYA_IMAGE',None)
    def run(args=(),**extra):
        return subprocess.run(['bash',str(root/'run.sh'),'--no-open',*args],capture_output=True,text=True,env=dict(env,**extra))
    return root,calls,run


def test_native_mac_docker_command_and_spaced_path(shell_fixture):
    root,calls,run=shell_fixture
    result=run();assert result.returncode==0,result.stderr
    text=calls.read_text()
    assert '--platform linux/arm64' in text and str(root)+':/workspace' in text
    assert '--network none' in text and '--cap-drop ALL' in text
    assert '/var/run/docker.sock:/var/run/docker.sock' not in text


@pytest.mark.parametrize('extra,expected',[
    ({'MOCK_RUN_EXIT':'7'},7),({'MOCK_OS':'Windows'},2),({'MOCK_ARCH':'mips'},2),
    ({'MOCK_ENDPOINT':'tcp://remote:2375'},1),({'MOCK_INFO_EXIT':'1'},1),
    ({'MOCK_IMAGE':'no','MOCK_BUILD_EXIT':'6'},6),
    ({'LITUYA_IMAGE':'missing-image','MOCK_IMAGE':'no'},1),
])
def test_launcher_failure_propagation(shell_fixture,extra,expected):
    _,_,run=shell_fixture
    assert run(**extra).returncode==expected


@pytest.mark.parametrize('extra',[
    {'MOCK_ARCH':'x86_64','MOCK_TRANSLATED':'1'},
    {'MOCK_OS':'Linux','MOCK_ARCH':'aarch64','MOCK_DESKTOP':'no'},
    {'MOCK_OS':'Linux','MOCK_ARCH':'x86_64','MOCK_IMAGE_ARCH':'amd64'},
])
def test_architecture_and_context_routing(shell_fixture,extra):
    _,calls,run=shell_fixture
    result=run(**extra);assert result.returncode==0,result.stderr
    if extra.get('MOCK_DESKTOP')=='no':assert '--context default' in calls.read_text()


def test_test_action_builds_dependency_only_target(shell_fixture):
    _,calls,run=shell_fixture
    result=run(['test'],MOCK_IMAGE='no');assert result.returncode==0,result.stderr
    assert '--target tests' in calls.read_text()


def test_local_mode_propagates_python_exit(tmp_path,shell_fixture):
    _,calls,run=shell_fixture
    fake=tmp_path/'fake-python';fake.write_text('#!/bin/sh\nexit 9\n');fake.chmod(0o755)
    result=run(['--local','test'],PYTHON=str(fake))
    assert result.returncode==9
    assert not calls.exists()


def test_existing_tag_is_not_treated_as_current_dockerfile(shell_fixture):
    """Regression: the earlier launcher skipped building when the tag existed."""
    root, calls, run = shell_fixture
    result = run(MOCK_IMAGE='yes', MOCK_IMAGE_ARCH='arm64')
    assert result.returncode == 0, result.stderr
    commands = calls.read_text().splitlines()
    build = next(i for i, c in enumerate(commands) if ' build ' in c)
    launch = next(i for i, c in enumerate(commands) if ' run ' in c)
    assert build < launch
    assert '--iidfile ' in commands[build]
    assert 'Project folder: ' + str(root) in result.stdout
    assert '--entrypoint python sha256:' in commands[launch]
    assert 'lituya-bay:runtime-2.0.0-arm64 -u' not in commands[launch]


def test_changed_dockerfile_is_submitted_on_next_invocation(shell_fixture):
    root, calls, run = shell_fixture
    assert run().returncode == 0
    with (root / 'Dockerfile').open('a') as stream:
        stream.write('\n# changed build instruction for routing test\n')
    assert run().returncode == 0
    commands = calls.read_text().splitlines()
    assert sum(' build ' in c for c in commands) == 2
    assert sum(' run ' in c for c in commands) == 2


def test_failed_rebuild_never_falls_back_to_old_image(shell_fixture):
    _, calls, run = shell_fixture
    result = run(MOCK_IMAGE='yes', MOCK_BUILD_EXIT='23')
    assert result.returncode == 23
    assert not any(' run ' in c for c in calls.read_text().splitlines())


@pytest.mark.parametrize('extra', [
    {'MOCK_WRITE_IID': 'no'},
    {'MOCK_IMAGE_ID': 'lituya-bay:stale'},
    {'MOCK_IMAGE_ID': 'sha256:123'},
])
def test_invalid_build_id_stops_before_container_run(shell_fixture, extra):
    _, calls, run = shell_fixture
    result = run(**extra)
    assert result.returncode == 1
    assert not any(' run ' in c for c in calls.read_text().splitlines())


def test_force_build_flag_remains_compatible(shell_fixture):
    _, calls, run = shell_fixture
    result = run(['--build', 'check'])
    assert result.returncode == 0, result.stderr
    text = calls.read_text()
    assert '--target runtime' in text and 'workflow.py check' in text


def test_custom_image_is_pinned_by_id_without_rebuilding(shell_fixture):
    _, calls, run = shell_fixture
    result = run(['check'], LITUYA_IMAGE='explicit-user-image')
    assert result.returncode == 0, result.stderr
    commands = calls.read_text().splitlines()
    assert not any(' build ' in c for c in commands)
    assert any('--entrypoint python sha256:' in c for c in commands)


@pytest.mark.parametrize('args,extra', [
    (['--build'], {}),
    ([], {'MOCK_IMAGE_ARCH': 'amd64'}),
    ([], {'MOCK_IMAGE_ID': 'invalid'}),
])
def test_custom_image_rejection_does_not_run_or_rebuild(shell_fixture, args, extra):
    _, calls, run = shell_fixture
    result = run(args, LITUYA_IMAGE='explicit-user-image', **extra)
    assert result.returncode == 1
    commands = calls.read_text().splitlines()
    assert not any(' build ' in c or ' run ' in c for c in commands)


def test_dockerfile_keeps_native_library_and_nonroot_manifest_gate():
    """Recipe assertion only; this is not an actual Docker build."""
    text = (ROOT / 'Dockerfile').read_text()
    assert 'libexpat1' in text
    created = text.index('python -m tools.image_manifest')
    chmod = text.index('chmod 0644 /opt/lituya-build-manifest.json /opt/lituya-smoke.json')
    user = text.index('USER 1000:1000')
    check = text.index('Non-root solver access check passed.')
    assert created < chmod < user < check
