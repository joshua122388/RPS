#!/usr/bin/env python3
"""
Lists and downloads VMware Cloud Foundation (VCF) offline patch bundles via
lcm-bundle-transfer-util.bat (the VCF Download Tool / Offline Bundle Transfer Utility).

Never requires administrator rights - all default paths live under the current
user's profile, and no pip packages are required (standard library only).

Run as a standard (non-admin) user:
    python invoke_vcf_bundle_download.py --source-version 5.2.0.0

List available bundles only, without downloading anything:
    python invoke_vcf_bundle_download.py --source-version 5.2.0.0 --list-only

Security note: the Broadcom download token is validated against a strict
letters/digits/-_.+/= character set before use. Windows always routes .bat
execution through cmd.exe's own command-line parser regardless of how
subprocess quotes arguments, so an unescaped &, %, or | in the token could
otherwise inject a second command - this was verified empirically, not
theoretical. There is no reliable quoting workaround, so the token is
validated instead.
"""

import sys

if sys.version_info < (3, 8):
    sys.stderr.write(
        "This script requires Python 3.8 or later (found {}.{}.{}).\n".format(*sys.version_info[:3])
    )
    sys.exit(1)

import argparse
import getpass
import logging
import os
import re
import subprocess
import tarfile
import tempfile
import uuid
import winreg
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional

TOOL_FILE_NAME = "lcm-bundle-transfer-util.bat"
TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_\-.+/=]+$")
SEPARATOR_PATTERN = re.compile(r"^-{5,}$")
SIZE_PATTERN = re.compile(r"([\d.]+)\s*(MB|GB|TB)")

logger = logging.getLogger("vcf_bundle_download")


@dataclass
class Bundle:
    index: int
    bundle_id: str
    product_version: str
    bundle_size_text: str
    bundle_component: str
    bundle_type: str


def get_desktop_path() -> Path:
    # Desktop can be redirected (e.g. by OneDrive backup); the registry value
    # reflects the real target, unlike assuming ~\Desktop.
    try:
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            value, _ = winreg.QueryValueEx(key, "Desktop")
            return Path(os.path.expandvars(value))
    except OSError:
        return Path.home() / "Desktop"


def setup_logging(log_directory: Path) -> Path:
    log_directory.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    log_file = log_directory / f"vcf-bundle-download_{timestamp}.log"

    formatter = logging.Formatter("[%(asctime)s] [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")

    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.DEBUG)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    console_handler.setLevel(logging.INFO)

    logger.setLevel(logging.DEBUG)
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    return log_file


def create_workspace(depot_root_dir: Path, output_directory: Path, log_directory: Path, tool_extract_dir: Path) -> None:
    for directory in (depot_root_dir, output_directory, log_directory, tool_extract_dir):
        directory.mkdir(parents=True, exist_ok=True)


def find_file_bounded(root: Path, filename: str, max_depth: int) -> Optional[Path]:
    if not root.exists():
        return None

    root_depth = len(root.resolve().parts)
    matches = []
    for current_dir, dirnames, filenames in os.walk(root):
        depth = len(Path(current_dir).parts) - root_depth
        if depth >= max_depth:
            dirnames[:] = []
        if filename in filenames:
            matches.append(Path(current_dir) / filename)

    if not matches:
        return None
    matches.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return matches[0]


