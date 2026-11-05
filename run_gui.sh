#!/usr/bin/env bash
# =============================================================================
# run_gui.sh - Launch Stark Industries Holographic HUD (Jarvis v3)
# =============================================================================
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
cd "$DIR" || exit 1

export DISPLAY="${DISPLAY:-:0.0}"

# Strictly limit CPU thread usage to 4 threads
export OMP_NUM_THREADS=4
export MKL_NUM_THREADS=4
export OPENBLAS_NUM_THREADS=4
export NUMEXPR_NUM_THREADS=4
export VECLIB_MAXIMUM_THREADS=4

# Suppress GNOME desktop portal DBus warning
export QT_LOGGING_RULES="qt.qpa.theme*=false;qt.qpa.portal*=false"
export QT_QPA_PLATFORMTHEME=""

python3 Jarvis_v3.py
