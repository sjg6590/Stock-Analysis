# Financial Glossary

Reference guide for common financial terms used in stock analysis and investing.

---

## P/L
**Profit and Loss** — the gain or loss on an investment. *Unrealized P/L* (also called open P/L) is the gain or loss on a position you still hold, calculated as (current market value − cost basis). *Realized P/L* is locked in when you sell. In this app, P/L % = (market_value − cost_basis) / cost_basis × 100.

## P/E Ratio
**Price-to-Earnings Ratio** — the stock's current price divided by its earnings per share (EPS) over the trailing twelve months (TTM). A higher P/E means investors are paying more per dollar of earnings, often implying growth expectations. Compare to sector median P/E to judge relative valuation. Also called the "multiple."

## Forward P/E
**Forward Price-to-Earnings** — same as P/E but uses *next twelve months* estimated EPS instead of trailing earnings. Useful for fast-growing companies where backward-looking P/E overstates value.

## PEG Ratio
**Price/Earnings-to-Growth** — P/E ratio divided by the earnings growth rate (%). A PEG below 1.0 is often considered undervalued relative to growth; above 2.0 may indicate overvaluation. More useful than raw P/E for growth stocks.

## P/B Ratio
**Price-to-Book Ratio** — stock price divided by book value per share (assets minus liabilities). A P/B below 1.0 means the market values the company below its accounting net worth. Common valuation metric for banks and asset-heavy businesses.

## P/S Ratio
**Price-to-Sales Ratio** — market cap divided by annual revenue. Useful for companies with no earnings yet. A lower P/S is generally cheaper; compare within the same sector.

## EV/EBITDA
**Enterprise Value to EBITDA** — EV (market cap + debt − cash) divided by EBITDA (Earnings Before Interest, Taxes, Depreciation, and Amortization). A capital-structure-neutral valuation multiple. Lower = potentially cheaper. Useful for comparing companies with different debt levels.

## EPS
**Earnings Per Share** — net income divided by shares outstanding. The core profitability metric per share. Earnings *beats* (actual > estimate) tend to push prices up; *misses* tend to push prices down.

## ROE
**Return on Equity** — net income divided by shareholders' equity, expressed as a %. Measures how efficiently a company uses shareholder capital to generate profit. Higher is better; compare within the same industry.

## ROA
**Return on Assets** — net income divided by total assets. Measures how efficiently a company uses all its assets. Less capital-intensive businesses (software) have higher ROA than capital-intensive ones (manufacturing).

## Profit Margin
**Net Profit Margin** — net income divided by revenue, expressed as a %. Shows how many cents of profit a company keeps per dollar of sales. Higher and expanding margins are positive signals.

## Operating Margin
**Operating Profit Margin** — operating income (revenue minus COGS and operating expenses, before interest and taxes) divided by revenue. A cleaner measure of core business profitability than net margin.

## EBITDA
**Earnings Before Interest, Taxes, Depreciation, and Amortization** — a proxy for operating cash flow. Strips out financing and accounting decisions to focus on core earnings power.

## Debt/Equity
**Debt-to-Equity Ratio** — total debt divided by shareholders' equity. High D/E means the company is more leveraged and financially riskier. In this app, stocks above MAX_DEBT_TO_EQUITY are pre-filtered out.

## Current Ratio
**Current Ratio** — current assets divided by current liabilities. Measures short-term liquidity. A ratio above 1.0 means the company can cover near-term obligations. Below 1.0 may signal liquidity stress.

## Quick Ratio
**Quick Ratio** (Acid Test) — (current assets − inventory) divided by current liabilities. A stricter liquidity measure than the current ratio because it excludes inventory, which may be slow to convert to cash.

## Market Cap
**Market Capitalization** — total shares outstanding multiplied by current stock price. Classifies companies as micro-cap (<$300M), small-cap ($300M–$2B), mid-cap ($2B–$10B), large-cap ($10B–$200B), or mega-cap (>$200B).

