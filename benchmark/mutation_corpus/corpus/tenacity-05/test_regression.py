"""Regression test for tenacity-05: wait_random's default min changed from 0 to 1 seconds."""



def test_wait_random_default_min_is_zero():
    from tenacity.wait import wait_random

    w = wait_random()
    assert w.wait_random_min == 0, f"expected default min 0, got {w.wait_random_min}"
