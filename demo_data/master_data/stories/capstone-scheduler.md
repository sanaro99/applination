---
title: "Timetabling 400 students without brute force"
tags: [algorithms, systems, python, backend, performance, api]
role_fit: [swe, backend, research, platform-engineer]
company_fit: [platform, enterprise, startup, mission-driven]
one_liner: "Cut a course scheduler's solve time from 90 seconds to 4 by reformulating room assignment as a flow problem."
---

Context: my senior capstone was a scheduler for the CS department, which timetables about 400 students across 60 sections each term and had been doing it in a spreadsheet maintained by one very patient administrator. Instructor availability, room capacity and prerequisite chains all constrain each other, so a greedy pass produces something that is nearly right and useless.

What I did: I modelled it in OR-Tools as a constraint program. The first version worked and took ninety seconds, which is fine for a batch job and hopeless for the thing the registrar actually wanted, which was to ask what happens if I move this section. Profiling showed almost all of it went to the room assignment variables, a boolean matrix of section against room against slot.

What mattered: realizing room assignment did not need the full generality of the constraint model. Once sections are placed in time slots, assigning rooms is bipartite matching with capacities, which is a flow problem with a fast exact solution. Splitting the two phases dropped solve time to about four seconds.

Outcome: I exposed it as a FastAPI service with a what-if endpoint, so the registrar could test a change before committing it. The general lesson was that the interesting optimization was not a faster solver but a smaller question to ask it.
