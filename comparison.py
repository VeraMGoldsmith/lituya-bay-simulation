"""Release-only entry point. Never imports or executes the calibration workflow."""
from simulation.cap_comparison import main

if __name__ == '__main__':
    raise SystemExit(main())
