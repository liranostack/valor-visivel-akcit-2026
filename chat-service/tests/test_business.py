"""Business profile: what she said in the onboarding reaches the agents (A.06.10)."""

from typing import Literal

from vv_chat.business import BASELINE_ID, business_profile, render_profile
from vv_contracts.state import Baseline, OnboardingAnswers, Session

ANSWERS = OnboardingAnswers(
    business_type="pastelaria",
    offer="Empanadas argentinas.",
    audience="Cafés, bares e restaurantes; também consumidor final, 80/20",
    channels=["WhatsApp", "Instagram"],
    goal="Atrair mais clientes",
    perceived_difficulty="Clientes comparam só pelo preço",
    difficulty_context="Ao passar orçamento",
)


def session(answers: OnboardingAnswers | None = ANSWERS) -> Session:
    return Session(session_id="s1", status="in_layer", onboarding=answers)


def test_every_answer_she_gave_becomes_a_citable_line() -> None:
    profile = business_profile(session(), Baseline(statement="Temos muitos sabores."))
    text = "\n".join(profile.values())
    for said in (
        "pastelaria",
        "Empanadas argentinas.",
        "80/20",
        "WhatsApp, Instagram",
        "Clientes comparam só pelo preço",
        "Ao passar orçamento",
        "Temos muitos sabores.",
    ):
        assert said in text
    assert BASELINE_ID in profile


def test_unanswered_fields_are_left_out() -> None:
    profile = business_profile(session(OnboardingAnswers(offer="bolo")), None)
    assert len(profile) == 1 and BASELINE_ID not in profile


def test_no_onboarding_gives_an_empty_profile() -> None:
    assert business_profile(session(None), None) == {}
    assert render_profile({}) == "(not known yet)"


def test_render_shows_the_id_to_cite() -> None:
    profile = business_profile(session(), None)
    rendered = render_profile(profile)
    assert all(f"[{pid}]" in rendered for pid in profile)


def test_opening_asks_for_the_last_episode_of_the_difficulty() -> None:
    from vv_chat.business import opening_question

    q = opening_question(ANSWERS, "Como foi a última vez que você fez {seu_trabalho}?")
    assert q == (
        "Você disse que a dificuldade é “Clientes comparam só pelo preço”, ao passar orçamento. "
        "Pensa na última vez que isso aconteceu: o que você disse, o que a pessoa respondeu e "
        "como terminou?"
    )


def test_opening_without_when_still_names_the_difficulty() -> None:
    from vv_chat.business import opening_question

    answers = ANSWERS.model_copy(update={"difficulty_context": None})
    assert opening_question(answers, "x").startswith(
        "Você disse que a dificuldade é “Clientes comparam só pelo preço”. Pensa"
    )


def test_opening_without_difficulty_falls_back_to_the_anchor() -> None:
    from vv_chat.business import opening_question

    answers = OnboardingAnswers(offer="Bolos de casamento")
    q = opening_question(answers, "Como foi a última vez que você fez {seu_trabalho}?")
    assert q == "Como foi a última vez que você fez bolos de casamento?"


def test_entry_focus_on_the_first_question_of_a_configured_stage() -> None:
    from vv_chat.business import entry_focus

    focus: dict[str, Literal["limit"]] = {"clarity.routine": "limit"}
    assert entry_focus(focus, "clarity.routine", attempt=1, gap=None) == "limit"
    assert entry_focus(focus, "clarity.routine", attempt=2, gap=None) is None
    assert entry_focus(focus, "clarity.routine", attempt=1, gap="lacuna") is None
    assert entry_focus(focus, "clarity.real_context", attempt=1, gap=None) is None


def test_closing_message_reads_the_hypothesis_without_citations() -> None:
    from vv_chat.business import READING_SECTION, closing_message

    content = {
        READING_SECTION: "Quem traz o filho encontra alguém paciente [fact:f1]. Faz sentido?",
        "O que você faz": "x [fact:f2]",
    }
    message = closing_message(content)
    assert "Quem traz o filho encontra alguém paciente. Faz sentido?" in message
    assert "[fact:" not in message


def test_closing_message_ends_asking_to_approve_or_adjust() -> None:
    # vv flow-rules: the closing asks her to approve or adjust; round 4 ended without a question.
    from vv_chat.business import READING_SECTION, closing_message

    message = closing_message({READING_SECTION: "Quem compra lembra da massa [fact:f1]."})
    assert message.rstrip().endswith("?")
    assert "ajustar" in message


def test_closing_message_without_reading_falls_back() -> None:
    from vv_chat.business import closing_message

    assert closing_message({"O que você faz": "x"}).startswith("Fechamos esta parte")
