#!/usr/bin/env python3
"""Build a Rust FFI crate for one target and stage the library under NuGet RID layout.

Stages at: {output-dir}/runtimes/{rid}/native/{lib-prefix}{lib-name}.{ext}

For musl targets (e.g., *-linux-musl), builds inside an Alpine container to avoid
host linker incompatibilities. For other targets, builds natively on the host.

Inputs (env vars):
    INPUT_TARGET: Rust target triple (required)
    INPUT_CRATE_NAME: cargo package name (default xberg-ffi)
    INPUT_LIB_NAME: library base name (default = crate-name with - → _)
    INPUT_RID: .NET runtime identifier (required), e.g. linux-x64
    INPUT_OUTPUT_DIR: staging root (default dist/csharp-natives)
    INPUT_DRY_RUN: "true" to skip cargo build (default false)
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from musl_builder import build_or_fallback


def library_filename(lib_name: str, target: str) -> str:
    if "windows" in target:
        return f"{lib_name}.dll"
    if "apple" in target or "darwin" in target:
        return f"lib{lib_name}.dylib"
    return f"lib{lib_name}.so"


def cargo_release_dir(target: str) -> Path:
    return Path("target") / target / "release"


def run_cargo_build(crate_name: str, target: str, glibc_version: str = "") -> None:
    """Build using musl Docker builder for musl targets, zigbuild for gnu targets, native otherwise."""
    build_or_fallback(crate_name, target, glibc_version=glibc_version)


def write_github_output(name: str, value: str) -> None:
    sink = os.environ.get("GITHUB_OUTPUT", "")
    line = f"{name}={value}\n"
    if sink:
        with Path(sink).open("a", encoding="utf-8") as handle:
            handle.write(line)
    else:
        sys.stdout.write(line)


def ensure_input(name: str, value: str) -> str:
    if not value:
        print(f"Error: {name} is required", file=sys.stderr)
        sys.exit(1)
    return value


def _macho_deps(binary: Path) -> list[str]:
    """Return a Mach-O's dylib load commands, excluding the header and its own id."""
    try:
        listing = subprocess.run(["otool", "-L", str(binary)], capture_output=True, text=True, check=True).stdout
        id_out = subprocess.run(["otool", "-D", str(binary)], capture_output=True, text=True, check=True).stdout
    except (subprocess.CalledProcessError, FileNotFoundError):
        return []

    # otool -D: line 0 is the "<path>:" header, line 1 (if present) is LC_ID_DYLIB.
    id_lines = [ln.strip() for ln in id_out.splitlines()[1:] if ln.strip()]
    own_id = id_lines[0] if id_lines else ""

    deps: list[str] = []
    for line in listing.splitlines()[1:]:  # skip the "<path>:" header line
        entry = line.strip().split(" (")[0].strip()
        if entry and entry != own_id:
            deps.append(entry)
    return deps


def _is_vendorable(dep: str) -> bool:
    """True for load commands that must be bundled beside the FFI dylib.

    System libraries and already-relocatable ``@loader_path``/``@executable_path``
    refs are left untouched; ``@rpath`` refs (ONNX Runtime) and absolute non-system
    paths (the libheif codec closure) are vendored.
    """
    if dep.startswith(("/usr/lib/", "/System/")):
        return False
    if dep.startswith(("@loader_path/", "@executable_path/")):
        return False
    if dep.startswith("@rpath/"):
        return True
    return dep.startswith("/")


def _resign(binary: Path) -> None:
    """Ad-hoc re-sign after rewriting load commands (invalidates the signature)."""
    subprocess.run(["codesign", "--remove-signature", str(binary)], capture_output=True, text=True, check=False)
    subprocess.run(["codesign", "-f", "-s", "-", str(binary)], capture_output=True, text=True, check=False)


def _locate_dep(dep: str, basename: str, search_roots: list[Path]) -> Path | None:
    """Resolve a load-command reference to an on-disk source file."""
    if dep.startswith("/"):  # absolute refs (libheif closure) carry their own path
        absolute = Path(dep)
        if absolute.is_file():
            return absolute.resolve()
    for root in search_roots:  # @rpath refs are basename-only; search known roots
        if not root.is_dir():
            continue
        direct = root / basename
        if direct.is_file():
            return direct.resolve()
        for match in root.rglob(basename):
            if match.is_file():
                return match.resolve()
    return None


