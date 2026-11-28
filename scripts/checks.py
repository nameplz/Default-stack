import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tokenize


TESTS = "plugin/skills/team-up/scripts/tests"
MANIFESTS = ("plugin/plugin.json", "plugin/.claude-plugin/plugin.json")
BASE_REFS = ("origin/main", "main")
DIRECTIVE = re.compile(r"#\s*(noqa|type:|pragma|pylint:|fmt:|SPDX-License-Identifier)")
LINK = re.compile(r"\]\(([^)\s]+)\)")
HUNK = re.compile(r"^@@ -\S+ \+(\d+)(?:,(\d+))? @@")
NO_COMMENT = "remove the comment and move the reason into a name, type, test or commit message"


def git(*args):
    return subprocess.run(["git", "-c", "core.quotePath=false", *args], cwd=ROOT,
                          capture_output=True, text=True, check=True).stdout


ROOT = Path(subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True,
                           text=True, check=True).stdout.strip())


def files():
    names = git("ls-files", "-z", "--cached", "--others", "--exclude-standard").split("\0")
    return sorted({name for name in names if name and (ROOT / name).is_file()
                   and not (ROOT / name).is_symlink()})


def untracked():
    return [name for name in git("ls-files", "-z", "--others", "--exclude-standard").split("\0")
            if name and (ROOT / name).is_file() and not (ROOT / name).is_symlink()]


def merge_base():
    override = os.environ.get("VERIFY_BASE")
    if override:
        return git("rev-parse", "--verify", override + "^{commit}").strip()
    for ref in BASE_REFS:
        found = subprocess.run(["git", "rev-parse", "--verify", "-q", ref + "^{commit}"], cwd=ROOT,
                               capture_output=True, text=True)
        if found.returncode == 0:
            return git("merge-base", "HEAD", ref).strip()
    raise SystemExit(f"verify: none of {', '.join(BASE_REFS)} exists; set VERIFY_BASE to the branch point")


def changed_lines(base):
    changed = {name: None for name in untracked()}
    current = None
    for line in git("diff", "-U0", "-M", "--no-color", "--diff-filter=AMR", base, "--").splitlines():
        if line.startswith("+++ "):
            current = line[6:] if line.startswith("+++ b/") else None
            if current is not None:
                changed.setdefault(current, set())
        elif current is not None and changed[current] is not None:
            hunk = HUNK.match(line)
            if hunk:
                start, count = int(hunk.group(1)), int(hunk.group(2) or 1)
                changed[current].update(range(start, start + count))
    return changed


def language(name):
    path = ROOT / name
    if path.suffix == ".py":
        return "python"
    if path.suffix == ".sh":
        return "shell"
    with path.open("rb") as file:
        first = file.readline()
    if first.startswith(b"#!"):
        return "python" if b"python" in first else "shell" if b"sh" in first else None
    return None


def comment_lines(name, kind):
    text = (ROOT / name).read_text()
    if kind == "python":
        tokens = tokenize.generate_tokens(io.StringIO(text).readline)
        found = [(token.start[0], token.string) for token in tokens if token.type == tokenize.COMMENT]
    else:
        found = [(number, line.strip()) for number, line in enumerate(text.splitlines(), 1)
                 if line.lstrip().startswith("#")]
    return [(number, comment) for number, comment in found
            if not (number == 1 and comment.startswith("#!")) and not DIRECTIVE.match(comment)]


def check_compile(base):
    errors = []
    for name in files():
        if name.endswith(".py"):
            try:
                compile((ROOT / name).read_text(), name, "exec")
            except SyntaxError as error:
                errors.append(f"{name}:{error.lineno}: {error.msg}; fix the syntax error")
    return errors


def check_json(base):
    errors = []
    for name in files():
        if name.endswith(".json"):
            try:
                json.loads((ROOT / name).read_text())
            except ValueError as error:
                errors.append(f"{name}: {error}; fix the JSON")
    return errors


def manifest(name):
    return json.loads((ROOT / name).read_text())


def version_tuple(version):
    return tuple(int(part) for part in version.split("."))


def check_manifests(base):
    values = {name: (manifest(name)["name"], manifest(name)["version"]) for name in MANIFESTS}
    if len(set(values.values())) > 1:
        listed = ", ".join(f"{name}={value[0]}@{value[1]}" for name, value in values.items())
        return [f"plugin manifests disagree ({listed}); set the same name and version in both"]
    return []


def check_version_bump(base):
    changed = sorted(set(git("diff", "--name-only", "-z", base, "--", "plugin").split("\0"))
                     | {name for name in untracked() if name.startswith("plugin/")})
    changed = [name for name in changed if name]
    if not changed:
        return []
    old = json.loads(git("show", f"{base}:{MANIFESTS[0]}"))["version"]
    new = manifest(MANIFESTS[0])["version"]
    if version_tuple(new) > version_tuple(old):
        return []
    return [f"{len(changed)} file(s) under plugin/ changed since {base[:7]} (first: {changed[0]}) "
            f"but the plugin version is still {new}; bump \"version\" above {old} in "
            f"{' and '.join(MANIFESTS)} so existing installs receive the change"]


def check_plugin_links(base):
    plugin = (ROOT / "plugin").resolve()
    errors = []
    for name in files():
        if not (name.startswith("plugin/") and name.endswith(".md")):
            continue
        path = ROOT / name
        for number, line in enumerate(path.read_text().splitlines(), 1):
            for target in LINK.findall(line):
                if re.match(r"^[a-z][a-z0-9+.-]*:", target) or target.startswith("#"):
                    continue
                resolved = (path.parent / target.split("#")[0]).resolve()
                if plugin not in resolved.parents and resolved != plugin:
                    errors.append(f"{name}:{number}: links to {target} outside plugin/, which installs do "
                                  "not ship; move the target into plugin/ or link to its GitHub URL")
                elif not resolved.exists():
                    errors.append(f"{name}:{number}: links to missing {target}; fix the path")
    return errors


def check_comments(base):
    errors = []
    for name, lines in sorted(changed_lines(base).items()):
        path = ROOT / name
        if not path.is_file() or path.is_symlink():
            continue
        kind = language(name)
        if kind is None:
            continue
        for number, comment in comment_lines(name, kind):
            if lines is None or number in lines:
                errors.append(f"{name}:{number}: {comment}; {NO_COMMENT}")
    return errors


def check_tests(base):
    result = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", TESTS], cwd=ROOT)
    return [] if result.returncode == 0 else [f"unittest exited {result.returncode}; fix the failing tests above"]


CHECKS = (
    ("compile", check_compile),
    ("json", check_json),
    ("manifests", check_manifests),
    ("version-bump", check_version_bump),
    ("plugin-links", check_plugin_links),
    ("no-comments", check_comments),
    ("unittest", check_tests),
)


def main():
    base = merge_base()
    print(f"verify: base {base[:12]}", flush=True)
    failed = []
    for name, check in CHECKS:
        errors = check(base)
        print(f"{'FAIL' if errors else 'ok  '} {name}", flush=True)
        for error in errors:
            print(f"  {error}", flush=True)
        if errors:
            failed.append(name)
    if failed:
        print(f"verify: FAILED ({', '.join(failed)})")
        return 1
    print("verify: passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
