#!/usr/bin/env python3
"""Deploy a Maven project to Maven Central.

Usage (GitHub Actions via env vars):
    INPUT_POM_FILE=pom.xml INPUT_DRY_RUN=false python3 deploy.py
"""

import os
import re
import subprocess
import sys
import tempfile
import threading
import xml.etree.ElementTree as ET
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

# ~keep Sonatype names the offending coordinate in its rejection, so the version that already
# exists is recoverable from the log. Reading it is what makes the already-published skip
# version-aware: without it a conflict on a stale artifact's version is indistinguishable from an
# idempotent re-run of the release, which is how a release reports success having published
# nothing. The Central Portal reports a purl (`pkg:maven/<group>/<artifact>@<version>`); older
# staging endpoints report `maven:/<group>:<artifact>:<version>`.
PURL_VERSION_PATTERN = re.compile(r"pkg:maven/[^\s@'\"]+@([^\s'\",)\]]+)", re.IGNORECASE)
LEGACY_COORDINATE_VERSION_PATTERN = re.compile(r"maven:/[\w.\-]+:[\w.\-]+:([\w.\-]+)", re.IGNORECASE)


def build_mvn_args(
    pom_file: str,
    maven_profile: str,
    extra_args: str,
    settings_file: str | None = None,
) -> list[str]:
    """Build the Maven argument list from config values."""
    args: list[str] = [
        "-f",
        pom_file,
        "-P",
        maven_profile,
        "-B",
        "--no-transfer-progress",
    ]
    if settings_file:
        args.extend(["-s", settings_file])
    if extra_args.strip():
        args.extend(extra_args.split())
    return args


def is_already_published(log_content: str) -> bool:
    """Return True if the Maven log indicates the version already exists."""
    return bool(re.search(r"component with package url.*already exists", log_content, re.IGNORECASE))


def extract_published_version(log_content: str) -> str | None:
    """Return the version named by Maven's already-exists message, or None when it names none."""
    for pattern in (PURL_VERSION_PATTERN, LEGACY_COORDINATE_VERSION_PATTERN):
        if match := pattern.search(log_content):
            return match.group(1)
    return None


def normalize_release_version(version: str) -> str:
    """Strip whitespace and a leading `v` so a tag (`v1.19.0`) compares to a POM version."""
    return version.strip().removeprefix("v")


def _local_name(tag: str) -> str:
    """Return an XML tag without its `{namespace}` prefix (POMs declare one, some POMs do not)."""
    return tag.rpartition("}")[2]


def _find_child(element: ET.Element, name: str) -> ET.Element | None:
    """Return the first direct child of ``element`` whose local tag name is ``name``."""
    return next((child for child in element if _local_name(child.tag) == name), None)


def read_pom_version(pom_file: str) -> str | None:
    """Return the project version declared by ``pom_file``, or None when it cannot be determined.

    Maven takes the project version from the POM's own ``<version>``, falling back to the
    ``<version>`` it inherits from ``<parent>``. A ``${...}`` placeholder (the ``revision``
    CI-friendly-versions pattern) only resolves during the build, so it is reported as
    undeterminable rather than guessed at.
    """
    try:
        root = ET.parse(pom_file).getroot()  # noqa: S314 — the POM is repo-controlled input
    except (ET.ParseError, OSError) as exc:
        print(f"Warning: could not parse {pom_file}: {exc}", file=sys.stderr)
        return None

    version_element = _find_child(root, "version")
    if version_element is None and (parent := _find_child(root, "parent")) is not None:
        version_element = _find_child(parent, "version")
    if version_element is None:
        return None

    version = (version_element.text or "").strip()
    if not version or "${" in version:
        return None
    return version


def assert_pom_matches_release(pom_version: str | None, expected_version: str) -> bool:
    """Fail before deploying when the POM carries a version other than the release's.

    Returns whether the POM version was determinable and verified, so the caller knows whether the
    already-published check still has a second, weaker source of truth to fall back on.

    ~keep This guard is what makes the `is_already_published` skip below safe, and the two must
    not be collapsed. Skipping is legitimate ONLY when the POM's version IS the release version
    (an idempotent re-run); it is silent data loss when the checkout is stale.
    This exact shape shipped two broken releases on sibling registries: tree-sitter-language-pack
    v1.16.0 on npm and liter-llm v1.19.0 on npm and PyPI each published a stale artifact, matched
    the registry's already-published response, and reported success having shipped nothing for the
    tag. publish-maven had the same unguarded skip; the guard is here so it never gets a turn.

    ~keep Runs as a pre-flight before `mvn deploy` rather than on the response, because Maven
    Central does not allow republishing a version: a mismatch noticed after the deploy has
    already shipped the wrong artifacts.
    """
    if pom_version is None:
        print(
            "::warning::The project version could not be read from the POM (inherited or "
            "property-driven), so the release version is verified only against the coordinate "
            "Maven Central names in an already-exists response."
        )
        return False

    if pom_version != expected_version:
        print(
            f"Error: the POM declares version {pom_version}, but the release being published is {expected_version}",
            file=sys.stderr,
        )
        print(
            "The checkout is stale. Deploying it would ship the wrong version, or be silently "
            "swallowed as an 'already published' skip.",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"Verified the POM carries the release version {expected_version}")
    return True


