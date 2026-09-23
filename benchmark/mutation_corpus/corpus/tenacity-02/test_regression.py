"""Regression test for tenacity-02: retry_if_exception_message drops the compiled 'match' regex."""


def test_match_pattern_is_compiled_and_used():
    from tenacity.retry import retry_if_exception_message

    r = retry_if_exception_message(match=r"connection.*refused")

    assert r.match is not None, "match pattern was dropped (should be a compiled regex)"
    assert r._check(ConnectionError("connection was refused")) is True
    assert r._check(ValueError("unrelated")) is False