def _macos_search_roots() -> list[Path]:
    """Where basename-only @rpath deps may have been staged by the toolchain."""
    search_roots: list[Path] = []
    ort_lib_location = os.environ.get("ORT_LIB_LOCATION")
    if ort_lib_location:
        search_roots.append(Path(ort_lib_location))
    search_roots.append(Path("/tmp/xberg-heif/lib"))  # noqa: S108 — fixed CI prefix from build-macos-heif-deps.sh
    xdg_cache = os.environ.get("XDG_CACHE_HOME")
    if xdg_cache:
        search_roots.append(Path(xdg_cache) / "ort.pyke.io" / "dfbin")
    home = Path.home()
    search_roots.extend(
        [
            home / ".cache" / "ort.pyke.io" / "dfbin",
            home / "Library" / "Caches" / "ort.pyke.io" / "dfbin",
        ]
    )
    return search_roots


def _stage_macos_dep(dep: str, basename: str, staging_dir: Path, search_roots: list[Path], binary_name: str) -> Path:
    """Copy one runtime dep beside the staged lib, exiting 1 if it cannot be vendored safely."""
    dest = staging_dir / basename
    if dest.exists():
        return dest

    source = _locate_dep(dep, basename, search_roots)
    if source is None:
        print(
            f"[build-csharp-natives] error: could not locate runtime dep {dep} for {binary_name}",
            file=sys.stderr,
        )
        sys.exit(1)
    if str(source).startswith(("/opt/homebrew/", "/usr/local/")):
        print(
            f"[build-csharp-natives] error: refusing to vendor Homebrew dylib {source} "
            "(would raise the macOS floor); build the closure from source at the "
            "deployment target instead",
            file=sys.stderr,
        )
        sys.exit(1)
    shutil.copy2(source, dest)
    dest.chmod(dest.stat().st_mode | 0o200)
    print(f"[build-csharp-natives] staged runtime dep: {dest.resolve()}")
    return dest


def _assert_no_unvendored_deps(staging_dir: Path) -> None:
    """Fail loudly if any vendorable dep still leaks anywhere in the closure."""
    leaks = 0
    for dylib in sorted(staging_dir.glob("*.dylib")):
        for dep in _macho_deps(dylib):
            if _is_vendorable(dep):
                print(f"[build-csharp-natives] error: unvendored dep {dylib.name} -> {dep}", file=sys.stderr)
                leaks += 1
    if leaks:
        sys.exit(1)


def copy_macos_runtime_deps(staged_lib: Path, staging_dir: Path) -> None:
    """Vendor a macOS dylib's non-system closure beside it and rewrite load commands.

    The staged FFI dylib links ONNX Runtime via ``@rpath`` (setup-onnx-runtime's
    ``system`` strategy exports ``ORT_LIB_LOCATION``) and the libheif codec closure
    via absolute ``/tmp/xberg-heif/lib`` install names. .NET's P/Invoke resolver
    locates the directly-imported ``libxberg_ffi.dylib`` under
    ``runtimes/{rid}/native/`` but does not resolve *its* dependencies, so each
    vendored dep must sit beside it and be referenced via ``@loader_path``. Mirrors
    the Linux ``$ORIGIN`` handling and scripts/ci/vendor-macos-node-dylibs.sh
    (xberg #1280 / C# HEIF-on-macOS).

    Args:
        staged_lib: The staged ``.dylib`` in ``runtimes/{rid}/native/`` to fix up.
        staging_dir: The directory holding the staged copy (dest for its deps).
    """
    if staged_lib.suffix != ".dylib" or not staged_lib.is_file():
        return
    if not (shutil.which("otool") and shutil.which("install_name_tool")):
        print(
            "[build-csharp-natives] warning: otool/install_name_tool unavailable; skipping macOS dep vendoring",
            file=sys.stderr,
        )
        return

    # @rpath refs are basename-only, so search where the toolchain stages them:
    # ORT_LIB_LOCATION (setup-onnx-runtime), the macOS heif prefix, the ORT cache.
    search_roots = _macos_search_roots()

    seen: set[str] = {staged_lib.name}
    queue: list[Path] = [staged_lib]
    while queue:
        binary = queue.pop(0)
        if not binary.is_file():
            continue
        changed = False
        for dep in _macho_deps(binary):
            if not _is_vendorable(dep):
                continue
            basename = dep.rsplit("/", 1)[-1]
            dest = _stage_macos_dep(dep, basename, staging_dir, search_roots, binary.name)
            subprocess.run(
                ["install_name_tool", "-change", dep, f"@loader_path/{basename}", str(binary)],
                capture_output=True,
                text=True,
                check=True,
            )
            changed = True
            if basename not in seen:
                seen.add(basename)
                queue.append(dest)
        if binary != staged_lib and binary.suffix == ".dylib":
            subprocess.run(
                ["install_name_tool", "-id", f"@loader_path/{binary.name}", str(binary)],
                capture_output=True,
                text=True,
                check=False,
            )
            changed = True
        if changed:
            _resign(binary)

    _assert_no_unvendored_deps(staging_dir)


