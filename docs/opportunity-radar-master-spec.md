# CLAUDE MASTER BUILD BRIEF
## Opportunity Radar — Local-First SWE Internship and New-Grad Monitor

**Version:** 1.0  
**Prepared for:** Patrick Ji Min Chung  
**Primary objective:** Detect high-quality software engineering internships and early-career roles faster than community GitHub lists, especially Winter, Spring, Fall, off-cycle, co-op, and year-round openings.  
**Operating model:** Local-first, privacy-conscious, deterministic by default, broad coverage, low-noise alerts, direct application links.  
**Primary notification channel:** Discord incoming webhook.  
**Primary runtime:** macOS laptop/desktop, with optional Docker and GitHub Actions support.  
**Recommended implementation language:** Python 3.12+.

---

# 0. COPY-PASTE DIRECTIVE TO CLAUDE

Build the complete application described in this document. Do not merely explain the architecture or provide pseudocode. Produce a working repository with source code, configuration files, tests, documentation, database migrations, sample fixtures, and setup scripts.

The application must:

1. Run fully on a local macOS machine.
2. Monitor employer career sites and public applicant-tracking-system endpoints.
3. Detect newly posted SWE internships, co-ops, off-cycle roles, and relevant new-grad roles.
4. Cast a wide net while ranking jobs for Patrick’s profile.
5. Alert through Discord with the correct direct application link.
6. Deduplicate listings across sources and locations.
7. Track new, changed, closed, saved, dismissed, and applied jobs.
8. Provide a local dashboard and command-line interface.
9. Avoid scraping LinkedIn, bypassing authentication, evading bot protection, or auto-submitting applications.
10. Respect robots.txt, rate limits, terms of service, and reasonable per-domain request pacing.
11. Prefer official/public ATS APIs and structured job data over browser automation.
12. Include strong automated tests and clear error reporting.
13. Be modular enough that new ATS adapters can be added without rewriting the core.
14. Work without any paid API or LLM. Optional local-LLM and search-API integrations may be added behind feature flags.
15. Include an initial target-company registry and make it easy to add companies.

When implementation choices are ambiguous, prioritize:
**reliability > accuracy > maintainability > breadth > speed > visual polish.**

Do not ask broad planning questions. Make reasonable choices from this specification and document them. Ask only when a missing secret or an intrinsically personal field cannot be inferred, such as work authorization.

---

# 1. USER PROFILE AND SEARCH GOALS

## 1.1 Candidate profile

The ranking engine should be tailored to this profile:

- Bachelor of Science in Computer Science, UC San Diego
- Expected graduation: **December 2027**
- GPA: 3.92
- Experience:
  - IBM Turbonomic Software Developer Intern
  - Los Angeles Housing Department, Systems Division
  - Google Software Engineer mentorship through Basta Code2Career
- Strongest demonstrated areas:
  - Production software engineering
  - Backend and database development
  - Cloud/platform engineering
  - ML systems productionization
  - React/TypeScript performance and state management
  - C#/.NET/Blazor/EF Core/SQL Server
  - Python/FastAPI/Flask/PostgreSQL
  - Operating systems, concurrency, and virtual memory
  - Developer tooling, AST parsing, retrieval systems
  - AWS, Docker, Kubernetes, Kubeflow, Jenkins, Azure DevOps, Jest, Git
- Strongest projects:
  - Repolix local codebase context engine
  - Multiprogramming OS kernel
  - Trading analytics/data pipeline
- Geographic preference:
  - United States and remote
  - Open to relocation for high-quality roles
  - California is convenient but must not be treated as a hard constraint
- Role priorities:
  1. General Software Engineering
  2. Backend / Platform / Infrastructure
  3. ML Systems / Applied ML Infrastructure
  4. Developer Tools
  5. Data Infrastructure / Databases
  6. Full-stack product engineering
  7. Frontend only when the company and technical scope are strong
- Search timing priorities:
  1. Summer 2027 internships
  2. Spring 2027 / Winter 2027 off-cycle internships and co-ops
  3. Fall 2027 off-cycle internships where eligibility permits
  4. Late-2027 and early-2028 new-grad roles
- Unknown personal fields must remain configurable:
  - U.S. citizenship
  - Permanent residency
  - Sponsorship requirement
  - Defense clearance eligibility
  - Willingness to work internationally

## 1.2 Core user problem

Community GitHub lists and social posts are often delayed, incomplete, duplicated, or biased toward Summer roles. The app must monitor employer source-of-truth systems directly and notify Patrick quickly when a relevant role appears.

## 1.3 Product name

Use **Opportunity Radar** as the repository and app name unless a technical naming conflict requires `opportunity-radar`.

---

# 2. PRODUCT REQUIREMENTS

## 2.1 Must-have capabilities

### Discovery
- Scan a curated registry of target companies.
- Support public ATS sources:
  - Greenhouse
  - Lever
  - Ashby
- Support generic employer career pages through:
  - `JobPosting` JSON-LD
  - HTML parsing
  - sitemaps
  - RSS/Atom when available
- Support browser rendering with Playwright only as a final fallback.
- Build an adapter/plugin architecture for:
  - Workday
  - SmartRecruiters
  - iCIMS
  - Eightfold
  - SAP SuccessFactors
  - Taleo
  - custom employer sites
- Allow manual source URLs and adapter hints per company.
- Detect ATS type automatically from URLs and HTML fingerprints when possible.

### Normalization
Every listing must be normalized into one common schema, regardless of source.

### Matching
- Detect internships, co-ops, off-cycle roles, apprenticeships, and new-grad roles.
- Detect SWE variants beyond exact title matches.
- Infer season and target start window from title and description.
- Score each listing for company quality, technical fit, timing, eligibility, location, and freshness.
- Preserve a broad “review” queue so borderline jobs are not silently discarded.