def assert_already_published_is_release(log_content: str, expected_version: str, *, pom_verified: bool) -> None:
    """Fail when Maven's already-exists response names a version other than the release's.

    ``mvn deploy`` exited non-zero, so resolving to success needs positive evidence that the
    conflict is this release's version. The coordinate in the response is that evidence; when it
    names no version at all, a POM already verified against the release is accepted as the
    fallback, and an unverified POM leaves nothing to attribute the skip to.
    """
    published_version = extract_published_version(log_content)

    if published_version is None:
        if pom_verified:
            print(
                "::warning::Maven Central reported an existing component without a parseable "
                f"coordinate; treating it as an idempotent re-run of {expected_version} because "
                "the POM was verified against the release version."
            )
            return
        print(
            "Error: Maven Central reported an existing component, but neither the POM nor the "
            f"response names a version, so the skip cannot be attributed to release "
            f"{expected_version}",
            file=sys.stderr,
        )
        sys.exit(1)

    if normalize_release_version(published_version) != expected_version:
        print(
            f"Error: Maven Central reports version {published_version} already exists, but the "
            f"release being published is {expected_version}. Nothing was published for "
            f"{expected_version}.",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"Confirmed the existing component is release version {expected_version}")


def verify_release_version(pom_file: str, expected_version: str) -> bool:
    """Run the stale-checkout pre-flight, or warn loudly that it is disabled.

    Returns whether the POM version was determinable and matched the release, which is the
    fallback evidence the already-published check falls back on.
    """
    if not expected_version:
        warn_expected_version_missing()
        return False
    return assert_pom_matches_release(read_pom_version(pom_file), expected_version)


def warn_expected_version_missing() -> None:
    """Warn that the stale-artifact guard is disabled because no expected-version was supplied."""
    print(
        "::warning::publish-maven was invoked without `expected-version`; a stale POM cannot be "
        "detected and Maven Central's 'component with package url ... already exists' response "
        "will be treated as an idempotent skip. Pass the release version from the caller to "
        "close this gap."
    )


def run_mvn_with_streaming(
    mvn_command: list[str],
    timeout_seconds: int,
) -> tuple[int, str]:
    """Run Maven command with streaming output and timeout.

    Returns (returncode, accumulated_log).
    On timeout, kills process and raises TimeoutError.
    """
    accumulated_log: list[str] = []
    timed_out: bool = False
    process_lock = threading.Lock()

    def read_stream() -> None:
        """Read stdout line-by-line and stream to console."""
        nonlocal timed_out
        try:
            if proc.stdout:
                for line in proc.stdout:
                    with process_lock:
                        if not timed_out:
                            print(line, end="", flush=True)
                            accumulated_log.append(line)
        except Exception:
            pass

    proc = subprocess.Popen(
        mvn_command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    reader_thread = threading.Thread(target=read_stream, daemon=True)
    reader_thread.start()

    try:
        returncode = proc.wait(timeout=timeout_seconds)
        reader_thread.join(timeout=5)
        return returncode, "".join(accumulated_log)
    except subprocess.TimeoutExpired as e:
        timed_out = True
        proc.kill()
        proc.wait()
        reader_thread.join(timeout=5)
        raise TimeoutError(f"Maven deploy exceeded {timeout_seconds}s timeout") from e


def write_settings_xml(server_id: str, username: str, password: str, gpg_passphrase: str) -> str:
    """Write a settings.xml with literal, XML-escaped credentials.

    Bypasses the silent-empty-string failure mode where ``${env.MAVEN_USERNAME}``
    references in setup-java's settings.xml resolve to empty strings inside
    a subprocess, producing an empty Authorization header that Sonatype
    Central rejects with HTTP 403 (empty body).

    Every interpolated value is run through :func:`xml.sax.saxutils.escape`
    so that ``&``/``<``/``>`` in a token cannot break the document.
    """
    safe_id = xml_escape(server_id)
    safe_user = xml_escape(username)
    safe_pass = xml_escape(password)
    safe_gpg = xml_escape(gpg_passphrase)
    settings = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<settings xmlns="http://maven.apache.org/SETTINGS/1.0.0">\n'
        "  <servers>\n"
        "    <server>\n"
        f"      <id>{safe_id}</id>\n"
        f"      <username>{safe_user}</username>\n"
        f"      <password>{safe_pass}</password>\n"
        "    </server>\n"
        "  </servers>\n"
        "  <profiles>\n"
        "    <profile>\n"
        "      <id>gpg-passphrase</id>\n"
        "      <properties>\n"
        f"        <gpg.passphrase>{safe_gpg}</gpg.passphrase>\n"
        "      </properties>\n"
        "    </profile>\n"
        "  </profiles>\n"
        "  <activeProfiles>\n"
        "    <activeProfile>gpg-passphrase</activeProfile>\n"
        "  </activeProfiles>\n"
        "</settings>\n"
    )
    fd, path = tempfile.mkstemp(suffix="-settings.xml", text=True)
    try:
        with os.fdopen(fd, "w") as fh:
            fh.write(settings)
    except Exception:
        Path(path).unlink(missing_ok=True)
        raise
    Path(path).chmod(0o600)
    return path