def _is_base_linux_lib(basename: str) -> bool:
    """True for libc/toolchain libs the base image always provides — never vendor these."""
    prefixes = (
        "ld-linux",
        "ld-musl",
        "libc.so",
        "libc.musl",
        "libc-",
        "libm.so",
        "libmvec.so",
        "libdl.so",
        "librt.so",
        "libpthread.so",
        "libresolv.so",
        "libgcc_s.so",
        "libstdc++.so",
        "libssl.so",
        "libcrypto.so",
    )
    return basename.startswith(prefixes)


def _ldd_deps(binary: Path) -> list[str]:
    """Return a binary's ``ldd``-resolved dependency references.

    Each entry is an absolute path, or the bare soname when ``ldd`` reports it as
    unresolved.
    """
    result = subprocess.run(["ldd", str(binary)], capture_output=True, text=True, check=False)
    deps: list[str] = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line or "linux-vdso" in line:
            continue
        match = re.search(r"=>\s*(/\S+)", line)
        if match:
            deps.append(match.group(1))
            continue
        match = re.match(r"^(/\S+)\s+\(0x", line)
        if match:
            deps.append(match.group(1))
            continue
        if "=> not found" in line:
            deps.append(line.split("=>", 1)[0].strip())
    return deps


def _require_linux_tooling() -> None:
    for tool, purpose in (("patchelf", "set RUNPATH"), ("ldd", "resolve runtime deps")):
        if not shutil.which(tool):
            print(f"[build-csharp-natives] error: {tool} unavailable; cannot {purpose}", file=sys.stderr)
            sys.exit(1)


def _stage_linux_closure(source_lib: Path, staging_dir: Path) -> set[str]:
    """Copy the transitive vendorable closure beside the staged lib. Returns unresolved deps."""
    seen: set[str] = {source_lib.name}
    unresolved: set[str] = set()
    queue: list[Path] = [source_lib]
    while queue:
        current = queue.pop(0)
        for dep in _ldd_deps(current):
            basename = Path(dep).name
            if basename in seen or _is_base_linux_lib(basename):
                continue
            seen.add(basename)
            source = Path(dep)
            if not source.is_file():
                unresolved.add(dep)
                continue
            dest = staging_dir / basename
            if not dest.exists():
                shutil.copy2(source, dest)
                dest.chmod(dest.stat().st_mode | 0o200)
                print(f"[build-csharp-natives] staged runtime dep: {dest.resolve()}")
            queue.append(source)
    return unresolved


def _set_origin_runpath(staged_lib: Path) -> None:
    rpath = subprocess.run(
        ["patchelf", "--set-rpath", "$ORIGIN", str(staged_lib)],
        capture_output=True,
        text=True,
        check=False,
    )
    if rpath.returncode != 0:
        print(f"[build-csharp-natives] error: patchelf --set-rpath failed: {rpath.stderr}", file=sys.stderr)
        sys.exit(1)
    print(f"[build-csharp-natives] set RUNPATH=$ORIGIN on {staged_lib.resolve()}")


def copy_linux_runtime_deps(source_lib: Path, staging_dir: Path) -> None:
    """Bundle a Linux .so's vendored deps and point its RUNPATH at ``$ORIGIN``.

    The FFI library is dynamically linked against the vendored ONNX Runtime
    (``libonnxruntime.so.N``) and, with imaging features, codec libraries. .NET's
    P/Invoke resolver locates the *directly* imported library under
    ``runtimes/{rid}/native/``, but the ELF loader then resolves that library's
    own ``NEEDED`` entries via its ``RUNPATH`` — which .NET does not augment. So
    each vendored dependency must sit beside the FFI library and the library must
    carry ``RUNPATH=$ORIGIN``.

    Resolution walks ``ldd`` (which honors the ``LD_LIBRARY_PATH``/``ORT_LIB_LOCATION``
    already exported by ``setup-onnx-runtime``) rather than guessing at cache
    directories — a prior fixed-search-root implementation silently shipped the FFI
    library alone whenever ONNX Runtime lived somewhere it didn't expect (e.g. the
    ``system``-strategy download directory), reproducing ``DllNotFoundException`` in
    containers. Mirrors xberg's own ``scripts/ci/vendor-native-closure.sh`` (used for
    its node/FFI/NIF artifacts) and :func:`copy_macos_runtime_deps` for Mach-O
    (xberg issue #1280).

    Args:
        source_lib: Path to the built ``.so`` in the cargo release dir.
        staging_dir: The ``runtimes/{rid}/native/`` directory holding the staged copy.
    """
    if not source_lib.name.endswith(".so"):
        return
    _require_linux_tooling()

    unresolved = _stage_linux_closure(source_lib, staging_dir)
    if unresolved:
        for dep in sorted(unresolved):
            print(
                f"[build-csharp-natives] error: could not resolve runtime dep '{dep}' required by {source_lib.name}",
                file=sys.stderr,
            )
        sys.exit(1)

    _set_origin_runpath(staging_dir / source_lib.name)


