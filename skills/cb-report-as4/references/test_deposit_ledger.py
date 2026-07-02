"""test_deposit_ledger.py — Addition T-3 (v54) unit tests."""
import os, sys
sys.path.insert(0, os.path.dirname(__file__))
from deposit_ledger import DepositLedger, is_placement, is_redemption, is_round


def test_bundled_ils_split():
    """ILS account: one פרעון פקדון line = principal + interest -> split."""
    led = DepositLedger()
    led.record_placement("D1", 1_600_000, acct="Leumi-ILS", ccy="ILS")
    legs, warn = led.split_redemption("D1", 1_605_326.90, acct="Leumi-ILS", ccy="ILS")
    assert warn is None
    assert len(legs) == 2, legs
    (p_amt, p_cat, p_sub), (i_amt, i_cat, i_sub) = legs
    assert p_cat == "Internal" and p_sub == "Deposit Redemption"
    assert abs(p_amt - 1_600_000) < 0.01
    assert i_cat == "Interest Income" and i_sub == "Deposit Interest"
    assert abs(i_amt - 5_326.90) < 0.01, i_amt


def test_usd_already_split_no_double_count():
    """USD account: principal leg exact-matches placement -> no extra interest row."""
    led = DepositLedger()
    led.record_placement("D2", 850_000, acct="Leumi-USD", ccy="USD")
    legs, warn = led.split_redemption("D2", 850_000, acct="Leumi-USD", ccy="USD")
    assert warn is None
    assert len(legs) == 1 and legs[0][1] == "Internal", legs


def test_no_match_nonround_warns():
    """No placement + non-round amount -> WARN asking to confirm principal."""
    led = DepositLedger()
    legs, warn = led.split_redemption("X9", 1_605_326.90, acct="Leumi-ILS", ccy="ILS")
    assert warn is not None and "קרן" in warn
    assert len(legs) == 1 and legs[0][1] == "Internal"
    assert led.warnings, "warning should be collected for pre-flight"


def test_no_match_round_no_warn():
    """No placement + round amount -> pure principal, no WARN."""
    led = DepositLedger()
    legs, warn = led.split_redemption("X8", 1_600_000, acct="Leumi-ILS", ccy="ILS")
    assert warn is None and len(legs) == 1


def test_preflight_confirmation_then_split():
    """After controller confirms principal, redemption splits automatically."""
    led = DepositLedger()
    led.confirm_principal("X9", 1_600_000)
    legs, warn = led.split_redemption("X9", 1_605_326.90, acct="Leumi-ILS", ccy="ILS")
    assert warn is None and len(legs) == 2
    assert abs(legs[1][0] - 5_326.90) < 0.01


def test_token_detectors():
    assert is_placement('הפקדת פק"מ')
    assert is_redemption('פרעון פקדון')
    assert not is_placement('פרעון פקדון')
    assert is_round(1_600_000) and not is_round(1_605_326.90)


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn(); print("PASS", fn.__name__)
    print(f"\nAll {len(fns)} tests passed.")
