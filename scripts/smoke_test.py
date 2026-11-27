"""Docker and Rex smoke tests for a disposable Linux CI runner."""

import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import tarfile
import tempfile
import time
import urllib.request
import uuid
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "smoke-results"
DIAGNOSTICS = REPORT / "diagnostics"


def run(*args, timeout=30, log=None):
    if log is not None:
        with (DIAGNOSTICS / log).open("ab") as output:
            return subprocess.run(args, stdout=output, stderr=subprocess.STDOUT,
                                  timeout=timeout, check=True)
    return subprocess.check_output(args, text=True, timeout=timeout).strip()


def wait_for(check, description, seconds=30):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        result = check()
        if result:
            return result
        time.sleep(0.2)
    raise RuntimeError(f"Timed out waiting for {description}")


class Smoke:
    def __init__(self, temp, image, labels):
        self.temp = temp
        self.home = temp / "home"
        self.name = "rex-smoke-" + uuid.uuid4().hex[:12]
        self.image = image or f"{self.name}:smoke"
        self.labels = labels
        self.started = False
        self.ssh_config = None

    def build(self):
        labels = [arg for label in self.labels for arg in ("--label", label)]
        run("docker", "build", "--platform", "linux/amd64", "-t", self.image, *labels, ".",
            timeout=600, log="build.log")
        self.image_id = run("docker", "image", "inspect", "--format", "{{.Id}}", self.image)

    def start(self):
        for name, uid, gid, mode in [
            ("home", "1000", "100", "0700"), ("brew", "1000", "100", "0750"),
            ("ssh", "0", "0", "0700"), ("auth", "0", "0", "0755"),
        ]:
            run("sudo", "install", "-d", "-o", uid, "-g", gid, "-m", mode, str(self.temp / name))
        key = self.temp / "client"
        run("ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(key))
        run("sudo", "install", "-o", "0", "-g", "0", "-m", "0644",
            str(key.with_suffix(".pub")), str(self.temp / "auth/authorized_keys"))
        template = ET.parse(ROOT / "unraid/my-rex-unraid.xml").getroot()
        extra = shlex.split(template.findtext("ExtraParams"))
        caps = [flag for index, value in enumerate(extra) if value in ("--cap-drop", "--cap-add")
                for flag in extra[index:index + 2]]
        mounts = {"home": "/home/rexuser", "brew": "/home/linuxbrew", "ssh": "/var/lib/rex-ssh",
                  "auth": "/run/rex-auth"}
        binds = []
        for name, destination in mounts.items():
            suffix = ",readonly" if name == "auth" else ""
            binds.extend(("--mount", f"type=bind,src={self.temp / name},dst={destination}{suffix}"))
        self.started = True
        run("docker", "run", "-d", "--name", self.name, "--publish", "127.0.0.1::22",
            "--security-opt", f"seccomp={ROOT / 'container/codex-seccomp.json'}",
            *caps, *binds, self.image_id, log="container-start.log")

        def healthy():
            state = json.loads(run("docker", "inspect", "--format", "{{json .State}}", self.name))
            if not state["Running"]:
                raise RuntimeError(f"Container stopped with exit status {state['ExitCode']}")
            return state["Health"]["Status"] == "healthy"

        wait_for(healthy, "Docker health", 100)

    def connect(self):
        dockerfile = (ROOT / "Dockerfile").read_text()
        digest, url = re.search(
            r"ADD --checksum=sha256:([a-f0-9]+)\s+\\\s+(https://[^ ]+) /rex.tar.gz",
            dockerfile,
        ).groups()
        with urllib.request.urlopen(url, timeout=20) as response:
            archive = response.read()
        if hashlib.sha256(archive).hexdigest() != digest:
            raise RuntimeError("Rex archive checksum mismatch")
        self.rex = self.temp / "rex"
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as bundle:
            member = next(item for item in bundle if item.isfile() and Path(item.name).name == "rex")
            self.rex.write_bytes(bundle.extractfile(member).read())
        self.rex.chmod(0o700)
        port = run("docker", "port", self.name, "22/tcp").rsplit(":", 1)[1]
        host_key = run("sudo", "ssh-keygen", "-y", "-f", str(self.temp / "ssh/ssh_host_ed25519_key"))
        known_hosts = self.temp / "known_hosts"
        known_hosts.write_text(f"[127.0.0.1]:{port} {host_key}\n")
        ssh_dir = Path.home() / ".ssh"
        ssh_dir.mkdir(mode=0o700, exist_ok=True)
        config = ssh_dir / "config"
        with config.open("x") as stream:
            self.ssh_config = config
            stream.write(f"Host 127.0.0.1\n  IdentityFile {self.temp / 'client'}\n"
                         f"  UserKnownHostsFile {known_hosts}\n"
                         "  IdentitiesOnly yes\n  StrictHostKeyChecking yes\n  BatchMode yes\n")
        self.remote = (str(self.rex), "-S", f"ssh://rexuser@127.0.0.1:{port}/run/rex/server.sock")
        self.session = json.loads(run(*self.remote, "new", "smoke", "--json"))["session_id"]
        run(*self.remote, "run", "-s", self.session, "--wait", "--shell=none", "--",
            "/bin/sh", "-c", 'id -u > "$HOME/smoke-uid"; id -un >> "$HOME/smoke-uid"',
            log="rex-ssh.log")
        identity = run("sudo", "cat", str(self.home / "smoke-uid"))
        if identity.splitlines() != ["1000", "rexuser"]:
            raise RuntimeError(f"Unexpected Rex identity: {identity}")

    def cleanup(self):
        if self.ssh_config is not None:
            self.ssh_config.unlink(missing_ok=True)
        if self.started:
            for args, log in [(("inspect", self.name), "container-inspect.json"),
                              (("logs", self.name), "container.log"),
                              (("rm", "-f", self.name), "cleanup.log")]:
                subprocess.run(("docker", *args), stdout=(DIAGNOSTICS / log).open("wb"),
                               stderr=subprocess.STDOUT, timeout=30, check=False)
        subprocess.run(("sudo", "chown", "-R", str(os.getuid()), str(self.temp)),
                       timeout=30, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image")
    parser.add_argument("--label", action="append", default=[])
    args = parser.parse_args()
    DIAGNOSTICS.mkdir(parents=True, exist_ok=True)
    suite = ET.Element("testsuite", name="container-smoke")
    failed = None
    with tempfile.TemporaryDirectory(prefix="rex-smoke-") as folder:
        # The container uses UID 1000, which need not match the GitHub runner UID.
        Path(folder).chmod(0o755)
        smoke = Smoke(Path(folder), args.image, args.label)
        try:
            for name, check in (
                ("docker_build", smoke.build), ("container_start", smoke.start),
                ("rex_ssh", smoke.connect),
            ):
                case = ET.SubElement(suite, "testcase", name=name, classname="rex_unraid.smoke")
                start = time.monotonic()
                if failed:
                    ET.SubElement(case, "skipped", message=f"Blocked by {failed}")
                else:
                    try:
                        check()
                    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
                        failed = name
                        ET.SubElement(case, "failure", message=str(error)).text = str(error)
                        print(f"{name}: {error}", flush=True)
                case.set("time", f"{time.monotonic() - start:.3f}")
                suite.set("tests", str(len(suite)))
                suite.set("failures", str(len(suite.findall("testcase/failure"))))
                suite.set("skipped", str(len(suite.findall("testcase/skipped"))))
                ET.ElementTree(suite).write(REPORT / "junit.xml", encoding="utf-8", xml_declaration=True)
        finally:
            smoke.cleanup()
    if failed is None:
        (REPORT / "image-id").write_text(smoke.image_id + "\n")
    return int(failed is not None)


if __name__ == "__main__":
    raise SystemExit(main())
