# The app's numbers

What the app handled in a period: how many items and sales, on how many channels, how many of those through an API, and how many double sales it recorded. They fill the first line about the project in the curriculum: *"Gestisce N articoli e X vendite su tre canali, uno dei quali sincronizzato via API, con Z doppie vendite e margine calcolato per ogni vendita"*.

## Method

- **Counted by the app, from its database.** The page *Numeri del curriculum* (*Conti* → *Numeri del curriculum*, `/reports/numbers`) counts every item and sale of a period, both days in, in days of Italy. With no period chosen, from the first day of use, the day of the first stock movement, to today. Nothing is sampled or estimated. Code: [`curriculum.py`](../../app/src/cards_warehouse/curriculum.py); tests with sample data and the numbers expected: [`test_curriculum.py`](../../app/tests/test_curriculum.py), [`test_curriculum_numbers.py`](../../app/tests/test_curriculum_numbers.py).
- **What each number counts.** The page writes it next to the numbers, and the file carries the same text under `how`:
  - *Articoli gestiti*: the items with at least one copy in the warehouse at some time of the period: there on its first day, or loaded, sold, opened or adjusted in it. A bulk is one item.
  - *Vendite*: the sales of the period, by the day of the sale, one for each order line even of several copies. Sales cancelled are out, and so are double sales: of an order partly double, the part of the copies there were counts.
  - *Canali con almeno una vendita*: the channels with at least one of those sales.
  - *Canali sincronizzati via API*: of those, the ones with a sale of the period that the app read from the channel's API and recorded by itself (a sale with the line of the channel's order). A channel set to publish through the API, whose sales were typed by hand, is not one.
  - *Doppie vendite*: the orders that came for copies sold already elsewhere, by the day of the sale: recorded as a double sale, or cancelled with that cause. Each order counts once, cancelled or not.
- **Recorded as the file the app gives.** *Scarica in JSON* downloads `numeri-<first day>-<last day>.json`: the period, when it was counted (`counted_at`), the version of the app that counted it (`version`, the commit), the numbers and how each is counted. The file goes unchanged in `app-numbers/`, next to this page, with a row below.

To record: open the app in production (through Tailscale), *Conti* → *Numeri del curriculum*, choose the period or keep the one from the first day of use, *Scarica in JSON*. Copy the file into `docs/measurements/app-numbers/`, add its row, commit.

## Recordings

| Counted on | Period | Production | Items | Sales | Channels | Through the API | Double sales |
|---|---|---|---|---|---|---|---|

None yet: the first is taken from production once this report is released.
