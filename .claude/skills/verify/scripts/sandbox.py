#!/usr/bin/env python3
"""Drive the team-up CLI in one disposable Git repository."""
import argparse
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time


SOURCE = Path(__file__).resolve().parents[4]
SCRIPT = SOURCE / "plugin/skills/team-up/scripts/team_up.py"
TMP = Path("/tmp").resolve()
PREFIX = "verify-team-up-sandbox."
PYTHON = os.environ.get("VERIFY_TEAM_UP_PYTHON", "/usr/bin/python3")
GIT_ENV = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
GIT_ENV.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")
FILE = "README.md"
V4_REVISION = "c94b299"


class Sandbox:
    def __init__(self, root, evidence):
        self.root = root
        self.evidence = evidence
        self.repo = root / "repo"
        self.worker = root / "worker"
        self.db = root / "state.db"
        self.manifest = root / "sandbox.json"
        self.env = GIT_ENV.copy()

    @classmethod
    def open(cls, path):
        root = Path(path).resolve()
        if root.parent != TMP or not root.name.startswith(PREFIX):
            raise ValueError("expected a sandbox path returned by launch")
        manifest = json.loads((root / "sandbox.json").read_text())
        if manifest["root"] != str(root):
            raise ValueError("sandbox manifest does not match the supplied path")
        return cls(root, Path(manifest["evidence"]))

    def save(self, name, value):
        (self.evidence / name).write_text(json.dumps(value, indent=2) + "\n")

    def command(self, *args, cwd=None, allowed=(0,), while_running=None):
        argv = list(map(str, args))
        cwd = cwd or self.repo
        if while_running is None:
            result = subprocess.run(argv, cwd=cwd, env=self.env, capture_output=True,
                                    text=True, timeout=30)
            self.log_command(result, cwd)
        else:
            with subprocess.Popen(argv, cwd=cwd, env=self.env, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, text=True) as process:
                try:
                    while_running(process)
                    stdout, stderr = process.communicate(timeout=10)
                except BaseException:
                    process.kill()
                    stdout, stderr = process.communicate()
                    raise
                finally:
                    result = subprocess.CompletedProcess(argv, process.returncode, stdout, stderr)
                    self.log_command(result, cwd)
        if result.returncode not in allowed:
            raise RuntimeError(f"{shlex.join(argv)} exited {result.returncode}: {result.stderr.strip()}")
        return result

    def log_command(self, result, cwd):
        argv = result.args
        with (self.evidence / "commands.jsonl").open("a") as log:
            log.write(json.dumps({"cwd": str(cwd), "argv": argv,
                                  "command": shlex.join(argv), "exit_code": result.returncode,
                                  "stdout": result.stdout, "stderr": result.stderr}) + "\n")

    def git(self, *args, **kwargs):
        return self.command("git", "-c", "core.hooksPath=/dev/null", *args, **kwargs).stdout

    def team(self, *args, **kwargs):
        return json.loads(self.command(PYTHON, SCRIPT, "--db", self.db, *args, **kwargs).stdout)

    def probe(self, *args, **kwargs):
        result = self.command(PYTHON, SCRIPT, "--db", self.db, *args, allowed=(0, 1), **kwargs)
        if result.returncode:
            return {"exit_code": result.returncode, "error": result.stderr.strip()}
        return {"exit_code": 0, "result": json.loads(result.stdout)}

    def read_db(self):
        # Each CLI process has already exited. Open a read-only snapshot without creating SQLite sidecars.
        return closing(sqlite3.connect(f"{self.db.as_uri()}?mode=ro&immutable=1", uri=True))

    def doctor(self):
        init = json.loads((self.evidence / "init.json").read_text())
        if init.get("warning") or init["db"] != str(self.db) or init["journal_mode"] != "wal":
            raise ValueError(f"unexpected team-up init report: {init}")
        manifest = json.loads(self.manifest.read_text())
        if manifest["script_sha256"] != hashlib.sha256(SCRIPT.read_bytes()).hexdigest():
            raise ValueError("team_up.py changed since launch")
        version = self.command(PYTHON, "-c", "import sqlite3; print(sqlite3.sqlite_version)").stdout.strip()
        if version != init["sqlite_version"] or PYTHON != manifest["python"]:
            raise ValueError("Python or SQLite changed since launch")
        common = self.git("rev-parse", "--path-format=absolute", "--git-common-dir").strip()
        worktrees = self.git("worktree", "list", "--porcelain")
        if common != str(self.repo / ".git") or f"worktree {self.worker}\n" not in worktrees:
            raise ValueError("the disposable repository or linked worktree is missing")
        with self.read_db() as db:
            identity = db.execute("SELECT common_dir FROM repository").fetchone()
            integrity = db.execute("PRAGMA quick_check").fetchone()
            version = db.execute("PRAGMA user_version").fetchone()
        if identity != (common,) or integrity != ("ok",) or version != (init["schema_version"],):
            raise ValueError("the initialized database does not match the sandbox Git repository")
        return {"ready": True, "git_common_dir": common, "worktrees": worktrees, **init}

    def status(self, run, name="status"):
        value = self.team("status", run)
        self.save(f"{name}.json", value)
        return value

    def capture(self):
        self.save("git-state.json", {
            "worktrees": self.git("worktree", "list", "--porcelain"),
            "refs": self.git("show-ref", "--heads"),
            "main": self.git("status", "--porcelain", "--untracked-files=all"),
            "worker": self.git("status", "--porcelain", "--untracked-files=all", cwd=self.worker)
            if self.worker.exists() else None,
        })
        with self.read_db() as db:
            db.row_factory = sqlite3.Row
            for table in ("events", "messages"):
                rows = db.execute(f"SELECT * FROM {table} ORDER BY id")
                self.save(f"{table}.json", [dict(row) for row in rows])

    def run(self, goal, slots=1):
        return self.team("run-create", "--goal", goal, "--slots", slots, "--base", "main")["id"]

    def task(self, run, goal, *args, scope="read-only"):
        return self.team("task-create", run, "--worker", "codex", "--goal", goal,
                         "--scope", scope, "--evidence", "Full result and command output", *args)["id"]

    def reserve(self, run, task):
        return self.team("reserve", run, "--task", task, "--worktree", self.worker, "--branch", "worker")

    def start(self, dispatch, turn):
        begun = self.team("begin", dispatch)
        require(begun["turn"] == turn, f"begin must return turn {turn}")
        started = self.team("started", dispatch, "--turn", turn,
                            "--runtime", f"shell-role:{dispatch}:{turn}", "--session", f"fixture:{dispatch}")
        require(started["session"] == f"fixture:{dispatch}", "the saved session must match")
        return begun

    def end(self, dispatch, turn):
        self.team("turn-ended", dispatch, "--turn", turn)
        return self.team("exited", dispatch, "--turn", turn, "--code", 0)

    def wake(self, run, kind):
        wake = self.team("wait", run, "--timeout", 0)
        events = wake["events"]
        require([event["kind"] for event in events] == [kind], f"wait must return one {kind} event")
        ack = self.team("ack", run, wake["cursor"])
        require(ack["cursor"] == wake["cursor"], "ack must persist the wake cursor")
        return events[0]

    def done(self, dispatch, turn, result, verification, patch=None, cwd=None):
        report = {"status": "success", "result": result, "changed_code": patch is not None,
                  "verification": [{"command": verification, "exit_code": 0, "location": "commands.jsonl"}]}
        if patch is not None:
            report["diff"] = patch
        return self.team("done", dispatch, "--turn", turn, "--evidence", json.dumps(report),
                         cwd=cwd or self.worker)


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def launch(directory):
    evidence = Path(directory).resolve()
    if evidence == TMP or TMP not in evidence.parents or not evidence.is_dir() or any(evidence.iterdir()):
        raise ValueError("provide an empty evidence directory under /tmp")
    root = Path(tempfile.mkdtemp(prefix=PREFIX, dir=TMP))
    box = Sandbox(root, evidence)
    box.manifest.write_text(json.dumps({"root": str(root), "evidence": str(evidence),
                                       "script_sha256": hashlib.sha256(SCRIPT.read_bytes()).hexdigest(),
                                       "python": PYTHON}))
    try:
        box.git("init", "-b", "main", "--template=", box.repo, cwd=root)
        box.git("fetch", "--no-tags", SOURCE, "HEAD")
        box.git("switch", "-C", "main", "FETCH_HEAD^")
        require((box.repo / FILE).is_file(), f"the parent revision must contain {FILE}")
        box.git("worktree", "add", "-b", "worker", box.worker, "main")
        box.save("init.json", box.team("init"))
    except Exception:
        cleanup(box)
        raise
    print(root)


