
# Sources

Marking: **[V]** = opened or searched this session (2026-10-20) and the figure read from the result; **[U]** = from memory, not checked this session. "fetch" = WebFetch of the page; "search" = confirmed only via a WebSearch result summary (secondary). Where a primary page could not be fetched (EPA pages failed TLS verification) the figure is marked search.

| Key | Used for | Figure | Status |
|---|---|---|---|
| GOOGLE | LOW water and CO2 per kWh; context | Google, "Measuring the environmental impact of AI inference", 21 Aug 2025: median Gemini text prompt 0.24 Wh, 0.26 mL, 0.03 gCO2e; PUE 1.09; active-chip-only 0.10 Wh ("optimistic at best"); not third-party verified. https://cloud.google.com/blog/products/infrastructure/measuring-the-environmental-impact-of-ai-inference | [V] fetch |
| EPOCH | LOW/HIGH per-token energy | Epoch AI, "How much energy does ChatGPT use?": ~0.3 Wh per GPT-4o query at 500 output tokens ("relatively pessimistic"), range 0.1 to 1-4 Wh; 10k input+500 out = 2.4-2.5 Wh; 100k input = ~40 Wh; 10% GPU utilisation, ~1500 W/GPU incl. overhead. https://epoch.ai/gradient-updates/how-much-energy-does-chatgpt-use | [V] fetch |
| JEGHAM | HIGH per-token energy, water and carbon factors | Jegham et al., "How Hungry is AI?", arXiv 2505.09598 (v6 HTML Table 4): Claude 3.7 Sonnet 0.950 Wh (100 in/300 out), 2.989 Wh (1k/1k), 5.671 Wh (10k/1.5k); AWS PUE 1.14, WUE 0.18 on-site + 5.11 off-site L/kWh, CIF 0.287 kgCO2e/kWh. Water/CO2 per query there were computed by the fetch tool from their equations, not copied. Energy is inferred from public API latency, not measured. https://arxiv.org/html/2505.09598v6 | [V] fetch |
| MISTRAL | Out-of-boundary comparator only | Mistral Large 2 lifecycle analysis (with ADEME/Carbone 4), July 2025: 400-token response = 1.14 gCO2e, 45 mL water, INCLUDES training and manufacturing amortisation, so it is NOT inside our operational boundary. At HIGH our water is lower than a full-LCA reading would give. | [V] search |
| IEA | Context only (no number enters compute.py) | IEA, "Energy and AI", Apr 2025: data centres ~415 TWh in 2024 (~1.5% of world electricity), ~945 TWh by 2030. https://iea.blob.core.windows.net/assets/de9dea13-b07d-42c5-a398-d1b3ae17d866/EnergyandAI.pdf | [V] search |
| ANTHROPIC-NONE | Claim "Anthropic does not publish per-token energy" | Search (Aug 2026 results) found no Anthropic per-token or per-query energy figure and no emissions report; Bloomberg (12 Aug 2026, via a secondary blog) reports it is starting company-wide footprint measurement. Absence of evidence from search, not proof. OpenAI: Altman cited ~0.34 Wh/query (Jun 2025) for ChatGPT only; nothing per token for GPT-6.x. | [V] search, secondary |
| EIA | "% Daily Value" joke | EIA FAQ 97: average US residential customer 10,791 kWh in 2022 = ~29.6 kWh/day. https://www.eia.gov/tools/faqs/faq.php?id=97&t=3 | [V] search |
| EPA-CAR | Car comparison | EPA: typical passenger vehicle ~400 g CO2/mile (22.2 mpg, 8,887 g CO2/gal), tailpipe only. https://www.epa.gov/greenvehicles/greenhouse-gas-emissions-typical-passenger-vehicle | [V] search (page fetch failed TLS) |
| EGRID | Sanity check on HIGH carbon (not used in a formula) | EPA eGRID2022 US average 823 lb CO2/MWh = ~0.37 kg/kWh; non-baseload 1,405 lb/MWh = ~0.64 kg/kWh. | [V] search |
| KETTLE | Kettle comparison | 1 kg water, 20 to 100 C: 4.18 x 80 = 334 kJ = 0.093 kWh; real kettles 0.10-0.12 kWh. | [V] search; physics also checkable by hand |
| GSEARCH | Google-search comparison | Google (Holzle), "Powering a Google search", Jan 2009: 0.0003 kWh (0.3 Wh) and 0.2 g CO2 per search. A 2024 arXiv paper (2407.16894) re-estimates ~0.00004 kWh (0.04 Wh). Both read from search summaries. | [V] search, secondary |
| LAUNDRY | Laundry comparison | Consumer/blog ranges: washer 0.2-0.5 kWh, electric dryer 2-4.5 kWh, combined ~2.5-5.5 kWh per load. Weak sources; ENERGY STAR finder lists annual figures only. | [V] search, weak |
| PHONE | Phone-charge comparison | Apple iPhone 16 battery 13.839 Wh (via search). Upper 20 Wh = ASSUMPTION (bigger phones up to ~18 Wh, plus charging loss). | [V] search + ASSUMPTION |
| SHOWER | Shower comparison | Average shower 17.2 gal, 8.2 min, 2.1 gpm (Home Water Works via retailer blog; EPA-attributed on a Home Depot blog). Not an EPA page. | [V] search, secondary |
| TOILET | Flush comparison | EPA WaterSense toilets 1.28 gpf; federal standard 1.6 gpf (1992). https://www.epa.gov/watersense/residential-toilets | [V] search |
| SAMSI, LUCCIONI | Not used | Samsi et al. 2023 (arXiv 2310.03003, LLaMA on V100/A100); Luccioni et al. 2023 "Power Hungry Processing". Abstract page of Samsi was fetched but gave no joules-per-token; no number from either enters compute.py. | [U] |

## Assumptions (no source; flagged ASSUMPTION in compute.py)
1. CENTRAL output energy 1.0 mWh/token: placed between EPOCH (0.6) and JEGHAM-Claude (3.2).
2. Fresh-input energy = 0.03 / 0.10 / 0.25 mWh per token. HIGH is anchored to EPOCH (0.21 mWh/input token at 10k context); LOW and CENTRAL are ratios (1/7, 1/10 of output) justified only by "prefill is batched and compute-bound", which EPOCH supports qualitatively.
3. Cache-read energy = 0.003 / 0.01 / 0.25 mWh per token. LOW/CENTRAL use 1/10 of fresh input, copying Anthropic's cache-read PRICE ratio (0.1x), a price not an energy measurement. HIGH uses NO discount (cache read = fresh input), the genuinely pessimistic case; EPOCH's 100k-context 40 Wh is upfront prefill, not cached attention, so it does not directly bound this. **Weakest assumption**: cache reads are ~96% of tokens and no published measurement we found covers them.
4. Codex/GPT-6.x models use the same per-token table as Claude (no data for either).
5. Water: ONE boundary in all columns, on-site cooling + off-site power-generation water. LOW = GOOGLE on-site 1.08 + off-site 1.0 L/kWh (the 1.0 off-site is an unsourced ASSUMPTION), HIGH = JEGHAM 0.18/1.14+5.11 = 5.27 (rounded 5.3), CENTRAL = geometric mean (~3.3). Carbon HIGH 0.50 kg/kWh = fossil-leaning mix, above EGRID average.
6. PUE is not applied again; the anchor studies already include datacentre overhead.
7. TV = 100 W (given in the task).
