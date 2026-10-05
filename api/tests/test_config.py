from orderdesk import config


def test_truth_lives_under_eval_and_money_is_integer_fils():
    assert config.TRUTH.parent == config.EVAL
    assert isinstance(config.FILS_PER_AED, int)