def cleanup(box):
    shutil.rmtree(box.root)
    box.save("cleanup.json", {"sandbox": str(box.root), "removed": not box.root.exists(),
                              "evidence_retained": sorted(item.name for item in box.evidence.iterdir())})
    print(f"Removed {box.root}. Evidence remains at {box.evidence}.")


def lifecycle(box, run):
    task = box.task(run, "Append and verify a README line", scope=FILE)
    dispatch = box.reserve(run, task)["id"]
    box.git("worktree", "list", "--porcelain")
    box.start(dispatch, 1)
    box.team("heartbeat", dispatch, "--turn", 1, cwd=box.worker)
    marker = "team-up verification fixture"
    with (box.worker / FILE).open("a") as file:
        file.write(f"\n{marker}\n")
    verification = ("grep", "-h", "-e", f"^{marker}$", "--", FILE)
    box.git(*verification, cwd=box.worker)
    box.git("--no-optional-locks", "status", "--short", "--untracked-files=all", "--", FILE, cwd=box.worker)
    diff = ("--no-pager", "diff", "--no-ext-diff", "--no-textconv", "--binary", "HEAD", "--", FILE)
    patch = box.git(*diff, cwd=box.worker)
    require(f"+{marker}" in patch, "the worker patch must contain the verified line")
    box.done(dispatch, 1, f"Added and verified {marker!r} in {FILE}", shlex.join(("git", *verification)), patch)
    wake = box.wake(run, "done")
    require(wake["dispatch_id"] == dispatch, "the done event must identify the Dispatch")
    closed = box.end(dispatch, 1)
    require(closed["outcome"] == "success" and closed["exit_code"] == 0, "worker exit must close successfully")
    require(box.git("status", "--porcelain", "--untracked-files=all", cwd=box.worker) == f" M {FILE}\n",
            "worker changes must stay within scope")
    require(closed["evidence"]["diff"] == box.git(*diff, cwd=box.worker), "worker and coordinator patches differ")
    (box.evidence / "delivered.patch").write_text(patch)
    box.team("delivered", dispatch)
    require(box.team("cleanup", run) == [], "cleanup must skip the dirty worktree")
    box.git("restore", "--", FILE, cwd=box.worker)
    require(box.team("cleanup", run) == [{"id": dispatch, "worktree": str(box.worker), "branch": "worker"}],
            "cleanup must list only the clean, delivered worktree")
    box.git("worktree", "remove", box.worker)
    require(box.team("cleanup", run) == [] and not box.worker.exists(), "Git must remove the worktree")
    box.git("show-ref", "--verify", "refs/heads/worker")
    return {"delivered_patch_and_removed_worktree": True}


