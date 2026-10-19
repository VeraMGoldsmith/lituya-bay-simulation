# Standard GeoClaw v5.14.0 solver; source motion is supplied through dtopo.
.DEFAULT_GOAL := .exe
ifndef CLAW
$(error CLAW is not set. Start this project with bash run.sh)
endif
CLAWMAKE = $(CLAW)/clawutil/src/Makefile.common
CLAW_PKG = geoclaw
EXE = xgeoclaw
SETRUN_FILE = setrun.py
OUTDIR = _output
FC = gfortran
FFLAGS ?= -O2
GEOLIB = $(CLAW)/geoclaw/src/2d/shallow
include $(GEOLIB)/Makefile.geoclaw
EXCLUDE_MODULES =
EXCLUDE_SOURCES =
MODULES =
SOURCES = $(CLAW)/riemann/src/rpn2_geoclaw.f \
          $(CLAW)/riemann/src/rpt2_geoclaw.f \
          $(CLAW)/riemann/src/geoclaw_riemann_utils.f
include $(CLAWMAKE)
