## Hydrological Calendar Standard (Iran)

### Water Year Definition

For all hydrological, climatological, groundwater, and water-resources analyses related to Iran, the **Persian Water Year** shall be used as the default temporal aggregation unit.

#### Water Year Boundaries

A water year begins on **1 Mehr** and ends on **31 Shahrivar** of the following Persian calendar year.

Examples:

| Water Year | Start Date  | End Date          |
| ---------- | ----------- | ----------------- |
| WY 1400    | 1 Mehr 1400 | 31 Shahrivar 1401 |
| WY 1401    | 1 Mehr 1401 | 31 Shahrivar 1402 |
| WY 1402    | 1 Mehr 1402 | 31 Shahrivar 1403 |

The water year is named according to the Persian calendar year in which it starts.

#### Mandatory Usage

Unless explicitly instructed otherwise, all analyses shall aggregate and report data using the Persian Water Year, including but not limited to:

* Precipitation
* Temperature
* Evapotranspiration (ET, AET, PET)
* Groundwater levels
* Groundwater storage anomalies
* Streamflow and runoff
* Drought indices
* Water balance calculations
* Reservoir storage
* Irrigation and agricultural water demand
* Recharge estimation
* Remote sensing time-series analyses

#### Seasonal Definition

Hydrological seasons shall follow the Persian calendar:

* Autumn: Mehr–Aban–Azar
* Winter: Dey–Bahman–Esfand
* Spring: Farvardin–Ordibehesht–Khordad
* Summer: Tir–Mordad–Shahrivar

#### Date Conversion Rule

When source datasets are provided in Gregorian dates, they must be converted or grouped according to the Persian Water Year before calculating annual statistics, trends, anomalies, correlations, or water-balance components.

#### Agent Behavior

When processing Iranian hydrological datasets:

1. Assume the Persian Water Year (Mehr–Shahrivar) by default.
2. Never aggregate annual hydrological variables using the Gregorian calendar year unless explicitly requested.
3. Label outputs using the corresponding Water Year (WY).
4. Preserve consistency of the water-year definition across all datasets used in the same analysis.
5. If the dataset spans multiple years, automatically assign each record to its corresponding Persian Water Year before performing annual analyses.

This standard overrides Gregorian-year aggregation for all Iranian hydrological and groundwater studies unless the user explicitly specifies another convention.