def questions(box, run):
    task = box.task(run, "Confirm which file to review")
    dispatch = box.reserve(run, task)["id"]
    box.start(dispatch, 1)
    question = box.team("record", dispatch, "--turn", 1, "Which file should I review?", cwd=box.worker)
    require(box.wake(run, "question")["data"]["message_id"] == question["id"], "wait must identify the question")
    waiting = box.end(dispatch, 1)
    require(waiting["phase"] == "waiting", "question exit must leave the Dispatch waiting")
    reply = f"Review {FILE}"
    box.team("answer", question["id"], reply)
    resumed = box.start(dispatch, 2)
    require(resumed["worktree"] == str(box.worker) and resumed["session"] == waiting["session"]
            and resumed["messages"][0]["answer"] == reply, "resume must retain placement, session and answer")
    box.git("ls-files", "--error-unmatch", FILE, cwd=box.worker)
    box.done(dispatch, 2, f"Reviewed {FILE}", f"git ls-files --error-unmatch {FILE}")
    box.wake(run, "done")
    require(box.end(dispatch, 2)["outcome"] == "success", "resumed turn must complete")
    return {"same_session_with_answer": True}


def gate(box, run):
    prerequisite = box.task(run, "Verify the candidate revision")
    rejected = box.task(run, "Rejected rollout", "--after-merge", prerequisite, "--gate", "rollout-reject")
    approved = box.task(run, "Approved rollout", "--after-merge", prerequisite, "--gate", "rollout-approve")
    require(box.team("reserve", run, "--task", rejected) is None, "undecided and unmerged Task must be blocked")
    dispatch = box.reserve(run, prerequisite)["id"]
    box.start(dispatch, 1)
    candidate = box.git("rev-parse", "FETCH_HEAD").strip()
    box.git("merge", "--ff-only", candidate, cwd=box.worker)
    box.git("diff", "--check", "main", "HEAD", cwd=box.worker)
    box.done(dispatch, 1, "Verified the existing candidate revision", "git diff --check main HEAD")
    box.wake(run, "done")
    require(box.end(dispatch, 1)["outcome"] == "success", "prerequisite must finish successfully")
    box.team("gate", run, "rollout-approve", "--decision", "approve")
    require(box.team("reserve", run, "--task", approved) is None, "approval cannot replace a merge")
    box.git("merge", "--ff-only", "worker")
    commit = box.git("rev-parse", "worker").strip()
    box.git("merge-base", "--is-ancestor", commit, "main")
    box.team("merged", prerequisite, "--base", "main", "--commit", commit)
    require(box.team("reserve", run, "--task", rejected) is None, "merge cannot replace a decision")
    box.team("gate", run, "rollout-reject", "--decision", "reject")
    denied = box.team("reserve", run, "--task", rejected)
    ready = box.team("reserve", run, "--task", approved)
    box.save("gate-reservations.json", {"after_reject": denied, "after_approve": ready})
    require(ready is not None and ready["task_id"] == approved, "approved, merged Task must be reservable")
    return {"rejected_task_stays_blocked": denied is None, "approved_task_reserves": True}


