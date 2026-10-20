# Deliverable 9 — competitive price response v1 (SYNTHETIC)

Built 2026-09-23. `python -m src.models.price_response` → `outputs/models/price_response/`.

## What this is allowed to claim

Every multi-date price is SYNTHETIC. Recovering the Blinkit-leader / follower structure shows the pipeline recovers
the generator's planted response (`docs/GENERATOR_v15_PARAMETERS.md` C). It is not evidence of who leads real
pricing, and it is **not an elasticity**: no demand exists.

What **does** transfer is a method finding. Shelf prices snapped to coarse grids hide about half of a price response
from a naive regression, and indirect inference with the observed grid undoes it. Real Blinkit prices are on such
grids (75% end in 0/5/9).

## Steps and results (2,000-product common panel)

**1. Naive OLS** on product-mean log deviations reproduces the documented "expected measured" coefficients exactly:
Instamart 0.220, Flipkart 0.154, BigBasket 0.181 (planted 0.45 / 0.30 / 0.35).

**2. Lags are discovered, not assumed.** With leader lags 0–3 entered together, the largest coefficient is at lag 1
for Instamart (0.195) and Flipkart (0.129) and at lag 2 for BigBasket (0.154). That matches the planted lags.

**3. Negative control: Blinkit follows no one.** Regressing Blinkit on the followers' lags 1–2 gives coefficients of
−0.008 to 0.029.

**4. Unrestricted VAR(2)** over the four platforms gives naive impulse responses (saved; attenuated like step 1).

**5. Indirect inference.** Each listing's price grid (step and remainder) is inferred from its own prices: Rs 1 1,903
panels; Rs 10 ending 0/5/9 4,215; Rs 50 ending 0/49 1,369; Rs 100 ending 99 513. The latent AR structure is
simulated, rounded to those grids, and measured with step 1's regression. Parameters are chosen so the simulated
measurements equal the real ones. The simulation uses common random numbers, fits the leader first and then each
follower, and gets its intervals from a 20-replication parametric bootstrap.

| Follower (lag) | Planted β | Naive β̂ | **Corrected β̂** | 95% CI |
|---|---|---|---|---|
| Swiggy Instamart (1) | 0.45 | 0.220 | **0.451** | 0.428–0.484 |
| Flipkart Minutes (1) | 0.30 | 0.154 | **0.296** | 0.268–0.324 |
| BigBasket (2) | 0.35 | 0.181 | **0.357** | 0.327–0.383 |

The leader's persistence and shock size are also recovered: ρ 0.624 (0.599–0.640, planted 0.6), σ 0.0298 (planted
0.03).

**The fix that made it work: latent level, not observed mean.** The first attempt recovered only ~68% of β. Simulating
at the planted values then gave too little price variance on coarse grids (x sd 0.034 vs 0.044 in the data), while the
Rs 1 grid matched exactly. That located the error. A listing that shows 99 most of the time and 199 sometimes must sit
near the 149 boundary, but its observed mean (~110) puts the simulated latent price far from it. Each panel's latent
level is now estimated by interval likelihood (each observed price = the interval of latent prices that round to it).
After that fix, simulating at the planted values reproduces the naive measurements to within simulation noise: the
saved check (`observation_operator_check` in metrics.json, one seed) gives 0.209 / 0.149 / 0.171 against 0.220 /
0.154 / 0.181 in the data, and another seed gave 0.218 / 0.157 / 0.185. The correction then recovers the planted
values.

**6. Impulse responses** to a 1% Blinkit move: planted, corrected and naive peaks are 0.45 / 0.451 / 0.22 (Instamart),
0.30 / 0.296 / 0.154 (Flipkart) and 0.35 / 0.357 / 0.181 (BigBasket).

## Honest caveat

One-step forecasts of the *observed* rounded price are slightly better with the naive coefficients (test MAE on log
deviation 0.0226 vs 0.0238). Naive OLS is the best linear predictor of rounded prices. The correction targets the
latent response parameter, which is what SIMULATE and OPTIMIZE need, not the forecast error of rounded prices.

Figure: `outputs/models/price_response/figures/price_response.png`.
