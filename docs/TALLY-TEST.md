# Real TallyPrime acceptance

Run this only against a disposable test company on a computer with TallyPrime. The Linux app does not install Tally or a VM. Record Tally version, date, expected values, actual values and evidence for every item. The simulator passing is not a substitute.

Configure Tally XML connectivity, its host/port in `kiwi/bahi.toml`, and the exact company in Kiwi. Run `kiwi tally-check`. Educational mode can use `[tally] edu_mode=true` to shift test dates; return it to false before working on real books.

1. Connection succeeds and lists the intended company.
2. Ledger masters/groups import correctly, including bank and cash classification.
3. Missing ledgers are created under the intended groups.
4. Payment, Receipt and Contra dates, amounts and debit/credit sides match source rows.
5. Bank allocation type, reference and bank date are accepted.
6. Bank reconciliation reflects the expected bank dates.
7. Custom voucher types work when configured, or are explicitly treated as unsupported.
8. With two companies open, vouchers reach only the configured company.
9. Exported masters and voucher XML files import successfully; verify company selection in Tally's import screen.
10. Repeated import and a connection interruption are investigated in a disposable company. Check for duplicates before retrying: exactly-once posting is not guaranteed. XML export undo resets local status; it does not delete vouchers already imported into Tally.
11. Bill-wise party ledgers are accepted or receive a diagnosed, resolved compatibility fix.

Also reconcile one full-period Tally export imported into Litchi: voucher count, ledger totals, cancelled vouchers, repeated import, and amended voucher updates. Preserve failed XML responses for debugging without publishing client details.

Release gate: all eleven checks passed, your own real bank statements parsed/reconciled, and an independently checked Litchi import. These gates are not claimed passed in this release.

References: [Tally XML integration](https://help.tallysolutions.com/xml-integration/), [sample XML](https://help.tallysolutions.com/sample-xml/). The original supplied checklist is preserved under `original-bahi/TALLY-TEST.md` for provenance.