### Notifications
- Send immediate Discord alerts for high-priority matches.
- Send scheduled Discord digests for medium-priority matches.
- Include a direct employer application link.
- Include why the listing matched.
- Include posted date when trustworthy and always include first-seen timestamp.
- Never alert the same unchanged job twice.
- Alert on meaningful changes when configured.

### Tracking
- Track:
  - new
  - changed
  - active
  - closed
  - saved
  - dismissed
  - applied
  - OA
  - interview
  - offer
  - rejected
- Allow notes, recruiter name, referral status, deadline, and resume variant.
- Export to CSV and JSON.

### Local interface
- CLI for all core operations.
- Local dashboard bound to `127.0.0.1`, not publicly exposed.
- Search, filters, sorting, and status updates.
- Source-health page showing broken adapters and last successful scan.

### Scheduling
- Local daemon mode.
- macOS `launchd` configuration.
- Manual `scan` command.
- Optional Docker Compose mode.
- Optional GitHub Actions scheduled mode, but local operation is the primary requirement.

---

# 3. NON-GOALS AND HARD SAFETY RULES

The application must not:

- Auto-submit job applications.
- Scrape LinkedIn or bypass LinkedIn restrictions.
- Bypass login pages, CAPTCHAs, access controls, or anti-bot systems.
- Rotate proxies to evade rate limits.
- Pretend an inferred start date is confirmed.
- Invent compensation, sponsorship, clearance, graduation eligibility, or deadlines.
- Use a cloud LLM by default.
- Require a paid API.
- Store Discord webhook URLs in source control.
- Expose the local dashboard to the public internet by default.
- Hammer employer sites.
- Treat robots.txt as authorization; it is a crawler preference mechanism, and terms of service still matter.
- Ingest applicant personal data or automate application forms.

Use official/public endpoints whenever available. If a source disallows automated access, disable it and log the reason.

---

# 4. RECOMMENDED TECH STACK

## 4.1 Runtime and packaging

- Python 3.12+
- `uv` for dependency and virtual-environment management
- `pyproject.toml`
- `ruff` for linting and formatting
- `mypy` or `pyright` for type checking
- `pytest` and `pytest-asyncio`
- `pre-commit`

## 4.2 Core libraries

- `httpx` — async HTTP
- `pydantic` v2 — models and configuration
- `sqlalchemy` 2.x — persistence
- `alembic` — migrations
- `aiosqlite` — local SQLite
- `typer` — CLI
- `fastapi` — local API/dashboard backend
- `uvicorn` — local server
- `jinja2` — server-rendered dashboard
- `beautifulsoup4`
- `lxml`
- `selectolax` — optional fast HTML parsing
- `dateparser`
- `python-dateutil`
- `rapidfuzz`
- `tenacity`
- `structlog`
- `apscheduler`
- `playwright` — fallback only
- `pyyaml`
- `orjson`
- `feedparser`
- `urllib.robotparser`
- `rich` — CLI output

## 4.3 Optional local intelligence

These must be optional and disabled by default:

- `sentence-transformers` for semantic role-fit similarity
- Ollama-compatible local model for summaries
- local embeddings for job-description similarity
- a paid search API for automatic career-page discovery

The application must work correctly without these.

---

# 5. REPOSITORY STRUCTURE

Claude should create at least:

```text
opportunity-radar/
├── README.md
├── pyproject.toml
├── uv.lock
├── .env.example
├── .gitignore
├── Makefile
├── Dockerfile
├── docker-compose.yml
├── alembic.ini
├── migrations/
├── config/
│   ├── settings.example.yaml
│   ├── profile.example.yaml
│   ├── companies.example.yaml
│   ├── scoring.example.yaml
│   └── title_rules.yaml
├── scripts/
│   ├── install_macos.sh
│   ├── install_launchd.sh
│   ├── uninstall_launchd.sh
│   └── baseline_scan.sh
├── launchd/
│   └── com.patrick.opportunity-radar.plist.template
├── src/opportunity_radar/
│   ├── __init__.py
│   ├── __main__.py
│   ├── cli.py
│   ├── config.py
│   ├── logging.py
│   ├── constants.py
│   ├── models/
│   │   ├── job.py
│   │   ├── company.py
│   │   ├── scan.py
│   │   └── application.py
│   ├── db/
│   │   ├── engine.py
│   │   ├── tables.py
│   │   ├── repositories.py
│   │   └── migrations.py
│   ├── adapters/
│   │   ├── base.py
│   │   ├── greenhouse.py
│   │   ├── lever.py
│   │   ├── ashby.py
│   │   ├── jsonld.py
│   │   ├── sitemap.py
│   │   ├── html_generic.py
│   │   ├── playwright_generic.py
│   │   └── registry.py
│   ├── discovery/
│   │   ├── ats_fingerprint.py
│   │   ├── career_links.py
│   │   └── source_validator.py
│   ├── pipeline/
│   │   ├── scanner.py
│   │   ├── normalizer.py
│   │   ├── deduper.py
│   │   ├── change_detector.py
│   │   └── closure_detector.py
│   ├── matching/
│   │   ├── title_classifier.py
│   │   ├── season_parser.py
│   │   ├── eligibility.py
│   │   ├── scorer.py
│   │   └── explanations.py
│   ├── notifications/
│   │   ├── discord.py
│   │   ├── digest.py
│   │   └── templates.py
│   ├── scheduler/
│   │   ├── daemon.py
│   │   └── jobs.py
│   ├── web/
│   │   ├── app.py
│   │   ├── routes.py
│   │   ├── schemas.py
│   │   ├── templates/
│   │   └── static/
│   └── utilities/
│       ├── hashing.py
│       ├── dates.py
│       ├── text.py
│       ├── urls.py
│       └── rate_limit.py
├── tests/
│   ├── fixtures/
│   ├── unit/
│   ├── integration/
│   └── end_to_end/
└── data/
    └── .gitkeep
```

---

# 6. DATA MODEL

## 6.1 Normalized Job model

Implement a strongly typed model similar to:

