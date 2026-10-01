#!/usr/bin/env python3
"""Build a relocatable Apple-silicon app from a verified Python and model cache.

No downloads, environment upgrades, app launches or process termination. Large
files use APFS clones where available. The archive is made separately after QA.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess


ROOT = Path(__file__).resolve().parents[1]


def clone_copy(source, destination):
    source = str(Path(source).resolve())
    result = subprocess.run(['cp', '-c', source, str(destination)], capture_output=True)
    if result.returncode:
        shutil.copy2(source, destination)
    else:
        shutil.copystat(source, destination)
    return destination


def ignore(directory, names):
    return [name for name in names if name in {'__pycache__', '.DS_Store', '_virtualenv.pth',
                                              '_virtualenv.py', 'direct_url.json'}]


def copy_tree(source, destination):
    shutil.copytree(source, destination, copy_function=clone_copy, ignore=ignore)


def dylib_id(path):
    lines = subprocess.check_output(['otool', '-D', str(path)], text=True).splitlines()
    return lines[1].strip() if len(lines) > 1 else None


def audit_and_sign(engine):
    # Python wheels can carry absolute LC_ID_DYLIB build paths. IDs are not
    # dependency loads; normalize them, then reject actual non-system loads.
    for path in sorted(engine.rglob('*')):
        if not path.is_file():
            continue
        with path.open('rb') as handle:
            magic = handle.read(4)
        if magic not in {b'\xcf\xfa\xed\xfe', b'\xce\xfa\xed\xfe', b'\xca\xfe\xba\xbe',
                          b'\xca\xfe\xba\xbf', b'\xbe\xba\xfe\xca', b'\xbf\xba\xfe\xca'}:
            continue
        identity = dylib_id(path)
        if identity and identity.startswith('/'):
            subprocess.run(['install_name_tool', '-id', '@rpath/' + path.name, str(path)], check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        lines = [line for line in subprocess.check_output(['otool', '-L', str(path)], text=True).splitlines()
                 if line.startswith('\t')]
        for line in lines:
            dependency = line.strip().split(' (')[0]
            if dependency == ('@rpath/' + path.name) or dependency == identity:
                continue
            if dependency.startswith('/') and not dependency.startswith(('/usr/lib/', '/System/Library/')):
                raise RuntimeError(f'External native dependency: {path}: {dependency}')
        subprocess.run(['codesign', '--force', '--sign', '-', str(path)], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--python-source', type=Path, required=True,
                        help='Relocatable python-build-standalone prefix, matching the dependency ABI')
    parser.add_argument('--site-packages', type=Path, required=True, help='Verified existing backend dependencies')
    parser.add_argument('--target', type=Path, required=True, help='Exact cached target snapshot')
    parser.add_argument('--draft', type=Path, required=True, help='Exact cached bf16 MTP snapshot')
    parser.add_argument('--licenses', type=Path, required=True, help='Redistribution notices and upstream license texts')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if not (args.licenses / "NOTICE.txt").is_file():
        raise RuntimeError("Model redistribution notices are required")
    bundle = args.output.resolve()
    if bundle.exists():
        raise RuntimeError('Choose a new output path; existing bundles are preserved')
    subprocess.run(['swift', 'build', '-c', 'release', '--package-path', str(ROOT / 'macos/LiveTR3Mac')], check=True)
    binary_dir = Path(subprocess.check_output(['swift', 'build', '-c', 'release', '--show-bin-path',
                                             '--package-path', str(ROOT / 'macos/LiveTR3Mac')], text=True).strip())
    resources = bundle / 'Contents/Resources'
    engine = resources / 'Engine'
    (bundle / 'Contents/MacOS').mkdir(parents=True)
    resources.mkdir()
    clone_copy(binary_dir / 'LiveTR3', bundle / 'Contents/MacOS/LiveTR3')
    clone_copy(ROOT / 'macos/LiveTR3Mac/Resources/AppIcon.icns', resources / 'AppIcon.icns')
    info = dict(CFBundleExecutable='LiveTR3', CFBundleIdentifier='com.livetr3.share-mtp',
                CFBundleName='LiveTR3', CFBundleDisplayName='LiveTR3', CFBundlePackageType='APPL',
                CFBundleIconFile='AppIcon', CFBundleShortVersionString='1.1', CFBundleVersion='11',
                LSMinimumSystemVersion='14.0', LSArchitecturePriority=['arm64'],
                NSMicrophoneUsageDescription='LiveTR3 captures speech for local transcription and translation.',
                NSPrincipalClass='NSApplication', LiveTR3BundledMTP=True)
    (bundle / 'Contents/Info.plist').write_bytes(plistlib.dumps(info))
    (engine / 'backend').mkdir(parents=True)
    # Only runtime modules; never copy validation recordings, .env, test logs,
    # session archives, development environments or private transcripts.
    for module in (ROOT / 'app/backend').glob('*.py'):
        clone_copy(module, engine / 'backend' / module.name)
    copy_tree(args.python_source, engine / 'python')
    version = subprocess.check_output([str(engine / 'python/bin/python3'), '-I', '-c',
                                       'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")'], text=True).strip()
    site = engine / f'python/lib/python{version}/site-packages'
    if site.exists():
        # Standalone distributions contain their own bootstrap pip; retain it
        # and overlay the exact verified dependency versions.
        shutil.copytree(args.site_packages, site, dirs_exist_ok=True, copy_function=clone_copy, ignore=ignore)
    else:
        copy_tree(args.site_packages, site)
    (engine / 'models').mkdir()
    copy_tree(args.target, engine / 'models/gemma-target')
    copy_tree(args.draft, engine / 'models/gemma-mtp')
    copy_tree(args.licenses, resources / 'Licenses')
    for path in bundle.rglob('*'):
        if path.is_symlink() and not path.resolve().is_relative_to(bundle):
            raise RuntimeError(f'External bundle symlink: {path}')
    audit_and_sign(engine / 'python')
    runtime_metadata = json.loads(subprocess.check_output([str(engine / 'python/bin/python3'), '-I', '-B', '-c',
        'import sys,json,importlib.metadata as m; print(json.dumps(dict(python=".".join(map(str,sys.version_info[:3])), packages={d.metadata["Name"]:d.version for d in m.distributions()})))'], text=True))
    manifest = dict(target_revision=args.target.name, drafter_revision=args.draft.name,
                    source_commit=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
                    python_version=runtime_metadata['python'], dependency_versions=runtime_metadata['packages'],
                    architecture='arm64', mtp_enabled=True,
                    native_binary_sha256=hashlib.sha256((bundle / 'Contents/MacOS/LiveTR3').read_bytes()).hexdigest(),
                    backend_hashes={p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                                    for p in (engine / 'backend').glob('*.py')})
    (resources / 'BuildManifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    subprocess.run(['codesign', '--force', '--deep', '--sign', '-', str(bundle)], check=True)
    subprocess.run(['codesign', '--verify', '--deep', '--strict', str(bundle)], check=True)
    print(bundle, flush=True)


if __name__ == '__main__':
    main()
