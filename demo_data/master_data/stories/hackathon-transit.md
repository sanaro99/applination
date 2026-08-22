---
title: "Cutting scope twice in 36 hours"
tags: [ml, data, python, product, prototyping, judgment]
role_fit: [swe, ml-engineer, product-engineer, backend]
company_fit: [startup, consumer, mission-driven, ai-first]
one_liner: "Shipped an honest transit delay predictor by dropping the feature that would have made the demo impressive and unreliable."
---

Context: a regional civic hackathon, 36 hours, four people who had not worked together. We set out to build a trip planner that routed around predicted bus delays, using historical GTFS feeds and live weather.

What I did: I owned the model and the data path. By hour ten it was clear the routing layer was going to eat the remaining time and still be fragile, so I argued for cutting it and shipping just the prediction, with a calibrated confidence interval, on a single route family. We cut again at hour twenty-four, dropping a live map for a static one, because the map was costing us the evaluation we had not yet run.

What mattered: the second cut was the one that mattered and the one the team resisted, because a static map demos worse. But it bought us time to actually check calibration, and the model turned out to be overconfident on rainy evenings in a way we could see and correct. Shipping a narrower thing that is honest about its uncertainty beat shipping a wider thing we could not vouch for.

Outcome: third of 42 teams, and the judges specifically mentioned the calibration plot. I learned that in a time box the scope decision is the engineering decision, and that the feature you are proudest of is usually the first one that should go.
