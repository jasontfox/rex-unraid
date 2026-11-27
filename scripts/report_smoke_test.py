"""Publish bounded smoke evidence for a verified same-repository pull request."""

import html
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import xml.etree.ElementTree as ET


CASES = ("docker_build", "container_start", "rex_ssh")
LOGS = {"docker_build": "build.log", "container_start": "container.log",
        "rex_ssh": "rex-ssh.log"}
MARKER = "rex-unraid-smoke"


def gh(*args):
    return json.loads(subprocess.check_output(("gh", "api", *args), text=True, timeout=30))


def verified_run():
    event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())["workflow_run"]
    repository = os.environ["GITHUB_REPOSITORY"]
    run = gh(f"repos/{repository}/actions/runs/{int(event['id'])}")
    workflow = gh(f"repos/{repository}/actions/workflows/container-image.yml")
    if (run["workflow_id"] != workflow["id"] or run["status"] != "completed"
            or run["run_attempt"] != event["run_attempt"]
            or run["event"] not in {"pull_request", "workflow_dispatch"}
            or (run.get("head_repository") or {}).get("full_name") != repository):
        return None
    return run


def matches(pr, run):
    repository = os.environ["GITHUB_REPOSITORY"]
    return (pr["state"] == "open" and pr["base"]["ref"] == "main"
            and pr["base"]["repo"]["full_name"] == repository
            and (pr["head"].get("repo") or {}).get("full_name") == repository
            and pr["head"]["ref"] == run["head_branch"]
            and pr["head"]["sha"] == run["head_sha"])


def resolve(run):
    repository = os.environ["GITHUB_REPOSITORY"]
    if run["event"] == "pull_request" and run["pull_requests"]:
        candidates = [gh(f"repos/{repository}/pulls/{int(pr['number'])}")
                      for pr in run["pull_requests"]]
    else:
        owner = repository.split("/")[0]
        candidates = gh("--method", "GET", f"repos/{repository}/pulls", "-f", "state=open",
                        "-f", "base=main", "-f", f"head={owner}:{run['head_branch']}")
    eligible = [pr for pr in candidates if matches(pr, run)]
    return eligible[0]["number"] if len(eligible) == 1 else None


def bounded(path, max_bytes, tail=False):
    with path.open("rb") as source:
        if tail:
            source.seek(max(0, path.stat().st_size - max_bytes))
        data = source.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise ValueError(f"{path.name} exceeds its reporting limit")
    return data


def render(root, run):
    body = [f"### Container smoke tests — {run['conclusion']}",
            f"[Actions run and artifacts]({run['html_url']}) · attempt {run['run_attempt']}",
            f"PR head: `{run['head_sha']}`"]
    try:
        tested = bounded(root / "smoke-sha", 80).decode().strip()
        if not re.fullmatch(r"[a-f0-9]{40}", tested):
            raise ValueError("invalid checkout revision")
        if run["event"] == "workflow_dispatch" and tested != run["head_sha"]:
            raise ValueError("manual checkout does not match its dispatched revision")
        body.append(f"Tested checkout: `{tested}`")
        xml = bounded(root / "junit.xml", 64 * 1024).decode("utf-8")
        if "<!DOCTYPE" in xml or "<!ENTITY" in xml:
            raise ValueError("XML declarations are forbidden")
        suite = ET.fromstring(xml)
        cases = suite.findall("testcase")
        if suite.tag != "testsuite" or sorted(case.get("name", "") for case in cases) != sorted(CASES):
            raise ValueError("unexpected JUnit test cases")
    except (OSError, ValueError, ET.ParseError):
        return "\n\n".join(body + ["JUnit evidence is unavailable or invalid."])

    rows = ["| Case | Result |", "| --- | --- |"]
    diagnostics = []
    for case in cases:
        name = case.attrib["name"]
        outcome = "passed"
        if case.find("failure") is not None or case.find("error") is not None:
            outcome = "failed"
            try:
                excerpt = bounded(root / "diagnostics" / LOGS[name], 1500,
                                  tail=True).decode(errors="replace")
                excerpt = re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", "", excerpt)
                diagnostics.append(f"<details><summary>{name} diagnostics</summary>\n\n"
                                   f"<pre>{html.escape(excerpt)}</pre>\n</details>")
            except OSError:
                pass
        elif case.find("skipped") is not None:
            outcome = "blocked"
        rows.append(f"| `{name}` | {outcome} |")
    return "\n\n".join(body + ["\n".join(rows)] + diagnostics)


def publish(number, run, root):
    repository = os.environ["GITHUB_REPOSITORY"]
    if resolve(run) != number:
        return
    endpoint = f"repos/{repository}/issues/{number}/comments"
    pages = gh("--paginate", "--slurp", endpoint)
    userid = "github-actions[bot]"
    prefix = f"<!-- {MARKER} "
    previous = next((item for page in pages for item in page
                     if item["user"]["login"] == userid and item["body"].startswith(prefix)), None)
    key = (run["created_at"], run["id"], run["run_attempt"])
    if previous:
        match = re.match(rf"<!-- {MARKER} (\S+) (\d+) (\d+) -->", previous["body"])
        if match and (match[1], int(match[2]), int(match[3])) >= key:
            return
    body = f"{prefix}{key[0]} {key[1]} {key[2]} -->\n\n" + render(root, run)
    if previous:
        gh("--method", "PATCH", f"repos/{repository}/issues/comments/{previous['id']}", "-f",
           f"body={body}")
    else:
        gh("--method", "POST", endpoint, "-f", f"body={body}")


if __name__ == "__main__":
    source_run = verified_run()
    if source_run:
        if sys.argv[1] == "resolve":
            if number := resolve(source_run):
                print(f"number={number}")
        else:
            publish(int(sys.argv[2]), source_run, Path(sys.argv[3]))
