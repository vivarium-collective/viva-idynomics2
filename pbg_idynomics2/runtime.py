"""Runtime helpers: locate or download the iDynoMiCS-2 JAR, locate a Java 11+ JVM."""

from __future__ import annotations

import hashlib
import os
import platform
import shutil
import subprocess
import urllib.request
import zipfile
from pathlib import Path

# Pinned to the July 2025 GitHub release.
IDYNO_RELEASE_TAG = "Release-2025-07"
IDYNO_ZIP_URL = (
    "https://github.com/kreft/iDynoMiCS-2/releases/download/"
    f"{IDYNO_RELEASE_TAG}/iDynoMiCS-2-July-2025.zip"
)
IDYNO_ZIP_SHA256 = "ea113a67983d7591e9671eb4afa78b1abe3ecfc4ecf0311fabe9b7c610f168a7"
IDYNO_JAR_NAME = "iDynoMiCS-2.0.jar"

CACHE_DIR = Path(
    os.environ.get(
        "PBG_IDYNOMICS2_CACHE",
        Path.home() / ".cache" / "pbg-idynomics2",
    )
)


def cache_dir() -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR


def jar_path() -> Path:
    """Return the path to the iDynoMiCS-2 JAR, honoring PBG_IDYNOMICS2_JAR."""
    override = os.environ.get("PBG_IDYNOMICS2_JAR")
    if override:
        return Path(override).expanduser().resolve()
    return cache_dir() / IDYNO_JAR_NAME


def release_root() -> Path:
    """Return the cached release root directory (contains config/, protocol/, the JAR)."""
    return cache_dir() / f"iDynoMiCS-2-{IDYNO_RELEASE_TAG}"


def ensure_release(verbose: bool = True) -> Path:
    """Download and unpack the iDynoMiCS-2 release if not already present. Returns the JAR path."""
    target_jar = jar_path()
    if os.environ.get("PBG_IDYNOMICS2_JAR") and target_jar.exists():
        return target_jar

    root = release_root()
    jar = root / IDYNO_JAR_NAME
    if jar.exists():
        if not target_jar.exists() or not target_jar.samefile(jar):
            target_jar.parent.mkdir(parents=True, exist_ok=True)
            if target_jar.exists():
                target_jar.unlink()
            shutil.copy2(jar, target_jar)
        return target_jar

    root.mkdir(parents=True, exist_ok=True)
    zip_path = cache_dir() / "iDynoMiCS-2-release.zip"
    if not zip_path.exists() or _sha256(zip_path) != IDYNO_ZIP_SHA256:
        if verbose:
            print(f"[pbg-idynomics2] downloading {IDYNO_ZIP_URL} ...")
        urllib.request.urlretrieve(IDYNO_ZIP_URL, zip_path)
        digest = _sha256(zip_path)
        if digest != IDYNO_ZIP_SHA256:
            raise RuntimeError(
                f"sha256 mismatch for {zip_path}: got {digest}, expected {IDYNO_ZIP_SHA256}"
            )

    if verbose:
        print(f"[pbg-idynomics2] extracting to {root} ...")
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(root)

    shutil.copy2(jar, target_jar)
    return target_jar


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------- JVM discovery ----------

def find_java11_home() -> str | None:
    """Return JAVA_HOME for a Java 11+ JVM, or None if none found."""
    override = os.environ.get("JAVA_HOME")
    if override and _java_major(override) >= 11:
        return override

    if platform.system() == "Darwin":
        for v in ("11", "17", "21"):
            try:
                out = subprocess.run(
                    ["/usr/libexec/java_home", "-v", v],
                    capture_output=True, text=True, timeout=5,
                )
                if out.returncode == 0 and out.stdout.strip():
                    return out.stdout.strip()
            except (FileNotFoundError, subprocess.TimeoutExpired):
                pass

    java = shutil.which("java")
    if java:
        home = Path(java).resolve().parent.parent
        if _java_major(str(home)) >= 11:
            return str(home)
    return None


def _java_major(java_home: str) -> int:
    java_bin = Path(java_home) / "bin" / "java"
    if not java_bin.exists():
        return 0
    try:
        out = subprocess.run(
            [str(java_bin), "-version"], capture_output=True, text=True, timeout=5,
        )
        line = (out.stderr or out.stdout).splitlines()[0]
        # e.g. 'openjdk version "11.0.26"' or 'java version "1.8.0_432"'
        version = line.split('"')[1]
        major = version.split(".")[0]
        if major == "1":
            major = version.split(".")[1]
        return int(major)
    except Exception:
        return 0


def jvm_library_path() -> str | None:
    """Return the path to libjvm (.dylib/.so/.dll) for a Java 11+ JVM, or None."""
    home = find_java11_home()
    if not home:
        return None
    candidates = [
        Path(home) / "lib" / "server" / "libjvm.dylib",
        Path(home) / "lib" / "server" / "libjvm.so",
        Path(home) / "bin" / "server" / "jvm.dll",
        Path(home) / "jre" / "lib" / "server" / "libjvm.so",
    ]
    for c in candidates:
        if c.exists():
            return str(c)
    return None
