#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Crash
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Esegue tutti i test (ognuno in un processo separato: QtWebEngine non si può riavviare nello stesso processo).
#   tests/run_all.sh [python]        es. tests/run_all.sh ~/.local/share/helpix/venv/bin/python
# Senza display usa la piattaforma «offscreen»; i test dei desktop girano in una sessione D-Bus privata.
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1
PY="${1:-python3}"
export QT_QPA_PLATFORM="${QT_QPA_PLATFORM:-offscreen}" QTWEBENGINE_DISABLE_SANDBOX=1 PYTHONDONTWRITEBYTECODE=1
export QTWEBENGINE_CHROMIUM_FLAGS="${QTWEBENGINE_CHROMIUM_FLAGS:---disable-gpu}"
failed=()
for t in tests/test_*.py; do
    wrap=()
    if [[ "$t" == tests/test_desktops.py ]] && command -v dbus-run-session >/dev/null; then
        wrap=(dbus-run-session --)
    fi
    start=$SECONDS
    if out="$(timeout "${TEST_TIMEOUT:-300}" "${wrap[@]}" "$PY" "$t" 2>&1)"; then
        printf '  ok    %-28s %3ss\n' "$t" "$((SECONDS - start))"
    else
        printf '  FAIL  %-28s %3ss\n' "$t" "$((SECONDS - start))"
        printf '%s\n' "$out" | tail -40 | sed 's/^/        /'
        failed+=("$t")
        if [[ "${GITHUB_ACTIONS:-}" == true ]]; then  # un'annotazione per test fallito (visibile anche dall'API)
            level=error; (( ${#failed[@]} > 10 )) && level=warning
            msg="$(printf '%s\n' "$out" | grep -v "gpu_channel_manager\|QRhi\|RHI for" | tail -n 25 \
                   | sed 's/%/%25/g; s/\r/%0D/g' | sed ':a;N;$!ba;s/\n/%0A/g')"
            echo "::$level title=$t::$msg"
        fi
    fi
done
if (( ${#failed[@]} )); then
    echo "Test falliti: ${failed[*]}"; exit 1
fi
echo "Tutti i test superati."
