#!/usr/bin/env python3
"""Lane and worktree manager for the Receipts build. Run from anywhere inside the repository.

  scaffold            create per-service stubs, make/lane-*.mk and .gitignore entries on the current branch
  create [lanes...]   create a git worktree and branch per lane (default: all wave-1 lanes)
  prompts [lanes...]  render agents/launch/<lane>.md, one launch prompt per agent tab
  list                dashboard of lanes: branch, ahead/behind, dirty, agent state
  sync [lanes...]     rebase clean lane branches onto the base branch
  gate <lane>         run the merge gate in the lane worktree
  remove <lane>       remove a lane worktree

Configuration lives in agents/lanes.json.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KIT = ROOT / "agents"
CONFIG = json.loads((KIT / "lanes.json").read_text(encoding="utf-8"))
LANES: dict[str, dict] = CONFIG["lanes"]
WT_ROOT = ROOT.parent / f"{ROOT.name}-wt"

GITIGNORE = ["out/", "*.egg-info/", ".agent/", ".venv/", "__pycache__/", ".pytest_cache/", ".ruff_cache/", "node_modules/",
             "agents/launch/", ".env"]


def run(cmd, cwd=ROOT, check=True, capture=True, shell=False):
    r = subprocess.run(cmd, cwd=cwd, text=True, capture_output=capture, shell=shell)
    if check and r.returncode != 0:
        sys.exit(f"command failed: {cmd}\n{r.stdout}\n{r.stderr}")
    return r


def git(*args, cwd=ROOT, check=True):
    return run(["git", *args], cwd=cwd, check=check)


def base_branch(args) -> str:
    if getattr(args, "base", None):
        return args.base
    if git("rev-parse", "--verify", "main", check=False).returncode == 0:
        return "main"
    return git("symbolic-ref", "--short", "HEAD").stdout.strip()


def branch_of(name: str) -> str:
    return f"lane/{LANES[name]['spec']}"


def worktree_of(name: str) -> Path:
    return WT_ROOT / name


def select(names: list[str], force: bool = False) -> list[str]:
    if not names:
        return [n for n, l in LANES.items() if not l.get("skip_create")]
    for n in names:
        if n not in LANES:
            sys.exit(f"unknown lane '{n}'. known: {', '.join(LANES)}")
        if LANES[n].get("skip_create") and not force:
            sys.exit(f"lane '{n}' is not created by default ({LANES[n].get('notes', '')}). Use --force.")
    return names


def ensure_lines(path: Path, lines: list[str]) -> list[str]:
    path.parent.mkdir(parents=True, exist_ok=True)
    have = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    add = [l for l in lines if l not in have]
    if add:
        with path.open("a", encoding="utf-8") as f:
            if have and not path.read_text(encoding="utf-8").endswith("\n"):
                f.write("\n")
            f.write("\n".join(add) + "\n")
    return add


# ----------------------------------------------------------------------------- scaffold
def mk_text(name: str, lane: dict) -> str:
    body = "".join(f"\t{c}\n" for c in lane.get("accept_cmds", [])) or '\t@echo "no acceptance commands yet for ' + name + '"\n'
    pkg = lane.get("scaffold")
    path = (f"export PYTHONPATH := $(CURDIR)/services/{pkg}/src$(if $(PYTHONPATH),:$(PYTHONPATH))\n\n") if pkg else ""
    return (f"# Owned by lane {name}. Edit only from the {name} worktree.\n{path}"
            f".PHONY: accept-{name}\naccept-{name}:\n{body}")


def cmd_scaffold(args):
    made = []
    for name, lane in LANES.items():
        mk = ROOT / "make" / f"lane-{name}.mk"
        if not mk.exists() and not lane.get("skip_create"):
            mk.parent.mkdir(exist_ok=True)
            mk.write_text(mk_text(name, lane), encoding="utf-8")
            made.append(str(mk.relative_to(ROOT)))
        pkg = lane.get("scaffold")
        if not pkg:
            continue
        svc = ROOT / "services" / pkg
        if svc.exists():
            continue
        (svc / "src" / pkg).mkdir(parents=True)
        (svc / "tests").mkdir()
        (svc / "pyproject.toml").write_text(
            '[build-system]\nrequires = ["setuptools>=68"]\nbuild-backend = "setuptools.build_meta"\n\n'
            f'[project]\nname = "receipts-{pkg}"\nversion = "0.1.0"\nrequires-python = ">=3.12"\n'
            '# receipts_common and contracts come from the shared environment (make setup); do not pin them here.\n'
            'dependencies = []\n\n[tool.setuptools.packages.find]\nwhere = ["src"]\n\n[tool.pytest.ini_options]\npythonpath = ["src"]\n', encoding="utf-8")
        (svc / "src" / pkg / "__init__.py").write_text(f'"""Lane {name}."""\n', encoding="utf-8")
        (svc / "tests" / "test_smoke.py").write_text(f"def test_imports():\n    import {pkg}  # noqa: F401\n", encoding="utf-8")
        made.append(str(svc.relative_to(ROOT)))
    (ROOT / "docs" / "lanes").mkdir(parents=True, exist_ok=True)
    keep = ROOT / "docs" / "lanes" / ".gitkeep"
    keep.touch()
    added = ensure_lines(ROOT / ".gitignore", GITIGNORE)
    print("created:", *(made or ["(nothing new)"]), sep="\n  ")
    if added:
        print(".gitignore += " + ", ".join(added))
    mf = ROOT / "Makefile"
    if mf.exists() and "make/*.mk" not in mf.read_text(encoding="utf-8"):
        print("\nNEXT: add this line to the root Makefile, and delete its placeholder accept-<lane> targets:\n  -include make/*.mk")
    print("\nThen commit on main before creating worktrees:  git add -A && git commit -m 'chore: lane scaffolding'")


# ----------------------------------------------------------------------------- create
def cmd_create(args):
    base = base_branch(args)
    for name in select(args.lanes, args.force):
        path = worktree_of(name)
        if path.exists():
            print(f"{name}: worktree exists, skipping")
            continue
        branch = branch_of(name)
        exists = git("rev-parse", "--verify", branch, check=False).returncode == 0
        if exists:
            git("worktree", "add", str(path), branch)
        else:
            git("worktree", "add", "-b", branch, str(path), base)
        agent = path / ".agent"
        agent.mkdir(exist_ok=True)
        (agent / "STATUS.md").write_text((KIT / "status.template.md").read_text(encoding="utf-8"), encoding="utf-8")
        for f in ("QUESTIONS.md", "LOG.md"):
            (agent / f).touch()
        common = Path(git("rev-parse", "--git-common-dir").stdout.strip())
        common = common if common.is_absolute() else ROOT / common
        ensure_lines(common / "info" / "exclude", [".agent/", ".venv/"])
        print(f"{name}: {path}  [{branch}]")
        if args.setup:
            run([sys.executable, "-m", "venv", ".venv"], cwd=path)
            r = run(["make", "setup", f"PY={path / '.venv' / 'bin' / 'python'}"], cwd=path, check=False)
            print(f"  setup: {'ok' if r.returncode == 0 else 'FAILED (run make setup in the worktree)'}")


# ----------------------------------------------------------------------------- prompts
def fmt_list(items):
    return "\n".join(f"- `{i}`" for i in items) if items else "- (see spec)"


def cmd_prompts(args):
    tmpl = (KIT / "prompts" / "launch.md.tmpl").read_text(encoding="utf-8")
    out = KIT / "launch"
    out.mkdir(exist_ok=True)
    review = ("Delegate the review to a fresh subagent using your subagent tool, with the prompt in "
              "`agents/prompts/reviewer.md` filled in (task, round, commit, worktree). The subagent must not edit non-test source."
              if args.subagents else
              "Write `.agent/REVIEW-REQUEST.md` with the commit hash and stop. The human runs the reviewer prompt "
              "(`agents/prompts/reviewer.md`) in another tab and tells you when the review file exists.")
    for name in select(args.lanes or list(LANES), force=True):
        lane = LANES[name]
        cmds = lane.get("accept_cmds", [])
        values = {
            "LANE": name, "NUM": lane["num"], "SPEC": lane["spec"], "BRANCH": branch_of(name),
            "WORKTREE": str(worktree_of(name)), "OWNS": fmt_list(lane["owns"]),
            "DEPENDS": "Foundation (`services/common`, merged on `main`) and `contracts/`.",
            "STUBS": lane.get("stubs") or lane.get("notes") or "None.",
            "ACCEPT_NOTE": ("Seed recipe in `make/lane-%s.mk`: %s. Extend it as the spec's acceptance task says."
                            % (name, "; ".join(f"`{c}`" for c in cmds))) if cmds else "Define it per the spec's acceptance task.",
            "REVIEW_STEP": review,
        }
        text = tmpl
        for k, v in values.items():
            text = text.replace("{{" + k + "}}", v)
        assert not re.search(r"\{\{[A-Z_]+\}\}", text), "unfilled placeholder"
        (out / f"{name}.md").write_text(text, encoding="utf-8")
        print(f"agents/launch/{name}.md")


# ----------------------------------------------------------------------------- list / sync / gate / remove
def agent_state(path: Path) -> str:
    f = path / ".agent" / "STATUS.md"
    if not f.exists():
        return "-"
    kv = dict(re.findall(r"^(state|task|round):\s*(\S*)", f.read_text(encoding="utf-8"), re.M))
    return f"{kv.get('state', '?')} t{kv.get('task', '?')} r{kv.get('round', '?')}"


def cmd_list(args):
    base = base_branch(args)
    print(f"{'lane':<12}{'branch':<26}{'vs ' + base:<14}{'dirty':<7}{'agent'}")
    for name, lane in LANES.items():
        path = worktree_of(name)
        if not path.exists():
            print(f"{name:<12}{branch_of(name):<26}{'-':<14}{'-':<7}{'(no worktree)' if not lane.get('skip_create') else '(managed elsewhere)'}")
            continue
        r = git("rev-list", "--left-right", "--count", f"{base}...{branch_of(name)}", check=False)
        behind, ahead = (r.stdout.split() + ["?", "?"])[:2]
        dirty = "yes" if git("status", "--porcelain", cwd=path, check=False).stdout.strip() else "no"
        print(f"{name:<12}{branch_of(name):<26}{'+%s -%s' % (ahead, behind):<14}{dirty:<7}{agent_state(path)}")


def cmd_sync(args):
    base = base_branch(args)
    for name in args.lanes or [n for n in LANES if worktree_of(n).exists()]:
        path = worktree_of(name)
        if not path.exists():
            continue
        if git("status", "--porcelain", cwd=path, check=False).stdout.strip():
            print(f"{name}: dirty, skipped (commit or stash first)")
            continue
        r = git("rebase", base, cwd=path, check=False)
        if r.returncode != 0:
            git("rebase", "--abort", cwd=path, check=False)
            print(f"{name}: CONFLICT, rebase aborted. Resolve in the worktree.\n{r.stdout.strip()[-300:]}")
        else:
            print(f"{name}: rebased onto {base}")


def cmd_gate(args):
    name = args.lane
    if name not in LANES:
        sys.exit(f"unknown lane {name}")
    path = worktree_of(name)
    if not path.exists():
        sys.exit(f"no worktree for {name}")
    base = base_branch(args)
    behind = git("rev-list", "--count", f"{branch_of(name)}..{base}", cwd=path).stdout.strip()
    if behind != "0":
        sys.exit(f"GATE FAIL: {name} is {behind} commits behind {base}. Run: python scripts/lanes.py sync {name}")
    if git("status", "--porcelain", cwd=path).stdout.strip():
        sys.exit("GATE FAIL: worktree is dirty")
    for tmpl in CONFIG["gate_cmds"]:
        cmd = tmpl.format(lane=name)
        print(f"$ {cmd}")
        if run(cmd, cwd=path, check=False, capture=False, shell=True).returncode != 0:
            sys.exit(f"GATE FAIL at: {cmd}")
    print(f"GATE OK: {name}. Merge with: git merge --no-ff {branch_of(name)} -m 'lane({name}): <summary>'")


def cmd_remove(args):
    path = worktree_of(args.lane)
    if not path.exists():
        sys.exit("no such worktree")
    git("worktree", "remove", *(["--force"] if args.force else []), str(path))
    print(f"removed {path} (branch {branch_of(args.lane)} kept)")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", help="base branch (default: main, else current)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("scaffold").set_defaults(fn=cmd_scaffold)
    p = sub.add_parser("create"); p.add_argument("lanes", nargs="*"); p.add_argument("--setup", action="store_true")
    p.add_argument("--force", action="store_true"); p.set_defaults(fn=cmd_create)
    p = sub.add_parser("prompts"); p.add_argument("lanes", nargs="*")
    p.add_argument("--no-subagents", dest="subagents", action="store_false"); p.set_defaults(fn=cmd_prompts, subagents=True)
    sub.add_parser("list").set_defaults(fn=cmd_list)
    p = sub.add_parser("sync"); p.add_argument("lanes", nargs="*"); p.set_defaults(fn=cmd_sync)
    p = sub.add_parser("gate"); p.add_argument("lane"); p.set_defaults(fn=cmd_gate)
    p = sub.add_parser("remove"); p.add_argument("lane"); p.add_argument("--force", action="store_true"); p.set_defaults(fn=cmd_remove)
    args = ap.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