def instructions(box, run):
    task = box.task(run, "Review README and accept follow-up instructions")
    dispatch = box.reserve(run, task)["id"]
    box.start(dispatch, 1)
    instruction = box.team("instruct", dispatch, "Check whether README has a top-level heading")
    box.git("ls-files", "--error-unmatch", FILE, cwd=box.worker)
    box.done(dispatch, 1, "Confirmed that README is tracked", f"git ls-files --error-unmatch {FILE}")
    box.wake(run, "done")
    running_follow_up = box.probe("instruct", dispatch, "Report the exact first heading")
    closed = box.end(dispatch, 1)
    closed_follow_up = box.probe("instruct", dispatch, "Report the exact first heading after exit")
    resume = box.probe("begin", dispatch)
    status = box.status(run, "instruction-status")
    persisted = any(message["id"] == instruction["id"] and message["text"] == instruction["text"]
                    for message in status["messages"])
    resumed = resume.get("result", {})
    continued = False
    if resumed:
        require(resumed["turn"] == 2 and resumed["session"] == closed["session"]
                and resumed["worktree"] == str(box.worker), "follow-up must reuse the session and worktree")
        box.team("started", dispatch, "--turn", 2, "--runtime", f"shell-role:{dispatch}:2",
                 "--session", closed["session"])
        verification = ("grep", "-n", "-e", "^# ", "--", FILE)
        heading = box.git(*verification, cwd=box.worker).splitlines()[0]
        box.done(dispatch, 2, f"README has a top-level heading: {heading}", shlex.join(("git", *verification)))
        box.wake(run, "done")
        continued = box.end(dispatch, 2)["outcome"] == "success"
        box.team("delivered", dispatch)

    # Diagnostic only: a conforming worker ends a blocking-question turn without calling done.
    # Give answer a real question ID to distinguish a completion refusal from an unknown question.
    diagnostic = box.task(run, "Probe answer against a reported completion")
    diagnostic_dispatch = box.team("reserve", run, "--task", diagnostic)["id"]
    box.start(diagnostic_dispatch, 1)
    question = box.team("record", diagnostic_dispatch, "--turn", 1, "Which heading?", cwd=box.worker)
    box.wake(run, "question")
    box.git("ls-files", "--error-unmatch", FILE, cwd=box.worker)
    box.done(diagnostic_dispatch, 1, "Reported completion with a question open", f"git ls-files --error-unmatch {FILE}")
    answer = box.probe("answer", question["id"], "Check the first heading")
    box.wake(run, "done")
    box.end(diagnostic_dispatch, 1)

    box.save("follow-up-probes.json", {"instruction": instruction, "instruction_persisted": persisted,
                                      "first_exit_phase": closed["phase"], "resume": resume,
                                      "instruct_after_done": running_follow_up,
                                      "instruct_after_exit": closed_follow_up, "answer_after_done": answer})
    message_ids = {message["id"] for message in resumed.get("messages", [])}
    follow_up_ids = {probe["result"]["id"] for probe in (running_follow_up, closed_follow_up)
                     if probe["exit_code"] == 0}
    return {"queued_instruction_reaches_next_turn": continued and instruction["id"] in message_ids,
            "post_done_follow_up_delivered": continued and bool(follow_up_ids & message_ids)}


def review_main(box, run):
    marker = "Uncommitted review-only change."
    with (box.repo / FILE).open("a") as file:
        file.write(f"\n{marker}\n")
    diff = ("--no-pager", "diff", "--no-ext-diff", "--no-textconv", "--binary", "HEAD", "--", FILE)
    before = box.git(*diff)
    (box.evidence / "checkout-under-review.patch").write_text(before)
    require(f"+{marker}" in before and box.git(*diff, cwd=box.worker) == "",
            "only the main checkout must contain the change under review")

    task = box.task(run, "Have Codex review this and report back")
    reservation = box.probe("reserve", run, "--task", task, "--review-main",
                            "--worktree", box.repo, "--branch", "main")
    dispatch = reservation.get("result")
    if dispatch is None:
        dispatch = box.team("reserve", run, "--task", task)
    dispatch = dispatch["id"]
    box.start(dispatch, 1)
    registration = box.probe("register", dispatch, "--turn", 1, "--worktree", box.repo, "--branch", "main")
    box.git("--no-optional-locks", "status", "--short", "--untracked-files=all", cwd=box.repo)
    require(box.git(*diff, cwd=box.repo) == before, "the first review turn must see the live patch")
    question = box.team("record", dispatch, "--turn", 1, "Should I review the new line for wording?", cwd=box.repo)
    box.wake(run, "question")
    waiting = box.end(dispatch, 1)
    require(waiting["phase"] == "waiting" and waiting["session"], "review must retain its question and session")
    box.team("answer", question["id"], "Yes, report the line and your finding")
    resume = box.probe("begin", dispatch)
    box.save("placement-probes.json", {"reserve_main": reservation, "register_main": registration,
                                       "waiting": waiting, "resume": resume})
    resumed = resume.get("result", {})
    completed = False
    if resumed:
        require(resumed["session"] == waiting["session"] and resumed["turn"] == 2,
                "main review must resume the same session in turn 2")
        box.team("started", dispatch, "--turn", 2, "--runtime", f"shell-role:{dispatch}:2",
                 "--session", waiting["session"])
        require(box.git(*diff, cwd=box.repo) == before, "the resumed worker must see the live patch")
        box.done(dispatch, 2, f"Reviewed {FILE}: {marker!r} adds fixture-only prose to the README.",
                 shlex.join(("git", *diff)), cwd=box.repo)
        box.wake(run, "done")
        completed = box.end(dispatch, 2)["outcome"] == "success"
        box.team("delivered", dispatch)
    after = box.git(*diff)
    (box.evidence / "checkout-after-review.patch").write_text(after)
    require(after == before, "a read-only review must preserve the main checkout patch")
    return {"same_session_main_review_delivered": completed, "main_checkout_patch_preserved": True}


def report_done(box, run, dispatch, turn=1):
    box.git("ls-files", "--error-unmatch", FILE, cwd=box.worker)
    box.done(dispatch, turn, f"Verified {FILE}", f"git ls-files --error-unmatch {FILE}")
    require(box.wake(run, "done")["dispatch_id"] == dispatch, "completion must identify the Dispatch")
    require(box.end(dispatch, turn)["outcome"] == "success", "the Dispatch must finish successfully")


