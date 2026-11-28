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


SOURCE = Path(__file__).resolve().parents[4]
SCRIPT = SOURCE / "plugin/skills/team-up/scripts/team_up.py"
TMP = Path("/tmp").resolve()
PREFIX = "verify-team-up-sandbox."
PYTHON = os.environ.get("VERIFY_TEAM_UP_PYTHON", "/usr/bin/python3")
GIT_ENV = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
GIT_ENV.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")
FILE = "README.md"


class Sandbox:
    def __init__(self, root, evidence):
        self.root = root
        self.evidence = evidence
        self.repo = root / "repo"
        self.worker = root / "worker"
        self.db = root / "state.db"
        self.manifest = root / "sandbox.json"

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

    def command(self, *args, cwd=None, allowed=(0,)):
        argv = list(map(str, args))
        cwd = cwd or self.repo
        result = subprocess.run(argv, cwd=cwd, env=GIT_ENV, capture_output=True,
                                text=True, timeout=30)
        with (self.evidence / "commands.jsonl").open("a") as log:
            log.write(json.dumps({"cwd": str(cwd), "argv": argv,
                                  "command": shlex.join(argv), "exit_code": result.returncode,
                                  "stdout": result.stdout, "stderr": result.stderr}) + "\n")
        if result.returncode not in allowed:
            raise RuntimeError(f"{shlex.join(argv)} exited {result.returncode}: {result.stderr.strip()}")
        return result

    def git(self, *args, **kwargs):
        return self.command("git", "-c", "core.hooksPath=/dev/null", *args, **kwargs).stdout

    def team(self, *args, cwd=None):
        return json.loads(self.command(PYTHON, SCRIPT, "--db", self.db, *args, cwd=cwd).stdout)

    def probe(self, *args):
        result = self.command(PYTHON, SCRIPT, "--db", self.db, *args, allowed=(0, 1))
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


JOURNEYS = {
    "lifecycle": (lifecycle, 1),
    "questions": (questions, 1),
    "gate": (gate, 2),
    "instructions": (instructions, 1),
    "review-main": (review_main, 1),
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
