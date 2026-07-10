# DRISHTi — MSME Loan Early-Warning System

*An entry for **IDBI Innovate 2026 · Track 4 (Default Prediction)**.*

**One line:** A tool that spots small-business loans heading for trouble **about a year in advance**, so a bank officer can step in while there's still time to save the account.

**🔴 Live demo:** **https://drishti-ews.vercel.app** — no login, no backend, loads in seconds.

---

## 1. The problem we're solving

IDBI Bank lends money to lakhs of small businesses (MSMEs). Some of them slowly slide into trouble and eventually **stop repaying** — which the bank must then write off, and set aside expensive "provisions" for. Today the bank can only see this coming about **3 months** ahead — far too late to actually help the business or protect the loan.

**DRISHTi gives the bank a ~12-month head start.** Think of it as a **fitness watch for business loans**: it notices the early warning signs (like a rising heart rate) long before the "heart attack" (a missed payment).

---

## 2. What we've built (three parts)

### Part 1 — Realistic practice data
The real bank data is only shared *after* a team is shortlisted, so we **generated our own realistic, made-up data**: **9,000 imaginary businesses**, tracked **month by month for 3 years**. Most stay healthy; about **1 in 11 slowly slides into default** (≈2.7%/year — matching IDBI's real small-business default rate). The failing ones deteriorate in a lifelike **order**:

> cash inflows & sales dip first (~12 months out) → they lean harder on their overdraft → payments start bouncing → and only at the very end do they actually **miss a loan payment**.

This is like a **flight simulator** — not real, but realistic enough to build and prove the system on. We deliberately sized everything to look like IDBI's real book (loan sizes ₹3L–₹5cr, mostly Micro/Small firms, ~3% of the book "flagged" at any time).

### Part 2 — The "brain" (the prediction model)
A program that **taught itself the early-warning patterns** from those thousands of examples. For any business it produces:
- a **risk score** (probability of default in the next 12 months) and a **traffic-light colour** — 🔴 act now / 🟠 watch / 🟢 healthy, and
- **plain-English reasons** for the flag ("GST sales down 21%", "credit-limit use at 94%", "62 days past due").

It's an industry-standard model (a "gradient-boosted tree" — LightGBM). We grade it **honestly** (see §4).

### Part 3 — The cockpit (the web app)
The screen a bank officer actually uses. Four tabs:

| Tab | What it shows |
|-----|---------------|
| **Watch-list** | The full book of businesses, ranked by risk, colour-coded, with each one's top warning signal, lead time, and a **predicted runway** ("≈N months before act-now", projected from the risk trend — median error ≈3 months, quoted honestly). Click any one to see its full story: a **risk-over-time chart**, the **"why it's sliding"** chart, the reasons, an **ecosystem chip** when trading partners are flagged, and an **auto-drafted alert memo**. |
| **Portfolio risk** | Where the risk is concentrated (which **sectors** and **segments** are stressed), a **"who to call first"** top-10 ranked by ₹ at risk, a **network-contagion lens** ("stress travels through trading networks" — accounts within one link of a red cluster, wired for CRILC/GST graphs in production), plus an interactive **"what early action is worth"** provisioning calculator. |
| **Model & Metrics** | The honest scorecard: how good the model is, how early it catches trouble, **why the Red/Amber thresholds sit where they do** (workload vs catch-rate), and the **rigour checks** a bank's risk team would demand. |
| **Real-data model** | The same method run on **real Indian MSMEs** (real defaults) → an honest ~0.81 score (with a bootstrap confidence interval), real anonymised companies and reason codes. Proof it works beyond synthetic data. |

---

## 3. The headline results (on our practice data)

- **Catches trouble early:** raises the first flag a **median of ~10 months** before a business goes bad; **93%** are flagged at least 6 months ahead.
- **Practical for officers:** by reviewing just the **riskiest 10%** of accounts each month, they catch **~87%** of all future defaults.
- **The money story:** acting early on flagged accounts could save on the order of **₹40–50 cr/year in provisioning** across IDBI's MSME book (illustrative, shown as an interactive what-if).
- **Proven on real data:** the same method, run on **~3,200 real Indian MSMEs** (real credit-rating defaults), scores an honest **0.81** — see §4.

---

## 4. Being honest about the numbers (important)

Our model scores very high (technical score ~0.95) **because the data is synthetic — we designed the very signals it reads.** That is **not** proof it beats a real-world model, and we never claim it is. Real bank default models typically score ~0.75–0.85; a real-data version of ours would likely land there too.

So we deliberately **lead with the things that are hard to fake**, not the headline score:
- **Lead-time** — *how early* we catch trouble (our sharpest, most defensible edge).
- **A leakage check** that proves the year-ahead warnings come from **cash-flow signals, not** the obvious "already late on payments" signal. (At 10–12 months out, cash-flow + overdraft-use drive **~81%** of the decision and missed-payments just **1.8%**.)
- **Calibration** — when it says "40% risk", the real default rate in that band *is* ~40%.
- **Out-of-time & leakage-safe testing** — tested on businesses (and time periods) it never trained on.
- **Robustness** — even a simple transparent scorecard reaches the same score, proving the signal is real and not a black-box trick.

**And we proved the method on real data.** We ran the *same modelling approach* on **~3,200 real Indian MSMEs** (17,000 company-years of real annual financials, FY2018–FY2026) with **1,284 real defaults** (an actual credit-rating downgrade to 'D'). On real data it scores an honest **AUC 0.81 (95% bootstrap CI 0.78–0.84)** — right in the realistic band — and here the model clearly **beats a logistic scorecard (0.81 vs 0.70)**, earning its keep. This is the **"Real-data model"** tab in the app, with real (anonymised) companies and real reason codes ("interest cover below 1", "negative net worth"). Almost no other team will have *any* real number.

We also say clearly, in the app itself, that the cockpit runs on synthetic data with the real bank data to come after shortlisting.

---

## 5. How it's built (tech, briefly)

- **Data + model:** Python (pandas, LightGBM, scikit-learn). Everything is pre-computed offline and baked into a single data file, so the live demo has **no backend to crash**.
- **App:** React + Vite + Tailwind + Recharts. Loads the data file at runtime (small, fast, deployable).

### Run it locally
```bash
# 1) build the data + model (from the msme-ews/ folder)
python3 src/generate_data.py     # make the practice data
python3 src/rigor.py             # run the model-rigour checks
python3 src/export_demo.py       # train model + export everything the app needs
python3 src/real_model.py        # REAL-data validation model (needs ../msme_data/*.csv)
cp data/demo_data.json  app/public/demo_data.json
cp data/real_model.json app/public/real_model.json

# 2) run the app
cd app
npm install
npm run dev                      # open http://localhost:5183
```

### Project layout
```
msme-ews/
├── src/
│   ├── generate_data.py   # creates the synthetic month-by-month business data
│   ├── baseline_model.py  # quick model sanity-check
│   ├── rigor.py           # calibration, leakage check, out-of-time, baseline
│   └── export_demo.py     # trains the model + writes demo_data.json for the app
├── data/                  # generated data (panel CSV, demo_data.json)
└── app/                   # the React cockpit
    ├── public/demo_data.json   # the data the app reads at runtime
    └── src/components/         # Watch-list, Account detail, Portfolio risk, Analytics
```

---

## 6. Where it stands (status)

**✅ Done & verified**
- Realistic synthetic dataset, calibrated to IDBI's real portfolio (default rate, sizes, sectors).
- Trained early-warning model with honest, banker-friendly metrics.
- Full model-rigour pack (calibration, leakage proof, out-of-time, baseline).
- **Real-data validation model on ~3,200 real Indian MSMEs (AUC 0.81)** — with its own app tab.
- Polished **4-tab** web app (Watch-list, Portfolio risk, Model & Metrics, Real-data model), tested across account types.
- Sector-concentration view + interactive ₹-provisioning what-if.

**✅ Also done**
- **Deployed live** at https://drishti-ews.vercel.app (static, no backend to crash).
- Public **GitHub repo** (this one).
- "Who to call first" ₹-at-risk ranking, Red/Amber **threshold justification** exhibit, bootstrap **confidence interval** on the real-data AUC, mobile layout, graceful error/retry state.

**📌 Open points / known limitations**
- The **cockpit** runs on **synthetic data** (by design at this stage) — real *bank* data comes only after shortlisting. (The **real-data validation** tab uses a real Indian MSME financial-statement + credit-rating dataset.)
- Real-data model caveats: rated-MSME universe (selection bias); annual financials (complements, not replaces, the monthly cockpit); default = a 'D' credit-rating event.

---

## 7. Next steps (post-shortlisting)

1. **Plug into the IDBI sandbox** — swap the synthetic panel for real internal loan-conduct data; the pipeline is already shaped for monthly account-level features.
2. **Blend the two models** — combine the real financial-statement risk score with the behavioural score into one unified number per account.
3. **Richer signals** — bureau enquiries, GST filings, transaction-graph "contagion" between linked borrowers.
4. **Production hardening** — model registry, monthly re-train + calibration monitoring, audit trail for every flag (RBI AI-governance friendly).

---

## 8. How this tailors to IDBI (context)

The demo is sized to IDBI's real figures (from public disclosures — to be re-verified before the pitch): MSME/priority book ~₹25–35k cr, gross bad-loan ratio ~2–3%, a "watch-list" (SMA) book ~₹3,000 cr, provision coverage ~99%. IDBI already runs an early-warning system called **SAJAG** — DRISHTi is designed to **complement** it by scoring accounts *before* they slip, not replace it.

> **Note:** This is a hackathon prototype on synthetic data. It is decision-support for a human credit officer — the model advises, the officer decides.
