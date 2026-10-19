# Third-party attribution and licensing boundaries

## Published scientific data
The raw reconstruction was uploaded by the user and checked against the public
Zenodo record. The geometry grids in data/reference and derived input files are
adapted from that reconstruction. Attribute:
Franco et al. (2020), “The 1958 Lituya Bay tsunami – pre-event bathymetry
reconstruction and 3D numerical modelling utilising the computational fluid
dynamics software Flow-3D”, Natural Hazards and Earth System Sciences 20, 2255–2279.
https://nhess.copernicus.org/articles/20/2255/2020/
Dataset: https://zenodo.org/records/3831448

The project does not assign a new license to the original model documents,
original data, or geometry derived from them. The archive’s licensing terms must
be checked with the authors/record before public redistribution. A public download
by itself is not a declaration that every component has an open-source license.
No FLOW-3D executable or source code is supplied. Original configuration text is
retained as source evidence, not executable code for this solver.

## GeoClaw / Clawpack
Obtained at build time from the official Clawpack repositories, release v5.14.0.
The project’s Fortran build recipe is adapted from the existing supplied Clawpack
starter. Clawpack’s own license applies to its code; it is not relicensed here.
https://github.com/clawpack/clawpack

## New glue code
New launcher, preparation, inspection, orchestration and plotting glue authored
for this project may be used under the MIT License below. This grant does not
extend to the third-party scientific data or third-party software above.

MIT License
Copyright (c) 2026 the project contributors

Permission is hereby granted, free of charge, to any person obtaining a copy of
this software and associated documentation files (the “Software”), to deal in the
Software without restriction, including without limitation the rights to use,
copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the
Software, and to permit persons to whom the Software is furnished to do so,
subject to the following conditions:
The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.
THE SOFTWARE IS PROVIDED “AS IS”, WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

## This source distribution

The seven reference assets listed in `required_private_inputs.json` are omitted.
The reference meshes, sampled terrain, original model documents, and full raw
simulation outputs are not bundled. See `docs/DATA.md` for acquisition limits.
Small project-generated result summaries and solver-input regression fixtures
are included. No third-party solver executable is included.
