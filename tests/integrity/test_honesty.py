"""Guards, not behaviour. These make honesty a build failure instead of a promise.

Counted separately from tests/unit and reported separately in the README, because
asserting that a string appears in a document is not a behavioural test and folding
these into one total would inflate it.

Every check here corresponds to a way a repository rots: the disclaimer gets edited
out, a number in the prose drifts from the artefact that produced it, a local path
leaks, the demo media goes missing, a badge starts lying.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
README = ROOT / "README.md"
NOTICES = ROOT / "THIRD_PARTY_NOTICES.md"
SURVEY = ROOT / "data" / "survey" / "summary.json"
BENCHMARK = ROOT / "data" / "survey" / "benchmark.json"
WALKTHROUGH = ROOT / "docs" / "walkthrough"


@pytest.fixture(scope="module")
def readme() -> str:
    return README.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def collapsed(readme) -> str:
    """The README as one line.

    Line breaks land in the middle of phrases, which silently disarmed four separate
    guards on the previous project. Every prose assertion runs against this.
    """
    return re.sub(r"\s+", " ", readme)


@pytest.fixture(scope="module")
def summary() -> dict:
    return json.loads(SURVEY.read_text())


# --- 10.1 the disclosures cannot be deleted -------------------------------------


def test_the_first_screen_says_no_model_runs(readme):
    above_the_fold = re.sub(r"\s+", " ", "\n".join(readme.splitlines()[:40]))
    assert re.search(r"no model is trained here and none runs", above_the_fold, re.I), (
        "the first screen of the README must say no model runs"
    )


def test_the_first_screen_says_it_is_not_live(readme):
    above_the_fold = re.sub(r"\s+", " ", "\n".join(readme.splitlines()[:40]))
    assert re.search(r"not live", above_the_fold, re.I)


def test_what_this_is_not_exists_and_is_near_the_top(readme):
    lines = readme.splitlines()
    heading = next(
        (i for i, line in enumerate(lines) if line.strip() == "## What this is NOT"), None
    )
    assert heading is not None, "the README needs a 'What this is NOT' section"
    assert heading < 40, f"'What this is NOT' is at line {heading}, it has to be above the fold"


def test_limitations_section_exists(readme):
    assert re.search(r"^## Limitations", readme, re.M)


def test_the_coverage_gap_is_stated_above_the_fold(collapsed):
    assert re.search(r"54\.5%", collapsed), "the coverage fraction must appear"
    assert re.search(r"does not see half the sky", collapsed, re.I)


def test_the_absence_of_covariance_is_stated(collapsed):
    assert re.search(r"carry no covariance", collapsed, re.I)


# The walkthrough disclosure used to be asserted here unconditionally, which made the
# repository unpublishable the moment a real recording landed: it demanded the words
# "not recorded" while test_the_walkthrough_is_either_present_and_real_or_declared_missing
# forbids them once the media exists. That test already enforces both states, absent
# media means the README must say so, present media means it must stop saying so, so
# the rule lives there and nothing is lost by removing the one-directional version.


# --- numbers in the prose match the artefacts that produced them -----------------


def test_the_headline_counts_match_the_survey(collapsed, summary):
    counts = summary["result"]["cumulative_counts_km"]
    for key, value in counts.items():
        assert f"{value:,}" in collapsed, (
            f"README does not carry the {key} count {value:,} from summary.json"
        )


def test_the_coverage_numbers_match_the_survey(collapsed, summary):
    coverage = summary["coverage"]
    assert f"{coverage['screened']:,}" in collapsed
    assert f"{coverage['on_orbit_catalogued']:,}" in collapsed
    assert f"{coverage['screened_percent']}%" in collapsed
    assert f"{coverage['by_object_type']['DEB']['percent']}%" in collapsed
    assert f"{coverage['by_object_type']['PAY']['percent']}%" in collapsed


def test_the_artefact_counts_match_the_survey(collapsed, summary):
    duplicated = summary["artefact_filter"]["shared_element_set"]["removed"]
    co_orbiting = summary["artefact_filter"]["co_orbiting"]["removed"]
    assert f"{duplicated} pairs" in collapsed or f"**{duplicated} pairs**" in collapsed
    assert f"{co_orbiting:,} pairs" in collapsed


def test_the_gate_radius_matches_the_survey(collapsed, summary):
    gate = summary["screening"]["gate_km"]
    assert f"{gate:.1f} km" in collapsed, f"README should carry the derived gate {gate:.1f} km"


def test_the_state_vector_count_matches_the_survey(collapsed, summary):
    assert f"{summary['screening']['state_vectors']:,}" in collapsed


def test_the_throughput_matches_the_benchmark(collapsed):
    benchmark = json.loads(BENCHMARK.read_text())
    rate = benchmark["sgp4"]["state_vectors_per_second"]
    assert f"{rate:,}" in collapsed, f"README throughput should be {rate:,} from benchmark.json"


def test_the_sensitivity_table_matches_the_survey(collapsed, summary):
    sensitivity = summary["artefact_filter"]["sensitivity_to_the_speed_floor"]
    for floor in ("0 km/s", "0.05 km/s", "0.2 km/s"):
        for value in sensitivity[floor].values():
            assert f"{value:,}" in collapsed, f"{floor} value {value:,} missing from the README"


def test_every_number_in_the_verification_table_has_a_command(readme):
    section = readme.split("## Verification", 1)[1].split("## Limitations", 1)[0]
    rows = [line for line in section.splitlines() if line.startswith("| ") and "`" in line]
    assert len(rows) >= 6, "the verification table should list every produced number"
    for row in rows:
        assert "`" in row, f"verification row without a command: {row}"


# --- 10.3 environment variables cannot drift ------------------------------------


def test_no_undocumented_environment_variable_is_read():
    """There is no .env.example because nothing reads the environment. Keep it that way."""
    pattern = re.compile(r"(?:os\.getenv|os\.environ\[|import\.meta\.env\.)([A-Za-z_\"']\w*)")
    found: set[str] = set()
    for path in list((ROOT / "backend").rglob("*.py")) + list((ROOT / "scripts").rglob("*.py")):
        for match in pattern.finditer(path.read_text(encoding="utf-8")):
            found.add(match.group(1).strip("\"'"))
    declared = set()
    example = ROOT / ".env.example"
    if example.exists():
        declared = {
            line.split("=")[0]
            for line in example.read_text().splitlines()
            if re.match(r"^\w+=", line)
        }
    assert found <= declared, (
        f"these variables are read but not documented in .env.example: {sorted(found - declared)}"
    )
    assert declared <= found, f"these are documented but never read: {sorted(declared - found)}"


# --- 10.4 no local paths, and the badge points at the test workflow -------------


def test_no_local_absolute_paths_in_the_docs():
    for path in (README, NOTICES, ROOT / "progress.md", ROOT / "docs" / "design.md"):
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"/Users/|/home/[a-z]|[A-Z]:\\\\", text), f"{path.name} leaks a path"
        assert "C:\\Users" not in text, f"{path.name} leaks a Windows path"


def test_the_badge_points_at_the_workflow_that_runs_tests(readme):
    badge = re.search(
        r"!\[ci\]\((https://github\.com/[^)]+/workflows/([^/]+)/badge\.svg)\)", readme
    )
    assert badge, "the README needs a workflow status badge"
    workflow = ROOT / ".github" / "workflows" / f"{badge.group(2)}"
    workflow = workflow if workflow.exists() else ROOT / ".github" / "workflows" / "ci.yml"
    assert workflow.exists(), "the badge points at a workflow that does not exist"


def test_ci_runs_tests_and_not_only_a_build():
    """A build-and-deploy workflow is a deploy pipeline, not CI."""
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text()
    runs = re.findall(r"run:\s*(.+)", workflow)
    commands = " ".join(runs)
    assert "pytest tests/unit" in commands, "CI does not run the behavioural suite"
    assert "pytest tests/integrity" in commands, "CI does not run the integrity suite"
    assert re.search(r"npm (run )?test", commands), "CI does not run the frontend suite"
    # A build alone would satisfy none of the above, which is the point.
    build_only = [c for c in runs if "build" in c]
    assert len(build_only) < len(runs), "CI is only building"


def test_ci_runs_on_linux():
    """Development is on Windows. Linux is what catches path assumptions."""
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text()
    assert "ubuntu-latest" in workflow
    assert "windows-latest" not in workflow or workflow.count("ubuntu-latest") >= 1


def test_ci_installs_the_frontend_from_the_lockfile():
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text()
    assert "npm ci" in workflow, "npm install ignores the lockfile"
    assert (ROOT / "web" / "package-lock.json").exists()


def test_every_workflow_path_filter_points_at_something_that_exists():
    """Deepwalker's CI watched a directory deleted months earlier and never fired."""
    for workflow in (ROOT / ".github" / "workflows").glob("*.yml"):
        text = workflow.read_text()
        for match in re.finditer(r'^\s+- ["\']([^"\']+/\*\*[^"\']*)["\']', text, re.M):
            target = match.group(1).split("/**")[0]
            assert (ROOT / target).exists(), (
                f"{workflow.name} filters on {target}, which does not exist, "
                "so the workflow can never fire"
            )


