# Real local preflight input-deck regression fixture

These are the unmodified generated `.data` files and matching configs from
`lituya-comparison-diagnostics-20261018T220415Z_311490f7-605c29.zip`.
The local preflight failed on an overly strict cap-padding comparison before
any Lituya water integration. The fixture preserves the actual Clawpack
v5.14.0 output formatting, both fgmax point lists, and setup metadata.

This fixture is input-deck evidence, NOT water-simulation results. Tests
replay settings verification without invoking a solver or changing inputs.

`generated_decks.fixture` is a ZIP container with a non-`.zip` extension so
the project's archive exclusions do not remove this fixture from Docker builds.