```python
class JobRecord(BaseModel):
    source_name: str
    source_adapter: str
    source_job_id: str
    company_id: str
    company_name: str

    title: str
    normalized_title: str
    description_html: str | None
    description_text: str
    department: str | None
    team: str | None

    primary_location: str | None
    all_locations: list[str]
    remote_type: Literal["remote", "hybrid", "onsite", "unknown"]
    country_codes: list[str]

    employment_type: str | None
    role_family: str | None
    seniority: str | None

    season: Literal[
        "winter", "spring", "summer", "fall",
        "off_cycle", "year_round", "unspecified"
    ]
    season_year: int | None
    start_date_min: date | None
    start_date_max: date | None
    duration_weeks: int | None
    full_time_required: bool | None

    degree_levels: list[str]
    graduation_min: date | None
    graduation_max: date | None
    requires_return_to_school: bool | None
    work_authorization_text: str | None
    citizenship_required: bool | None
    clearance_required: bool | None

    compensation_min: Decimal | None
    compensation_max: Decimal | None
    compensation_period: str | None
    compensation_currency: str | None

    posted_at: datetime | None
    updated_at: datetime | None
    first_seen_at: datetime
    last_seen_at: datetime
    closed_at: datetime | None

    apply_url: HttpUrl
    canonical_url: HttpUrl
    source_url: HttpUrl

    content_hash: str
    identity_hash: str
    status: Literal["active", "closed", "unknown"]

    match_score: float
    match_reasons: list[str]
    risk_flags: list[str]
    season_confidence: float
    eligibility_confidence: float
```

## 6.2 Identity and deduplication

Use multiple identifiers:

1. `source_adapter + company + source_job_id`
2. canonicalized apply URL
3. normalized company + title + location
4. content fingerprint

Do not merge distinct jobs simply because titles match.

Create a `job_aliases` table so one logical role can have:
- several source URLs
- several city variants
- duplicate listings on a company site and ATS
- reposts

## 6.3 Application tracking

Create an `applications` table:

```text
job_id
status
saved_at
applied_at
resume_variant
referral_status
referrer_name
recruiter_name
deadline
oa_date
interview_stage
follow_up_date
notes
```

---

# 7. SOURCE ADAPTER CONTRACT

Create an abstract adapter interface:

```python
class JobSourceAdapter(Protocol):
    name: str

    async def validate(self, company: CompanySource) -> ValidationResult:
        ...

    async def fetch_jobs(
        self,
        company: CompanySource,
        client: httpx.AsyncClient,
    ) -> list[RawJob]:
        ...

    def normalize(
        self,
        raw_job: RawJob,
        company: CompanySource,
    ) -> JobRecord:
        ...
```

Adapters must:
- have deterministic unit-test fixtures
- produce structured errors
- expose `last_success_at`
- indicate whether failures are retryable
- support conditional HTTP requests where possible
- avoid logging secrets
- return zero jobs only when that is distinguishable from a failed fetch

---

# 8. ATS IMPLEMENTATION DETAILS

## 8.1 Greenhouse

Use the public Job Board API.

Expected pattern:

```text
GET https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs?content=true
```

Store:
- job ID
- title
- location
- updated time
- absolute URL
- content
- departments/offices when present

Greenhouse GET job-board data is public and does not require authentication. Do not use the application submission endpoint.

Board-token discovery:
- detect `boards.greenhouse.io/{token}`
- detect `job-boards.greenhouse.io/{token}`
- detect `gh_jid`
- inspect career-page links and embedded scripts

## 8.2 Lever

Use Lever’s published Postings API or hosted postings data.

Support:
- global `jobs.lever.co`
- EU instance where present
- site token
- pagination
- direct hosted apply URL

Do not attempt programmatic application.

## 8.3 Ashby

Use:

```text
GET https://api.ashbyhq.com/posting-api/job-board/{JOB_BOARD_NAME}?includeCompensation=true
```

Capture:
- title
- location
- secondary locations
- department/team
- published state
- compensation when returned
- job URL and apply URL

## 8.4 Generic JSON-LD

Parse:

```html
<script type="application/ld+json">
```

Accept:
- a single object
- arrays
- `@graph`
- nested `JobPosting`

Map fields such as:
- title
- description
- datePosted
- validThrough
- employmentType
- hiringOrganization
- jobLocation
- applicantLocationRequirements
- jobLocationType
- baseSalary

Do not assume every field is accurate. Preserve source values and confidence.

## 8.5 Sitemap and feed adapter

Support:
- `sitemap.xml`
- sitemap indexes
- careers-specific sitemaps
- RSS/Atom feeds

Filter candidate URLs using terms such as:
`job`, `jobs`, `career`, `careers`, `position`, `opening`, `requisition`.

## 8.6 Generic HTML adapter

Use configurable selectors in `companies.yaml`.

Example:

```yaml
adapter: html_generic
list_url: https://example.com/careers
selectors:
  card: ".job-card"
  title: ".job-card__title"
  location: ".job-card__location"
  url: "a@href"
```

The generic adapter should support:
- pagination
- “load more” URLs
- query parameters
- detail-page fetching
- relative URL normalization

## 8.7 Playwright fallback

Use only when:
- the page is JavaScript-rendered
- no public API, JSON-LD, feed, sitemap, or stable HTML path exists
- robots/terms permit access

Requirements:
- Chromium only by default
- block images/fonts/media to reduce cost
- wait for a specific selector, not arbitrary long sleeps
- hard timeout
- one page per domain at a time
- screenshots only for debugging
- never attempt CAPTCHA solving

## 8.8 Unsupported ATS

Create adapter placeholders and documentation for:
- Workday
- SmartRecruiters
- iCIMS
- Eightfold
- SAP SuccessFactors
- Taleo

Do not build the application around undocumented endpoints. If a stable public JSON request is discovered for a specific company, implement it as a company-specific adapter or configurable fetch strategy with tests.

---

# 9. COMPANY REGISTRY

## 9.1 Registry format