def test_no_static_count_badges(readme):
    """A hand-typed 'tests-74-passing' badge is a claim nothing checks."""
    bad = re.findall(r"img\.shields\.io/badge/[^)]*(?:passing|coverage|\d+%)", readme)
    assert not bad, f"static measurement badges found: {bad}"


def test_the_readme_h1_matches_the_repository_name(readme):
    assert readme.splitlines()[0].strip() == "# kessler"


# --- voice ----------------------------------------------------------------------


def test_no_marketing_vocabulary(collapsed):
    banned = [
        "robust",
        "seamless",
        "powerful",
        "leverage",
        "delve",
        "comprehensive",
        "cutting-edge",
        "unlock",
    ]
    found = [word for word in banned if re.search(rf"\b{word}\b", collapsed, re.I)]
    assert not found, f"banned words in the README: {found}"


def test_no_em_dashes_or_en_dashes_anywhere_in_the_docs():
    for path in (README, NOTICES, ROOT / "progress.md", ROOT / "docs" / "design.md"):
        text = path.read_text(encoding="utf-8")
        for character, name in (
            ("\u2014", "em dash"),
            ("\u2013", "en dash"),
            ("\u00b7", "middle dot"),
        ):
            assert character not in text, f"{path.name} contains {name}"


def test_no_boilerplate_sections(readme):
    for heading in ("## Features", "## Roadmap", "## Contributing"):
        assert heading not in readme, f"{heading} is boilerplate on a solo project"