def fake_github(box, number):
    fixture = box.root / "github.json"
    executable = box.root / "gh"
    executable.write_text(f"#!{PYTHON}\n" + """import json
import sys
from pathlib import Path

fixture = Path(__file__).with_name("github.json")
state = json.loads(fixture.read_text())
args = sys.argv[1:]
with fixture.with_name("gh-calls.jsonl").open("a") as log:
    print(json.dumps(args), file=log)
number = str(state["number"])
remote = state["remote"]
if len(args) == 5 and args[:4] == ["pr", "view", number, "--json"]:
    print(json.dumps(remote))
elif args == ["pr", "merge", number, "--disable-auto"]:
    remote["autoMergeRequest"] = None
    fixture.write_text(json.dumps(state))
elif args == ["pr", "merge", number, "--auto", "--squash", "--match-head-commit", remote["headRefOid"]]:
    remote["autoMergeRequest"] = {"enabled": True}
    fixture.write_text(json.dumps(state))
else:
    sys.exit(f"Unexpected fake gh command: {args!r}")
""")
    executable.chmod(0o700)
    box.env["PATH"] = str(box.root) + os.pathsep + box.env.get("PATH", os.defpath)
    box.env["TEAM_UP_GH"] = str(executable)
    remote = {
        "headRefOid": box.git("rev-parse", "worker").strip(),
        "statusCheckRollup": [{"name": "verify", "conclusion": "SUCCESS"}],
        "mergeable": "MERGEABLE", "mergeStateStatus": "CLEAN",
        "autoMergeRequest": None, "state": "OPEN", "mergeCommit": None,
        "files": [{"path": FILE, "changeType": "MODIFIED"}], "changedFiles": 1,
        "url": f"https://example.invalid/pull/{number}", "baseRefName": "main",
    }
    fixture.write_text(json.dumps({"number": number, "remote": remote}))
    return fixture


def remote_update(fixture, **changes):
    state = json.loads(fixture.read_text())
    state["remote"].update(changes)
    fixture.write_text(json.dumps(state))


def board(box, run):
    done = box.task(run, "Already delivered")
    task = box.task(run, "Fix a failed PR")
    queued = box.task(run, "Ready task")
    gated = box.task(run, "Needs a decision", "--gate", "release")
    blocked = box.task(run, "Waits for release", "--after-merge", task)
    first = box.reserve(run, done)["id"]
    box.start(first, 1)
    report_done(box, run, first)
    box.team("delivered", first)
    dispatch = box.reserve(run, task)["id"]
    box.start(dispatch, 1)
    report_done(box, run, dispatch)
    review = box.team("board", run, "--json")
    box.team("delivered", dispatch)
    fixture = fake_github(box, 42)
    box.team("pr-open", dispatch, "--number", 42)
    remote_update(fixture, statusCheckRollup=[{"name": "verify", "conclusion": "FAILURE"}])
    box.team("pr-sync", run)
    merging = box.team("board", run, "--json")
    page = box.root / "slots.html"
    box.team("board", run, "--html", page)
    idle = page.read_text()
    before = box.team("status", run)
    box.team("instruct", dispatch, "Fix the failing verify check")
    resumed = box.start(dispatch, 2)
    expected_state = box.team("status", run)
    current = box.team("board", run, "--json")
    plain = box.command(PYTHON, SCRIPT, "--db", box.db, "board", run).stdout
    box.team("board", run, "--html", page)
    fixing = page.read_text()
    denied = box.team("reserve", run, "--task", queued)
    box.save("board-snapshots.json", {"review": review, "merging": merging, "fixing": current, "queued": denied})
    (box.evidence / "board.txt").write_text(plain)
    (box.evidence / "board-idle.html").write_text(idle)
    (box.evidence / "board-fixing.html").write_text(fixing)

    groups = {
        group["key"]: [item["task_id"] for item in group["tasks"]]
        for group in current["groups"]
    }
    sections = [(group["title"], group["count"]) for group in current["groups"] if group["tasks"]]
    headings = [line for line in plain.splitlines() if line and not line.startswith(" ")]
    return {
        "review_then_merge_then_fix": board_tasks(review, "review") == [task]
        and board_tasks(merging, "merging") == [task]
        and groups["in_progress"] == [task, queued],
        "one_group_per_task": groups == {
            "needs_user": [gated], "in_progress": [task, queued], "review": [],
            "merging": [], "blocked": [blocked], "done": [done],
        },
        "text_matches_json": headings == [f"{title} ({count})" for title, count in sections]
        and all(f"  #{task_id} codex " in plain for task_id in (task, queued, gated, blocked, done))
        and "대기열" in plain and f"← #{task}" in plain,
        "fix_turn_occupies_slot": resumed["session"] == f"fixture:{dispatch}"
        and before["pull_requests"][0]["fix_rounds"] == 0
        and expected_state["pull_requests"][0]["fix_rounds"] == 1
        and '<span class="count">0/1</span>' in idle
        and '<span class="count">1/1</span>' in fixing and denied is None,
        "board_is_read_only": box.team("status", run) == expected_state,
    }


def board_tasks(snapshot, key):
    return [item["task_id"] for group in snapshot["groups"] if group["key"] == key for item in group["tasks"]]