def copy_windows_runtime_deps(staged_lib: Path, staging_dir: Path) -> None:
    """Vendor ``onnxruntime.dll`` beside the staged FFI DLL.

    The FFI library dynamically links ONNX Runtime, but Windows has no rpath
    concept — the loader resolves sibling DLL imports from the directory the
    importing module lives in, so ``onnxruntime.dll`` need only sit beside
    ``xberg_ffi.dll`` in ``runtimes/{rid}/native/`` (no linker rewrite needed,
    unlike the Linux ``$ORIGIN``/macOS ``@loader_path`` cases). ``setup-onnx-runtime``'s
    Windows script exports ``ORT_DYLIB_PATH`` pointing at the staged DLL and also
    copies it onto ``PATH``; fall back to a ``PATH`` scan if the env var is absent.
    Fixes ``DllNotFoundException`` in .NET apps consuming the ``win-x64`` NuGet
    native (xberg issue #1280).

    Args:
        staged_lib: The staged ``.dll`` in ``runtimes/{rid}/native/`` to vendor beside.
        staging_dir: The directory holding the staged copy (destination for the dep).
    """
    if staged_lib.suffix.lower() != ".dll" or not staged_lib.is_file():
        return

    dll_name = "onnxruntime.dll"
    candidates: list[Path] = []
    ort_dylib_path = os.environ.get("ORT_DYLIB_PATH")
    if ort_dylib_path:
        candidates.append(Path(ort_dylib_path))
    ort_lib_location = os.environ.get("ORT_LIB_LOCATION")
    if ort_lib_location:
        candidates.append(Path(ort_lib_location) / dll_name)
    for entry in os.environ.get("PATH", "").split(os.pathsep):
        if entry:
            candidates.append(Path(entry) / dll_name)

    source = next((candidate for candidate in candidates if candidate.is_file()), None)
    if source is None:
        print(
            f"[build-csharp-natives] error: could not locate {dll_name} to bundle beside "
            f"{staged_lib.name} (checked ORT_DYLIB_PATH, ORT_LIB_LOCATION, PATH)",
            file=sys.stderr,
        )
        sys.exit(1)

    dest = staging_dir / dll_name
    if not dest.exists():
        shutil.copy2(source.resolve(), dest)
        print(f"[build-csharp-natives] staged runtime dep: {dest.resolve()}")


def main() -> None:
    target = ensure_input("INPUT_TARGET", os.environ.get("INPUT_TARGET", ""))
    rid = ensure_input("INPUT_RID", os.environ.get("INPUT_RID", ""))
    crate_name = os.environ.get("INPUT_CRATE_NAME", "xberg-ffi") or "xberg-ffi"
    lib_name = os.environ.get("INPUT_LIB_NAME", "") or crate_name.replace("-", "_")
    output_dir = Path(os.environ.get("INPUT_OUTPUT_DIR", "") or "dist/csharp-natives")
    dry_run = os.environ.get("INPUT_DRY_RUN", "false").lower() == "true"
    glibc_version = os.environ.get("INPUT_GLIBC_VERSION", "")

    lib_filename = library_filename(lib_name, target)
    staging_dir = output_dir / "runtimes" / rid / "native"
    staged_lib = staging_dir / lib_filename

    if dry_run:
        print("[build-csharp-natives] dry-run: skipping cargo build")
        print(f"  target:      {target}")
        print(f"  rid:         {rid}")
        print(f"  lib:         {lib_filename}")
        print(f"  staging-dir: {staging_dir}")
        print(f"  library:     {staged_lib}")
        if glibc_version:
            print(f"  glibc-version: {glibc_version}")
        write_github_output("library-path", str(staged_lib.resolve() if staged_lib.exists() else staged_lib))
        write_github_output("staging-dir", str(staging_dir.resolve() if staging_dir.exists() else staging_dir))
        return

    run_cargo_build(crate_name, target, glibc_version)

    release_dir = cargo_release_dir(target)
    source_lib = release_dir / lib_filename
    if not source_lib.is_file():
        print(f"Error: built library not found at {source_lib}", file=sys.stderr)
        sys.exit(1)

    staging_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_lib, staged_lib)

    print(f"[build-csharp-natives] staged: {staged_lib.resolve()}")

    if "darwin" in target or "apple" in target:
        copy_macos_runtime_deps(staged_lib, staging_dir)
    elif "linux" in target:
        copy_linux_runtime_deps(source_lib, staging_dir)
    elif "windows" in target:
        copy_windows_runtime_deps(staged_lib, staging_dir)

    write_github_output("library-path", str(staged_lib.resolve()))
    write_github_output("staging-dir", str(staging_dir.resolve()))


if __name__ == "__main__":
    main()