# --- provenance -----------------------------------------------------------------


def test_third_party_notices_covers_every_committed_data_file():
    notices = NOTICES.read_text(encoding="utf-8")
    snapshot = ROOT / "data" / "snapshots"
    for path in snapshot.rglob("*.csv"):
        assert path.name in notices, f"{path.name} is committed but not in THIRD_PARTY_NOTICES.md"


def test_the_manifest_hashes_match_the_committed_files():
    """The notices claim a SHA-256 per file. Check the claim."""
    import hashlib

    for manifest_path in (ROOT / "data" / "snapshots").rglob("MANIFEST.json"):
        manifest = json.loads(manifest_path.read_text())
        for filename, record in manifest["files"].items():
            path = manifest_path.parent / filename
            assert path.exists(), f"{filename} is in the manifest but not on disk"
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            assert digest == record["sha256"], f"{filename} does not match its recorded hash"
            assert path.stat().st_size == record["bytes"]


def test_the_notices_end_with_what_the_data_is_not():
    notices = re.sub(r"\s+", " ", NOTICES.read_text(encoding="utf-8"))
    assert "What the derived values are not" in notices
    assert "not observations" in notices
    assert "not collision probabilities" in notices


def test_the_debris_rule_is_stated_in_both_places(collapsed):
    notices = re.sub(r"\s+", " ", NOTICES.read_text(encoding="utf-8"))
    rule = "every debris cloud CelesTrak publishes as a fetchable GROUP"
    assert rule.lower() in collapsed.lower(), "the README must state the debris inclusion rule"
    assert rule.lower() in notices.lower()


# --- 10.2 the walkthrough media ---------------------------------------------------

WALKTHROUGH_FILES = {
    "app-walkthrough.mp4": (4, 8, b"ftyp"),
    "app-walkthrough.gif": (0, 6, b"GIF89a"),
    "app-walkthrough-poster.jpg": (0, 3, bytes([0xFF, 0xD8, 0xFF])),
}


