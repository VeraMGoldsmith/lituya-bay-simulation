#!/usr/bin/env python3
"""Host launcher for the fixed existing image; never builds or pulls images."""
import argparse
import json
from pathlib import Path
import subprocess

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('action',choices=['preflight','run','check','report','tests'])
    p.add_argument('--private-root',type=Path,required=True,help='Original Lituya_Cap_Comparison folder containing data/reference and comparison_runs')
    p.add_argument('--session',type=Path,required=True,help='Separate private experiment output directory')
    p.add_argument('--grid',choices=['original','fine'])
    p.add_argument('--case')
    a=p.parse_args();protocol=json.loads((HERE/'protocol.json').read_text())
    private=a.private_root.resolve();session=a.session.resolve()
    archive=private/protocol['archived_session']
    if session==archive or session.is_relative_to(archive) or archive.is_relative_to(session):
        p.error('New outputs must be separate from the original archive')
    if session.is_relative_to(ROOT):p.error('Keep raw experiment output outside the publication checkout')
    if not archive.is_dir() or not (private/'data/reference').is_dir():p.error('Original archive/reference directories unavailable')
    # Empty mount point only; reference bytes remain outside the public checkout.
    (ROOT/'data/reference').mkdir(parents=True,exist_ok=True)
    session.mkdir(parents=True,exist_ok=True)
    image=protocol['runtime_image']
    actual=subprocess.check_output(['docker','image','inspect',image,'--format','{{.Id}}'],text=True).strip()
    if actual!=image:p.error('Docker image identity differs')
    cmd=['docker','run','--rm','--pull','never','--network','none','--read-only','--tmpfs','/tmp:rw,exec,nosuid',
         '-e','PYTHONDONTWRITEBYTECODE=1','-e','LITUYA_RUN_IMAGE_ID='+image,
         '--mount',f'type=bind,source={ROOT},target=/repo,readonly',
         '--mount',f'type=bind,source={private/"data/reference"},target=/repo/data/reference,readonly',
         '--mount',f'type=bind,source={archive},target=/archive,readonly',
         '--mount',f'type=bind,source={session},target=/session'+(',readonly' if a.action in ('check','report','tests') else ''),
         '--workdir','/repo','--entrypoint','python']
    if a.action=='report':
        cmd+=['--mount',f'type=bind,source={HERE},target=/report']
    cmd += [image,'-B']
    if a.action=='tests':
        cmd += ['-m','unittest','discover','-s','experiments/speed-limit-grid-resolution','-p','test_*.py','-v']
    elif a.action=='report':cmd+=['experiments/speed-limit-grid-resolution/report.py','--session','/session','--output','/report']
    else:
        cmd+=['experiments/speed-limit-grid-resolution/experiment.py',a.action]
        if a.grid:cmd+=['--grid',a.grid]
        if a.case:cmd+=['--case',a.case]
    print(' '.join(cmd),flush=True)
    raise SystemExit(subprocess.call(cmd))


if __name__=='__main__':main()