```yaml
companies:
  - id: google
    name: Google
    domain: google.com
    tier: core
    enabled: true
    career_urls:
      - https://www.google.com/about/careers/applications/jobs/results/
    adapter: auto
    tags: [faang, cloud, ai, infrastructure]
    scan_interval_minutes: 30

  - id: example-greenhouse
    name: Example
    domain: example.com
    tier: strong
    enabled: true
    adapter: greenhouse
    adapter_config:
      board_token: example
```

## 9.2 Target tiers

- `core`: Must alert quickly; highest-quality targets
- `strong`: FAANG-equivalent, top infrastructure, fintech, trading, AI, aerospace, or high-growth firms
- `broad`: Good engineering employers and selective startups
- `exploratory`: New or uncertain companies; digest only

## 9.3 Initial target universe

Claude should generate a starter registry and attempt to populate career URLs and ATS hints. At minimum include these names, grouped by category. This is a seed list, not a claim that each company currently has an opening.

### Core large technology
Google, Meta, Amazon, AWS, Apple, Netflix, Microsoft, NVIDIA, IBM, Adobe, Salesforce, Oracle, Cisco, Intel, AMD, Qualcomm, Broadcom, SAP, ServiceNow, Workday.

### AI, ML, and compute infrastructure
OpenAI, Anthropic, xAI, Scale AI, Databricks, Snowflake, CoreWeave, Lambda, Cerebras, Groq, SambaNova, Together AI, Hugging Face, Cohere, Mistral AI, Perplexity, Anysphere, Glean, Harvey, Runway, ElevenLabs, Weights & Biases, Modal, Baseten, Replicate, Pinecone.

### Cloud, infrastructure, databases, observability, and developer tools
Cloudflare, Datadog, MongoDB, Confluent, Elastic, HashiCorp, Redis, Cockroach Labs, PlanetScale, Supabase, Vercel, Netlify, Sentry, Grafana Labs, Temporal, Docker, GitHub, GitLab, Atlassian, JetBrains, Postman, Twilio, PagerDuty, New Relic, Splunk, Fastly, DigitalOcean, Heroku, Fivetran, dbt Labs, Astronomer, Airbyte, MotherDuck, Materialize.

### Product and collaboration software
Figma, Notion, Airtable, Linear, Asana, Dropbox, Box, Zoom, Slack, HubSpot, Canva, Miro, Monday.com, Smartsheet, DocuSign, Grammarly.

### Consumer and marketplace technology
Airbnb, Uber, Lyft, DoorDash, Instacart, Pinterest, Snap, Reddit, Roblox, Discord, Spotify, Duolingo, Twitch, Etsy, eBay, Walmart Global Tech, Wayfair.

### Fintech and financial infrastructure
Stripe, Block, Plaid, Ramp, Brex, Robinhood, Coinbase, Chime, SoFi, Affirm, Mercury, Rippling, Carta, Gusto, Adyen, Marqeta, Toast, Bill, Alloy, Modern Treasury, Highnote, Lithic.

### Quantitative trading and market technology
Jane Street, Hudson River Trading, Citadel, Citadel Securities, Two Sigma, D. E. Shaw, IMC, Optiver, DRW, Susquehanna International Group, Jump Trading, Tower Research Capital, Akuna Capital, Five Rings, Virtu Financial, Valkyrie Trading, Belvedere Trading, Old Mission, Wolverine Trading, TransMarket Group.

### Security
CrowdStrike, Palo Alto Networks, Wiz, Zscaler, Okta, SentinelOne, Snyk, Vanta, Rubrik, Verkada, Cloudflare, 1Password, Arctic Wolf, Rapid7, Tenable, Netskope, Abnormal Security, Chainguard.

### Autonomous systems, aerospace, defense, and robotics
Palantir, Anduril, SpaceX, Tesla, Waymo, Zoox, Aurora, Nuro, Applied Intuition, Skydio, Shield AI, Saronic, Hermeus, Varda Space, Hadrian, Astranis, Relativity Space, Rocket Lab, Zipline, Figure AI, Agility Robotics, Neuralink, Gecko Robotics, Saildrone, Covariant, Dexterity, Machina Labs, Epirus.

### Semiconductors and hardware-adjacent software
Arm, Synopsys, Cadence, ASML, Applied Materials, Lam Research, Micron, Western Digital, Seagate, Marvell, MediaTek, Texas Instruments, Analog Devices, NXP, Keysight, KLA.

### Healthcare, biotech, and life-science software
Epic, Flatiron Health, Tempus, Benchling, Veeva, Moderna, Illumina, Recursion, Insitro, PathAI, 10x Genomics, Verily, Color Health, Komodo Health, Nuna, Cedar, Abridge.

### Public-sector, industrial, transportation, and enterprise operations
Palantir, Samsara, Motive, Procore, Autodesk, Bentley Systems, Esri, Trimble, Siemens, GE Aerospace, Honeywell, Northrop Grumman, Lockheed Martin, RTX, Boeing, General Dynamics, Leidos, MITRE.

### Startup discovery sources
YC Work at a Startup, Wellfound, company-specific Greenhouse/Lever/Ashby boards, accelerator portfolio pages, and public startup career pages.

The registry must be editable without code changes. Add a CLI command:

```bash
opportunity-radar companies add
opportunity-radar companies discover
opportunity-radar companies validate
opportunity-radar companies disable
```

---

# 10. TITLE AND ROLE CLASSIFICATION

## 10.1 Positive title patterns

Include, but do not limit to:

```text
software engineer
software engineering
software developer
software development engineer
SDE
backend engineer
backend developer
platform engineer
infrastructure engineer
systems engineer
product engineer
full stack engineer
full-stack engineer
frontend engineer
front-end engineer
machine learning engineer
ML engineer
ML systems
data engineer
database engineer
developer tools
cloud engineer
site reliability engineer
SRE
robotics software
embedded software
simulation software
HMI software
engineering intern
software co-op
```

## 10.2 Student/early-career signals