def run_notes(box, run):
    task = box.task(run, "Read shared conventions")
    first = box.team("note", run, "Keep the README heading")
    dispatch = box.reserve(run, task)["id"]
    initial = box.start(dispatch, 1)
    second = box.team("note", run, "Use the latest wording")
    active = box.team("status", run)
    box.team("record", dispatch, "--turn", 1, "Can I continue?", cwd=box.worker)
    question = box.wake(run, "question")["data"]["message_id"]
    box.end(dispatch, 1)
    box.team("answer", question, "Continue with the latest note")
    resumed = box.start(dispatch, 2)
    oversized = "한글" * 2200
    third = box.team("note", run, oversized)
    report_done(box, run, dispatch, 2)
    box.team("delivered", dispatch)
    other = box.run("Independent notes scope")
    other_task = box.task(other, "Read another Run's conventions")
    other_note = box.team("note", other, "Other run only")
    other_dispatch = box.reserve(other, other_task)["id"]
    isolated = box.start(other_dispatch, 1)
    report_done(box, other, other_dispatch)
    box.team("delivered", other_dispatch)
    latest_task = box.task(run, "Read the truncated brief")
    latest = box.start(box.reserve(run, latest_task)["id"], 1)
    stored = box.team("status", run)
    box.save("notes-briefs.json", {"initial": initial, "resumed": resumed, "latest": latest,
                                  "isolated": isolated, "active": active})
    prefix, _, marker = latest["notes"].rpartition("\n")
    return {
        "notes_version_advances_per_run": [first["notes_version"], second["notes_version"],
                                           third["notes_version"], other_note["notes_version"]] == [1, 2, 3, 1]
        and active["dispatches"][0]["notes_version"] == 1 and stored["run"]["notes_version"] == 3,
        "next_turn_gets_latest_first": initial["notes"] == first["text"]
        and resumed["notes"] == f"{second['text']}\n\n{first['text']}"
        and resumed["notes_version"] == 2,
        "notes_are_run_scoped": isolated["notes"] == other_note["text"],
        "brief_truncated_but_status_keeps_full_notes": bool(prefix) and oversized.startswith(prefix)
        and marker == "[Run notes truncated]" and len(latest["notes"].encode()) <= 4096
        and [note["text"] for note in stored["notes"]] == [first["text"], second["text"], oversized],
    }


def worker_progress(box, run):
    task = box.task(run, "Report fixture edits")
    dispatch = box.reserve(run, task)["id"]
    box.start(dispatch, 1)

    def snapshot():
        result = box.team("board", run, "--json")
        running = [item for group in result["groups"] if group["key"] == "in_progress"
                   for item in group["tasks"] if item["task_id"] == task]
        require(len(running) == 1, "the progress Task must appear once under in progress")
        return running[0]

    initial = snapshot()
    report = box.team("progress", dispatch, "--turn", 1, "--step", "2/4", "Editing fixture", cwd=box.worker)
    update = box.team("progress", dispatch, "--turn", 1, "Reviewing fixture", cwd=box.worker)
    stale_turn = box.probe("progress", dispatch, "--turn", 2, "Wrong turn", cwd=box.worker)
    tracked = box.worker / FILE
    _, _, remaining = tracked.read_text().partition("\n")
    tracked.write_text("Progress fixture heading\nProgress fixture detail\n" + remaining)
    (box.worker / "progress-untracked.txt").write_text("one\ntwo\n")
    (box.worker / "progress-binary").write_bytes(b"\x00\xff")
    active = snapshot()
    old = "2000-01-01T00:00:00+00:00"
    with closing(sqlite3.connect(box.db)) as db, db:
        db.execute("UPDATE dispatches SET heartbeat_at = ?, progress_at = ? WHERE id = ?", (old, old, dispatch))
    stalled = snapshot()
    plain = box.command(PYTHON, SCRIPT, "--db", box.db, "board", run).stdout
    heartbeat = box.team("heartbeat", dispatch, "--turn", 1, cwd=box.worker)
    recovered = snapshot()
    box.save("progress-snapshots.json", {"initial": initial, "report": report, "active": active,
                                         "stalled": stalled, "recovered": recovered, "stale_turn": stale_turn})
    (box.evidence / "progress-stalled.txt").write_text(plain)
    return {
        "optional_step_and_current_turn": all(initial[key] is None for key in
                                             ("progress_text", "progress_step", "progress_total", "progress_at"))
        and (report["progress_step"], report["progress_total"]) == (2, 4)
        and (active["progress_step"], active["progress_total"], active["progress_text"]) == (2, 4, "Reviewing fixture")
        and active["last_update_at"] == update["progress_at"] and stale_turn["exit_code"] == 1
        and "2/4 단계" in plain and "Reviewing fixture" in plain,
        "diff_stats_include_untracked_and_binary": active["diff_stats"] == {"files": 3, "added": 4, "deleted": 1}
        and "3개 파일 +4 -1" in plain,
        "stalls_and_recovers": active["stalled"] is False and stalled["stalled"] is True
        and stalled["last_update_at"] == old and "⚠ 정체" in plain
        and recovered["stalled"] is False and recovered["last_update_at"] == heartbeat["heartbeat_at"],
    }


