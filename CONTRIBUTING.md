# Contributing to pbg-idynomics2

## Development setup

`uv` is required.  Install with `brew install uv` (or `pip install uv`).

```bash
uv venv .venv
source .venv/bin/activate
uv pip install -e ".[dev]"
pytest
```

You also need a **Java 11+ JDK** on the machine — iDynoMiCS-2 is JVM code.

```bash
# macOS
brew install openjdk@11

# Debian / Ubuntu
sudo apt install openjdk-11-jdk
```

The first time you run the demo (or any JVM-requiring test), the iDynoMiCS-2
release zip (~12 MB) is fetched to `~/.cache/pbg-idynomics2/`.  Override with
`PBG_IDYNOMICS2_CACHE` or skip the download entirely by pointing
`PBG_IDYNOMICS2_JAR` at an existing JAR.

## Tests

```bash
pytest -v
```

JVM-requiring tests skip automatically if no Java 11+ JVM is reachable.

## Editable installs and auto-discovery

A subtle gotcha: hatchling's editable install (`uv pip install -e .`) does
not emit a `top_level.txt`, so `importlib.metadata.packages_distributions()`
cannot map the import name back to the distribution — and that's what
`bigraph_schema`'s discovery uses to find process libraries.

If `allocate_core()` claims it can't resolve `local:IDynoMiCS2Process`, do
one of:

* `uv pip install .` (non-editable) — discovery works,
* or pass the class explicitly: `allocate_core(top={"IDynoMiCS2Process": IDynoMiCS2Process})`.

## Releasing to PyPI

Tag a commit with `git tag v<VERSION>` and push the tag.  The
`.github/workflows/release.yml` workflow publishes to PyPI automatically
using trusted publishing (no tokens needed after initial setup).

PyPI trusted publishing must be configured once per repo.  See
<https://docs.pypi.org/trusted-publishers/>.