def expand_tool_package(tool_extract_dir: Path, script_dir: Path) -> Optional[Path]:
    existing = find_file_bounded(tool_extract_dir, TOOL_FILE_NAME, max_depth=6)
    if existing:
        logger.info("Tool already extracted at: %s", existing)
        return existing

    search_dirs = []
    for candidate in (Path.home() / "Downloads", script_dir):
        if candidate and candidate.exists() and candidate not in search_dirs:
            search_dirs.append(candidate)

    archive = None
    for directory in search_dirs:
        candidates = sorted(
            directory.glob("vcf-download-tool-*.tar.gz"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if candidates:
            archive = candidates[0]
            break

    if not archive:
        return None

    logger.info("Extracting %s to %s ...", archive, tool_extract_dir)
    tool_extract_dir.mkdir(parents=True, exist_ok=True)

    had_errors = False
    with tarfile.open(archive, "r:gz") as tar:
        if hasattr(tarfile, "data_filter"):
            tar.extraction_filter = tarfile.data_filter
        for member in tar.getmembers():
            try:
                tar.extract(member, path=tool_extract_dir)
            except Exception as exc:
                # The package bundles a Linux JRE containing symlinks, which Windows
                # can't create without elevation/Developer Mode - expected and harmless
                # as long as the Windows bin\*.bat files still extract fine.
                had_errors = True
                logger.debug("Skipped extracting %s: %s", member.name, exc)

    if had_errors:
        logger.warning(
            "Some entries in %s could not be extracted (commonly Linux-only symlinks that Windows "
            "can't create without elevation - harmless if %s still extracted). Checking for the tool anyway.",
            archive,
            TOOL_FILE_NAME,
        )

    found = find_file_bounded(tool_extract_dir, TOOL_FILE_NAME, max_depth=6)
    if not found:
        raise RuntimeError(
            f"Extracted {archive} to {tool_extract_dir} but could not locate {TOOL_FILE_NAME} inside. "
            f"The package structure may have changed, or extraction failed before reaching it; "
            f"inspect {tool_extract_dir} manually."
        )

    logger.info("Auto-extracted tool to: %s", found)
    return found


def find_tool_path(tool_path_arg: Optional[str], tool_extract_dir: Path, script_dir: Path) -> Path:
    if tool_path_arg:
        candidate = Path(tool_path_arg)
        if not candidate.exists():
            raise RuntimeError(f"The --tool-path you provided does not exist: {candidate}")
        if candidate.name != TOOL_FILE_NAME:
            raise RuntimeError(f"The --tool-path you provided does not point to {TOOL_FILE_NAME} (got: {candidate})")
        logger.info("Using tool path supplied via --tool-path: %s", candidate)
        return candidate

    search_roots = []
    for candidate in (script_dir, tool_extract_dir, Path.home() / "Downloads", get_desktop_path(), Path.home()):
        if candidate and candidate.exists() and candidate not in search_roots:
            search_roots.append(candidate)

    for root in search_roots:
        logger.debug("Searching for %s under: %s", TOOL_FILE_NAME, root)
        found = find_file_bounded(root, TOOL_FILE_NAME, max_depth=6)
        if found:
            logger.info("Found tool at: %s", found)
            return found

    logger.warning("Tool not found in known locations; attempting to auto-extract a vcf-download-tool package.")
    extracted = expand_tool_package(tool_extract_dir, script_dir)
    if extracted:
        return extracted

    searched = "\n  - ".join(str(r) for r in search_roots)
    raise RuntimeError(
        f"Could not locate {TOOL_FILE_NAME}. Searched:\n  - {searched}\n"
        f"Extract the vcf-download-tool-*.tar.gz package (from Downloads or elsewhere) and re-run with "
        f"--tool-path \"<path>\\bin\\{TOOL_FILE_NAME}\", or place the extracted folder under one of the "
        f"searched locations."
    )


def validate_token_charset(token: str) -> None:
    if not token:
        raise RuntimeError("Token is empty.")
    if not TOKEN_PATTERN.match(token):
        raise RuntimeError(
            "Token contains characters outside the expected set (letters, digits, and - _ . + / =). "
            "This check exists to prevent command-line injection when the token is passed to "
            "lcm-bundle-transfer-util.bat. Re-copy the token from the Broadcom portal and make sure no "
            "extra characters, quotes, or whitespace were included."
        )


def create_depot_token_file(token: str, path: Path) -> None:
    validate_token_charset(token)
    try:
        data = token.encode("ascii")
    except UnicodeEncodeError as exc:
        raise RuntimeError("Token contains non-ASCII characters, which the tool's token file cannot accept.") from exc

    path.write_bytes(data)
    actual_length = path.stat().st_size
    if actual_length != len(data):
        raise RuntimeError(
            f"Token file byte length ({actual_length}) does not match token length ({len(data)}) - "
            "unexpected encoding issue."
        )
    logger.info("Token file written and verified at %s (%d bytes).", path, actual_length)


def remove_depot_token_file(path: Path) -> None:
    if not path.exists():
        return
    try:
        path.unlink()
        logger.info("Removed plaintext token file: %s", path)
    except OSError as exc:
        logger.warning("Could not delete plaintext token file at %s - please delete it manually. Error: %s", path, exc)


def run_tool_command(tool_path: Path, args: List[str], redacted_args: List[str]) -> str:
    logger.info("Running: %s %s", tool_path, " ".join(redacted_args))
    result = subprocess.run([str(tool_path), *args], shell=False, capture_output=True, text=True)
    combined_output = (result.stdout or "") + (result.stderr or "")
    for line in combined_output.splitlines():
        logger.debug(line)
    if result.returncode != 0:
        tail = "\n".join(combined_output.splitlines()[-20:])
        raise RuntimeError(f"exit code {result.returncode}. Last output:\n{tail}")
    return combined_output


def invoke_bundle_listing(
    tool_path: Path, depot_root_dir: Path, depot_url: str, token_file_path: Path, source_version: str
) -> str:
    args = [
        "--setUpOfflineDepot",
        "--offlineDepotRootDir", str(depot_root_dir),
        "--offlineDepotUrl", depot_url,
        "--depotDownloadTokenFile", str(token_file_path),
        "--sourceVersion", source_version,
    ]
    redacted = [
        "--setUpOfflineDepot",
        "--offlineDepotRootDir", str(depot_root_dir),
        "--offlineDepotUrl", depot_url,
        "--depotDownloadTokenFile", "<redacted>",
        "--sourceVersion", source_version,
    ]
    try:
        return run_tool_command(tool_path, args, redacted)
    except RuntimeError as exc:
        raise RuntimeError(f"Bundle listing failed ({exc})") from exc


def invoke_bundle_download(tool_path: Path, bundle_ids: str, raw_token: str, output_directory: Path) -> None:
    args = [
        "--download", "withCompatibilitySets",
        "-b", bundle_ids,
        "--depotDownloadToken", raw_token,
        "--outputDirectory", str(output_directory),
    ]
    redacted = [
        "--download", "withCompatibilitySets",
        "-b", bundle_ids,
        "--depotDownloadToken", "<redacted>",
        "--outputDirectory", str(output_directory),
    ]
    try:
        run_tool_command(tool_path, args, redacted)
    except RuntimeError as exc:
        raise RuntimeError(
            f"Bundle download failed ({exc})\nCheck available disk space in {output_directory} and "
            f"network/VPN connectivity, then re-run the script."
        ) from exc
    logger.info("Download completed successfully for bundles: %s", bundle_ids)


def parse_bundle_table(text: str) -> List[Bundle]:
    lines = text.splitlines()

    separator_indices = [i for i, line in enumerate(lines) if SEPARATOR_PATTERN.match(line.strip())]
    if len(separator_indices) < 2:
        return []

    data_start = separator_indices[1] + 1
    data_end = separator_indices[2] - 1 if len(separator_indices) >= 3 else len(lines) - 1

    bundles: List[Bundle] = []
    index = 1
    for i in range(data_start, min(data_end, len(lines) - 1) + 1):
        line = lines[i]
        if not line.strip() or "|" not in line:
            continue
        fields = [f.strip() for f in line.split("|")]
        if len(fields) < 5:
            continue
        bundles.append(Bundle(index, fields[0], fields[1], fields[2], fields[3], fields[4]))
        index += 1

    return bundles


def get_total_bundle_size_text(size_texts: List[str]) -> str:
    total_mb = 0.0
    for text in size_texts:
        match = SIZE_PATTERN.search(text)
        if not match:
            continue
        value = float(match.group(1))
        unit = match.group(2)
        if unit == "GB":
            total_mb += value * 1024
        elif unit == "TB":
            total_mb += value * 1024 * 1024
        else:
            total_mb += value

    if total_mb >= 1024:
        return f"{total_mb / 1024:.2f} GB"
    return f"{total_mb:.1f} MB"


def show_bundle_selection_menu(bundles: List[Bundle], max_attempts: int) -> Optional[List[Bundle]]:
    print()
    print("Available bundles:")
    print(f"{'Idx':<5} {'BundleId':<24} {'Version':<10} {'Size':>12}  {'Component':<40} Type")
    for b in bundles:
        print(f"{b.index:<5} {b.bundle_id:<24} {b.product_version:<10} {b.bundle_size_text:>12}  {b.bundle_component:<40} {b.bundle_type}")

    for _attempt in range(max_attempts):
        response = input("Enter comma-separated bundle numbers to download (or 'Q' to quit): ").strip()

        if response.lower() == "q":
            logger.info("User chose to quit at the bundle selection menu.")
            return None

        tokens = [t.strip() for t in response.split(",") if t.strip()]
        if not tokens:
            print("No input provided. Enter at least one number, a comma-separated list, or 'Q' to quit.")
            continue

        indices = []
        valid = True
        for t in tokens:
            if not t.isdigit() or not (1 <= int(t) <= len(bundles)):
                print(f"'{t}' is not a valid bundle number (expected 1-{len(bundles)}).")
                valid = False
                break
            indices.append(int(t))

        if not valid:
            continue

        selected = [b for b in bundles if b.index in indices]
        total_size = get_total_bundle_size_text([b.bundle_size_text for b in selected])

        print()
        print("Selected bundles:")
        for b in selected:
            print(f"{b.index:<5} {b.bundle_id:<24} {b.product_version:<10} {b.bundle_size_text:>12}  {b.bundle_component}")
        print(f"Total download size: {total_size}")
        logger.info("User selected bundles: %s", ", ".join(b.bundle_id for b in selected))
        return selected

    logger.warning("Maximum selection attempts exceeded.")
    return None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="List and download VMware Cloud Foundation (VCF) offline patch bundles."
    )
    parser.add_argument(
        "--tool-path",
        help="Direct path to lcm-bundle-transfer-util.bat. If omitted, common locations are searched "
        "and a matching vcf-download-tool-*.tar.gz package is auto-extracted if found.",
    )
    parser.add_argument("--source-version", required=True, help="Baseline VCF version, e.g. 5.2.0.0")
    parser.add_argument("--offline-depot-root-dir", default=str(Path.home() / "VCF-Payloads" / "Depot"))
    parser.add_argument("--output-directory", default=str(Path.home() / "VCF-Payloads" / "Downloads"))
    parser.add_argument("--log-directory", default=str(Path.home() / "VCF-Payloads" / "Logs"))
    parser.add_argument("--tool-extract-dir", default=str(Path.home() / "VCF-Payloads" / "Tool"))
    parser.add_argument("--offline-depot-url", default="http://localhost")
    parser.add_argument("--list-only", action="store_true", help="List and select bundles, but stop before downloading.")
    parser.add_argument(
        "--keep-token-file", action="store_true", help="Skip deleting the plaintext token file (diagnostics only)."
    )
    parser.add_argument("--max-selection-attempts", type=int, default=3)
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    depot_root_dir = Path(args.offline_depot_root_dir)
    output_directory = Path(args.output_directory)
    log_directory = Path(args.log_directory)
    tool_extract_dir = Path(args.tool_extract_dir)
    script_dir = Path(__file__).resolve().parent

    print("=== VCF Offline Bundle Download ===")

    create_workspace(depot_root_dir, output_directory, log_directory, tool_extract_dir)
    log_file = setup_logging(log_directory)
    logger.info("Log file: %s", log_file)

    try:
        resolved_tool_path = find_tool_path(args.tool_path, tool_extract_dir, script_dir)
    except Exception as exc:
        logger.error("%s", exc)
        return 1

    token = getpass.getpass("Enter your Broadcom support portal download token: ")
    if not token.strip():
        token = getpass.getpass("Token was empty. Enter your Broadcom support portal download token: ")
    if not token.strip():
        logger.error("No token provided after retry. Exiting.")
        return 2

    token_file_path = Path(tempfile.gettempdir()) / f"vcf-download-token-{uuid.uuid4().hex}.txt"
    try:
        create_depot_token_file(token, token_file_path)
    except Exception as exc:
        logger.error("Failed to prepare token file: %s", exc)
        return 2

    try:
        listing_output = invoke_bundle_listing(
            resolved_tool_path, depot_root_dir, args.offline_depot_url, token_file_path, args.source_version
        )
    except Exception as exc:
        logger.error("%s", exc)
        return 3
    finally:
        if not args.keep_token_file:
            remove_depot_token_file(token_file_path)

    bundles = parse_bundle_table(listing_output)
    if not bundles:
        logger.error(
            "No bundles could be parsed from the tool's output. Check the log file for the raw output, "
            "and verify --source-version and token entitlement. Log: %s",
            log_file,
        )
        return 4

    selected = show_bundle_selection_menu(bundles, args.max_selection_attempts)
    if not selected:
        logger.info("No bundles selected. Exiting.")
        return 0

    confirm = input(f"Proceed with download of {len(selected)} bundle(s)? [Y/N]: ").strip().lower()
    if confirm not in ("y", "yes"):
        logger.info("Download not confirmed by user. Exiting.")
        return 0

    if args.list_only:
        logger.info("--list-only specified; stopping before download.")
        return 0

    bundle_ids = ",".join(b.bundle_id for b in selected)
    try:
        invoke_bundle_download(resolved_tool_path, bundle_ids, token, output_directory)
    except Exception as exc:
        logger.error("%s", exc)
        return 6
    finally:
        token = None  # best-effort only: CPython str is immutable, this just drops the reference

    print()
    print(f"Downloaded bundles: {bundle_ids}")
    print(f"Output directory:   {output_directory}")
    print(f"Log file:           {log_file}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nCancelled.")
        sys.exit(130)
