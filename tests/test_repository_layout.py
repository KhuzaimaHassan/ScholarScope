from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_foundation_files_exist() -> None:
    assert (ROOT / "README.md").is_file()
    assert (ROOT / "LICENSE").is_file()
    assert (ROOT / "docs" / "05-milestones-and-issues.md").is_file()
    assert (ROOT / "docs" / "adr" / "README.md").is_file()
