#!/bin/sh
set -eu

fail() {
  printf '%s\n' "$1" >&2
  exit 1
}

case ${1-} in
  staged|history) [ "$#" -eq 1 ] || fail 'Usage: check-secrets.sh staged|history' ;;
  *) fail 'Usage: check-secrets.sh staged|history' ;;
esac

for tool in git python3 gitleaks; do
  command -v "$tool" >/dev/null 2>&1 || fail "Security check requires $tool."
done

script_dir=$(CDPATH='' cd -- "$(dirname -- "$0")" 2>/dev/null && pwd -P) || fail 'Security policy directory is unavailable.'
config="$script_dir/../.gitleaks.toml"
[ -f "$config" ] || fail 'Gitleaks policy is unavailable.'
path_checker="$script_dir/check-sensitive-paths.py"
[ -f "$path_checker" ] || fail 'Sensitive filename policy is unavailable.'

export GIT_NO_REPLACE_OBJECTS=1
repo_root=$(git rev-parse --show-toplevel 2>/dev/null) || fail 'Security check requires a Git worktree.'
cd -- "$repo_root" 2>/dev/null || fail 'Security check cannot enter the Git worktree.'

scan() {
  status=0
  gitleaks "$@" --config "$config" --redact=100 --no-banner \
    --ignore-gitleaks-allow --gitleaks-ignore-path /dev/null --exit-code 42 \
    >/dev/null 2>&1 || status=$?
  case $status in
    0) ;;
    42) fail 'Security check blocked potential credentials or local paths.' ;;
    *) fail 'Security check could not complete the Gitleaks scan.' ;;
  esac
}

if [ "$1" = staged ]; then
  snapshot=$(mktemp -d "${TMPDIR:-/tmp}/skill-loop-secret-scan.XXXXXXXX" 2>/dev/null) || fail 'Cannot create a private scan directory.'
  trap 'rm -rf -- "$snapshot"' 0
  trap 'exit 1' HUP INT TERM
  python3 "$path_checker" staged "$snapshot"
  scan dir "$snapshot"
else
  shallow=$(git rev-parse --is-shallow-repository 2>/dev/null) || fail 'Cannot determine whether Git history is complete.'
  [ "$shallow" = false ] || fail 'History scan requires a non-shallow Git checkout.'
  [ ! -e .gitleaksignore ] && [ ! -L .gitleaksignore ] || fail 'The scan target contains a disallowed Gitleaks ignore file.'
  python3 "$path_checker" history
  history_options='--full-history --root --diff-merges=first-parent --text --no-textconv --no-ext-diff --no-renames'
  scan git . --log-opts="$history_options --format=medium --no-color --no-show-signature HEAD"
fi

printf 'Security check passed (%s).\n' "$1"