## Enterprise Value (EV)
**Enterprise Value** — market cap + total debt − cash and equivalents. Represents the theoretical takeover price. More complete than market cap for comparing companies with different capital structures.

## Beta
**Beta** — a measure of a stock's volatility relative to the market (S&P 500). Beta of 1.0 moves with the market. Above 1.0 = more volatile; below 1.0 = less volatile. Negative beta = tends to move opposite the market (e.g., gold miners).

## Alpha
**Alpha** — excess return above a benchmark (usually the S&P 500) after adjusting for risk (beta). Positive alpha means the investment outperformed its risk-adjusted expected return.

## Dividend Yield
**Dividend Yield** — annual dividend per share divided by current stock price, expressed as a %. Income investors seek higher yields. A very high yield (>8%) may signal the dividend is unsustainable (dividend trap).

## Payout Ratio
**Payout Ratio** — dividends paid divided by earnings, expressed as %. A ratio above 100% means the company is paying more in dividends than it earns, which is often unsustainable.

## 52-Week High / Low
The highest and lowest price the stock has traded over the past 52 weeks. A stock near its 52-week high may have momentum; near its 52-week low may be in distress or a contrarian opportunity.

## Analyst Target Price
The average price target from Wall Street analysts covering the stock. Implied upside = (target − current price) / current price × 100. In this app, stocks with high implied upside and strong fundamentals rank higher.

## Analyst Recommendation
Consensus recommendation from covering analysts, typically on a scale: Strong Buy → Buy → Hold → Underperform → Sell. A strong buy consensus with high implied upside is a positive signal.

## Revenue Growth (YoY)
Year-over-year change in revenue. Positive and accelerating revenue growth indicates expanding business. Negative growth (revenue decline) is a risk flag.

## Earnings Growth (YoY)
Year-over-year change in EPS or net income. Strong earnings growth combined with reasonable valuation (low PEG) is the basis for many growth investing strategies.

## Fair Value
An estimate of what a stock is intrinsically worth, independent of its current market price. Calculated via methods like DCF, comparable company analysis, or analyst models. If market price < fair value, the stock may be undervalued.

## DCF
**Discounted Cash Flow** — a valuation method that estimates fair value by projecting future free cash flows and discounting them back to today using a required rate of return (discount rate). Sensitive to growth and discount rate assumptions.

## Intrinsic Value
The "true" underlying worth of a stock based on fundamentals, independent of market sentiment. Value investors (Warren Buffett style) buy when market price is significantly below intrinsic value (margin of safety).

## Cost Basis
The original purchase price of an investment, used to calculate P/L. For a position built over multiple purchases, it's the average purchase price times total shares.

## Unrealized P/L
Gain or loss on a position you still hold, not yet locked in. Calculated as (current value − cost basis). Also called open P/L or paper gain/paper loss.

## Realized P/L
Gain or loss that has been locked in by selling a position. Subject to capital gains tax in most jurisdictions.

## Portfolio Weight
The percentage of your total portfolio value represented by a single position. Weight % = position market value / total portfolio value × 100. High concentration in one stock or sector increases risk.

## Diversification
Spreading investments across multiple stocks, sectors, and asset classes to reduce the risk that any single holding causes large losses. The goal is uncorrelated assets that don't all fall together.

## Short Interest
The percentage of a stock's float that has been sold short (bet against). High short interest (>20%) can indicate bearish sentiment, but also creates potential for a short squeeze if the stock rises.

## Float
The number of shares available for public trading (total shares minus insider-held and restricted shares). Low-float stocks are more volatile because small trades move the price more.

## Volume
Number of shares traded in a given period. Above-average volume on a price move adds conviction. Volume spikes on big news are common. Compare to the stock's average daily volume (ADV).

## RSI
**Relative Strength Index** — a momentum oscillator (0–100) measuring the speed and magnitude of recent price changes. Above 70 = typically overbought (may pull back); below 30 = typically oversold (may bounce). A technical indicator, not a fundamental one.