```text
intern
internship
co-op
coop
off-cycle
off cycle
year-round
student
university
undergraduate
new college graduate
new grad
graduate software engineer
early career
apprentice
```

## 10.3 Exclusion/downranking patterns

Hard exclude only when high confidence:

```text
senior
staff
principal
lead
manager
director
architect
10+ years
8+ years
PhD required
licensed professional engineer
nurse
mechanical-only
civil-only
marketing
sales
IT support
help desk
unpaid trial
```

Do not hard-exclude:
- roles with vague seniority
- roles listing 1–2 years preferred
- roles saying “graduate degree preferred”
- mixed software/hardware positions with substantial software work

## 10.4 Role families

Classify into:
- general_swe
- backend
- infrastructure
- ml_systems
- data_infrastructure
- developer_tools
- frontend
- fullstack
- embedded
- robotics
- security
- quant_developer
- research_engineering
- adjacent
- irrelevant

---

# 11. SEASON AND DATE PARSING

## 11.1 Season vocabulary

```text
winter
spring
summer
fall
autumn
off-cycle
off cycle
year-round
semester
quarter
Q1
Q2
Q3
Q4
January
February
March
April
May
June
July
August
September
October
November
December
```

## 11.2 Inference rules

Priority:
1. Explicit title
2. Explicit description
3. Explicit start-date field
4. Date range in description
5. Program name
6. Posting month heuristic, with low confidence only

Never convert a low-confidence inference into a confirmed season.

Examples:
- “Spring 2027 Software Engineering Intern” → spring 2027, confidence 1.0
- “Starts January or February 2027” → winter/spring 2027, confidence 0.9
- “12-week internship, start dates in Aug/Sept” → fall, confidence 0.9
- generic “Software Intern” posted in November → unspecified, not automatically spring

## 11.3 Patrick’s target windows

Use configurable windows:

```yaml
target_windows:
  - name: spring_2027
    start: 2027-01-01
    end: 2027-06-15
    priority: 95
  - name: summer_2027
    start: 2027-05-15
    end: 2027-09-15
    priority: 100
  - name: fall_2027
    start: 2027-08-01
    end: 2027-12-31
    priority: 80
  - name: new_grad_late_2027
    start: 2027-10-01
    end: 2028-06-30
    priority: 70
```

---

# 12. ELIGIBILITY ENGINE

The system must distinguish:
- confirmed eligible
- likely eligible
- uncertain
- likely ineligible
- confirmed ineligible

Inputs:
- expected graduation December 2027
- degree level
- enrollment/return-to-school language
- graduation-window language
- full-time availability requirements
- work authorization
- citizenship/clearance
- location

Important:
- Do not assume considering a master’s satisfies a return-to-school requirement.
- Do not assume part-time enrollment satisfies full-time-student requirements.
- Surface the exact eligibility sentence in the job detail.
- Make citizenship and sponsorship configurable.

Example risk flags:
- `requires_full_academic_term_after_internship`
- `graduate_students_only`
- `phd_only`
- `us_citizenship_required`
- `security_clearance_required`
- `graduation_window_uncertain`
- `fall_2027_conflicts_with_expected_graduation`
- `international_work_authorization_unknown`

---

# 13. SCORING MODEL

Use deterministic weighted scoring. Store both total score and individual components.

## 13.1 Suggested score

```text
Company quality:              0–25
Role-family fit:              0–20
Season/timing fit:            0–20
Technical-skill overlap:      0–15
Production/systems relevance: 0–10
Location/remote fit:          0–5
Freshness:                    0–5
Eligibility adjustment:     -50–0
Risk/noise adjustment:      -30–0
```

Clamp to 0–100.

## 13.2 Company quality

Example:
- core: 25
- strong: 20
- broad: 14
- exploratory: 8

Do not let company tier overwhelm actual role relevance.

## 13.3 Role-fit priorities

```yaml
role_family_weights:
  general_swe: 20
  backend: 20
  infrastructure: 20
  ml_systems: 19
  developer_tools: 19
  data_infrastructure: 18
  fullstack: 16
  quant_developer: 15
  robotics: 14
  frontend: 12
  embedded: 10
  adjacent: 5
```

## 13.4 Skill weights tailored to Patrick

Highest:
- Python
- Java
- C#
- C/C++
- JavaScript/TypeScript
- React
- SQL
- .NET
- backend APIs
- cloud
- distributed systems
- infrastructure
- databases
- Kubernetes
- Docker
- ML pipelines
- developer tooling
- operating systems
- concurrency

Medium:
- AWS
- PostgreSQL
- SQL Server
- FastAPI
- Flask
- Jest
- Jenkins
- Azure DevOps
- Tree-sitter
- retrieval systems
- data pipelines

Do not penalize a role simply because its exact framework is absent. Concepts transfer.

## 13.5 Alert thresholds

```yaml
alerts:
  immediate_min_score: 82
  digest_min_score: 60
  dashboard_min_score: 35
  suppress_below_score: 20
```

Immediate alert overrides:
- explicit Spring/Winter/Fall SWE role at core/strong company
- role posted within last 24 hours and match score ≥75
- deadline within 5 days and match score ≥70
- saved target company opens first relevant role of season

---

# 14. DEDUPLICATION AND CHANGE DETECTION

## 14.1 First-run baseline

This is critical.

Default first run must:
- import existing jobs
- mark them as baseline
- send no individual alerts
- produce one summary: number of active listings by score and source

Provide:
```bash
opportunity-radar baseline
```

To alert on existing roles:
```bash
opportunity-radar baseline --alert-existing
```

## 14.2 Meaningful changes

Alert optionally when:
- title changes
- location expands to remote/US
- season or start date changes
- deadline added
- eligibility changes
- role reopens after closure
- description changes substantially
- compensation added

Do not alert for:
- whitespace
- HTML formatting
- tracking parameters
- minor punctuation
- reordered boilerplate

## 14.3 Closure

