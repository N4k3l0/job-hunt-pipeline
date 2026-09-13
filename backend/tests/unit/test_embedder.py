import json
from decimal import Decimal

import pytest

from app.services.scoring.embedder import cosine_similarity


class ArrayLike(list):
    """Behaves like the numpy arrays pgvector < 0.5 returned: truthiness
    raises, and elements aren't plain floats (so not JSON-serializable)."""

    def __bool__(self):
        raise ValueError("The truth value of an array with more than one element is ambiguous")


def test_identical_vectors_score_one():
    assert cosine_similarity([1.0, 2.0, 3.0], [1.0, 2.0, 3.0]) == pytest.approx(1.0)


def test_orthogonal_vectors_score_zero():
    assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)


def test_array_like_vectors_do_not_raise():
    a = ArrayLike([Decimal("0.1"), Decimal("0.2"), Decimal("0.3")])
    b = ArrayLike([Decimal("0.3"), Decimal("0.2"), Decimal("0.1")])
    assert cosine_similarity(a, b) == pytest.approx(10 / 14)


def test_result_is_a_json_serializable_float():
    a = ArrayLike([Decimal("0.5"), Decimal("0.5")])
    result = cosine_similarity(a, a)
    assert type(result) is float
    json.dumps({"semantic_cosine": round(result, 4)})


@pytest.mark.parametrize(
    "a, b",
    [
        (None, [1.0]),
        ([1.0], None),
        ([], []),
        ([1.0, 2.0], [1.0]),
        ([0.0, 0.0], [1.0, 1.0]),
    ],
)
def test_degenerate_inputs_score_zero(a, b):
    assert cosine_similarity(a, b) == 0.0
