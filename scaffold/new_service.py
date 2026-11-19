#!/usr/bin/env python3
"""Create a new service repository from a platform preset.

  scaffold/new_service.py --name orders-service --team commerce --language python \
      --description "Records orders" --dest ../orders-service [--org example-org] \
      [--image-registry 123456789012.dkr.ecr.us-east-1.amazonaws.com] [--git] [--create-github]

The result builds, tests and deploys with the platform's central workflows unchanged:
the developer fills in business logic, tests, and the `aws:` block of deploy/values-*.yaml
(the new-service skill does the latter interactively). Standard library only.

--create-github runs `gh repo create <org>/<name> --private --source <dest> --push`.
It publishes code, so the new-service skill always confirms with the user first.
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "templates"
PRESETS = {"python": "python-fastapi", "go": "go-http", "java": "java-springboot"}
NAME_RE = re.compile(r"^[a-z]([-a-z0-9]{0,30}[a-z0-9])?$")
TEAM_RE = re.compile(r"^[a-z][-a-z0-9]{1,40}$")
SKIP = {".venv", "__pycache__", ".pytest_cache", ".ruff_cache", "target", ".DS_Store"}
BINARY_SUFFIXES = {".jar", ".png", ".jpg", ".ico"}


def placeholders(a: argparse.Namespace) -> dict[str, str]:
    compact = a.name.replace("-", "")
    org = a.org.lower().replace("-", "")
    repo = f"{a.image_registry}/{a.name}" if a.image_registry else f"localhost:5001/{a.name}"
    return {
        "__SERVICE_NAME__": a.name,
        "__TEAM__": a.team,
        "__DESCRIPTION__": a.description,
        "__IMAGE_REPOSITORY__": repo,
        "__GO_MODULE__": f"github.com/{a.org}/{a.name}",
        "__JAVA_GROUP__": f"com.{org}",
        "__JAVA_PACKAGE__": f"com.{org}.{compact}",
        "__JAVA_PACKAGE_PATH__": f"com/{org}/{compact}",
    }


def render(src: Path, dest: Path, subs: dict[str, str]) -> list[Path]:
    written = []
    for path in sorted(src.rglob("*")):
        rel = path.relative_to(src)
        if any(part in SKIP for part in rel.parts):
            continue
        rel_str = str(rel)
        for k, v in subs.items():
            rel_str = rel_str.replace(k, v)
        target = dest / rel_str
        if path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            text = path.read_text() if path.suffix not in BINARY_SUFFIXES else None
        except UnicodeDecodeError:
            text = None
        if text is None:
            shutil.copy2(path, target)
        else:
            for k, v in subs.items():
                text = text.replace(k, v)
            target.write_text(text)
            shutil.copymode(path, target)
        written.append(target)
    return written


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--name", required=True, help="service name (DNS label, <= 32 chars)")
    p.add_argument("--team", required=True, help="owning team")
    p.add_argument("--language", required=True, choices=sorted(PRESETS))
    p.add_argument("--description", default="A platform microservice.")
    p.add_argument("--dest", required=True, help="directory to create (must not exist)")
    p.add_argument("--org", default="example-org", help="GitHub org")
    p.add_argument("--image-registry", default="", help="ECR registry host (default: local registry)")
    p.add_argument("--git", action="store_true", help="git init and make the initial commit")
    p.add_argument("--create-github", action="store_true", help="create <org>/<name> on GitHub and push")
    a = p.parse_args(argv)

    if not NAME_RE.match(a.name):
        p.error(f"--name {a.name!r}: lowercase letters, digits and '-', start with a letter, <= 32 chars")
    if not TEAM_RE.match(a.team):
        p.error(f"--team {a.team!r}: lowercase letters, digits and '-', 2-41 chars")
    dest = Path(a.dest).resolve()
    if dest.exists():
        p.error(f"{dest} already exists")

    src = TEMPLATES / PRESETS[a.language]
    subs = placeholders(a)
    files = render(src, dest, subs)
    leftover = [
        str(f.relative_to(dest))
        for f in files
        if f.suffix not in BINARY_SUFFIXES and any(k in f.read_text(errors="ignore") for k in subs)
    ]
    if leftover:
        print(f"error: unreplaced placeholders in {leftover}", file=sys.stderr)
        return 1
    print(f"created {a.language} service {a.name!r} at {dest} ({len(files)} files) from templates/{src.name}")

    if a.git or a.create_github:
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=dest, check=True)
        subprocess.run(["git", "add", "-A"], cwd=dest, check=True)
        subprocess.run(
            ["git", "commit", "-q", "-m", f"chore: scaffold {a.name} from {src.name} preset"], cwd=dest, check=True
        )
        print("initialised git repository with the scaffold commit")
    if a.create_github:
        subprocess.run(
            ["gh", "repo", "create", f"{a.org}/{a.name}", "--private", "--source", str(dest), "--push"], check=True
        )
        print(f"created https://github.com/{a.org}/{a.name}")

    print("next: fill in your logic and tests, then set aws: in deploy/values-*.yaml (new-service skill)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
