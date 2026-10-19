#!/usr/bin/env bash
# macOS only: make torch use the conda env's OpenMP runtime instead of its
# own bundled copy.
#
# On macOS, conda-forge numpy (OpenBLAS) loads the env's llvm-openmp
# lib/libomp.dylib and pip torch loads torch/lib/libomp.dylib. Two OpenMP
# runtimes in one process segfault on the first YOLO inference, and
# KMP_DUPLICATE_LIB_OK only hides the error. This replaces torch's copy
# with a symlink to the env's, keeping the original as libomp.dylib.bak.
#
# Changes only the active local env; environment.yml and Windows are
# unaffected. Re-run after reinstalling/upgrading torch. Safe to re-run.
#
#   conda activate esp32-robot-autonomy
#   bash autonomy/macos_fix_openmp.sh

set -euo pipefail

if [[ "$(uname)" != "Darwin" ]]; then
  echo "not macOS, nothing to do"
  exit 0
fi
if [[ -z "${CONDA_PREFIX:-}" ]]; then
  echo "activate the conda env first (conda activate esp32-robot-autonomy)" >&2
  exit 1
fi

env_omp="$CONDA_PREFIX/lib/libomp.dylib"
torch_lib="$(python -c 'import os, importlib.util as u; print(os.path.join(os.path.dirname(u.find_spec("torch").origin), "lib"))')"
torch_omp="$torch_lib/libomp.dylib"

if [[ ! -e "$env_omp" ]]; then
  echo "no $env_omp in this env, nothing to link to" >&2
  exit 1
fi
if [[ -L "$torch_omp" && "$(readlink "$torch_omp")" == "$env_omp" ]]; then
  echo "already fixed: $torch_omp -> $env_omp"
  exit 0
fi
if [[ -f "$torch_omp" && ! -L "$torch_omp" ]]; then
  mv "$torch_omp" "$torch_omp.bak"
fi
ln -sf "$env_omp" "$torch_omp"
echo "linked $torch_omp -> $env_omp"
