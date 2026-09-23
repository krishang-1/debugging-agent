"""Regression test for tenacity-03: retry_all.__and__ drops a plain-callable operand when flattening."""


def plain_predicate(retry_state):
    return True


def test_and_with_plain_callable_keeps_operand():
    from tenacity.retry import retry_if_exception_type

    r1 = retry_if_exception_type(ValueError)
    r2 = retry_if_exception_type(TypeError)

    combo = r1 & r2          # retry_all(r1, r2), via __rand__
    combo2 = combo & plain_predicate  # self is already retry_all + plain callable -> hits __and__'s flatten branch

    assert combo2.retries[-1] is plain_predicate, f"expected plain_predicate in retries, got {combo2.retries!r}"
    assert None not in combo2.retries
