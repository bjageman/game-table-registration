#!/usr/bin/env bash
set -euo pipefail
case "${1:-}" in
  dev) branch=dev ;;
  prod) branch=main ;;
  *) echo "Usage: $0 dev|prod" >&2; exit 2 ;;
esac
environment=$1
repo=${DEPLOY_REPO:-$(cd "$(dirname "$0")/.." && pwd)}
exec 9>"$repo/.git/deploy.lock"
flock 9
env_file="$repo/.env.$environment"
test -f "$env_file" || { echo "Missing $env_file" >&2; exit 1; }
export DOCKER_HOST="${DOCKER_HOST:-unix:///tank/services/docker.sock}"
git -C "$repo" fetch origin "$branch"
revision=$(git -C "$repo" rev-parse FETCH_HEAD)
build_dir=$(mktemp -d "/tmp/game-table-registration-$environment.XXXXXX")
trap 'rm -rf "$build_dir"' EXIT
git -C "$repo" archive "$revision" | tar -x -C "$build_dir"
export APP_ENV_FILE="$env_file"
compose=(docker compose --env-file "$env_file" --project-directory "$build_dir" -f "$build_dir/docker-compose.$environment.yml")
"${compose[@]}" config --quiet
"${compose[@]}" build --pull
"${compose[@]}" up -d --wait db
"${compose[@]}" run --rm -T --interactive=false migrate
"${compose[@]}" up -d --no-deps --wait --wait-timeout 180 api web
printf 'Deployed %s (%s)\n' "$environment" "$revision"
