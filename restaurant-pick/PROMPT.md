# Restaurant Pick — the prompt

Everything below the rule is the prompt. Paste it verbatim into each harness as a
single first message, in the same `/goal` mode used for the hangar test, and change
nothing between runs. The context pack is fixed input, so it costs every run the
same number of input tokens.

The diner is a composite persona. The taste profile is real preference data with the
identifying details removed: no name, no street address, no contact details, no
employer. Suburb-level geography is all the task needs.

---

Plan dinner for two people on **Saturday 26 September 2026 at 7:00pm** in Sydney,
Australia, and write the recommendation up as one self-contained HTML file called
`recommendation.html`.

The brief, in the diner's own words:

> Somewhere nice for Saturday night, share plates if you can. Two of us, 7pm.
> Also — I've been wanting to try Lo Presti's in Redfern. Does it work for that
> night? If not, what's the closest thing to it?

## Who you are booking for

- **Starts from:** Ultimo, inner-city Sydney (postcode 2007)
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

Margaret, Rockpool, Nomad (Surry Hills), Baba's Place (Marrickville), New Shanghai,
Yeodongsik, JONGRO HWARO BBQ, Chin Chin, Bistecca, Ragazzi, Alberto's Lounge,
Westwood, Bella Brutta (Newtown), Arthur.

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
- **Open** on Saturday 26 September 2026 at 7:00pm. Quote the hours you found
- Within **30–45 minutes' drive of Ultimo**. State the drive time

## The part that is actually being tested

Opening hours tell you when a venue is *open*. They tell you nothing about whether
it has a *table*. For every venue you recommend, go and check its real booking
system, and report what you found.

Known behaviour of the platforms, so you do not waste the run on it:

- **SevenRooms** answers a plain availability request. Load a SevenRooms page first
  so the request carries cookies, then fetch from inside the page:
  `https://www.sevenrooms.com/api-yoa/availability/widget/range?venue=<slug>&time_slot=19%3A00&party_size=2&halo_size_interval=100&start_date=2026-09-26&num_days=1&channel=SEVENROOMS_WIDGET`
  In the JSON, `data.availability["<date>"]` holds the shifts; bookable slots are the
  entries with `type === "book"`. Wrong slugs cost nothing — they 400 or come back
  empty — so guessing a slug is a cheap way in. Verify the venue's identity and
  address on the page before you trust a slug: slugs point at the wrong suburb often
  enough to change a recommendation. Date parameters in the booking *page* URL are
  ignored and silently render today, so trust the API, not the page.
- **NowBookIt**: `https://api.nowbookit.com/bookings/get-schedule/venue/<venueid>?date=2026-9-26&numofpeople=2`,
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
