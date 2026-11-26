# Findings: what was fixed on 2026-11-26 and what is left

## Fixed on the live sites

| Finding | Before | After | How |
|---|---|---|---|
| First Amazon link in the bottom half | 168 | 36 | Product box added near the top |
| First Amazon link 30-50% down | 34 | 10 | Product box added near the top |
| Amazon links but no affiliate disclosure | 2 | 1 | The box carries the Associates statement |
| Pages with a finding that costs clicks or commission | 490 | 372 | |

154 pages across seven sites received a box in this round (160 pages carry one in total). Every
box only repeats products or Amazon searches the page already linked to, with the tracking ID the
page already used. Each page was checked on the live site after saving, Cloudflare's cached copies
were purged, and the changed pages were submitted to search engines. WordPress keeps the previous
version of every page as a revision, and each box is one `<div class="ace-quick-picks">` that can
be deleted.

Three GearUpToFit calculator pages (`/running/heart-rate-zone-calculator/`,
`/running/running-calorie-calculator/`, `/running/running-pace-calculator/`) have the box saved
and show it on an uncached request, but Cloudflare still served the older cached copy after two
purge attempts. Purging the whole GearUpToFit zone in Cloudflare will refresh them.

## Left, and why

### Needs a decision from you

**271 pages use a tracking ID that is not their site's.** 264 of them are GearUpToFit
`/watch-match/` pages using `papalex-20` while the rest of the site uses `papalex-gutf-20`. Both
IDs earn commission; the only cost is that Watch Match clicks cannot be told apart in Associates
reports. Before anything is switched: confirm in Associates Central (Account > Manage your
tracking IDs) that `papalex-gutf-20` exists. A link carrying an ID that is not registered earns
nothing, so this must not be changed blind. If you prefer to keep `papalex-20` there, add it to
GearUpToFit's `tags` in `sites.yaml` and the finding goes away.

**1 earning page is set to noindex**: `gearuptofit.com/shoe-finder/shoes/topo-ultrafly-6/`. A second
page under `/shoe-finder/shoes/` that was checked is noindex too, so this looks like a rule for
that whole section of generated pages, not a mistake on one page. Removing it means opening that whole section to
Google, which is a call about thin generated pages on a site Google has largely stopped indexing.

### Needs access this engine does not have

**Outdoor Misting** is not WordPress, so the engine cannot edit it. One page carries four
findings: `outdoormisting.com/comparing-outdoor-cooling-technologies/` links to an Amazon product
with no tracking ID, no `rel="sponsored nofollow"`, no affiliate disclosure, and the link sits at
the very end. Fix in the site's own editor: add `?tag=<your tracking ID>` to the Amazon link, add
`rel="sponsored nofollow"`, and add the sentence "As an Amazon Associate I earn from qualifying
purchases." near the top.

**5 GearUpToFit pages use amzn.to short links** (`/review/nike-pegasus-41/`,
`/fitness/cardio-workout-for-fat-loss/`, `/review/amazfit-gtr-4-review/`, `/review/hoka-bondi-9/`,
`/review/puma-deviate-elite-4/`). The links work; their tracking ID just cannot be read. Replacing
them needs the full Amazon address behind each short link, and amzn.to could not be reached from
the environment this work ran in.

**29 pages have no meta description, and 8 pages have a title or description that wins few
clicks.** All six WordPress sites use Yoast, and Yoast does not accept titles or descriptions
through the WordPress API. They have to be pasted in the editor (Yoast SEO box > Meta
description). Ready-to-paste text for the pages that matter:

| Page | Meta description |
|---|---|
| gearuptofit.com/running/running-pace-calculator/ | Free running pace calculator and race time predictor. Enter your distance and time to get your pace and estimate finish times for other races. |
| gearuptofit.com/running-shoe-decision-guide/ | A practical framework for choosing running shoes by fit, training load, terrain and comfort, so hype does not make the decision for you. |
| gearuptofit.com/strength-training-hub/ | Strength training workouts, equipment guides and hypertrophy plans from GearUpToFit, organised so you can find the right starting point fast. |
| gearuptofit.com/calculators/ | Free fitness and running calculators: estimate race pace, set training zones, plan calories and understand body metrics without the jargon. |
| plantastichaven.com/philodendron-pink-princess-care/ | Philodendron Pink Princess care: bright light, a chunky fast-draining aroid mix, water when the top 2-3 cm is dry, plus how to handle reversion. |
| plantastichaven.com/philodendron-white-knight-care/ | Philodendron White Knight care: bright indirect light to keep the white variegation, chunky aroid soil, careful watering, and how to identify it. |
| plantastichaven.com/string-of-pearls-plant-care/ | String of pearls care indoors: bright indirect light, a gritty fast-draining mix, and water only when fully dry. Plus fixes for common problems. |
| plantastichaven.com/plant-care-starter/ | A calm, repeatable system for solving houseplant problems: yellow leaves, brown edges, pests, slow growth and inconsistent watering. |
| affiliatemarketingforsuccess.com/affiliate-tools/ | How to choose affiliate marketing tools for publishing, analytics, email and conversion by the bottleneck you have, not by hype or feature lists. |
| affiliatemarketingforsuccess.com/faq/ | Answers to the 28 most common affiliate marketing questions, each linking to a full guide. Bookmark it as your affiliate marketing reference. |
| frenchyfab.com/french-bulldog-training-hub/ | French Bulldog training and behavior guides: positive-reinforcement methods with short sessions and awareness of the breed's breathing limits. |
| frenchyfab.com/free-french-bulldog-checklists/ | Free French Bulldog checklists and planners for daily care, heat safety, feeding, puppy routines and early warning signs. |
| mysticaldigits.com/numerology-chart/ | A clear, responsible introduction to building a numerology chart for reflection, journaling and personal meaning. |
| efficientgptprompts.com/writing-prompt-pack/ | A starter creative writing prompt pack: a practical system for turning vague ideas into scenes with movement, conflict and a reason to keep reading. |

The other pages without a description are policy, contact, blog-index and search pages, where a
description changes nothing worth the time.

### Needs product data

**64 pages link only to Amazon searches, never to a specific product**, and **46 pages still have
a late first link** because their links could not be named (image-only links, a single unnamed
product, or amzn.to links). Fixing either means choosing specific products and confirming each is
still sold. The product-data service used for that check returned "payment required" on
2026-11-26, and product names or availability are not something to guess.

### Notes, not problems to fix page by page

- **No Amazon link in the article (1,657 pages):** only matters on pages about something people
  buy. The work queue ranks the ones with measured demand.
- **Near-duplicates (313):** 259 are GearUpToFit `/watch-match/` comparison pages, left alone on
  your instruction.
- **Thin pages (49), duplicate titles (6), canonical elsewhere (3):** mostly hubs, tool results and
  utility pages. Adding text for its own sake would make them worse, not better.
