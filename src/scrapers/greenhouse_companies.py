"""
Built-in list of tech companies known to use Greenhouse job boards.

Slugs map to boards-api.greenhouse.io/v1/boards/{slug}/jobs.
Incorrect or stale slugs return 404 and are silently skipped.
"""

BUILT_IN_SLUGS: list[str] = [
    # --- Verified (default config) ---
    "airbnb", "stripe", "instacart", "robinhood", "figma",
    "databricks", "cloudflare", "anthropic", "scaleai", "datadog",
    "mongodb", "twilio", "affirm", "carta", "asana", "brex", "mercury",

    # --- SaaS / Productivity ---
    "notion", "airtable", "loom", "miro", "retool", "linear",
    "webflow", "amplitude", "mixpanel", "intercom", "pagerduty",
    "zendesk", "hubspot", "gong", "outreach", "salesloft", "clari",
    "coda", "framer", "canva", "lattice", "cultureamp", "leapsome",
    "15five", "personio", "workato", "zapier",

    # --- Developer Tools / Infrastructure ---
    "hashicorp", "confluent", "elastic", "cockroachdb", "yugabyte",
    "sentry", "postman", "netlify", "vercel", "digitalocean", "fastly",
    "fivetran", "dbt-labs", "hightouch",
    "grafana", "harness", "temporal", "stytch", "snyk",
    "redpandadata", "imply", "starburst", "cribl",
    "celonis", "contentful", "segment",

    # --- Security ---
    "abnormalsecurity", "lacework", "wiz", "vectra",
    "anduril", "samsara", "palantir",

    # --- AI / ML ---
    "cohere", "labelbox", "modal", "baseten",
    "together-ai", "weights-biases", "scale",

    # --- Fintech / Payments ---
    "plaid", "marqeta", "chime", "ramp", "gusto", "rippling",
    "deel", "remote", "moderntreasury", "column",
    "coinbase", "chainalysis", "alchemy", "figment", "consensys",

    # --- Consumer / Marketplace ---
    "lyft", "pinterest", "reddit", "discord", "duolingo", "coursera",
    "masterclass", "chegg", "doordash", "toast", "olo", "opendoor",
    "opentable", "faire", "hopin", "eventbrite",

    # --- Health / Biotech ---
    "benchling", "ginkgobioworks", "recursionpharma", "tempus",
    "hims", "ro", "flatironhealth", "verily",

    # --- Autonomous / Robotics ---
    "aurorainc", "cruise", "nuro", "motional",

    # --- Media / Gaming / Consumer ---
    "roblox", "niantic", "calm", "headspace",
    "peloton", "strava", "hinge", "bumble",

    # --- Other notable tech ---
    "cloudkitchens", "dutchie", "sonder", "hippo", "gopuff",
]
