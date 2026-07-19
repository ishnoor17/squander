from pathlib import Path

import pytest

from squander.parser import iter_session_files, parse_session_file

FIXTURE = Path(__file__).parent / "fixtures" / "sample_session.jsonl"


@pytest.fixture
def records():
    return parse_session_file(FIXTURE)


def test_deduplicates_content_blocks_into_one_record_per_message(records):
    # msg_AAA111 spans three JSONL lines (thinking/text/tool_use) that
    # all carry the same cumulative usage -- it must appear once.
    message_ids = [r.message_id for r in records]
    assert message_ids.count("msg_AAA111") == 1


def test_skips_non_assistant_and_usage_less_lines(records):
    # system/user lines, a blank line, invalid JSON, and an assistant
    # line with no usage block (msg_DDD444) should all be dropped.
    message_ids = {r.message_id for r in records}
    assert "msg_DDD444" not in message_ids
    assert len(records) == 3


def test_captures_full_token_split_for_deduplicated_message(records):
    aaa = next(r for r in records if r.message_id == "msg_AAA111")
    assert aaa.session_id == "fixture-session-001"
    assert aaa.model == "claude-sonnet-5"
    assert aaa.input_tokens == 2
    assert aaa.output_tokens == 20
    assert aaa.cache_read_tokens == 1000
    assert aaa.cache_write_tokens == 500
    assert aaa.reasoning_tokens is None
    assert aaa.is_sidechain is False
    assert aaa.request_id == "req_AAA"


def test_preserves_sidechain_flag_and_per_message_model(records):
    ccc = next(r for r in records if r.message_id == "msg_CCC333")
    assert ccc.is_sidechain is True
    assert ccc.model == "claude-haiku-4-5"
    assert ccc.input_tokens == 800
    assert ccc.output_tokens == 10


def test_total_tokens_sums_all_components(records):
    bbb = next(r for r in records if r.message_id == "msg_BBB222")
    assert bbb.total_tokens == bbb.input_tokens + bbb.output_tokens + bbb.cache_read_tokens + bbb.cache_write_tokens


def test_timestamps_are_parsed_and_ordered(records):
    timestamps = [r.timestamp for r in records]
    assert timestamps == sorted(timestamps)


def test_parse_session_file_accepts_str_path():
    records = parse_session_file(str(FIXTURE))
    assert len(records) == 3


def test_missing_session_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        parse_session_file(tmp_path / "does_not_exist.jsonl")


def test_iter_session_files_finds_nested_jsonl(tmp_path):
    project_dir = tmp_path / "-Users-someone-project"
    project_dir.mkdir()
    session_file = project_dir / "abc123.jsonl"
    session_file.write_text("")

    found = list(iter_session_files(tmp_path))

    assert found == [session_file]


def test_iter_session_files_returns_empty_for_missing_root(tmp_path):
    missing = tmp_path / "does-not-exist"
    assert list(iter_session_files(missing)) == []