Mark a job closed when:
- API no longer returns it for two consecutive successful scans, or
- detail URL returns clear 404/410/closed state, or
- `validThrough` passed and page confirms closure

Do not mark closed if the source scan failed.

---

# 15. DISCORD NOTIFICATIONS

## 15.1 Use incoming webhook

A simple incoming webhook is sufficient. No Discord bot account is required.

## 15.2 Immediate alert format

```text
🚨 NEW HIGH-PRIORITY ROLE

Company: Palantir
Role: Software Engineer Intern — Spring 2027
Location: New York, NY
Season: Spring 2027
Score: 93/100
First seen: 8 minutes ago
Posted: 2026-08-05, if confirmed

Why it matches:
• Core target company
• Production SWE role
• Java/Python/backend overlap
• Graduation window appears compatible
• Explicit off-cycle timing

Risks:
• Full-time availability required
• Work authorization language not found

Apply: [Direct employer link]
Dashboard: [Local job page]
```

Use Discord embeds with:
- title linked to `apply_url`
- company
- role
- score
- season
- location
- match reasons
- risk flags
- timestamps
- source
- color based on score

Sanitize user-controlled text and disable accidental mentions.

## 15.3 Digests

Send:
- morning digest
- evening digest
- optional weekly summary

Digest sections:
- New high-priority
- New review-worthy
- Deadlines approaching
- Changed/reopened
- Source failures requiring attention

## 15.4 Failure notifications

Notify only when:
- a core source fails 3 consecutive scans
- Discord itself fails
- database migration fails
- the scheduler has not completed a successful scan within the expected window

---

# 16. LOCAL DASHBOARD

Run at:

```text
http://127.0.0.1:8765
```

Pages:

## Home
- high-priority new today
- off-season openings
- Summer 2027 openings
- approaching deadlines
- recently changed
- source health

## Jobs
Filters:
- status
- season
- year
- score
- company tier
- role family
- location
- remote type
- posted/first-seen date
- eligibility
- source
- saved/applied/dismissed

Actions:
- save
- dismiss
- apply
- mark OA
- mark interview
- add note
- copy application link
- open employer page
- choose resume variant

## Job detail
Show:
- full normalized description
- source excerpt
- exact eligibility text
- match explanation
- risk flags
- change history
- source URLs
- direct apply link
- application history

## Companies
- target tier
- adapter
- scan interval
- last successful scan
- active relevant jobs
- failure count
- enable/disable

## Source health
- scan latency
- HTTP status
- robots status
- last error
- consecutive failures
- job count anomaly

## Settings
- profile
- notification thresholds
- target seasons
- location
- work authorization
- scan cadence

Use simple server-rendered HTML. Avoid a large JavaScript frontend unless necessary.

---

# 17. CLI

Implement:

```bash
opportunity-radar init
opportunity-radar baseline
opportunity-radar scan
opportunity-radar scan --company stripe
opportunity-radar scan --adapter greenhouse
opportunity-radar daemon
opportunity-radar serve
opportunity-radar status
opportunity-radar jobs list
opportunity-radar jobs show JOB_ID
opportunity-radar jobs save JOB_ID
opportunity-radar jobs dismiss JOB_ID
opportunity-radar jobs applied JOB_ID
opportunity-radar jobs export --format csv
opportunity-radar companies list
opportunity-radar companies add
opportunity-radar companies discover COMPANY
opportunity-radar companies validate
opportunity-radar sources health
opportunity-radar notify test
opportunity-radar db migrate
opportunity-radar doctor
```

`doctor` should verify:
- Python version
- config files
- database path
- write permissions
- Discord webhook
- Playwright installation
- network connectivity
- company registry validity

---

# 18. CONFIGURATION

## 18.1 `.env.example`

```dotenv
OPPORTUNITY_RADAR_ENV=local
OPPORTUNITY_RADAR_DB_URL=sqlite+aiosqlite:///./data/opportunity_radar.db
DISCORD_WEBHOOK_URL=
OPPORTUNITY_RADAR_SECRET_KEY=
OLLAMA_BASE_URL=http://127.0.0.1:11434
SEARCH_API_KEY=
```

## 18.2 `profile.yaml`

```yaml
candidate:
  expected_graduation: 2027-12-01
  degree_level: bachelors
  school: University of California, San Diego
  country: US

  requires_sponsorship: null
  us_citizen: null
  permanent_resident: null
  clearance_eligible: null

preferences:
  countries: [US]
  allow_remote: true
  willing_to_relocate: true
  preferred_locations:
    - California
    - New York
    - Seattle
    - Boston
    - Austin
    - Remote

  role_families:
    - general_swe
    - backend
    - infrastructure
    - ml_systems
    - developer_tools
    - data_infrastructure
    - fullstack

  target_seasons:
    - spring_2027
    - summer_2027
    - fall_2027
    - new_grad_late_2027

skills:
  languages:
    - Python
    - Java
    - C#
    - C
    - C++
    - JavaScript
    - TypeScript
    - SQL
  technologies:
    - React
    - .NET
    - Blazor
    - Entity Framework Core
    - FastAPI
    - Flask
    - PostgreSQL
    - SQL Server
    - AWS
    - Docker
    - Kubernetes
    - Kubeflow
    - Jenkins
    - Azure DevOps
    - Jest
    - Git
    - Tree-sitter
    - ChromaDB
  concepts:
    - production software
    - backend systems
    - cloud infrastructure
    - distributed systems
    - machine learning systems
    - developer tooling
    - databases
    - operating systems
    - concurrency
    - data pipelines
```

## 18.3 Scheduler settings

```yaml
scheduler:
  default_interval_minutes: 30
  core_interval_minutes: 20
  strong_interval_minutes: 45
  broad_interval_minutes: 120
  exploratory_interval_minutes: 360
  max_concurrency_global: 8
  max_concurrency_per_domain: 1
  request_timeout_seconds: 30
  retries: 3
  backoff_seconds: [2, 8, 30]
  jitter_seconds: 45
```

---

