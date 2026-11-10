"""The review prompts' messages: the card's detail reaches the grader as background, and only when there is some."""

from __future__ import annotations

from archie_api.review import prompts


def test_a_cards_detail_is_a_more_block_of_bullets_between_the_answer_and_the_learners_words() -> None:
    """Each stored line is a bullet under `More (not required):`; a blank line is dropped."""
    message = prompts.grade_message(
        question="When would you choose Convex?", accepted="Real-time apps", detail="Live queries\n\nNo polling",
        answer="real time apps",
    )  # fmt: skip

    assert message == (
        "Question: When would you choose Convex?\nAccepted answer: Real-time apps\n"
        "More (not required):\n- Live queries\n- No polling\nAnswer: 'real time apps'"
    )


def test_a_card_without_detail_has_no_more_block() -> None:
    """No detail (or only blank lines) reads exactly as a card did before detail; the care message follows suit."""
    for detail in ("", "\n"):
        assert prompts.grade_message(question="Q?", accepted="A", detail=detail, answer="a") == (
            "Question: Q?\nAccepted answer: A\nAnswer: 'a'"
        )
    assert prompts.care_message(question="Q?", accepted="A", detail="Why", note="n") == (
        "Question: Q?\nAccepted answer: A\nMore (not required):\n- Why\nWhat the learner cares about: 'n'"
    )
