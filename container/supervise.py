import fcntl
import os
from pathlib import Path
import pwd
import re
import signal
import stat
import subprocess
import sys
import tempfile
import time
import uuid


IDENTITY = Path("/var/lib/rex-ssh")
AUTH = Path("/run/rex-auth")
SOCKET = Path("/run/rex/server.sock")
SSHD = ("/usr/sbin/sshd", "-f", "/etc/ssh/sshd_config.rex")
STOP_GRACE_SECONDS = 20
stop_requested = False


def request_stop(_signum, _frame):
    global stop_requested
    stop_requested = True


def require_mount(path):
    if subprocess.run(("mountpoint", "-q", str(path))).returncode:
        raise RuntimeError(f"Mount {path} before starting the container.")


def require_ownership(path, uid, forbidden_mode, *, directory=False):
    details = path.lstat()
    is_expected_type = stat.S_ISDIR if directory else stat.S_ISREG
    if (
        not is_expected_type(details.st_mode)
        or details.st_uid != uid
        or details.st_mode & forbidden_mode
    ):
        raise RuntimeError(f"Check the type, owner, and permissions of {path}.")


def prepare_identity():
    machine_id_file = IDENTITY / "machine-id"
    host_key = IDENTITY / "ssh_host_ed25519_key"
    with tempfile.TemporaryDirectory(dir=IDENTITY) as staging:
        staging = Path(staging)
        if not machine_id_file.exists():
            new_id = staging / "machine-id"
            new_id.write_text(uuid.uuid4().hex + "\n", encoding="ascii")
            new_id.replace(machine_id_file)
        if not host_key.exists():
            new_key = staging / host_key.name
            subprocess.run(
                ("ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", "rex-unraid", "-f", new_key),
                check=True,
            )
            new_key.replace(host_key)

    require_ownership(machine_id_file, 0, 0o077)
    require_ownership(host_key, 0, 0o077)
    machine_id = machine_id_file.read_text(encoding="ascii").strip()
    if not re.fullmatch(r"[a-f0-9]{32}", machine_id) or machine_id == "0" * 32:
        raise RuntimeError(f"{machine_id_file} must contain a valid machine ID.")
    Path("/etc/machine-id").write_text(machine_id + "\n", encoding="ascii")
    os.chmod("/etc/machine-id", 0o444)
    subprocess.run(("ssh-keygen", "-lf", host_key), check=True)


def stop_children(children):
    for _, child in children:
        if child.poll() is None:
            child.terminate()

    deadline = time.monotonic() + STOP_GRACE_SECONDS
    for name, child in children:
        try:
            child.wait(timeout=max(0, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            print(f"{name} exceeded the shutdown grace period.", file=sys.stderr, flush=True)
            child.kill()
            child.wait()


def supervise(account, home):
    rex_env = {
        **os.environ,
        "HOME": str(home),
        "USER": account.pw_name,
        "LOGNAME": account.pw_name,
        "SHELL": account.pw_shell,
    }
    children = []
    try:
        if stop_requested:
            return 0
        rex = subprocess.Popen(
            (
                "/usr/local/bin/rex", "server", "run",
                "--listen", str(SOCKET),
                "--state-dir", str(home / ".local/state/rex"),
                "--socket-mode", "0600",
                "--log-format", "text",
            ),
            env=rex_env,
            cwd="/workspace",
            user=account.pw_uid,
            group=account.pw_gid,
            extra_groups=[],
            umask=0o022,
        )
        children.append(("Rex", rex))
        if stop_requested:
            return 0
        sshd = subprocess.Popen((*SSHD, "-D", "-e"), umask=0o022)
        children.append(("OpenSSH", sshd))

        while not stop_requested:
            for name, child in children:
                status = child.poll()
                if status is not None:
                    if stop_requested:
                        return 0
                    print(f"{name} exited unexpectedly with status {status}.", file=sys.stderr, flush=True)
                    return 1
            time.sleep(0.2)
        return 0
    finally:
        stop_children(children)


def main():
    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    os.umask(0o077)
    account = pwd.getpwnam("rexuser")
    home = Path(account.pw_dir)
    for path in (home, IDENTITY, AUTH):
        require_mount(path)
    require_ownership(home, account.pw_uid, 0o022, directory=True)
    require_ownership(IDENTITY, 0, 0o077, directory=True)
    require_ownership(AUTH, 0, 0o022, directory=True)
    authorized_keys = AUTH / "authorized_keys"
    require_ownership(authorized_keys, 0, 0o022)
    if authorized_keys.stat().st_size == 0:
        raise RuntimeError(f"Add client public keys to {authorized_keys}.")

    with (IDENTITY / ".lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RuntimeError(f"Another container is using {IDENTITY}.") from error

        prepare_identity()
        Path("/run/sshd").mkdir(mode=0o755, exist_ok=True)
        SOCKET.parent.mkdir(mode=0o700, exist_ok=True)
        os.chown(SOCKET.parent, account.pw_uid, account.pw_gid)
        SOCKET.unlink(missing_ok=True)
        subprocess.run((*SSHD, "-t"), check=True)
        return supervise(account, home)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f"rex-unraid: {error}", file=sys.stderr)
        sys.exit(1)
