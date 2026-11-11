#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Crash
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Prima di apt, sulle macchine Ubuntu di GitHub: mette in testa il primo mirror di Ubuntu che risponde davvero.
# Il mirror preimpostato (azure.archive.ubuntu.com) a volte resta irraggiungibile per ore («Temporary failure
# resolving …») e blocca la build dei pacchetti (2026-11-11, rilascio 0.19.8). I pacchetti sono firmati da
# Ubuntu e apt controlla la firma, quindi un mirror diverso non cambia cosa si installa.
#   sudo .github/scripts/apt-mirrors.sh
set -uo pipefail

arch="$(dpkg --print-architecture)"
suite="$(. /etc/os-release && echo "${VERSION_CODENAME}")"
if [ "$arch" = amd64 ] || [ "$arch" = i386 ]; then
  fallback=(http://azure.archive.ubuntu.com/ubuntu/ http://archive.ubuntu.com/ubuntu/
            https://mirrors.edge.kernel.org/ubuntu/ https://mirror.kumi.systems/ubuntu/)
else
  fallback=(http://azure.ports.ubuntu.com/ubuntu-ports/ http://ports.ubuntu.com/ubuntu-ports/
            https://mirror.kumi.systems/ubuntu-ports/ https://ftp.tu-chemnitz.de/pub/linux/ubuntu-ports/)
fi

# tentativi e tempi massimi: un mirror lento non deve fermare apt per minuti
cat > /etc/apt/apt.conf.d/80-helpix-ci <<'EOF'
Acquire::Retries "3";
Acquire::http::Timeout "20";
Acquire::https::Timeout "20";
EOF

ok() { curl -fsS --max-time 15 -o /dev/null "${1%/}/dists/$suite/Release"; }

# i mirror già configurati sulla macchina, poi quelli di riserva, senza doppioni
list=/etc/apt/apt-mirrors.txt
mapfile -t current < <(
  { [ -f "$list" ] && cut -f1 "$list"
    grep -hoE '^URIs: .*' /etc/apt/sources.list.d/*.sources 2>/dev/null | cut -d' ' -f2- | tr ' ' '\n'
  } | grep -E '^https?://' || true)
mapfile -t candidates < <(printf '%s\n' "${current[@]}" "${fallback[@]}" | sed 's#/*$#/#' | awk '!seen[$0]++')

good=()
for url in "${candidates[@]}"; do
  if ok "$url"; then good+=("$url"); echo "mirror raggiungibile: $url"; else echo "mirror irraggiungibile: $url"; fi
done
if [ "${#good[@]}" -eq 0 ]; then
  echo "::warning::Nessun mirror di Ubuntu raggiungibile: lascio la configurazione com'è"
  exit 0
fi

if [ -f "$list" ]; then
  # la lista che apt usa con «mirror+file:»: i raggiungibili, nell'ordine, con la priorità
  : > "$list"
  n=1
  for url in "${good[@]}"; do printf '%s\tpriority:%d\n' "$url" "$n" >> "$list"; n=$((n + 1)); done
else
  # niente lista di mirror: si cambia l'indirizzo nelle sorgenti deb822 di Ubuntu, solo se quello attuale non risponde
  f=/etc/apt/sources.list.d/ubuntu.sources
  if [ -f "$f" ]; then
    for url in "${current[@]}"; do
      case " ${good[*]} " in *" ${url%/}/ "*) continue ;; esac
      sed -i "s#${url%/}/*#${good[0]}#g" "$f"
      echo "sostituito $url con ${good[0]} in $f"
    done
  fi
fi
echo "::notice::Mirror di Ubuntu per apt: ${good[0]}"
