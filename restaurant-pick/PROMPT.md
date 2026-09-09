# Restaurant Pick — the prompt

Everything below the rule is the prompt. Paste it verbatim into each harness as a
single first message, in the same `/goal` mode used for the hangar test.

**Before pasting, substitute the two date placeholders** — and nothing else. The
target date must be a **Saturday at least 14 days after the run date**, so that
booking systems still hold real inventory for it; a date in the past makes "fully
booked" and "the date has passed" indistinguishable and the Verification section
unscoreable. Record both dates in `score.json`. Everything else is fixed input and
costs every run the same number of input tokens.

- `{{TARGET_DATE}}` — e.g. `Saturday 17 October 2026`
- `{{TARGET_DATE_ISO}}` — the same date as `2026-10-17`
- `{{TARGET_DATE_ISO_UNPADDED}}` — the same date as `2026-10-17` with months and
  days unpadded, e.g. `2026-10-7` for the 7th. NowBookIt requires this form; the
  difference is deliberate, not a typo.

The diner is a composite persona, built to exercise the task rather than to describe
anyone: an inner-city Sydney base, a drive radius, a budget band, and a set of
calibration venues. It carries no name, address, contact details or employer.

---

Plan dinner for two people on **{{TARGET_DATE}} at 7:00pm** in Sydney,
Australia, and write the recommendation up as one self-contained HTML file called
`recommendation.html`.

The brief, in the diner's own words:

> Somewhere nice for Saturday night, share plates if you can. Two of us, 7pm.
> Also — I've been wanting to try Lo Presti's in Redfern. Does it work for that
> night? If not, what's the closest thing to it?

## Who you are booking for

- **Starts from:** Ultimo, inner-city Sydney
- **Transport:** drives, does not use rideshare. Maximum 30–45 minutes' drive from
  Ultimo. Parking is part of the recommendation, not an afterthought
- **Group size:** 2

### Areas that work

- Walking distance to Ultimo: Pyrmont, Glebe, Chippendale, Darling Harbour, Haymarket
- Inner west: Newtown, Surry Hills, Erskineville, Enmore, Marrickville, Redfern
- CBD and Circular Quay
- Eastern suburbs: Bondi, Paddington, Coogee, Randwick
- Strathfield is worth the drive, but only for Korean and Vietnamese

### Budget

"Somewhere nice" means **$100–$150 for two, excluding drinks**. Polished but not
formal. Not a tasting-menu night, not a cheap night either.

### What the diner actually likes

Every one of these is a place they rate. Use them to calibrate, not to copy —
suggesting one of them back is a weak answer.

Nomad (Surry Hills), Baba's Place (Marrickville), Yeodongsik, JONGRO HWARO BBQ,
Bistecca, Ragazzi, Alberto's Lounge, Bella Brutta (Newtown), Arthur.

These are reference points, not candidates and not a shortlist — they are there to
calibrate judgement, and every one of them is independent and single-site, which is
the standard the hard filters below hold new suggestions to.

What those have in common — this is the real filter:

- A **clear, specific identity**. The place does one thing and owns it
- Price is not the signal. The list runs from tasting menus to $20 bowls
- **Share plates and communal eating** is the dominant format
- Heavy lean toward **Italian, Korean, Middle Eastern, Chinese, Vietnamese, Thai**
- Rooms that feel **lived-in and confident** — not trying too hard, not generic
- A bias toward **new openings and places currently getting press**

### Hard avoids — a suggestion that trips one of these is a failed suggestion

- Hotel restaurants
- "The view is the point" dining
- Generic modern Australian bistros with no specific hook
- Wine-bar formats that lead with the list over the food
- Chains and franchises, however good. Independent venues only

### Hard filters

- Google rating **4.4 or above**. Quote the rating and the review count
- **Independent** venues only
- **Open** on {{TARGET_DATE}} at 7:00pm. Quote the hours you found
- Within **30–45 minutes' drive of Ultimo**. State the drive time

## Confirming a table

Opening hours tell you when a venue is *open*. They tell you nothing about whether
it has a *table*. For every venue you recommend, go and check its real booking
system, and report what you found.

What is known about the platforms, so no run burns its budget rediscovering it:

- **SevenRooms** answers a plain availability request. Load a SevenRooms page first
  so the request carries cookies, then fetch from inside the page:
  `https://www.sevenrooms.com/api-yoa/availability/widget/range?venue=<slug>&time_slot=19%3A00&party_size=2&halo_size_interval=100&start_date={{TARGET_DATE_ISO}}&num_days=1&channel=SEVENROOMS_WIDGET`
  In the JSON, `data.availability["<date>"]` holds the shifts; bookable slots are the
  entries with `type === "book"`. Wrong slugs cost nothing — they 400 or come back
  empty — so guessing a slug is a cheap way in. Verify the venue's identity and
  address on the page before you trust a slug: slugs point at the wrong suburb often
  enough to change a recommendation. Date parameters in the booking *page* URL are
  ignored and silently render today, so trust the API, not the page.
- **NowBookIt**: `https://api.nowbookit.com/bookings/get-schedule/venue/<venueid>?date={{TARGET_DATE_ISO_UNPADDED}}&numofpeople=2`,
  with the date unpadded. `bookingOptionsCount` is always 0 and means nothing. A slot
  is genuinely bookable only when both `isBlockOut` and `onlySharedTablesRemain` are
  false.
- **OpenTable blocks every automated route.** Restaurant pages hang or throw
  `ERR_HTTP2_PROTOCOL_ERROR`, the `restref` availability endpoints are retired and
  return 503, and the widget iframe is an empty client-rendered shell. Do not spend
  the run on it. Report the venue as unconfirmed, say plainly that OpenTable blocked
  the check, and give the diner the phone number or booking page so they can close it
  themselves. **Lo Presti's books through OpenTable.**

If you cannot confirm a table, say so in those words. **A venue reported as
confirmed when it was never checked is worse than a venue reported as unconfirmed.**

## Output

Write exactly one file, `recommendation.html`, self-contained, inline CSS, no build
step and no external assets. It must contain:

1. A one-line summary of what you found
2. **Two or three options**, no more. For each one: venue name, suburb, address,
   cuisine and format, Google rating and review count, opening hours on the night,
   drive time from Ultimo, a parking note, price estimate for two, one sentence on
   why it suits this diner specifically, and its booking status in one of these four
   forms — *bookable at [times]* / *fully booked* / *booking unconfirmed — [reason],
   contact [number or link]* / *walk-in only*
3. **A direct answer on Lo Presti's** — does it work for that night, and if it cannot
   be confirmed, what is the closest thing to it and why
4. **One starred pick** with a one-sentence reason it wins
5. **A "Checks" section** listing every venue you checked, which booking platform it
   uses, what you queried, and what came back. This is the section that gets scored
   hardest — it is the difference between research and a guess

Cite a source URL for every rating and every set of opening hours.
