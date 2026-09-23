"""Regression test for tenacity-04: retry_if_not_exception_type drops its configured exception_types."""



def test_exception_types_stored_and_usable():
    from tenacity.retry import retry_if_not_exception_type

    r = retry_if_not_exception_type(ValueError)
    assert r.exception_types == ValueError

    # _check must be able to isinstance-check against it without raising
    assert r._check(TypeError("x")) is True
    assert r._check(ValueError("x")) is False
