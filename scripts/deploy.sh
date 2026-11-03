#!/usr/bin/env bash
set -euo pipefail
case "${1:-}" in
  dev) branch=dev ;;
  prod) branch=main ;;
  *) echo "Usage: $0 dev|prod [brand]" >&2; exit 2 ;;
esac
environment=$1
brand=${2:-}
if (( $# > 2 )) || { [[ -n "$brand" ]] && [[ ! "$brand" =~ ^[a-z0-9]+(-[a-z0-9]+)*$ ]]; }; then
  echo "Brand must contain lowercase letters, digits, and single hyphens." >&2
  exit 2
fi
repo=${DEPLOY_REPO:-$(cd "$(dirname "$0")/.." && pwd)}
exec 9>"$repo/.git/deploy.lock"
flock 9
if [[ -n "$brand" ]]; then
  env_file="$repo/.env.$brand.$environment"
  export DEPLOY_PROJECT_NAME="game-table-registration-$brand-$environment"
  export DEPLOY_IMAGE_TAG="$brand-$environment"
  branding_dir="$repo/branding/$brand/$environment"
else
  env_file="$repo/.env.$environment"
  export DEPLOY_PROJECT_NAME="game-table-registration-$environment"
  export DEPLOY_IMAGE_TAG="$environment"
  branding_dir="$repo/branding/$environment"
fi
export DEPLOY_ENV="$environment"
test -f "$env_file" || { echo "Missing $env_file" >&2; exit 1; }
export DOCKER_HOST="${DOCKER_HOST:-unix:///tank/services/docker.sock}"
git -C "$repo" fetch origin "$branch"
revision=$(git -C "$repo" rev-parse FETCH_HEAD)
build_dir=$(mktemp -d "/tmp/game-table-registration-$environment.XXXXXX")
trap 'rm -rf "$build_dir"' EXIT
git -C "$repo" archive "$revision" | tar -x -C "$build_dir"
export APP_ENV_FILE="$env_file"
export BRANDING_CONFIG_DIR="${BRANDING_CONFIG_DIR:-$branding_dir}"
mkdir -p "$BRANDING_CONFIG_DIR/public"
compose=(docker compose --env-file "$env_file" --project-directory "$build_dir" -f "$build_dir/docker-compose.$environment.yml")
"${compose[@]}" config --quiet
"${compose[@]}" build --pull
"${compose[@]}" up -d --wait db
"${compose[@]}" run --rm -T --interactive=false migrate
"${compose[@]}" up -d --no-deps --wait --wait-timeout 180 api web
printf 'Deployed %s (%s)\n' "$environment" "$revision"
