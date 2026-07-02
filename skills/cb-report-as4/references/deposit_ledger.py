"""
deposit_ledger.py — Addition T-3 (v54, additive).

Problem this solves
--------------------
The Leumi USD (dollar) account splits a matured time-deposit into TWO rows:
    פרעון פקדון   (principal returned)   +   ריבית מט"ח   (FX interest)
The Leumi ILS (shekel) account bundles BOTH into ONE row:
    פרעון פקדון   = principal + interest   (e.g. ₪1,605,326.9)

Before v54 the skill read exactly what the bank gave and classified the whole
bundled ₪1,605,326.9 line as `Internal` — so the embedded interest silently
vanished from OPERATIONAL CASH IN (understating income / yield).

There was no matching between the original placement (principal) and the later
redemption, so the engine could not know that ₪1,600,000 was the principal and
₪5,326.9 was interest.

What this module adds
---------------------
1. A `DepositLedger` that, DURING parsing, records every deposit PLACEMENT as
   `ref -> principal` (and keeps a currency + account for matching).
2. On a REDEMPTION (`פרעון פקדון` / deposit maturity), it finds the matching
   placement and, when the redeemed amount exceeds the known principal, SPLITS
   the single line into:
       principal  -> Internal / Deposit Redemption   (nets out, per Addition D)
       interest   -> Interest Income / Deposit Interest   (operational, per v46/v48)
3. When no placement can be matched, it applies a heuristic: a redemption whose
   amount is NOT a round multiple of 1,000 (has אגורות / cents) probably carries
   embedded interest, so it emits a WARN for the Step -1 pre-flight and asks the
   controller to confirm the original principal. Once confirmed, the split is
   applied automatically.

Design notes
------------
* Additive & backward-compatible: emits the SAME columns A-R. The split simply
  turns one Internal row into (a) an Internal row + (b) an Interest Income row.
  If the bank already split the legs (USD account), matching finds an exact
  principal so `interest == 0` and NO extra row is produced (no double count).
* Currency-agnostic: works on native amounts (ILS or USD). FX conversion is
  applied downstream exactly as for any other row, at the transaction date.
* Deterministic: matching prefers exact-principal, then same account+currency
  with the smallest non-negative (redeemed - principal) gap within tolerance.
"""

from __future__ import annotations

# Description tokens (Leumi + generic). Matched case-insensitively, substring.
PLACEMENT_TOKENS = (
    'הפקדת פק"מ', 'הפקדת פקמ', 'פקדון', 'פקדון במט"ח', 'פיקדון',
    'משוטף לפקדון', 'העברה לפקדון', 'deposit placement', 'time deposit',
)
REDEMPTION_TOKENS = (
    'פרעון פקדון', 'פרעון פיקדון', 'פירעון פקדון', 'פדיון פקדון',
    'deposit redemption', 'deposit maturity',
)
# Interest tokens — used only to recognise an ALREADY-split interest leg so we
# do not double-count it (the USD account emits ריבית מט"ח as its own row).
INTEREST_TOKENS = (
    'ריבית מט"ח', 'ריבית מטח', 'ריבית פקדון', 'ריבית זכות', 'ריבית',
    'deposit interest', 'interest paid',
)

# A redemption is treated as "round" (no embedded interest expected) when the
# native amount is a whole multiple of this unit.
ROUND_UNIT = 1000.0
# Absolute tolerance when comparing an amount to a known principal (rounding).
MATCH_TOL = 0.05


def _norm(s) -> str:
    return (str(s) if s is not None else "").strip().lower()


def _has(desc: str, tokens) -> bool:
    d = _norm(desc)
    return any(_norm(t) in d for t in tokens)


def is_placement(desc: str) -> bool:
    return _has(desc, PLACEMENT_TOKENS) and not _has(desc, REDEMPTION_TOKENS)


def is_redemption(desc: str) -> bool:
    return _has(desc, REDEMPTION_TOKENS)


def is_round(amount_native: float, unit: float = ROUND_UNIT) -> bool:
    a = abs(float(amount_native))
    return abs(a - round(a / unit) * unit) <= MATCH_TOL


