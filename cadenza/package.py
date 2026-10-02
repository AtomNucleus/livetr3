#!/usr/bin/env python3
"""Build a relocatable Cadenza.app from the installed runtime and cached model."""
import argparse
import importlib.metadata as metadata
import json
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys

from packaging.requirements import Requirement

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent


def run(*args):
    subprocess.run([str(a) for a in args], check=True)


def copy(source, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    # APFS clones avoid duplicating 8 GB of cached weights on the build machine.
    # Fall back to an ordinary copy on filesystems without clone support.
    try:
        run("/bin/cp", "-cRL", source, destination)
    except subprocess.CalledProcessError:
        if destination.is_dir():
            shutil.rmtree(destination)
        elif destination.exists():
            destination.unlink()
        if source.is_dir():
            shutil.copytree(source, destination, symlinks=False)
        else:
            shutil.copy2(source, destination)


def installed_dependencies():
    found = {}
    def visit(name):
        dist = metadata.distribution(name)
        key = dist.metadata["Name"].lower().replace("_", "-")
        if key in found:
            return
        found[key] = dist
        for text in dist.requires or []:
            req = Requirement(text)
            if req.marker is None or req.marker.evaluate({"extra": ""}):
                visit(req.name)
    for name in ["mlx", "mlx-vlm", "numpy", "soundfile"]:
        visit(name)
    return found


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python-runtime", type=Path,
                        default=Path.home()/".local/share/uv/python/cpython-3.13.13-macos-aarch64-none")
    parser.add_argument("--output", type=Path, default=REPO/"dist/Cadenza.app")
    args = parser.parse_args()
    from engine.raw_model import cached_model, REVISION
    model = cached_model()
    if not (args.python_runtime/"bin/python3").exists():
        parser.error("Standalone Python runtime missing; provide --python-runtime")
    if sys.version_info[:2] != (3, 13):
        parser.error("Run with the installed MLX Python 3.13 environment")
    dependencies = installed_dependencies()
    expected = {"mlx": "0.32.2", "mlx-vlm": "0.7.3", "transformers": "5.17.0"}
    for name, version in expected.items():
        if dependencies[name].version != version:
            parser.error(f"Expected {name} {version}, found {dependencies[name].version}")
    lock_path = ROOT / "requirements.lock"
    if lock_path.exists():
        locked = dict(line.split("==", 1) for line in lock_path.read_text().splitlines()
                      if line and not line.startswith("#"))
        installed = {name: dist.version for name, dist in dependencies.items()}
        if locked != installed:
            parser.error("Installed dependency closure differs from requirements.lock")
    run("swift", "build", "-c", "release", "--package-path", ROOT)
    binary_dir = subprocess.check_output(["swift", "build", "-c", "release", "--package-path", str(ROOT),
                                          "--show-bin-path"], text=True).strip()
    destination = args.output.resolve()
    if destination.exists():
        parser.error(f"Output already exists: {destination}; choose another --output or remove your prior build")
    staging = destination.with_suffix(".staging")
    if staging.exists():
        parser.error(f"Staging already exists: {staging}")
    resources = staging/"Contents/Resources"
    macos = staging/"Contents/MacOS"
    macos.mkdir(parents=True)
    resources.mkdir(parents=True)
    copy(Path(binary_dir)/"Cadenza", macos/"Cadenza")
    copy(ROOT/"Resources/AppIcon.icns", resources/"AppIcon.icns")
    (resources/"engine").mkdir()
    for name in ["engine.py", "pipeline.py", "raw_model.py"]:
        copy(ROOT/"engine"/name, resources/"engine"/name)
    copy(args.python_runtime, resources/"Python")
    site = resources/"Python/lib/python3.13/site-packages"
    shutil.rmtree(site)
    site.mkdir()
    tops = {}
    for dist in dependencies.values():
        for file in dist.files or []:
            top = str(file).split("/")[0]
            if top in ["..", "."]:
                continue
            tops[top] = Path(dist.locate_file(top))
    for name, source in sorted(tops.items()):
        copy(source, site/name)
    copy(model, resources/"Model")
    versions = {name: dist.version for name, dist in sorted(dependencies.items())}
    (resources/"runtime.json").write_text(json.dumps(dict(model_revision=REVISION, packages=versions), indent=2)+"\n")
    (ROOT/"requirements.lock").write_text("# Installed, verified runtime; package.py copies these distributions.\n" +
                                         "\n".join(f"{name}=={version}" for name, version in versions.items())+"\n")
    info = dict(CFBundleExecutable="Cadenza", CFBundleIdentifier="org.atomnucleus.cadenza",
                CFBundleName="Cadenza", CFBundleDisplayName="Cadenza", CFBundleIconFile="AppIcon",
                CFBundlePackageType="APPL", CFBundleShortVersionString="0.1.0", CFBundleVersion="1",
                LSMinimumSystemVersion="14.0", NSHighResolutionCapable=True,
                NSMicrophoneUsageDescription="Cadenza captures speech for local English and Spanish captions.",
                NSPrincipalClass="NSApplication")
    with (staging/"Contents/Info.plist").open("wb") as file:
        plistlib.dump(info, file)
    # Sign inside out, then verify the complete bundle. Ad-hoc local signature.
    for file in resources.rglob("*"):
        if file.is_file() and not file.is_symlink() and file.suffix in [".so", ".dylib"]:
            run("codesign", "--force", "--sign", "-", file)
    run("codesign", "--force", "--sign", "-", resources/"Python/bin/python3.13")
    run("codesign", "--force", "--deep", "--sign", "-", staging)
    run("codesign", "--verify", "--deep", "--strict", staging)
    staging.rename(destination)
    run(destination/"Contents/Resources/Python/bin/python3", "-B", "-s", "-c",
        "import mlx.core, mlx_vlm, soundfile; print('Bundled imports passed')")
    print(f"Built {destination}")


if __name__ == "__main__":
    main()