def html_board(box, run):
    task = box.task(run, "Show <fixture> safely")
    dispatch = box.reserve(run, task)["id"]
    box.start(dispatch, 1)
    single = box.team("board", run, "--html")
    default = box.root / "boards" / f"run-{run}.html"
    one_shot = default.read_text()
    path = box.root / "watch.html"
    refresh = '<meta http-equiv="refresh" content="1">'

    def finish_run(process):
        deadline = time.monotonic() + 10
        while not path.exists() and process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.05)
        require(path.is_file(), "watch must write its first page before the Run finishes")
        active = path.read_text()
        (box.evidence / "html-live.html").write_text(active)
        report_done(box, run, dispatch)
        box.team("delivered", dispatch)

    watch = box.team("board", run, "--html", path, "--watch", 1, while_running=finish_run)
    live = (box.evidence / "html-live.html").read_text()
    final = path.read_text()
    (box.evidence / "html-default.html").write_text(one_shot)
    (box.evidence / "html-final.html").write_text(final)
    return {
        "one_shot_uses_database_directory": single == {"path": str(default), "finished": False}
        and "Show &lt;fixture&gt; safely" in one_shot,
        "active_watch_refreshes": refresh in live and '<span class="count">1/1</span>' in live
        and "전달됨" not in live,
        "finished_watch_exits_and_leaves_final_page": watch == {"path": str(path), "finished": True}
        and 'http-equiv="refresh"' not in final and "전달됨" in final
        and '<span class="count">0/1</span>' in final and "Show &lt;fixture&gt; safely" in final,
    }


def pr_follow_up(box, run):
    number = 42
    task = box.task(run, "Deliver a PR for monitoring")
    dependent = box.task(run, "Ready after the PR merges", "--after-merge", task, "--gate", "rollout")
    dispatch = box.reserve(run, task)["id"]
    box.start(dispatch, 1)
    report_done(box, run, dispatch)
    box.team("delivered", dispatch)
    fixture = fake_github(box, number)
    remote_update(fixture, autoMergeRequest={"enabled": True})
    opened = box.team("pr-open", dispatch, "--number", number)
    held_arm = box.probe("pr-arm", task)
    gate = f"merge-pr-{number}"
    unapproved = box.probe("pr-policy", task, "auto", "--gate", gate)
    box.team("gate", run, "rollout", "--decision", "approve")
    attached = box.probe("pr-policy", task, "auto", "--gate", "rollout")
    box.team("gate", run, gate, "--decision", "approve")
    automatic = box.team("pr-policy", task, "auto", "--gate", gate)
    armed = box.team("pr-arm", task)
    passed = box.team("wait", run, "--timeout", 0)
    box.team("ack", run, passed["cursor"])
    remote_update(fixture, statusCheckRollup=[{"name": "verify", "conclusion": "FAILURE"}])
    failed = box.team("wait", run, "--sync-prs", 1, "--timeout", 2)
    box.team("ack", run, failed["cursor"])
    blocked = box.team("reserve", run, "--task", dependent)
    remote_update(fixture, state="MERGED", mergeCommit={"oid": armed["head_sha"]}, autoMergeRequest=None)
    synced = box.team("pr-sync", run)["pull_requests"][0]
    merged = box.team("wait", run, "--timeout", 0)
    available = box.team("reserve", run, "--task", dependent)
    calls = [json.loads(line) for line in (box.root / "gh-calls.jsonl").read_text().splitlines()]
    box.save("gh-calls.json", calls)
    box.save("pr-probes.json", {"opened": opened, "held_arm": held_arm, "unapproved": unapproved,
                                 "attached_gate": attached, "automatic": automatic, "armed": armed,
                                 "passed": passed, "failed": failed, "synced": synced, "merged": merged,
                                 "blocked": blocked, "available": available})
    return {
        "default_hold_disarms_and_refuses_arm": opened["number"] == number and opened["policy"] == "hold"
        and opened["auto_merge"] == 0 and "requires auto" in held_arm.get("error", ""),
        "auto_requires_dedicated_approved_gate": "approved gate" in unapproved.get("error", "")
        and "dedicated PR gate" in attached.get("error", "")
        and automatic["policy"] == "auto" and automatic["approval_gate"] == gate and automatic["auto_merge"] == 0,
        "arm_uses_observed_head": armed["auto_merge"] == 1
        and [call for call in calls if call[:2] == ["pr", "merge"]] == [
            ["pr", "merge", str(number), "--disable-auto"],
            ["pr", "merge", str(number), "--auto", "--squash", "--match-head-commit", armed["head_sha"]],
        ],
        "wait_sync_reports_failure": [event["kind"] for event in passed["events"]] == ["pr-checks-passed"]
        and [event["kind"] for event in failed["events"]] == ["pr-checks-failed"]
        and failed["events"][0]["task_id"] == task,
        "sync_records_merge_and_unblocks_dependent": synced["state"] == "MERGED"
        and synced["merged_commit"] == armed["head_sha"]
        and [event["kind"] for event in merged["events"]] == ["pr-merged"]
        and blocked is None and available is not None and available["task_id"] == dependent,
    }


