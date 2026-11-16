#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd -P)"

usage() {
  cat <<'EOF'
Usage: scripts/create-hermes-profile.sh <role> [options]

Create a Hermes Agent profile from role/<name>. The profile name defaults to
the role name. Skills listed in role/<name>/SKILLS.md are copied from origin/.

Options:
  --name NAME          Hermes profile name (default: role name)
  --description TEXT   Override the profile description
  --no-alias           Do not create a command alias for the profile
  --dry-run            Print the resolved plan without changing anything
  -h, --help           Show this help

Environment:
  HERMES_BIN           Hermes executable (default: hermes)
  HERMES_HOME          Hermes home used by the Hermes CLI
EOF
}

die() {
  printf 'error: %s\n' "$*" >&2
  exit 1
}

role_input=""
profile_name=""
description=""
create_alias=true
dry_run=false

while (($# > 0)); do
  case "$1" in
    --name)
      (($# >= 2)) || die "--name requires a value"
      profile_name="$2"
      shift 2
      ;;
    --description)
      (($# >= 2)) || die "--description requires a value"
      description="$2"
      shift 2
      ;;
    --no-alias)
      create_alias=false
      shift
      ;;
    --dry-run)
      dry_run=true
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    -*)
      die "unknown option: $1"
      ;;
    *)
      [[ -z "$role_input" ]] || die "only one role may be specified"
      role_input="$1"
      shift
      ;;
  esac
done

[[ -n "$role_input" ]] || {
  usage >&2
  exit 2
}

if [[ "$role_input" == */* ]]; then
  role_dir="$role_input"
else
  role_dir="$REPO_ROOT/role/$role_input"
fi
role_dir="$(cd "$role_dir" 2>/dev/null && pwd -P)" || die "role not found: $role_input"
role_name="$(basename "$role_dir")"

[[ -f "$role_dir/PERSONA.md" ]] || die "missing PERSONA.md in $role_dir"
[[ -f "$role_dir/SKILLS.md" ]] || die "missing SKILLS.md in $role_dir"

if [[ -f "$role_dir/USAGE.md" ]]; then
  has_usage=true
else
  has_usage=false
fi

if [[ -z "$profile_name" ]]; then
  profile_name="$role_name"
fi
profile_name="$(printf '%s' "$profile_name" | tr '[:upper:]' '[:lower:]')"
[[ "$profile_name" =~ ^[a-z0-9][a-z0-9_-]*$ ]] ||
  die "invalid Hermes profile name: $profile_name"

if [[ -z "$description" ]]; then
  description="$(
    awk '
      /^# / { next }
      /^## / { exit }
      /^[[:space:]]*$/ { next }
      { print; exit }
    ' "$role_dir/PERSONA.md"
  )"
fi
description="${description:-Role profile generated from $role_dir}"

hermes_home="${HERMES_HOME:-$HOME/.hermes}"
hermes_home="${hermes_home/#\~/$HOME}"
hermes_root="$hermes_home"
if [[ "$(basename "$(dirname "$hermes_root")")" == "profiles" ]]; then
  hermes_root="$(dirname "$(dirname "$hermes_root")")"
fi
profile_dir="$hermes_root/profiles/$profile_name"
hermes_bin="${HERMES_BIN:-hermes}"

skill_sources=()
skill_names=()
while IFS= read -r source; do
  [[ -n "$source" ]] || continue

  if [[ "$source" == /* ]]; then
    resolved_source="$source"
  else
    resolved_source="$role_dir/$source"
  fi
  resolved_source="$(cd "$resolved_source" 2>/dev/null && pwd -P)" ||
    die "indexed skill source not found: $source"
  [[ -f "$resolved_source/SKILL.md" ]] ||
    die "indexed skill has no SKILL.md: $source"

  case "$resolved_source" in
    "$REPO_ROOT"/origin/*) ;;
    *) die "skill source must stay under origin/: $source" ;;
  esac

  skill_name="$(basename "$resolved_source")"
  if ((${#skill_sources[@]} > 0)); then
    for existing_source in "${skill_sources[@]}"; do
      [[ "$existing_source" != "$resolved_source" ]] ||
        die "duplicate skill in index: $source"
    done
  fi
  skill_sources+=("$resolved_source")
  skill_names+=("$skill_name")
done < <(
  sed -nE 's/^- \[[^]]+\]\(([^)]+)\).*/\1/p' "$role_dir/SKILLS.md"
)

((${#skill_sources[@]} > 0)) || die "no skills indexed in $role_dir/SKILLS.md"

if [[ "$dry_run" != true ]]; then
  [[ ! -e "$profile_dir" ]] ||
    die "Hermes profile already exists: $profile_dir"
  command -v "$hermes_bin" >/dev/null 2>&1 ||
    die "Hermes executable not found: $hermes_bin"
fi

printf 'Role:          %s\n' "$role_name"
printf 'Profile:       %s\n' "$profile_name"
printf 'Profile home:  %s\n' "$profile_dir"
printf 'Skill count:   %d\n' "${#skill_sources[@]}"
printf 'Description:   %s\n' "$description"

if [[ "$dry_run" == true ]]; then
  printf '\nHermes command:\n'
  printf '  %q profile create %q --no-skills --description %q' \
    "$hermes_bin" "$profile_name" "$description"
  if [[ "$create_alias" == false ]]; then
    printf ' --no-alias'
  fi
  printf '\n\nSkills:\n'
  for i in "${!skill_sources[@]}"; do
    printf '  %-42s <- %s\n' "${skill_names[$i]}" "${skill_sources[$i]}"
  done
  printf '\nSOUL.md: %s' "$role_dir/PERSONA.md"
  if [[ "$has_usage" == true ]]; then
    printf ' + %s' "$role_dir/USAGE.md"
  fi
  printf '\n'
  exit 0
fi

hermes_args=(profile create "$profile_name" --no-skills --description "$description")
if [[ "$create_alias" == false ]]; then
  hermes_args+=(--no-alias)
fi

"$hermes_bin" "${hermes_args[@]}"

[[ -d "$profile_dir/skills" ]] ||
  die "Hermes created the profile but its skills directory is missing: $profile_dir/skills"

cp "$role_dir/PERSONA.md" "$profile_dir/SOUL.md"
if [[ "$has_usage" == true ]]; then
  printf '\n\n---\n\n' >>"$profile_dir/SOUL.md"
  cat "$role_dir/USAGE.md" >>"$profile_dir/SOUL.md"
fi

for source in "${skill_sources[@]}"; do
  cp -R "$source" "$profile_dir/skills/"
done

printf '\nProfile created: %s\n' "$profile_dir"
if [[ "$create_alias" == true ]]; then
  printf 'Configure credentials with: %s setup\n' "$profile_name"
  printf 'Start chatting with:       %s chat\n' "$profile_name"
else
  printf 'Configure credentials with: hermes -p %s setup\n' "$profile_name"
  printf 'Start chatting with:       hermes -p %s chat\n' "$profile_name"
fi
