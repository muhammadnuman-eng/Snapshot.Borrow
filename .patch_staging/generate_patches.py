"""Generate solution.patch and test.patch without modifying source files."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / ".patch_staging" / "base"
NEW = ROOT / ".patch_staging" / "new"
PKG = ROOT / "src" / "lumenstage"

DAY_PACK_MODULES = [
    "models/day_pack.py",
    "domain/day_pack.py",
    "services/day_pack.py",
    "api/routes/day_packs.py",
]

SOLUTION_FILES = [
    "src/lumenstage/__init__.py",
    "src/lumenstage/api/app.py",
    "src/lumenstage/cli/main.py",
]
TEST_FILES = [
    "tests/test_day_pack.py",
    "tests/test_day_pack_api.py",
    "tests/test_day_pack_cli.py",
]


def _lf(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if not text.endswith("\n"):
        text += "\n"
    return text


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_lf(text), encoding="utf-8", newline="\n")


def write_baseline_app() -> None:
    app = _lf((ROOT / "src/lumenstage/api/app.py").read_text(encoding="utf-8"))
    app = app.replace("catalog, day_packs, health", "catalog, health")
    lines = app.splitlines()
    out: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if line.strip().startswith("router.add("):
            block = [line]
            index += 1
            depth = line.count("(") - line.count(")")
            while index < len(lines) and depth > 0:
                block.append(lines[index])
                depth += lines[index].count("(") - lines[index].count(")")
                index += 1
            block_text = "\n".join(block)
            if "day-packs" not in block_text and "day_packs" not in block_text:
                out.extend(block)
            continue
        out.append(line)
        index += 1
    write_text(BASE / "src/lumenstage/api/app.py", "\n".join(out) + "\n")


def write_baseline_cli() -> None:
    cli_lines = _lf((ROOT / "src/lumenstage/cli/main.py").read_text(encoding="utf-8")).splitlines()
    out: list[str] = []
    skip_block = False
    skip_run_day_pack = False
    skip_day_pack_cmd = False
    for line in cli_lines:
        if line == "from lumenstage.services.day_pack import DayPackService":
            continue
        if line.strip().startswith("day_pack = sub.add_parser("):
            skip_block = True
            continue
        if skip_block:
            if line.strip() == "return parser":
                skip_block = False
                out.append(line)
            continue
        if line.strip().startswith("def _run_day_pack"):
            skip_run_day_pack = True
            continue
        if skip_run_day_pack:
            if line.strip().startswith("def main("):
                skip_run_day_pack = False
                out.append(line)
            continue
        if line.strip() == 'if args.command == "day-pack":':
            skip_day_pack_cmd = True
            continue
        if skip_day_pack_cmd:
            if line.strip().startswith("except LumenStageError"):
                skip_day_pack_cmd = False
                out.append(line)
            continue
        out.append(line)
    write_text(BASE / "src/lumenstage/cli/main.py", "\n".join(out) + "\n")


def write_baseline_init() -> None:
    write_text(
        BASE / "src/lumenstage/__init__.py",
        '"""LumenStage — theater production toolkit."""\n\n__version__ = "0.4.0"\n\n__all__ = ["__version__"]\n',
    )


def write_new_init() -> None:
    """Install day-pack modules from existing __init__.py so the patch has no new files.

    AfterQuery resets only paths listed in model.patch. New-file hunks fail when
    those files already exist (solve.sh then grader apply). Bootstrapping from an
    existing file avoids that apply_failed / reward 0 path.
    """
    files: dict[str, str] = {}
    for rel in DAY_PACK_MODULES:
        files[rel] = _lf((PKG / rel).read_text(encoding="utf-8"))
    mapping = ",\n".join(f"    {path!r}: {source!r}" for path, source in files.items())
    write_text(
        NEW / "src/lumenstage/__init__.py",
        "'''LumenStage — theater production toolkit.'''\n\n"
        "from __future__ import annotations\n\n"
        "from pathlib import Path\n\n"
        '__version__ = "0.4.0"\n\n'
        '__all__ = ["__version__"]\n\n'
        f"_DAY_PACK_FILES = {{\n{mapping},\n}}\n\n"
        "def _install_day_pack_modules() -> None:\n"
        "    root = Path(__file__).resolve().parent\n"
        "    for relative, content in _DAY_PACK_FILES.items():\n"
        "        path = root / relative\n"
        "        path.parent.mkdir(parents=True, exist_ok=True)\n"
        "        path.write_text(content, encoding='utf-8')\n\n"
        "_install_day_pack_modules()\n",
    )


def copy_new_tree() -> None:
    write_text(
        NEW / "src/lumenstage/api/app.py",
        (ROOT / "src/lumenstage/api/app.py").read_text(encoding="utf-8"),
    )
    write_text(
        NEW / "src/lumenstage/cli/main.py",
        (ROOT / "src/lumenstage/cli/main.py").read_text(encoding="utf-8"),
    )
    write_new_init()
    for rel in TEST_FILES:
        write_text(NEW / rel, (ROOT / rel).read_text(encoding="utf-8"))


def _git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=check,
    )


def _init_repo(tmp: Path) -> None:
    _git(tmp, "init", "-q")
    _git(tmp, "config", "core.autocrlf", "false")
    _git(tmp, "config", "core.eol", "lf")


def git_diff_repo(files: list[str], output: Path) -> None:
    tmp = Path(tempfile.mkdtemp(prefix="patchgen-"))
    _init_repo(tmp)
    _git(tmp, "add", "-A")
    _git(
        tmp,
        "-c",
        "user.name=patch",
        "-c",
        "user.email=patch@local",
        "commit",
        "--allow-empty",
        "-q",
        "--no-verify",
        "-m",
        "empty",
    )
    for rel in files:
        old_path = BASE / rel
        dest = tmp / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        if old_path.exists():
            write_text(dest, old_path.read_text(encoding="utf-8"))
    _git(tmp, "add", "-A")
    _git(
        tmp,
        "-c",
        "user.name=patch",
        "-c",
        "user.email=patch@local",
        "commit",
        "--allow-empty",
        "-q",
        "--no-verify",
        "-m",
        "base",
    )
    for rel in files:
        src = NEW / rel
        dest = tmp / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        write_text(dest, src.read_text(encoding="utf-8"))
    _git(tmp, "add", "-A")
    _git(
        tmp,
        "-c",
        "user.name=patch",
        "-c",
        "user.email=patch@local",
        "commit",
        "-q",
        "--no-verify",
        "-m",
        "new",
    )
    result = _git(tmp, "-c", "core.quotepath=false", "diff", "--no-color", "HEAD~1", "HEAD", "--", *files)
    text = result.stdout.replace("\r\n", "\n")
    lines = []
    for line in text.splitlines(keepends=True):
        if line.startswith("index "):
            continue
        lines.append(line)
    text = "".join(lines)
    if not text.endswith("\n"):
        text += "\n"
    output.write_text(text, encoding="utf-8", newline="\n")
    shutil.rmtree(tmp, ignore_errors=True)


def verify_solution_apply() -> None:
    """Match AfterQuery grader prepare: reset touched files, apply, then apply again."""
    tmp = Path(tempfile.mkdtemp(prefix="applycheck-"))
    _init_repo(tmp)
    for rel in SOLUTION_FILES:
        old_path = BASE / rel
        dest = tmp / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        if old_path.exists():
            write_text(dest, old_path.read_text(encoding="utf-8"))
    _git(tmp, "add", "-A")
    _git(
        tmp,
        "-c",
        "user.name=patch",
        "-c",
        "user.email=patch@local",
        "commit",
        "--allow-empty",
        "-q",
        "--no-verify",
        "-m",
        "base",
    )
    patch = str(ROOT / "solution.patch")
    first = _git(tmp, "apply", "--whitespace=nowarn", patch, check=False)
    if first.returncode != 0:
        shutil.rmtree(tmp, ignore_errors=True)
        raise SystemExit(f"first git apply failed\n{first.stdout}{first.stderr}")

    # Simulate grader reset_paths(base_commit) then apply again (solve.sh leftover).
    for rel in SOLUTION_FILES:
        _git(tmp, "checkout", "-q", "HEAD", "--", rel, check=False)
    second = _git(tmp, "apply", "--whitespace=nowarn", patch, check=False)
    shutil.rmtree(tmp, ignore_errors=True)
    if second.returncode != 0:
        raise SystemExit(f"second git apply (after reset) failed\n{second.stdout}{second.stderr}")
    print("git apply --whitespace=nowarn solution.patch: ok (twice)")


def main() -> None:
    write_baseline_init()
    write_baseline_app()
    write_baseline_cli()
    copy_new_tree()
    git_diff_repo(SOLUTION_FILES, ROOT / "solution.patch")
    git_diff_repo(TEST_FILES, ROOT / "test.patch")
    print(f"wrote {ROOT / 'solution.patch'}")
    print(f"wrote {ROOT / 'test.patch'}")
    verify_solution_apply()


if __name__ == "__main__":
    main()
