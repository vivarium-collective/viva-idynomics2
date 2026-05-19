"""JVM lifecycle: start once per Python process, expose iDynoMiCS classes."""

from __future__ import annotations

import os
import threading
from pathlib import Path

import jpype
import jpype.imports  # noqa: F401  (registers Java import hooks)

from . import runtime

_lock = threading.Lock()
_started = False


def start_jvm(jar: str | os.PathLike | None = None,
              jvm_path: str | None = None,
              extra_classpath: list[str] | None = None) -> None:
    """Start the JVM with iDynoMiCS-2 on the classpath. Idempotent."""
    global _started
    with _lock:
        if _started or jpype.isJVMStarted():
            _started = True
            return

        if jar is None:
            jar = runtime.ensure_release(verbose=False)
        jar = str(Path(jar).resolve())
        if not Path(jar).exists():
            raise FileNotFoundError(
                f"iDynoMiCS-2 JAR not found at {jar}. "
                "Run `python -m pbg_idynomics2.runtime` or set PBG_IDYNOMICS2_JAR."
            )

        if jvm_path is None:
            jvm_path = runtime.jvm_library_path()
        if jvm_path is None:
            raise RuntimeError(
                "Could not find a Java 11+ JVM. Install one (e.g. `brew install openjdk@11`) "
                "or set JAVA_HOME to a JDK 11+ install."
            )

        classpath = [jar]
        if extra_classpath:
            classpath.extend(str(p) for p in extra_classpath)

        jpype.startJVM(jvm_path, classpath=classpath, convertStrings=False)
        _started = True


def is_started() -> bool:
    return jpype.isJVMStarted()


def shutdown_jvm() -> None:
    """Shut down the JVM. Note: JPype JVMs cannot generally be restarted in the same process."""
    global _started
    if jpype.isJVMStarted():
        jpype.shutdownJVM()
    _started = False
