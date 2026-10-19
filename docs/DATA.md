# Reference data

This repository does not include the seven files listed in
`required_private_inputs.json`. Their SHA-256 hashes identify the exact inputs
used in the completed comparison. The code license does not grant rights to
redistribute the original reconstruction or its derived geometry.

Original source: Franco et al. (2020), DOI
https://doi.org/10.5194/nhess-20-2255-2020; reconstruction record:
https://doi.org/10.5281/zenodo.3831448.

Review the dataset's component terms before obtaining or redistributing it.
`tools/rebuild_reference.py` checks the original archive hash and resamples its
STL meshes, but only produces `mesh_surfaces_15m.npz` and `mesh_sampling.json`.
It does not recover the other five metadata/source files. This is not a complete
public input-acquisition pipeline.

For an authorized local checkout that already has the reviewed inputs, restore
them under `data/reference/`, following the paths in the checksum manifest.
Then run:

```sh
python -m pytest --with-reference-data --cov-fail-under=90
```

This command fails before test execution if any required file is missing or
has the wrong hash. It prepares inputs for tests but starts no water solver.
Reference files are excluded by `.gitignore` and `.dockerignore`.

Raw production fields, prepared terrain, machine-local logs, claims, the
one-time recovery launcher, and research drafts remain in the private local
project. The small published results are records of that run, not a replacement
for those full inputs and outputs.
