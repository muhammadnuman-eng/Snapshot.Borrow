from lumenstage.domain.validators.program import validate_record


def test_program_validator_flags_missing_slug() -> None:
    issues = validate_record({"name": "Sample"})
    assert any("slug" in issue for issue in issues)


def test_program_validator_accepts_minimal() -> None:
    issues = validate_record({"name": "Sample", "slug": "sample", "tags": [], "metadata": {}})
    assert issues == []
