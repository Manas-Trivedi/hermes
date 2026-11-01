import pytest

from gateway import estimate_tokens


def test_estimate_is_the_prompt_at_four_characters_a_token_rounded_up_plus_the_most_it_may_generate():
    assert estimate_tokens("", 0) == 0
    assert estimate_tokens("a" * 8, 100) == 102
    assert estimate_tokens("a" * 9, 100) == 103  # a partial token counts whole
    with pytest.raises(ValueError):
        estimate_tokens("x", -1)
