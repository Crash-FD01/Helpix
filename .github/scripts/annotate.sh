#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Crash
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Esegue un comando; se fallisce, ne mette le ultime righe in un'annotazione di errore, visibile nel riepilogo
# dell'esecuzione (e dall'API) senza aprire il log completo.
#   .github/scripts/annotate.sh "Titolo" comando [argomenti…]
set -uo pipefail
title="$1"; shift
log="$(mktemp)"
"$@" 2>&1 | tee "$log"
rc="${PIPESTATUS[0]}"
if (( rc != 0 )); then
    msg="$(grep -v "gpu_channel_manager\|socket_manager.cc\|QRhi\|RHI for\|Permissions-Policy\|WebGPU" "$log" \
           | tail -n 40 | sed 's/%/%25/g; s/\r/%0D/g' | sed ':a;N;$!ba;s/\n/%0A/g')"
    echo "::error title=$title::$msg"
fi
rm -f "$log"
exit "$rc"