## MACD
**Moving Average Convergence Divergence** — a trend-following momentum indicator showing the relationship between two moving averages (typically 12-day and 26-day EMAs). A MACD crossover above the signal line is bullish; below is bearish.

## Moving Average
The average closing price over a defined period (e.g., 50-day MA, 200-day MA). A stock above its 200-day MA is in a long-term uptrend. The 50-day crossing above the 200-day is called a "Golden Cross" (bullish signal).

## Earnings Calendar
The scheduled date when a company releases its quarterly earnings report. Stocks often experience significant volatility around earnings. In this app, stocks with earnings in the next 5 days are excluded from screening to avoid binary event risk.

## Earnings Beat / Miss
**Beat**: actual reported EPS or revenue exceeds analyst consensus estimate. Usually bullish.
**Miss**: actual results come in below consensus. Usually bearish.
**Guidance**: management's forward outlook for the next quarter or year, often more impactful than the actual results.

## BUY_CANDIDATE
In this app, a stock screened by the AI and assigned a score ≥ 70, meeting all pre-filter criteria (PE, market cap, debt, sector, analysts), with positive valuation and sentiment signals. Suggests the stock may be worth buying at or below the suggested_buy_price.

## WATCH
In this app, a stock that passed pre-filtering and shows some positive attributes but has mixed or uncertain signals. Not a clear buy, but worth monitoring. Score typically 40–69.

## AVOID
In this app, a stock with concerning fundamentals, poor sentiment, or overvaluation. Score typically below 40. Consider reducing or exiting positions.

## Score
In this app, the AI-generated composite score (0–100) for a screened stock. Factors include valuation, growth, profitability, analyst consensus, and news sentiment. Higher = more attractive based on the screener's criteria.

## Suggested Buy Price
In this app, the price at or below which the AI believes the stock offers acceptable risk/reward, based on analyst targets, valuation metrics, and the configured minimum upside threshold.

## Estimated Upside
In this app, the percentage gain implied if the stock reaches the analyst consensus target price from its current price. Calculated as (analyst_target − current_price) / current_price × 100.

## Short Squeeze
When a heavily shorted stock rises sharply, forcing short sellers to buy shares to cover their positions, which drives the price even higher. Can cause violent, rapid price spikes disconnected from fundamentals.

## Options
Financial derivatives giving the holder the right (but not obligation) to buy (call) or sell (put) shares at a specified price (strike) before a certain date (expiration). In this app, options data includes implied volatility and put/call ratio.

## Implied Volatility (IV)
Market-derived expectation of future price volatility, extracted from options prices. High IV means options are expensive; the market expects large moves. IV spikes around earnings or macro events.

## Put/Call Ratio
The volume of put options divided by call options. A high ratio (>1.0) suggests bearish sentiment. A low ratio suggests bullish sentiment. Contrarian investors sometimes use extreme readings as signals.

## Market Cap Weighted
A portfolio or index where larger companies have more influence. The S&P 500 is market-cap weighted, so mega-caps (Apple, Microsoft, NVIDIA) drive most of its movement.

## Sector
A broad classification of companies by their primary business activity. Common sectors: Technology, Healthcare, Consumer Discretionary, Consumer Staples, Financials, Energy, Industrials, Materials, Real Estate, Utilities, Communication Services.

## Index
A basket of stocks used as a benchmark. Common indices: S&P 500 (SPX) — 500 large US companies; Nasdaq 100 (COMPX) — 100 largest Nasdaq-listed non-financial companies; Dow Jones (DJI) — 30 large US companies.

## Bull Market / Bear Market
**Bull market**: a sustained rise in stock prices, typically defined as a 20%+ gain from a recent low. **Bear market**: a sustained decline, typically 20%+ from a recent high. Corrections (10%+ decline) are shorter and more common.
