"""The next question is not the last one again (2026-10-08).

A live ML interview asked "training loss falls, validation loss rises" twice
running, filed under two different concepts. The ranking's variety terms read
nothing: the route never passed the last concepts, and the repeat count was
taken over the pool. Now the caller says what this interview has asked
(`asked_this_session`), and the ranking reads it three ways.
"""

from __future__ import annotations

from backend_M05_Question_Intelligence import selection as sel

from .conftest import make_question


def asked(req, *questions):
    """As M06 sends it: what this interview asked, in order — and, as ever,
    never to be asked again."""
    ids = [q.id for q in questions]
    return req.model_copy(update={"asked_this_session": ids, "seen_item_ids": set(ids)})


def test_the_topic_just_asked_is_not_asked_again_next(req):
    just = make_question(concept="concept:hashing")
    same = make_question(concept="concept:hashing", stem="How does a hash map resize?")
    other = make_question(concept="concept:recursion")
    result = sel.select([just, same, other], asked(req, just))
    assert result.question_id == other.id


def test_a_question_that_reads_like_one_already_asked_waits(req):
    """Different concepts, the same question: what the student hears."""
    first = make_question(
        concept="concept:gradient_descent",
        stem=(
            "You notice that after a few epochs your model's training loss keeps dropping but "
            "validation loss starts rising sharply. What is happening?"
        ),
    )
    twin = make_question(
        concept="concept:recursion",
        stem=(
            "You notice the training loss keeps decreasing but the validation loss plateaus and "
            "then rises after a few epochs. What does this tell you?"
        ),
    )
    fresh = make_question(concept="concept:joins", stem="When would a join use an index?")
    result = sel.select([first, twin, fresh], asked(req, first))
    assert result.question_id == fresh.id


def test_a_topic_asked_twice_gives_way_to_one_not_asked(req):
    """Hashing twice already (not just now — recursion came between): the
    third hashing question loses to a topic this interview has not asked."""
    a1 = make_question(concept="concept:hashing", stem="Why is lookup constant on average?")
    gap = make_question(concept="concept:recursion")
    a2 = make_question(concept="concept:hashing", stem="What happens when two keys collide?")
    between = make_question(concept="concept:recursion", stem="When does recursion overflow?")
    third = make_question(concept="concept:hashing", stem="How would you pick a bucket count?")
    fresh = make_question(concept="concept:joins", stem="When would a join use an index?")
    bank = [a1, gap, a2, between, third, fresh]
    result = sel.select(bank, asked(req, a1, gap, a2, between))
    assert result.question_id == fresh.id


def test_with_nothing_else_to_ask_the_round_still_gets_a_question(req):
    """Variety reorders; it never empties a round."""
    just = make_question(concept="concept:hashing")
    same = make_question(concept="concept:hashing", stem="How does a hash map resize?")
    result = sel.select([just, same], asked(req, just))
    assert result.question_id == same.id


def test_stems_alike_is_about_content_not_the_frame():
    assert (
        sel.alike(
            "Tell me about a time when you disagreed with a teammate.",
            "Tell me about a time when you missed a deadline.",
        )
        < sel.ALIKE_AT
    )