def test_the_walkthrough_is_either_present_and_real_or_declared_missing(collapsed):
    """No recording is allowed. A broken or faked recording is not.

    While the media is absent the README has to say so, which the disclosure test
    above enforces. Once any of it appears, all of it has to be real: the magic bytes
    are checked, so a renamed file or a placeholder fails the build.
    """
    present = {
        name: (WALKTHROUGH / name) for name in WALKTHROUGH_FILES if (WALKTHROUGH / name).exists()
    }
    if not present:
        assert re.search(r"not recorded", collapsed, re.I), (
            "with no walkthrough committed, the README must say it is not recorded"
        )
        return

    missing = set(WALKTHROUGH_FILES) - set(present)
    assert not missing, f"walkthrough is partly committed, missing: {sorted(missing)}"

    for name, path in present.items():
        start, stop, magic = WALKTHROUGH_FILES[name]
        data = path.read_bytes()[:stop]
        assert data[start:stop] == magic, f"{name} is not the format its extension claims"

    assert (WALKTHROUGH / "app-walkthrough.gif").stat().st_size < 8 * 1024 * 1024
    assert (WALKTHROUGH / "app-walkthrough.mp4").stat().st_size < 5 * 1024 * 1024
    assert not re.search(r"not recorded", collapsed, re.I), (
        "the walkthrough is committed, so the README should stop saying it is missing"
    )


# --- committed artefacts stay consistent -----------------------------------------


def test_the_committed_csv_matches_the_summary(summary):
    import csv

    path = ROOT / "data" / "survey" / "conjunctions.csv"
    with path.open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    passages = [r for r in rows if r["classification"] == "passage"]
    artefacts = [r for r in rows if r["classification"] != "passage"]
    assert len(passages) == summary["result"]["cumulative_counts_km"]["<=5"]
    expected_artefacts = (
        summary["artefact_filter"]["shared_element_set"]["removed"]
        + summary["artefact_filter"]["co_orbiting"]["removed"]
    )
    assert len(artefacts) == expected_artefacts


def _ignored_names() -> set[str]:
    """Directory and file patterns .gitignore already excludes."""
    text = (ROOT / ".gitignore").read_text(encoding="utf-8")
    names = set()
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        names.add(line.rstrip("/").lstrip("*").lstrip("/").split("/")[0])
    return names


def test_no_build_artefacts_or_logs_would_be_committed():
    """Anything .gitignore covers is fine. Anything it does not cover is not.

    Running the suite creates __pycache__, so checking the working tree alone would
    fail on its own side effects. What matters is whether the ignore rules catch it.
    """
    ignored = _ignored_names()
    always_skip = {".venv", "node_modules", ".git"}
    offenders = []
    patterns = (
        "*.log",
        "*.pyc",
        "dist",
        ".next",
        "__pycache__",
        ".DS_Store",
        "*.egg-info",
        ".pytest_cache",
        ".ruff_cache",
        "*.tsbuildinfo",
    )
    for pattern in patterns:
        for path in ROOT.rglob(pattern):
            parts = set(path.relative_to(ROOT).parts)
            if parts & always_skip:
                continue
            covered = (
                bool(parts & ignored)
                or path.name in ignored
                # "*.egg-info/" reduces to ".egg-info", which is the suffix, dot included.
                or path.suffix in ignored
                or path.suffix.lstrip(".") in ignored
            )
            if covered:
                continue
            offenders.append(str(path.relative_to(ROOT)))
    assert not offenders, f"build output that .gitignore does not cover: {offenders}"


def test_the_artefact_check_would_notice_something_new():
    """The guard above is only worth having if it fails on an uncovered pattern."""
    ignored = _ignored_names()
    assert "coverage.xml" not in ignored
    assert ".egg-info" in ignored, "the egg-info rule is what this test was added for"


def test_gitignore_actually_covers_the_usual_rot():
    ignored = _ignored_names()
    for expected in ("__pycache__", ".venv", "node_modules", ".pytest_cache", ".ruff_cache"):
        assert expected in ignored, f".gitignore does not cover {expected}"


def test_no_secrets():
    pattern = re.compile(r"sk-[a-zA-Z0-9]{20,}")
    for path in ROOT.rglob("*"):
        if not path.is_file() or ".venv" in path.parts or "node_modules" in path.parts:
            continue
        if path.suffix not in {".py", ".ts", ".js", ".md", ".json", ".yml", ".toml", ".html"}:
            continue
        if ".git" in path.parts:
            continue
        assert not pattern.search(path.read_text(encoding="utf-8", errors="ignore")), path