def main() -> None:
    pom_file = os.environ.get("INPUT_POM_FILE", "")
    maven_profile = os.environ.get("INPUT_MAVEN_PROFILE", "publish")
    extra_args = os.environ.get("INPUT_EXTRA_ARGS", "")
    dry_run = os.environ.get("INPUT_DRY_RUN", "false").lower() == "true"
    server_id = os.environ.get("INPUT_SERVER_ID", "ossrh")
    username = os.environ.get("MAVEN_USERNAME", "")
    password = os.environ.get("MAVEN_PASSWORD", "")
    gpg_passphrase = os.environ.get("MAVEN_GPG_PASSPHRASE", "")
    deploy_timeout = int(os.environ.get("INPUT_DEPLOY_TIMEOUT", "1800"))
    expected_version = normalize_release_version(os.environ.get("INPUT_EXPECTED_VERSION", ""))

    if not pom_file:
        print("Error: INPUT_POM_FILE is required", file=sys.stderr)
        sys.exit(1)

    if not Path(pom_file).is_file():
        print(f"Error: POM file not found: {pom_file}", file=sys.stderr)
        sys.exit(1)

    # ~keep Runs before the dry-run branch below on purpose: a dry run exists to catch a stale
    # checkout before the real release, so it must apply the same version assertion.
    pom_verified = verify_release_version(pom_file, expected_version)

    settings_file: str | None = None
    if not dry_run and username and password:
        settings_file = write_settings_xml(server_id, username, password, gpg_passphrase)
        print(f"Wrote credentials settings.xml to {settings_file} (server-id={server_id})")
    elif not dry_run:
        print(
            "Warning: MAVEN_USERNAME or MAVEN_PASSWORD unset; falling back to default settings.xml",
            file=sys.stderr,
        )

    mvn_args = build_mvn_args(pom_file, maven_profile, extra_args, settings_file)

    if dry_run:
        print(f"[dry-run] mvn clean deploy {' '.join(mvn_args)}")
        subprocess.run(["mvn", "-f", pom_file, "clean", "verify", "-B", "--no-transfer-progress"], check=False)
        sys.exit(0)

    print("Deploying to Maven Central...")

    with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        returncode: int
        log_content: str
        try:
            returncode, log_content = run_mvn_with_streaming(
                ["mvn", "clean", "deploy", *mvn_args],
                deploy_timeout,
            )
        except TimeoutError as e:
            sys.stdout.flush()
            print(
                f"Error: {e}",
                file=sys.stderr,
            )
            print(
                "Maven deploy exceeded timeout — Central Portal likely stuck on publish confirmation;\n"
                "check https://central.sonatype.com deployments.\n"
                "If waitUntil=published, switch to validated.",
                file=sys.stderr,
            )
            sys.exit(1)

        Path(tmp_path).write_text(log_content)

        if returncode == 0:
            print("Maven deploy completed successfully")
        elif is_already_published(log_content):
            if expected_version:
                assert_already_published_is_release(log_content, expected_version, pom_verified=pom_verified)
            print("Version already published to Maven Central, skipping")
            github_actions = os.environ.get("GITHUB_ACTIONS", "")
            if github_actions:
                print("::notice::Version already exists on Maven Central")
        else:
            print("Maven deploy failed", file=sys.stderr)
            sys.exit(1)
    finally:
        Path(tmp_path).unlink(missing_ok=True)
        if settings_file:
            Path(settings_file).unlink(missing_ok=True)


if __name__ == "__main__":
    main()