class DepositLedger:
    """Tracks placements so redemptions can be split into principal + interest.

    Usage during parsing (per transaction, in date order):
        led = DepositLedger()
        ...
        if is_placement(desc):
            led.record_placement(ref, abs(amt_native), acct, ccy)
        if is_redemption(desc):
            legs, warn = led.split_redemption(ref, abs(amt_native), acct, ccy, desc)
            # `legs` is a list of (amount, category, sub_category) to emit;
            # `warn` is None or a pre-flight WARN string to surface.
    """

    def __init__(self):
        # list of dicts so we can match by ref OR by (acct,ccy,principal)
        self._placements = []            # {ref, principal, acct, ccy, used}
        self.confirmed_principals = {}    # ref -> principal (from pre-flight answer)
        self.warnings = []                # collected WARN strings for pre-flight

    # ---- placement side -------------------------------------------------
    def record_placement(self, ref, principal, acct=None, ccy=None):
        self._placements.append({
            "ref": (str(ref) if ref is not None else None),
            "principal": abs(float(principal)),
            "acct": acct, "ccy": ccy, "used": False,
        })

    # ---- pre-flight confirmation ---------------------------------------
    def confirm_principal(self, ref, principal):
        """Record a controller-supplied principal (answer to the pre-flight Q)."""
        self.confirmed_principals[str(ref)] = abs(float(principal))

    # ---- matching -------------------------------------------------------
    def find_matching_deposit(self, ref, redeemed, acct=None, ccy=None):
        """Return the best-guess principal for a redemption, or None.

        Precedence:
          1. controller-confirmed principal for this ref (pre-flight answer)
          2. unused placement with the SAME ref
          3. unused placement, same acct+ccy, with the smallest non-negative
             (redeemed - principal) gap (interest is >= 0 and small)
        """
        r = str(ref) if ref is not None else None
        if r in self.confirmed_principals:
            return self.confirmed_principals[r]
        # exact ref
        for p in self._placements:
            if not p["used"] and p["ref"] is not None and p["ref"] == r:
                p["used"] = True
                return p["principal"]
        # same account/currency, principal <= redeemed, smallest gap
        best, best_gap = None, None
        for p in self._placements:
            if p["used"]:
                continue
            if acct is not None and p["acct"] is not None and p["acct"] != acct:
                continue
            if ccy is not None and p["ccy"] is not None and p["ccy"] != ccy:
                continue
            gap = abs(float(redeemed)) - p["principal"]
            if gap >= -MATCH_TOL and (best_gap is None or gap < best_gap):
                best, best_gap = p, gap
        if best is not None:
            best["used"] = True
            return best["principal"]
        return None

    # ---- the split ------------------------------------------------------
    def split_redemption(self, ref, redeemed, acct=None, ccy=None, desc=""):
        """Split one bundled redemption into principal + interest legs.

        Returns (legs, warn):
          legs = [(amount_native, category, sub_category), ...]
          warn = None | str  (a pre-flight WARN to surface for confirmation)
        """
        redeemed = abs(float(redeemed))
        principal = self.find_matching_deposit(ref, redeemed, acct, ccy)

        if principal is not None:
            interest = round(redeemed - principal, 2)
            if interest > MATCH_TOL:
                # bundled line (ILS account): emit principal + interest
                return ([
                    (round(principal, 2), "Internal", "Deposit Redemption"),
                    (interest, "Interest Income", "Deposit Interest"),
                ], None)
            # exact match — already split by the bank (USD account) or no yield
            return ([(redeemed, "Internal", "Deposit Redemption")], None)

        # No principal known. Heuristic on roundness.
        if not is_round(redeemed):
            warn = (
                f'פרעון פקדון בסכום לא עגול ({redeemed:,.2f} {ccy or ""}) '
                f'— ייתכן ריבית מוטמעת. נא לאשר את קרן ההפקדה המקורית '
                f'(ref={ref}, חשבון={acct}).'
            )
            self.warnings.append(warn)
            # keep as Internal for now; the split is applied after confirmation
            return ([(redeemed, "Internal", "Deposit Redemption")], warn)

        # round amount, no match -> treat as pure principal return
        return ([(redeemed, "Internal", "Deposit Redemption")], None)


__all__ = [
    "DepositLedger", "is_placement", "is_redemption", "is_round",
    "PLACEMENT_TOKENS", "REDEMPTION_TOKENS", "INTEREST_TOKENS",
]