# 19. LOCAL macOS OPERATION

## 19.1 Installation flow

README must include:

```bash
git clone <repo>
cd opportunity-radar
brew install uv
uv sync
cp .env.example .env
cp config/profile.example.yaml config/profile.yaml
cp config/companies.example.yaml config/companies.yaml
uv run playwright install chromium
uv run opportunity-radar init
uv run opportunity-radar doctor
uv run opportunity-radar baseline
uv run opportunity-radar serve
```

## 19.2 Discord setup

Explain:
1. Create a private Discord server or channel.
2. Channel Settings → Integrations → Webhooks.
3. Create webhook.
4. Copy URL into `.env`.
5. Run:
   ```bash
   uv run opportunity-radar notify test
   ```

## 19.3 launchd

Provide an installer that:
- writes an absolute-path plist
- starts `opportunity-radar daemon`
- restarts on failure
- writes logs to `~/Library/Logs/OpportunityRadar/`
- loads with `launchctl`
- includes uninstall instructions

The daemon should scan on its own schedule. Do not use a one-shot launchd job every few minutes if a resilient long-running process is simpler.

## 19.4 Sleep behavior

Document that scans do not run while the Mac is fully asleep. On resume, the daemon should:
- detect missed scan windows
- run one catch-up scan
- avoid launching many duplicate catch-up jobs

---

# 20. OPTIONAL GITHUB ACTIONS MODE

Provide an optional workflow for users who want scanning while the local Mac is offline.

Requirements:
- secrets stored in GitHub Actions secrets
- SQLite state stored safely, preferably via artifact or external database
- do not commit a frequently changing database to Git unless explicitly chosen
- use concurrency control
- allow manual dispatch
- schedule at a non-round minute to reduce congestion
- note that scheduled workflows can be delayed
- local mode remains canonical

Example outline:

```yaml
name: Opportunity Radar Scan

on:
  schedule:
    - cron: "17 * * * *"
      timezone: "America/Los_Angeles"
  workflow_dispatch:

concurrency:
  group: opportunity-radar-scan
  cancel-in-progress: false
```

A hosted Postgres/Supabase option may be documented, but it must not be required.

---

# 21. RATE LIMITING, CACHING, AND POLITENESS

Implement:
- descriptive user agent:
  `OpportunityRadar/1.0 (+local personal job monitor; contact configurable)`
- per-domain semaphore
- exponential backoff
- retry only retryable status codes
- honor `Retry-After`
- ETag and `If-None-Match`
- `Last-Modified` and `If-Modified-Since`
- response cache
- robots.txt check for generic crawling
- long intervals for static pages
- no recursive crawling beyond configured depth
- no more than necessary to detect changes

ATS public APIs may use normal polling but still require sensible pacing.

---

# 22. LOGGING AND OBSERVABILITY

Use structured logs with:
- scan ID
- company ID
- adapter
- URL host
- duration
- response status
- job count
- new count
- changed count
- closed count
- retry count
- error category

Log levels:
- INFO: summary
- DEBUG: request and parsing detail without secrets
- WARNING: recoverable source issue
- ERROR: failed source
- CRITICAL: database/scheduler failure

Create a `scan_runs` table and dashboard metrics.

Anomaly detection:
- source previously had 80 jobs and now has 0 → warn, do not close all
- parsing selector returns no cards → adapter degraded
- unusually high duplicate rate → warn
- all URLs changed at once → likely site migration

---

# 23. TESTING

## 23.1 Unit tests

Test:
- title normalization
- season parsing
- date parsing
- graduation windows
- location normalization
- URL canonicalization
- identity hashes
- content hashes
- score components
- exclusion rules
- Discord embed construction
- robots decisions

## 23.2 Adapter fixture tests

Save sanitized fixtures for:
- Greenhouse
- Lever
- Ashby
- JSON-LD single object
- JSON-LD `@graph`
- sitemap index
- HTML cards
- closed page
- malformed response
- rate-limit response

No live network required for default test suite.

## 23.3 Integration tests

- fetch fixture server
- normalize jobs
- persist
- deduplicate
- score
- create alert
- update listing
- close listing

## 23.4 End-to-end smoke test

A local fake careers site should:
- publish one job
- update it
- remove it
- verify expected notifications and states

## 23.5 Quality gates

CI must run:
- ruff format check
- ruff lint
- type checker
- pytest
- migration check

Target at least 80% coverage for core parsing, matching, and state logic.

---

# 24. SECURITY AND PRIVACY

- Store secrets only in `.env`, Keychain integration, or secret manager.
- `.env` and local DB must be gitignored.
- Do not log webhook URLs.
- Bind dashboard to localhost.
- Use CSRF protection for state-changing dashboard actions.
- Use secure session cookie if authentication is enabled.
- Escape all job-description HTML.
- Sanitize Discord content.
- Do not execute scripts from scraped pages.
- Playwright must use a fresh isolated context.
- Treat all scraped content as untrusted.
- Avoid storing unnecessary personal data.

---

# 25. APPLICATION WORKFLOW

The app should support this daily process:

1. Discord alert arrives.
2. Patrick opens direct employer link.
3. Patrick checks the local detail page for:
   - eligibility
   - season
   - deadline
   - score reasons
   - role-specific risks
4. Patrick marks:
   - saved
   - dismissed
   - applied
5. If applied:
   - record resume variant
   - referral
   - application date
   - notes
6. Dashboard shows follow-ups and deadlines.

Resume variants:
- `general_swe`
- `backend_infrastructure`
- `ai_ml_systems`
- `startup_product`

The app may recommend a variant, but it must not rewrite or auto-edit the resume.

---

# 26. MATCH EXPLANATION

Every score must be explainable.

Example:

```json
{
  "score": 91,
  "reasons": [
    "Core target company",
    "Explicit Spring 2027 internship",
    "Backend/platform role family",
    "Matches Python, Java, SQL, Docker, and distributed-systems experience",
    "Expected graduation appears within stated window",
    "Posted within the last 12 hours"
  ],
  "risks": [
    "Full-time availability required",
    "Sponsorship policy not found"
  ]
}
```

