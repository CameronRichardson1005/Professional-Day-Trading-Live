# V1 Top-2 Manipulation Forward Validation

## Hypothesis freeze

Freeze date: 2026-08-13

Historical research through 2026-08-13 identified a candidate
scanner modification:

- Strategy: Manipulation Opening 15M
- Production scanner: V1 Top-3
- Forward challenger: V1 Top-2
- Challenger includes scanner ranks 1 and 2 only.
- Rank 3 remains part of the production baseline.
- Quick Flip is not part of this hypothesis.

The challenger is research-only and must not alter production INVEST
routing during the forward-validation period.

## Why this hypothesis was selected

Across the historical 2026-03-02 through 2026-08-13 research sample:

- V1 Top-2 Manipulation expectancy per selection was positive in
  TRAIN, TEST, and FULL samples.
- V1 Top-2 was positive in all five chronological 23-session blocks.
- V1 Top-2 was positive in each monthly period evaluated.
- V1 rank 3 reduced historical expectancy materially.
- A 5-session block bootstrap showed:

  TRAIN:
  - Top-2 expectancy: 0.102%
  - Top-3 expectancy: 0.056%
  - Difference: +0.046%
  - P(difference > 0): 95.1%
  - 95% interval: -0.008% to +0.100%

  TEST:
  - Top-2 expectancy: 0.033%
  - Top-3 expectancy: -0.013%
  - Difference: +0.046%
  - P(difference > 0): 83.8%
  - 95% interval: -0.051% to +0.131%

  FULL:
  - Top-2 expectancy: 0.081%
  - Top-3 expectancy: 0.035%
  - Difference: +0.046%
  - P(difference > 0): 97.4%
  - 95% interval: -0.001% to +0.092%

These historical results are exploratory because the Top-2 hypothesis
was discovered using this dataset.

## Forward period

Forward observations must have a trading date strictly after
2026-08-13.

Historical observations through 2026-08-13 must never be counted as
forward evidence.

## Challenger

For each trading session:

1. Run the existing V1 scanner normally.
2. Preserve the production Top-3 selections.
3. Mark V1 ranks 1 and 2 as the research challenger.
4. Evaluate Manipulation using the existing strategy implementation.
5. Apply the same realized-outcome logic to challenger and baseline.
6. Do not alter execution assumptions between samples.

## Primary metric

Expectancy per scanner selection.

A selected stock that generates no filled Manipulation trade contributes
0% to selection expectancy, consistent with the historical research.

## Secondary metrics

- Number of scanner selections
- Manipulation INVEST signals
- Filled trades
- Expectancy per signal
- Expectancy per filled trade
- Target rate
- Stop rate
- Profit factor
- Win rate
- Daily equal-weight compounded return
- Maximum drawdown
- Sharpe ratio where sample size is meaningful

## Primary comparison

Forward V1 Top-2 expectancy per selection

minus

Forward V1 Top-3 expectancy per selection.

The difference must be reported even when negative.

## Data quality

Use genuine Webull historical/live market data.

Do not fabricate missing one-minute candles.

Data-quality flags must remain visible in the forward dataset.

Both all-data and strict-clean results should be reported when missing
market data could affect realized outcomes.

## No-tuning rule

During this forward-validation experiment, do not change:

- V1 ranking formula
- Top-2 definition
- Manipulation strategy rules
- ATR multiplier
- entry geometry
- target geometry
- trading stop geometry
- outcome sequencing assumptions
- primary comparison metric
- experiment start date

Any later modification creates a new hypothesis and requires a new
forward-validation start date.

## Quick Flip

No scanner hypothesis is currently approved for Quick Flip.

Historical V1, V2, V3, and V4 scanner uplift failed to remain reliably
positive for Quick Flip in the chronological holdout.

Quick Flip therefore remains outside this Top-2 forward experiment.

## Production rule

This experiment is shadow research only.

Production continues to use the existing scanner behavior unless a
future explicit production decision is made after reviewing genuinely
forward observations.