def migrate_v4(box, run):
    legacy_script = box.root / "team_up_v4.py"
    legacy_script.write_text(box.git("show", f"{V4_REVISION}:{SCRIPT.relative_to(SOURCE)}"))
    legacy_db = box.root / "legacy.db"

    def legacy(*args, cwd=None):
        return json.loads(box.command(PYTHON, legacy_script, "--db", legacy_db, *args, cwd=cwd).stdout)

    legacy_init = legacy("init")
    old_run = legacy("run-create", "--goal", "Preserve this v4 run", "--slots", 1, "--base", "main")["id"]
    task = legacy("task-create", old_run, "--worker", "codex", "--goal", "Preserve this task",
                  "--scope", "read-only", "--evidence", "Full result")["id"]
    dispatch = legacy("reserve", old_run, "--task", task, "--worktree", box.worker, "--branch", "worker")["id"]
    session = f"v4-fixture:{dispatch}"
    legacy("begin", dispatch)
    legacy("started", dispatch, "--turn", 1, "--runtime", session, "--session", session)
    question = legacy("record", dispatch, "--turn", 1, "Keep this question?", cwd=box.worker)["id"]
    legacy("turn-ended", dispatch, "--turn", 1)
    legacy("exited", dispatch, "--turn", 1, "--code", 0)
    before = legacy("status", old_run)

    def migrated(*args, **kwargs):
        return box.command(PYTHON, SCRIPT, "--db", legacy_db, *args, **kwargs)

    denied = migrated("status", old_run, allowed=(0, 1))
    init = json.loads(migrated("init").stdout)
    after = json.loads(migrated("status", old_run).stdout)
    note = json.loads(migrated("note", old_run, "A v5 note on the preserved Run").stdout)
    migrated("answer", question, "Yes")
    resumed = json.loads(migrated("begin", dispatch).stdout)
    before_repeat = json.loads(migrated("status", old_run).stdout)
    repeated = json.loads(migrated("init").stdout)
    after_repeat = json.loads(migrated("status", old_run).stdout)
    with closing(sqlite3.connect(f"{legacy_db.as_uri()}?mode=ro", uri=True)) as db:
        integrity = db.execute("PRAGMA integrity_check").fetchall()
        foreign_keys = db.execute("PRAGMA foreign_key_check").fetchall()
    box.save("migration.json", {"legacy_init": legacy_init, "before": before, "after": after,
                                 "init": init, "repeat_init": repeated, "resumed": resumed,
                                 "before_repeat": before_repeat, "after_repeat": after_repeat,
                                 "integrity": integrity, "foreign_keys": foreign_keys})
    preserved = all(
        [{key: row[key] for key in old} for row, old in zip(after[table], before[table])] == before[table]
        and len(after[table]) == len(before[table])
        for table in ("tasks", "dispatches", "messages", "gates", "dependencies", "task_gates")
    )
    return {
        "init_required_for_v4": legacy_init["schema_version"] == 4 and denied.returncode == 1
        and "run init" in denied.stderr,
        "in_place_v5_upgrade_is_idempotent": init["schema_version"] == 5 and init["db"] == legacy_init["db"]
        and init == repeated and before_repeat == after_repeat and integrity == [("ok",)] and foreign_keys == [],
        "v4_history_and_v5_defaults": preserved
        and {key: after["run"][key] for key in before["run"]} == before["run"]
        and after["run"]["notes_version"] == 0 and after["notes"] == [] and after["pull_requests"] == []
        and all(after["dispatches"][0][key] is None for key in
                ("notes_version", "progress_text", "progress_step", "progress_total", "progress_at")),
        "v4_dispatch_resumes_with_v5_note": resumed["id"] == dispatch and resumed["session"] == session
        and resumed["turn"] == 2 and resumed["notes"] == note["text"]
        and resumed["notes_version"] == 1 and resumed["messages"][0]["answer"] == "Yes",
    }


JOURNEYS = {
    "lifecycle": (lifecycle, 1),
    "questions": (questions, 1),
    "gate": (gate, 2),
    "instructions": (instructions, 1),
    "review-main": (review_main, 1),
    "board": (board, 1),
    "run-notes": (run_notes, 1),
    "progress": (worker_progress, 1),
    "board-html": (html_board, 1),
    "pr-follow-up": (pr_follow_up, 1),
    "migration-v5": (migrate_v4, 1),
}


def drive(box, name):
    marker = box.evidence / "journey.txt"
    with marker.open("x") as file:
        file.write(name + "\n")
    journey, slots = JOURNEYS[name]
    run = box.run(name, slots)
    try:
        checks = journey(box, run)
        passed = all(checks.values())
        report = {"journey": name, "verdict": "PASS" if passed else "FAILING", "checks": checks}
        box.save("verdict.json", report)
        print(json.dumps(report))
        return 0 if passed else 1
    finally:
        box.status(run)
        box.capture()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    commands.add_parser("launch").add_argument("evidence")
    for name in ("doctor", "drive", "cleanup"):
        command = commands.add_parser(name)
        command.add_argument("sandbox")
        if name == "drive":
            command.add_argument("journey", choices=JOURNEYS)
    args = parser.parse_args()
    try:
        if args.action == "launch":
            launch(args.evidence)
        else:
            box = Sandbox.open(args.sandbox)
            if args.action == "doctor":
                result = box.doctor()
                print(json.dumps(result, indent=2))
            elif args.action == "drive":
                return drive(box, args.journey)
            else:
                cleanup(box)
    except (OSError, RuntimeError, ValueError, sqlite3.Error, subprocess.SubprocessError) as error:
        print(f"sandbox: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