Avoid generic LLM-style claims. Explanations should cite extracted sentences or fields when possible.

---

# 27. OPTIONAL LOCAL LLM FEATURES

Only after the deterministic app works:

- summarize role in 3 bullets
- extract technical requirements
- explain why Patrick matches
- detect ambiguous season language
- generate search keywords
- propose resume variant

Rules:
- optional
- local-first through Ollama
- no job excluded solely by LLM output
- cache outputs
- label AI-derived fields
- deterministic parser remains source of truth
- do not send resume or personal profile to external services without explicit opt-in

---

# 28. SECONDARY SOURCES

Support optional ingestion from:
- public GitHub internship lists
- YC company jobs
- Wellfound public pages where permitted
- company portfolio pages
- public university job boards where accessible without authentication
- RSS feeds
- public newsletters

These are secondary signals. Employer source-of-truth pages remain primary.

When a secondary source links to an employer application:
- store both URLs
- prefer employer apply URL
- use secondary source only for discovery
- deduplicate against existing jobs

---

# 29. FRESHNESS STRATEGY

Use `first_seen_at` as the most reliable internal freshness measure.

`posted_at` hierarchy:
1. ATS API timestamp
2. structured-data `datePosted`
3. explicit page text
4. unknown

Do not infer a precise posted date from search-engine snippets.

High-priority freshness boosts:
- first seen < 6 hours
- first seen < 24 hours
- first seen < 72 hours

Decay gradually, not abruptly.

---

# 30. ACCEPTANCE CRITERIA

The build is complete only when all are true:

1. Fresh install works from README on macOS.
2. A user can set a Discord webhook and receive a test message.
3. Baseline scan imports jobs without flooding alerts.
4. Greenhouse, Lever, and Ashby adapters work against fixtures and at least one live public board each.
5. JSON-LD fallback works.
6. Jobs are normalized into one schema.
7. Duplicate listings are merged safely.
8. New jobs produce one alert.
9. Changed jobs are tracked and optionally alerted.
10. Closed jobs are not falsely closed after a source failure.
11. The scoring system reflects Patrick’s profile.
12. Explicit Winter/Spring/Fall roles receive timing priority.
13. The dashboard works locally.
14. The CLI supports scan, daemon, status, companies, and job status changes.
15. Local daemon survives transient network failures.
16. `launchd` installer works.
17. Tests pass.
18. Type checking and linting pass.
19. Secrets are not committed.
20. No auto-application functionality exists.
21. Documentation explains how to add a company and adapter.
22. Source-health failures are visible.
23. CSV export works.
24. Direct application links are preserved.
25. The app can run without a paid API or LLM.

---

# 31. IMPLEMENTATION PLAN FOR CLAUDE

## Phase 1 — Foundation
- package setup
- config
- logging
- database
- models
- CLI
- migrations

## Phase 2 — Source adapters
- Greenhouse
- Lever
- Ashby
- JSON-LD
- fixtures and tests

## Phase 3 — Pipeline
- scanner
- normalization
- hashing
- dedupe
- change detection
- closure safety

## Phase 4 — Matching
- title classifier
- season parser
- eligibility
- scoring
- explanations

## Phase 5 — Notifications
- Discord
- immediate alerts
- digests
- failure alerts

## Phase 6 — Dashboard
- job table
- filters
- job detail
- status updates
- companies
- source health

## Phase 7 — Scheduling
- daemon
- catch-up scans
- macOS launchd
- optional Docker/GitHub Actions

## Phase 8 — Broad coverage
- sitemap
- generic HTML
- Playwright fallback
- ATS discovery
- starter company registry validation

## Phase 9 — Polish
- documentation
- security review
- performance
- export
- optional local intelligence

At the end of every phase:
- run tests
- update README
- provide exact commands to verify

---

# 32. EXPECTED CLAUDE OUTPUT

Claude must return a repository, not a conceptual answer.

At minimum, provide:
- every source file
- `pyproject.toml`
- working migrations
- sample config
- populated starter registry
- `.env.example`
- tests and fixtures
- local dashboard templates
- Discord implementation
- macOS scripts
- README
- screenshots or terminal-output examples if possible

If response size prevents returning the entire repository in one message:
1. create files in the available coding environment,
2. provide a downloadable archive, or
3. deliver in ordered implementation batches without omitting files.

Do not replace working implementation with “left as an exercise.”

---

# 33. OFFICIAL TECHNICAL REFERENCES

These were current when this brief was prepared. Claude should re-check them before implementation.

- Greenhouse Job Board API:  
  https://developers.greenhouse.io/job-board.html
- Lever Postings API documentation:  
  https://github.com/lever/postings-api
- Ashby public Job Postings API:  
  https://developers.ashbyhq.com/docs/public-job-posting-api
- Google `JobPosting` structured data:  
  https://developers.google.com/search/docs/appearance/structured-data/job-posting
- Discord webhooks:  
  https://docs.discord.com/developers/platform/webhooks
- Discord webhook resource:  
  https://docs.discord.com/developers/resources/webhook
- GitHub Actions workflow syntax and schedules:  
  https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax
- Playwright Python browser setup:  
  https://playwright.dev/python/docs/browsers
- Robots Exclusion Protocol, RFC 9309:  
  https://www.rfc-editor.org/rfc/rfc9309.html

---

# 34. FINAL PRODUCT PRINCIPLE

Opportunity Radar is not an auto-application bot and not a generic job scraper.

It is:

> **A high-recall, low-noise, local-first monitor that watches employer source-of-truth career systems, detects newly opened software-engineering opportunities across all recruiting seasons, ranks them for Patrick’s actual profile, and delivers fast, actionable alerts with direct application links.**

The product succeeds when Patrick learns about a relevant off-season or Summer 2027 opening early enough to apply before delayed community lists surface it.
