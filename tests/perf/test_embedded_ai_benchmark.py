import pytest

from tools.benchmark_ai_embedded import markdown_report, quality, validate_output_path


def test_text_pairing_does_not_hide_backward_timestamps():
    result = quality("[00:01.00]First line\n[00:05.00]Second line", "[00:04.00]Second line\n[00:02.00]First line", 10)
    assert result["coverage"] == 1
    assert result["median_error_s"] == 1
    assert result["backward_timestamps"] == 1
    assert result["within_1s"] == 1


def test_repeated_lines_are_paired_by_occurrence():
    result = quality("[00:01.00]Same words\n[00:05.00]Same words", "[00:01.10]same words!\n[00:04.80]Same words", 10)
    assert result["matched_lines"] == 2
    assert result["median_error_s"] == pytest.approx(.15)
    assert result["max_error_s"] == pytest.approx(.2)


def test_missing_and_changed_lines_reduce_coverage_without_shifting_other_matches():
    result = quality("[00:01.00]First\n[00:05.00]Second", "[00:01.10]First\n[00:04.80]Different", 10)
    assert result["coverage"] == .5
    assert result["missing_lines"] == 1
    assert result["extra_or_changed_lines"] == 1
    assert result["within_1s"] == .5


def test_timestamp_health_records_duplicates_and_outside_audio():
    result = quality("[00:01.00]First\n[00:05.00]Second", "[00:11.00]First\n[00:11.00]Second", 10)
    assert result["duplicate_timestamps"] == 1
    assert result["outside_audio"] == 2


def test_benchmark_refuses_to_write_inside_an_input_directory(tmp_path):
    source = tmp_path / "library/song.flac"
    with pytest.raises(ValueError, match="outside"):
        validate_output_path([source], tmp_path / "library/reports")
    validate_output_path([source], tmp_path / "isolated-reports")


def test_report_handles_a_result_with_no_matching_reference_lines():
    result = quality("[00:01.00]Reference", "[00:01.00]Different", 10)
    report = {"captured_at": "2026-11-13", "configurations": [{
        "input": "test", "device": "cpu", "demucs": "off", "duration_s": 10,
        "cold": {"elapsed_s": 1}, "runs": [{"ok": True, "elapsed_s": 1, "quality": result}],
    }]}
    assert "n/a" in markdown_report(report)
