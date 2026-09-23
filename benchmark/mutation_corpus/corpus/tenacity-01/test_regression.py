"""Regression test for tenacity-01: get_callback_name silently degrades to repr() for every callable."""



def named_function():
    pass


def test_get_callback_name_returns_qualified_name():
    from tenacity._utils import get_callback_name

    result = get_callback_name(named_function)
    assert "named_function" in result, f"expected qualified name, got {result!r}"
    assert not result.startswith("<function"), f"got raw repr() fallback: {result!r}"
