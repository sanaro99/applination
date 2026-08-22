# Canned responses for the demo account

`src/providers/demo_provider.py` serves these instead of calling a model, so
the demo account can exercise every AI flow without an API key and without
spending anyone's money.

Each `.txt` file is one response, chosen by matching cues in the system
prompt. `generic.txt` is the fallback. Keep them in John Doe's voice and
consistent with `demo_data/master_data/` — a visitor who reads the resume and
then the cover letter should see the same person.

No em dashes: `src/tailor.py` strips them for ATS compatibility, so a fixture
containing one would render differently from everything else the pipeline
produces. `tests/test_demo_provider.py` enforces this.
