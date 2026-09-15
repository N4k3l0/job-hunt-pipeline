from app.services.scoring.evaluation import ranking_metrics


def test_perfect_ranking():
    scored = [(90, True), (80, True), (40, False), (30, False)]
    m = ranking_metrics(scored)
    assert m["ranking_accuracy"] == 1.0
    assert m["inbox"] == {"size": 2, "good": 2}
    assert m["missed_good"] == 0
    assert m["top"] == {"size": 4, "good": 2}


def test_reversed_ranking_and_ties():
    assert ranking_metrics([(30, True), (90, False)])["ranking_accuracy"] == 0.0
    assert ranking_metrics([(60, True), (60, False)])["ranking_accuracy"] == 0.5


def test_missed_good_jobs_and_top_ten():
    scored = [(95 - i, i % 2 == 0) for i in range(12)] + [(45, True)]
    m = ranking_metrics(scored)
    assert m["top"] == {"size": 10, "good": 5}
    assert m["missed_good"] == 1
    assert m["rated"] == 13 and m["good"] == 7


def test_only_one_kind_of_rating_has_no_accuracy():
    assert ranking_metrics([(70, True)])["ranking_accuracy"] is None
    assert ranking_metrics([])["ranking_accuracy"] is None
