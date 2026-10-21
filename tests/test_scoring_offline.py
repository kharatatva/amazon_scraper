"""Pure scoring formula tests that do not read the project database."""

import pytest

from src.analysis.scoring import (
    compute_competition_scores,
    compute_demand_scores,
    compute_final_score,
    compute_quality_gap_score,
)


def test_demand_scores_normalize_reviews_and_velocity_within_a_niche():
    snapshot = [
        {"product_id": 1, "review_count": 100, "parsed_at": "2024-03-01T00:00:00+00:00"},
        {"product_id": 2, "review_count": 200, "parsed_at": "2024-03-01T00:00:00+00:00"},
    ]
    histories = {
        1: [("2024-01-01T00:00:00+00:00", 10), ("2024-02-01T00:00:00+00:00", 20)],
        2: [("2024-01-01T00:00:00+00:00", 10), ("2024-02-01T00:00:00+00:00", 50)],
    }

    scores = compute_demand_scores(snapshot, review_histories=histories)

    assert scores == {1: 0.0, 2: 100.0}


def test_competition_and_quality_gap_scores_are_bounded():
    snapshot = [
        {"product_id": 1, "review_count": 50, "rating": 3.75},
        {"product_id": 2, "review_count": 25, "rating": 4.8},
        {"product_id": 3, "review_count": 15, "rating": 4.2},
        {"product_id": 4, "review_count": 5, "rating": 4.4},
        {"product_id": 5, "review_count": 5, "rating": 4.1},
    ]

    competition = compute_competition_scores(snapshot)
    quality_gap = compute_quality_gap_score(1, snapshot)

    assert all(score == pytest.approx(10.0) for score in competition.values())
    assert 0 <= quality_gap <= 100


def test_final_score_redistributes_missing_signal_weight():
    score = compute_final_score(
        80,
        40,
        None,
        {"demand": 0.5, "competition": 0.3, "quality_gap": 0.2},
    )

    assert score == pytest.approx(65.0)
