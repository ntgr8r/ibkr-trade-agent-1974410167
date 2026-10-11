#!/usr/bin/env python3
"""Install a self-removing, 24-hour IBKR Show recovery sudo bridge."""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

POLICY = Path("/etc/sudoers.d/codex-ibkr-show-ticket")
WRAPPER = Path("/usr/local/sbin/codex-ibkr-show-admin")
ROOT_COPY = Path("/root/codex-tools/grant_temp_sudo.py")
UNIT = "codex-ibkr-show-sudo-revoke.service"
ACTIONS = (
    "status", "logs", "elasticsearch-health", "elasticsearch-retry-allocation",
    "worker-init-retry", "restart-backend", "restart-frontend", "restart-scheduler",
)
SUDOERS = "dmabee ALL=(root) NOPASSWD: " + ", ".join(f"{WRAPPER} {action}" for action in ACTIONS) + "\n"
WRAPPER_TEXT = r'''#!/usr/bin/env bash
set -euo pipefail
PROJECT=ibkr_show
ELASTICSEARCH=ibkr_show-elasticsearch-1
WORKER_INIT=ibkr_show-worker-init-1
BACKEND=ibkr_show-backend-1
FRONTEND=ibkr_show-frontend-1
SCHEDULER=ibkr_show-worker-scheduler-1
require_project_container() {
  local name="$1"
  [ "$(docker inspect --format '{{index .Config.Labels "com.docker.compose.project"}}' "$name")" = "$PROJECT" ] || {
    echo "unexpected container project: $name" >&2; exit 2;
  }
  [ "$(docker inspect --format '{{.HostConfig.Privileged}}' "$name")" = "false" ] || {
    echo "refusing privileged container: $name" >&2; exit 2;
  }
}
for container in "$ELASTICSEARCH" "$WORKER_INIT" "$BACKEND" "$FRONTEND" "$SCHEDULER"; do
  require_project_container "$container"
done
case "${1:-}" in
  status)
    docker ps -a --filter "label=com.docker.compose.project=$PROJECT" --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}' ;;
  logs)
    for container in "$ELASTICSEARCH" "$WORKER_INIT" "$BACKEND" "$FRONTEND" "$SCHEDULER"; do
      echo "===== $container ====="; docker logs --tail 200 "$container"
    done ;;
  elasticsearch-health)
    docker exec "$ELASTICSEARCH" curl -fsS 'http://localhost:9200/_cluster/health?pretty' ;;
  elasticsearch-retry-allocation)
    docker exec "$ELASTICSEARCH" curl -fsS -X POST 'http://localhost:9200/_cluster/reroute?retry_failed=true' ;;
  worker-init-retry) docker start "$WORKER_INIT" ;;
  restart-backend) docker restart "$BACKEND" ;;
  restart-frontend) docker restart "$FRONTEND" ;;
  restart-scheduler) docker restart "$SCHEDULER" ;;
  *) echo 'invalid IBKR Show admin action' >&2; exit 64 ;;
esac
'''

def run(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, check=check, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

def require_trusted_root_copy() -> None:
    source = Path(__file__)
    if source != ROOT_COPY or source.is_symlink():
        raise RuntimeError(f"sudo install -D -o root -g root -m 0700 grant_temp_sudo.py {ROOT_COPY} && sudo /usr/bin/python3 {ROOT_COPY}")
    metadata, parent = source.stat(), source.parent.stat()
    if metadata.st_uid != 0 or (metadata.st_mode & 0o777) != 0o700:
        raise RuntimeError("trusted root copy must be root-owned with mode 0700")
    if parent.st_uid != 0 or parent.st_mode & 0o022:
        raise RuntimeError("root-copy directory must be root-owned and not group/other writable")

def main() -> int:
    if os.geteuid() != 0:
        print(f"sudo install -D -o root -g root -m 0700 grant_temp_sudo.py {ROOT_COPY} && sudo /usr/bin/python3 {ROOT_COPY}", file=sys.stderr)
        return 1
    try:
        require_trusted_root_copy()
    except RuntimeError as error:
        print(error, file=sys.stderr)
        return 1
    candidate: Path | None = None
    wrapper_candidate: Path | None = None
    try:
        with tempfile.NamedTemporaryFile("w", dir="/etc/sudoers.d", delete=False, encoding="utf-8") as handle:
            handle.write(SUDOERS)
            candidate = Path(handle.name)
        os.chmod(candidate, 0o440)
        validation = run("/usr/sbin/visudo", "-cf", str(candidate), check=False)
        if validation.returncode:
            print(validation.stderr.strip() or "sudoers validation failed", file=sys.stderr)
            return 2
        os.replace(candidate, POLICY)
        candidate = None
        os.chmod(POLICY, 0o440)
        descriptor, path = tempfile.mkstemp(dir="/usr/local/sbin", prefix=".codex-ibkr-show-admin.")
        os.close(descriptor)
        wrapper_candidate = Path(path)
        wrapper_candidate.write_text(WRAPPER_TEXT, encoding="utf-8")
        os.chmod(wrapper_candidate, 0o750)
        os.replace(wrapper_candidate, WRAPPER)
        wrapper_candidate = None
        os.chmod(WRAPPER, 0o750)
        run("/usr/bin/systemctl", "stop", UNIT, check=False)
        run("/usr/bin/systemctl", "reset-failed", UNIT, check=False)
        expiry = run("/usr/bin/systemd-run", "--unit=codex-ibkr-show-sudo-revoke", "--on-active=24h", "--collect", "/usr/bin/rm", "-f", str(POLICY), str(WRAPPER), check=False)
        if expiry.returncode:
            POLICY.unlink(missing_ok=True)
            WRAPPER.unlink(missing_ok=True)
            print(expiry.stderr.strip() or "could not schedule automatic removal", file=sys.stderr)
            return 3
        print("CODEX_IBKR_SHOW_ADMIN=ACTIVE_FOR_24_HOURS")
        print("Allowed actions: " + ", ".join(ACTIONS))
        return 0
    finally:
        if candidate is not None:
            candidate.unlink(missing_ok=True)
        if wrapper_candidate is not None:
            wrapper_candidate.unlink(missing_ok=True)

if __name__ == "__main__":
    raise SystemExit(main())
