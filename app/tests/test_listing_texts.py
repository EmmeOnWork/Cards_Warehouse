from dataclasses import replace
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from cards_warehouse.items import LANGUAGES, Card, Condition, Grading, Item, Kind, Sealed
from cards_warehouse.listing_texts import Texts, generate

MEW_PSA_10 = Item(
    Kind.SINGLE_CARD,
    game="Pokémon",
    name="Mew ex",
    language="it",
    details=Card(Grading("PSA", Decimal(10)), set_name="151", number="205/165", variant="Hyper Rare"),
)


# What a buyer searches comes first, the game last. The grade takes the place of the condition.
def test_a_graded_card_has_every_field_in_its_title_and_one_line_each_in_its_description():
    assert generate(MEW_PSA_10) == Texts(
        title="Mew ex 205/165 151 Hyper Rare ITA PSA 10 Pokémon",
        description="Mew ex\n"
        "\n"
        "Gioco: Pokémon\n"
        "Set: 151\n"
        "Numero: 205/165\n"
        "Variante: Hyper Rare\n"
        "Lingua: Italiano\n"
        "Gradazione: PSA 10",
    )


# As the database gives it back, with one decimal: written as Manuel writes it in the rest of the app.
@pytest.mark.parametrize(("grade", "written"), [(Decimal("10.0"), "PSA 10"), (Decimal("9.5"), "PSA 9,5")])
def test_a_grade_is_written_without_a_trailing_zero_and_with_a_decimal_comma(grade, written):
    card = replace(MEW_PSA_10.details, state=Grading("PSA", grade))

    texts = generate(replace(MEW_PSA_10, details=card))

    assert texts.title.endswith(f" ITA {written} Pokémon")
    assert texts.description.endswith(f"\nGradazione: {written}")


# In the title the condition as on Cardmarket, where buyers have learnt it; in full in the description.
def test_a_card_not_graded_has_its_condition_short_in_the_title_and_in_full_in_the_description():
    card = replace(MEW_PSA_10.details, state=Condition.NEAR_MINT)

    texts = generate(replace(MEW_PSA_10, language="en", details=card))

    assert texts.title == "Mew ex 205/165 151 Hyper Rare ENG NM Pokémon"
    assert texts.description.endswith("\nLingua: Inglese\nCondizione: Near Mint")


# Set, number and variant are not asked for: a field left empty leaves no gap and no line with nothing in it.
def test_the_fields_left_empty_are_left_out_of_both_texts():
    card = Card(Condition.EXCELLENT, number="4/102")

    texts = generate(replace(MEW_PSA_10, name="Charizard", details=card))

    assert texts == Texts(
        title="Charizard 4/102 ITA EX Pokémon",
        description="Charizard\n\nGioco: Pokémon\nNumero: 4/102\nLingua: Italiano\nCondizione: Excellent",
    )


# The name of a sealed often says already what it is: the title does not say it twice. The description has it all.
def test_a_sealed_has_its_product_type_and_set_once_in_the_title_and_each_on_its_line():
    box = Item(
        Kind.SEALED,
        game="Pokémon",
        name="Booster box Evoluzioni a Paldea",
        language="it",
        details=Sealed(product_type="Booster box", set_name="Evoluzioni a Paldea"),
    )

    assert generate(box) == Texts(
        title="Booster box Evoluzioni a Paldea ITA Pokémon",
        description="Booster box Evoluzioni a Paldea\n"
        "\n"
        "Gioco: Pokémon\n"
        "Tipo di prodotto: Booster box\n"
        "Set: Evoluzioni a Paldea\n"
        "Lingua: Italiano",
    )


# A magazine has no fields of its own, nor has the bulk, nor a card loaded before the fields existed.
@pytest.mark.parametrize("kind", [Kind.MAGAZINE, Kind.BULK, Kind.SINGLE_CARD])
def test_an_item_without_fields_of_its_kind_has_its_name_language_and_game(kind):
    magazine = Item(kind, game="One Piece", name="Rivista ufficiale n. 3", language="ja")

    assert generate(magazine) == Texts(
        title="Rivista ufficiale n. 3 JAP One Piece",
        description="Rivista ufficiale n. 3\n\nGioco: One Piece\nLingua: Giapponese",
    )


# What tells the card apart and what makes its price stay: name, number, language, condition or grade. The game
# goes first, then the variant, then the set. Whole parts, never half a word.
@pytest.mark.parametrize(
    ("limit", "title"),
    [
        (48, "Mew ex 205/165 151 Hyper Rare ITA PSA 10 Pokémon"),
        (47, "Mew ex 205/165 151 Hyper Rare ITA PSA 10"),
        (39, "Mew ex 205/165 151 ITA PSA 10"),
        (28, "Mew ex 205/165 ITA PSA 10"),
    ],
)
def test_a_title_too_long_for_the_limit_loses_game_variant_and_set_in_this_order(limit, title):
    texts = generate(MEW_PSA_10, title_limit=limit)

    assert texts.title == title
    assert texts.description == generate(MEW_PSA_10).description


# With game, variant and set gone the title is still too long: the name loses its last words, never half of one.
# The description keeps it whole.
def test_a_name_too_long_for_the_title_is_cut_after_a_whole_word():
    pikachu = Item(
        Kind.SINGLE_CARD,
        game="Pokémon",
        name="Pikachu with Grey Felt Hat Van Gogh Museum Promo",
        language="en",
        details=Card(Grading("PSA", Decimal(10)), set_name="SVP Black Star Promos", number="085"),
    )

    texts = generate(pikachu, title_limit=40)

    assert texts.title == "Pikachu with Grey Felt 085 ENG PSA 10"
    assert texts.description.startswith("Pikachu with Grey Felt Hat Van Gogh Museum Promo\n")


words = st.text(st.characters(categories=["L", "N", "P", "Zs"]), max_size=40)
cards = st.builds(
    Card,
    state=st.sampled_from(Condition)
    | st.builds(Grading, words, st.integers(2, 20).map(lambda halves: Decimal(halves) / 2)),
    set_name=words,
    number=words,
    variant=words,
)
any_items = st.builds(
    Item,
    kind=st.sampled_from(Kind),
    game=words,
    name=words,
    language=st.sampled_from(list(LANGUAGES)),
    details=st.none() | cards | st.builds(Sealed, words, words),
)


# Whatever the fields, in any language the app offers, and however tight the channel.
@given(any_items, st.integers(min_value=1, max_value=100))
def test_the_title_never_goes_over_the_limit(item, limit):
    assert len(generate(item, title_limit=limit).title) <= limit
