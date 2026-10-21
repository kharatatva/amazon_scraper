"""
Scoring functions for products within a niche.

Demand scoring combines:
1. Review count
2. Review velocity

Competition scoring measures how concentrated reviews are among the
top 3 products in the niche.

Competition interpretation:
    High score  -> fragmented market -> lower review concentration
    Low score   -> concentrated market -> higher review concentration
"""

from datetime import datetime, timezone

from src.storage.queries import get_review_histories

from src.config import *


def _min_max_normalize(value, minimum, maximum):
    """
    Convert a value to a 0-100 score using min-max normalization.

    Formula:
        (value - minimum) / (maximum - minimum) * 100

    If minimum == maximum, every value is identical. In that situation
    there is no meaningful relative difference between the products,
    so a neutral score of 0 is returned.
    """

    if maximum == minimum:
        return 0.0

    return ((value - minimum) / (maximum - minimum)) * 100.0


def _as_utc_datetime(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _calculate_review_velocity(history):
    """
    Calculate review velocity from a product's review history.

    Parameters
    ----------
    history : list[tuple[str, int | None]]
        History returned by get_review_velocity():

        [
            (timestamp, review_count),
            ...
        ]

    Returns
    -------
    float | None
        Reviews gained per day.

        None is returned when:
        - fewer than two valid data points exist
        - timestamps cannot be parsed
        - elapsed time is zero
        - review counts are unavailable
    """

    valid_points = []
    for timestamp, review_count in history:
        parsed_time = _as_utc_datetime(timestamp)
        try:
            count = float(review_count)
        except (TypeError, ValueError):
            continue
        if parsed_time is not None:
            valid_points.append((parsed_time, count))

    if len(valid_points) < 2:
        return None

    valid_points.sort(key=lambda point: point[0])

    earliest_time, earliest_reviews = valid_points[0]
    latest_time, latest_reviews = valid_points[-1]

    elapsed_seconds = (
        latest_time - earliest_time
    ).total_seconds()

    # Prevent division by zero if two snapshots have the same timestamp.
    if elapsed_seconds <= 0:
        return None

    elapsed_days = elapsed_seconds / 86400.0

    review_change = latest_reviews - earliest_reviews

    return review_change / elapsed_days


def _get_product_id(snapshot):
    """
    Extract the product ID from a niche snapshot row.

    Keeping this in a helper makes the expected snapshot structure easy
    to change later if get_niche_snapshot() is modified.
    """

    return snapshot["product_id"]


def _get_review_count(snapshot):
    """
    Extract the review count from a niche snapshot row.

    Missing review counts are treated as 0 for scoring purposes.
    """

    review_count = snapshot.get("review_count")

    return review_count if review_count is not None else 0


def compute_demand_scores(niche_snapshot, review_histories=None):
    """
    Compute demand scores for products in one point-in-time niche snapshot.

    The score combines:

        70% -> normalized review count
        30% -> normalized review velocity

    Review count is normalized against all products in niche_snapshot.

    Review velocity is calculated for every product with at least two
    historical points and then normalized against the available
    velocities within the same niche.

    Histories are cut off at each product snapshot's parsed_at timestamp,
    so historical backfills cannot use observations recorded later.
    """

    if not niche_snapshot:
        return {}

    product_ids = [_get_product_id(snapshot) for snapshot in niche_snapshot]
    if review_histories is None:
        snapshot_times = [
            parsed
            for parsed in (_as_utc_datetime(row.get("parsed_at")) for row in niche_snapshot)
            if parsed is not None
        ]
        history_cutoff = max(snapshot_times).isoformat() if snapshot_times else None
        review_histories = get_review_histories(product_ids, as_of=history_cutoff)

    velocities = {}
    for snapshot in niche_snapshot:
        product_id = _get_product_id(snapshot)
        cutoff = _as_utc_datetime(snapshot.get("parsed_at"))
        if cutoff is None:
            continue
        history = [
            (timestamp, count)
            for timestamp, count in review_histories.get(product_id, [])
            if (_as_utc_datetime(timestamp) is not None
                and _as_utc_datetime(timestamp) <= cutoff)
        ]
        velocity = _calculate_review_velocity(history)
        if velocity is not None:
            velocities[product_id] = velocity

    if not velocities:
        return {product_id: None for product_id in product_ids}

    review_counts = [
        _get_review_count(snapshot)
        for snapshot in niche_snapshot
    ]

    minimum_reviews = min(review_counts)
    maximum_reviews = max(review_counts)

    minimum_velocity = min(velocities.values())
    maximum_velocity = max(velocities.values())
    scores = {product_id: None for product_id in product_ids}

    for snapshot in niche_snapshot:
        product_id = _get_product_id(snapshot)
        velocity = velocities.get(product_id)
        if velocity is None:
            continue
        review_count_score = _min_max_normalize(
            _get_review_count(snapshot), minimum_reviews, maximum_reviews
        )
        velocity_score = _min_max_normalize(
            velocity, minimum_velocity, maximum_velocity
        )
        demand_score = (
            REVIEW_COUNT_WEIGHT * review_count_score
            + REVIEW_VELOCITY_WEIGHT * velocity_score
        )
        scores[product_id] = max(0.0, min(100.0, demand_score))

    return scores


def compute_demand_score(product_id, niche_snapshot):
    """Compatibility wrapper for callers that score a single product."""
    return compute_demand_scores(niche_snapshot).get(product_id)


def compute_competition_scores(niche_snapshot: list[dict]) -> dict[int, float]:
    """
    Compute the competition score for every product in a niche.

    Competition is a property of the entire niche rather than an
    individual product, so every product in the supplied niche snapshot
    receives the same competition score.

    The core signal is review concentration:

        review_concentration =
            sum(top 3 review counts) / sum(all review counts)

    This concentration is inverted because high concentration means
    stronger competition:

        competition_score =
            (1 - review_concentration) * 100

    Therefore:

        90% of reviews held by top 3
            -> competition score = 10

        50% of reviews held by top 3
            -> competition score = 50

        20% of reviews held by top 3
            -> competition score = 80

    Parameters
    ----------
    niche_snapshot : list[dict]
        Point-in-time product data returned by get_niche_snapshot().

        Each snapshot is expected to contain:
            product_id
            review_count

    Returns
    -------
    dict[int, float]
        Dictionary keyed by product_id.

        Every product in the niche receives the same competition score.

        Example:
            {
                101: 18.5,
                102: 18.5,
                103: 18.5,
            }

    Notes
    -----
    Missing review counts are treated as 0.

    If the niche is empty, an empty dictionary is returned.

    If total review count is 0, there is no measurable review
    concentration, so a neutral competition score of 0 is returned.
    """

    # -----------------------------------------------------------------------
    # 1. Handle an empty niche.
    # -----------------------------------------------------------------------

    if not niche_snapshot:
        return {}

    # -----------------------------------------------------------------------
    # 2. Extract review counts.
    #
    # Missing review counts are treated as 0 by _get_review_count().
    # -----------------------------------------------------------------------

    review_counts = [
        _get_review_count(snapshot)
        for snapshot in niche_snapshot
    ]

    # -----------------------------------------------------------------------
    # 3. Calculate total reviews in the niche.
    # -----------------------------------------------------------------------

    total_reviews = sum(review_counts)

    # If there are no reviews anywhere in the niche, concentration cannot
    # be meaningfully calculated.
    if total_reviews <= 0:
        competition_score = 0.0
    else:
        # ---------------------------------------------------------------
        # 4. Find the top 3 review counts.
        # ---------------------------------------------------------------

        top_review_counts = sorted(
            review_counts,
            reverse=True,
        )[:TOP_COMPETITORS_COUNT]

        # ---------------------------------------------------------------
        # 5. Calculate review concentration.
        #
        # Example:
        #     total reviews = 100,000
        #     top 3 reviews = 90,000
        #
        #     concentration = 0.90
        # ---------------------------------------------------------------

        top_reviews = sum(top_review_counts)

        review_concentration = top_reviews / total_reviews

        # ---------------------------------------------------------------
        # 6. Invert concentration.
        #
        # High concentration -> low competition score
        # Low concentration  -> high competition score
        # ---------------------------------------------------------------

        competition_score = (
            1.0 - review_concentration
        ) * 100.0

        # Guard against floating-point errors.
        competition_score = max(
            0.0,
            min(100.0, competition_score),
        )

    # -----------------------------------------------------------------------
    # 7. Assign the same niche-level score to every product.
    # -----------------------------------------------------------------------

    return {
        _get_product_id(snapshot): competition_score
        for snapshot in niche_snapshot
    }
def _get_rating(snapshot):
    """
    Extract the product rating.

    Missing or invalid ratings cannot contribute to the quality-gap score.
    """

    rating = snapshot.get("rating")

    if rating is None:
        return None

    try:
        return float(rating)
    except (TypeError, ValueError):
        return None


def _calculate_rating_gap_score(rating):
    """
    Convert product rating into a 0-100 quality-gap score.

    Ratings in the 3.3-4.2 range are considered the most potentially
    beatable because they indicate a product that is selling but does
    not have exceptionally strong customer ratings.

    The score peaks around 3.75.

    Very high ratings receive a low score because they indicate stronger
    customer satisfaction and therefore less obvious quality gap.
    """

    if rating is None:
        return None

    if rating <= QUALITY_RATING_LOW:
        return 100.0

    if rating <= QUALITY_RATING_IDEAL:
        return (
            (rating - QUALITY_RATING_LOW)
            / (QUALITY_RATING_IDEAL - QUALITY_RATING_LOW)
        ) * 100.0

    if rating <= QUALITY_RATING_HIGH:
        return (
            (QUALITY_RATING_HIGH - rating)
            / (QUALITY_RATING_HIGH - QUALITY_RATING_IDEAL)
        ) * 100.0

    # Ratings above the target band are increasingly difficult to
    # characterize as a quality gap.
    return 0.0


def _calculate_listing_gap_score(snapshot):
    """
    Calculate listing-quality weakness from Phase B fields.

    Returns None when no Phase B listing fields are available.

    Missing individual fields are ignored rather than treated as weak.
    """

    signals = []

    images_count = snapshot.get("images_count")

    if images_count is not None:
        try:
            images_count = float(images_count)

            image_gap = (
                max(
                    0.0,
                    QUALITY_TARGET_IMAGES - images_count,
                )
                / QUALITY_TARGET_IMAGES
            ) * 100.0

            signals.append(image_gap)

        except (TypeError, ValueError):
            pass

    bullet_points_count = snapshot.get("bullet_points_count")

    if bullet_points_count is not None:
        try:
            bullet_points_count = float(bullet_points_count)

            bullet_gap = (
                max(
                    0.0,
                    QUALITY_TARGET_BULLETS - bullet_points_count,
                )
                / QUALITY_TARGET_BULLETS
            ) * 100.0

            signals.append(bullet_gap)

        except (TypeError, ValueError):
            pass

    has_a_plus_content = snapshot.get("has_a_plus_content")

    if has_a_plus_content is not None:
        if has_a_plus_content:
            a_plus_gap = 0.0
        else:
            a_plus_gap = 100.0

        signals.append(a_plus_gap)

    if not signals:
        return None

    return sum(signals) / len(signals)
def compute_quality_gap_score(product_id, niche_snapshot):
    """
    Compute a 0-100 quality-gap score for one product.

    A higher score indicates a potentially more beatable competitor.

    The score combines:

        40% -> review-count strength
        35% -> rating-based quality gap
        25% -> listing-quality gap

    Review count is normalized against the products in the supplied niche.

    Rating gap is highest around the middling rating range of 3.3-4.2.

    Listing-quality signals are used only when Phase B data exists.
    Missing Phase B fields are excluded from the calculation rather than
    being treated as weak listing signals.

    If listing data is completely unavailable, the score is calculated
    using review count + rating only, with their weights re-normalized.

    Returns
    -------
    float | None
        Quality-gap score from 0 to 100.

        None is returned only when the product cannot provide enough
        information for a meaningful score, such as a missing rating.
    """

    # -----------------------------------------------------------------------
    # 1. Find the target product.
    # -----------------------------------------------------------------------

    target_snapshot = None

    for snapshot in niche_snapshot:
        if _get_product_id(snapshot) == product_id:
            target_snapshot = snapshot
            break

    if target_snapshot is None:
        return None

    # -----------------------------------------------------------------------
    # 2. Calculate review-count strength.
    #
    # A high review count indicates an established product.
    # -----------------------------------------------------------------------

    review_counts = [
        _get_review_count(snapshot)
        for snapshot in niche_snapshot
    ]

    minimum_reviews = min(review_counts)
    maximum_reviews = max(review_counts)

    target_review_count = _get_review_count(target_snapshot)

    review_score = _min_max_normalize(
        target_review_count,
        minimum_reviews,
        maximum_reviews,
    )

    # -----------------------------------------------------------------------
    # 3. Calculate rating gap.
    # -----------------------------------------------------------------------

    rating = _get_rating(target_snapshot)

    rating_score = _calculate_rating_gap_score(rating)

    if rating_score is None:
        return None

    # -----------------------------------------------------------------------
    # 4. Calculate listing gap if Phase B data exists.
    # -----------------------------------------------------------------------

    listing_score = _calculate_listing_gap_score(
        target_snapshot
    )

    # -----------------------------------------------------------------------
    # 5. Combine available components.
    #
    # If listing data is unavailable, its weight is removed and the
    # remaining weights are normalized so missing Phase B data does not
    # artificially lower the score.
    # -----------------------------------------------------------------------

    if listing_score is None:
        total_weight = (
            QUALITY_REVIEW_WEIGHT
            + QUALITY_RATING_WEIGHT
        )

        quality_gap_score = (
            QUALITY_REVIEW_WEIGHT * review_score
            + QUALITY_RATING_WEIGHT * rating_score
        ) / total_weight

    else:
        quality_gap_score = (
            QUALITY_REVIEW_WEIGHT * review_score
            + QUALITY_RATING_WEIGHT * rating_score
            + QUALITY_LISTING_WEIGHT * listing_score
        )

    # -----------------------------------------------------------------------
    # 6. Guard against floating-point errors.
    # -----------------------------------------------------------------------

    return max(
        0.0,
        min(100.0, quality_gap_score),
    )
def compute_final_score(
    demand,
    competition,
    quality_gap,
    weights
) -> float:
    """
    Compute the final opportunity score from the available
    scoring signals.

    Missing signals are excluded from the calculation and
    their weights are redistributed across the available signals.

    Returns:
        Final score between 0 and 100.

    Raises:
        ValueError: If all scoring signals are missing or
                    no valid weight is available.
    """

    scores = {
        "demand": demand,
        "competition": competition,
        "quality_gap": quality_gap,
    }

    available = {
        name: score
        for name, score in scores.items()
        if score is not None
    }

    if not available:
        raise ValueError(
            "Cannot compute final score: all scoring signals are missing."
        )

    available_weights = {
        name: weights[name]
        for name in available
        if weights.get(name, 0) > 0
    }

    total_weight = sum(available_weights.values())

    if total_weight <= 0:
        raise ValueError(
            "Cannot compute final score: no valid weights are available."
        )

    final_score = sum(
        available[name] * available_weights[name]
        for name in available
    ) / total_weight

    return max(0.0, min(100.0, final_score))
