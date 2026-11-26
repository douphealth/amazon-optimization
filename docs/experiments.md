# Experiments

Each change to a live page is logged here with its baseline, so the next reports can show
whether it worked. Baseline Search Console numbers are for 2026-11-11 to 2026-11-24 (14 days).

## 2026-11-26: product boxes near the top (Plantastic Haven)

| Page | Google clicks | Impressions | Position | First Amazon link before | After |
|---|---|---|---|---|---|
| /how-cold-can-philodendron-tolerate/ | 10 | 518 | 4.0 | 79% down | 2% down |
| /dripping-water-in-philodendron-plants/ | 8 | 391 | 4.8 | 57% down | 6% down |
| /plants-that-look-like-spider-plants/ | 20 | 915 | 10.8 | 73% down | 14% down |
| /string-of-pearls-plant-care/ | 0 | 512 | 10.7 | no Amazon links | 5% down |

- **Measure:** Amazon Associates > Reports, tracking ID `papalex-ph-20`, clicks per day.
- **Baseline to record:** `papalex-ph-20` clicks for Nov 1-25 (not yet available to this repo; put the
  Tracking ID Summary export in `data/associates/`).
- **Review on:** 2026-12-10, two weeks of data.
- **Success:** at least 2x the daily clicks on `papalex-ph-20`. **Failure:** under 1.3x, which would
  mean placement is not the constraint and traffic is.
- **Note:** Black Friday and Cyber Monday fall inside the window and lift clicks on their own, so
  compare against the same days if last year's export is available.

## 2026-11-26: wrong-product links repointed (Plantastic Haven)

22 links on 12 pages pointed at product B084KRDD5F, which now shows Miracle-Gro Indoor Plant Food
instead of potting mix. They now open an Amazon search for the product the link text names.
No traffic effect expected; the gain is that a click lands on the right product.

## 2026-11-26: table of contents repaired (Plantastic Haven)

On /dripping-water-in-philodendron-plants/ a three-question FAQ block had been inserted inside the
last table-of-contents link. It was moved to just below the table of contents. Words and tags are
unchanged. Watch the page's position (4.8) in the next Search Console pull.

## 2026-11-26: titles matched to the searches Google shows them for (Plantastic Haven)

| Page | Query (impressions, position, clicks in 14 days) | Old title | New title |
|---|---|---|---|
| /string-of-pearls-plant-care/ | "string of pearls indoor care" (465, 8.9, 0) | String of Pearls Plant Care: The Complete Guide to Growing Curio Rowleyanus Indoors | String of Pearls Indoor Care: Light, Watering, Soil & Fixes |
| /how-to-start-a-philodendron/ | "how to grow philodendron" (440, 8.7, 0) | How to Start a Philodendron: Beginner Setup and Early Care Guide | How to Grow a Philodendron: Beginner Setup, Light, Soil & Watering |

- String of pearls: the page title and the on-page heading both changed.
- Philodendron: only the on-page heading changed. Its search title is a custom value stored in
  Yoast, which the WordPress API cannot write. Paste the new title into Yoast's "SEO title" field.
- The philodendron page also shows for "when to plant philodendron" (316 impressions). The article
  does not answer that, so the title does not promise it. Adding a sourced paragraph on timing
  would be the way to earn that query.
- URLs did not change. **Review on:** 2026-12-17. **Success:** click-through rate above 2% at a
  similar position. **Roll back if:** the page's average position falls by more than 5 places.
