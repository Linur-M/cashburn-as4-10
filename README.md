# cb-report-as4 (v55)

CFO Financial System — strict monthly cash burn reports (Nextage).

## v55 — data-completeness hardening + TIER1 precision (additive)
Two additive changes, columns A-R unchanged.

**(A) Data-completeness hardening**
- `COMPANY_FILE_PATTERNS` file-pattern registry replaces hardcoded filename lists; `load_all()` discovers files by glob (unmatched files -> WARN, files matching >1 key -> AMBIGUOUS_FILE WARN).
- `COMPANY_REQUIRED_ACCOUNTS` marks accounts that must have data every month.
- Pre-flight Step -1 now presents a Month x Account coverage matrix + opening-balance check.
- New HSBC Commercial One Card PDF parser (`parse_hsbc_cc`).
- Post-load assertion U-11 (`assert_coverage`) writes `validation.json -> coverage_matrix` and raises RuntimeError (BLOCK) when a required account is missing a month; WARN on optional.

**(B) Classification precision — Addition W**
- TIER1a exact whole-field match always checked first; TIER1b substring scoped to Desc2 for bank/wire tabs and Description+Vendor_Raw for card tabs — never the generic wire Description.
- Fixes false-positive vendor hijack (e.g. "TRANSFER" outranking "Nextage" by raw length).
- Adds `validation.json -> keyword_risk_audit` (GENERIC_KEYWORD_RISK warn).

## v54 — embedded deposit-interest split (Addition T-3)
A `deposit_ledger` splits a bundled Leumi-ILS `פרעון פקדון` redemption into principal (Internal) + embedded interest (Interest Income), mirroring the USD account's two rows; unmatched non-round redemptions raise a pre-flight WARN to confirm the principal, then split automatically.
