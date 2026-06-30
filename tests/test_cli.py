from free_food_dartmouth.cli import DEFAULT_WINDOW_DAYS, parser


def test_default_window_is_three_weeks() -> None:
    args = parser().parse_args(["sync"])

    assert DEFAULT_WINDOW_DAYS == 21
    assert args.window_days == 21
