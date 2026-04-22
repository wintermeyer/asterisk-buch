#!/usr/bin/env bash
set -euo pipefail

# Deploy script intended for a self-hosted Antora runner.
# Mirrors the ruby-book deployment pattern: atomic symlink swap under
# /var/www/asterisk-buch/releases/<timestamp>/, served at /asterisk/book/.

# Activate mise so node / npm / npx resolve on the non-interactive shell
# GitHub Actions spawns. `mise activate` only wires the shim dir via a
# precmd hook that never fires here, so prepend the shim dir to PATH
# directly.
if command -v mise >/dev/null 2>&1; then
  eval "$(mise activate bash)"
elif [ -x "$HOME/.local/bin/mise" ]; then
  eval "$("$HOME/.local/bin/mise" activate bash)"
fi
export PATH="${HOME}/.local/share/mise/shims:${PATH}"

cd "$(dirname "$0")/.."

npm install
npx antora --fetch antora-playbook.yml

TS="$(date +%Y%m%d%H%M%S)"
RELEASES="/var/www/asterisk-buch/releases"
TARGET="${RELEASES}/${TS}"
LINK="/var/www/asterisk-buch/current"

mkdir -p "${TARGET}"
cp -r build/site/. "${TARGET}/"

# Pre-compress text assets so nginx can serve .br / .gz siblings
# directly via brotli_static / gzip_static with zero CPU per request.
# Drop any sibling that did not actually shrink the payload.
echo "[deploy] Pre-compressing text assets..."
_jobs="$(nproc 2>/dev/null || echo 4)"
_text=( -name '*.html' -o -name '*.css' -o -name '*.js' -o -name '*.mjs'
        -o -name '*.svg' -o -name '*.json' -o -name '*.xml'
        -o -name '*.txt' -o -name '*.map' )
if command -v brotli >/dev/null 2>&1; then
  find "${TARGET}" -type f \( "${_text[@]}" \) -print0 \
    | xargs -0 -r -n 8 -P "${_jobs}" brotli -k -q 11 -f --
else
  echo "[deploy] WARN: brotli not installed; skipping .br siblings"
fi
find "${TARGET}" -type f \( "${_text[@]}" \) -print0 \
  | xargs -0 -r -n 8 -P "${_jobs}" gzip -k -9 -n -f --
find "${TARGET}" -type f \( -name '*.br' -o -name '*.gz' \) -print0 \
  | while IFS= read -r -d '' _c; do
      _o="${_c%.*}"
      [ -f "${_o}" ] || continue
      _cs=$(stat -c%s "${_c}" 2>/dev/null || echo 0)
      _os=$(stat -c%s "${_o}" 2>/dev/null || echo 1)
      [ "${_cs}" -ge "${_os}" ] && rm -f "${_c}"
    done

ln -sfn "${TARGET}" "${LINK}.new"
mv -Tf "${LINK}.new" "${LINK}"

# Keep the last five releases only.
ls -1dt "${RELEASES}"/*/ 2>/dev/null | tail -n +6 | xargs -r rm -rf
