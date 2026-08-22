---
title: "Teaching debugging instead of data structures"
tags: [teaching, mentoring, feedback, communication, python]
role_fit: [teaching, swe, devtools, product-engineer]
company_fit: [mission-driven, startup, enterprise, accessibility]
one_liner: "Rewrote a lab after noticing students could describe a data structure but not instrument one, lifting median scores 12 points."
---

Context: I have been a teaching assistant for Data Structures for two years, running two weekly sections for about 120 students. Most of them arrive able to recite the properties of a balanced tree and unable to find out why theirs is not balanced.

What I did: I started reading office-hours questions as data instead of as interruptions. The pattern was consistent. Students were not stuck on the concept; they were stuck because their only debugging tool was rereading their own code and hoping. So I rewrote the debugging lab around instrumenting a broken implementation we supplied: print the invariant at each step, watch where it first fails, work backwards from there.

What mattered: the temptation was to explain better. Explaining harder does not help someone who understands the idea and cannot see their own program. What helped was making the program observable and letting them find it themselves, which is slower in the room and much faster by week ten.

Outcome: median lab scores rose about twelve points and office-hours traffic shifted from "my code is wrong" to specific questions about specific states. I also got much better at asking what someone has already tried before offering an answer, which turns out to be the same skill as reviewing a pull request well.
