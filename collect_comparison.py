"""Standard-library-only Mac collector/status viewer. Never imports GeoClaw."""
from pathlib import Path
import argparse
import json
import uuid
import zipfile


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('action',choices=['collect','status'])
    args=p.parse_args(argv)
    root=Path(__file__).resolve().parent
    pointer=root/'comparison_results/latest_attempt.json'
    if not pointer.is_file():
        raise SystemExit('No comparison attempt exists yet. Preserve comparison_logs for build failures.')
    rel=Path(json.loads(pointer.read_text())['session'])
    session=(root/rel).resolve()
    if rel.is_absolute() or '..' in rel.parts or not session.is_relative_to(root/'comparison_runs'):
        raise SystemExit('Unsafe saved comparison path.')
    if args.action=='status':
        for name in ['preflight.json','experiment.json','comparison_summary.json']:
            f=session/name
            if f.is_file():print(name+'\n'+f.read_text())
        return
    out=root/f'lituya-comparison-diagnostics-{session.name}-{uuid.uuid4().hex[:6]}.zip'
    manifest={'included':[],'omitted':[],'session':str(rel)}
    with zipfile.ZipFile(out,'x',compression=zipfile.ZIP_DEFLATED) as z:
        for f in sorted(session.rglob('*')):
            if f.is_symlink():raise SystemExit('Collector refuses symlinked files.')
            if not f.is_file():continue
            name=f.relative_to(session).as_posix()
            keep=(f.suffix in {'.json','.csv','.data','.html'} or
                  f.name in {'fort.amr','solver.log','synthetic_smoke.log'} or
                  (f.name.startswith(('fgmax','gauge','fort.t')) and f.suffix!='.npz'))
            if keep and f.stat().st_size<=20*1024*1024:
                z.write(f,'experiment/'+name);manifest['included'].append(name)
            else:manifest['omitted'].append({'path':name,'size_bytes':f.stat().st_size})
        # Shell/build logs are useful even when solver startup failed.
        for f in sorted((root/'comparison_logs').glob('*')):
            if f.is_file() and not f.is_symlink() and f.stat().st_size<=20*1024*1024:
                z.write(f,'host_logs/'+f.name)
        z.writestr('manifest.json',json.dumps(manifest,indent=2))
    print(out)


if __name__=='__main__':
    main()
