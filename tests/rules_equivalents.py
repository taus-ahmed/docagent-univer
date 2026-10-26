"""The coded family checks, written as declarative rules (Part 3.1).

`rules_for(doc)` gives, for one locale fixture (tests/fixtures/
make_locale_fixtures.py), the rules a template author would declare to get the
family's coded checks without any code. tests/test_rules_equality.py runs each
fixture both ways and compares what each marks low. Not a test module itself.
"""


def _between(fields, first, last):
    labs = list(fields)
    i, j = labs.index(first), labs.index(last)
    return labs[i + 1:j]


def rules_for(doc):
    fam, f = doc["family"], doc["fields"]
    if fam in ("invoice", "receipt"):
        return [
            {"name": "lines_sum", "type": "sum_equals",
             "terms": ["rows.Amount"], "total": "Subtotal"},
            {"name": "grand_total", "type": "sum_equals",
             "terms": ["Subtotal"] + [f"{lab}?" for lab in _between(f, "Subtotal", "Total")],
             "total": "Total"}]
    if fam == "payslip":
        return [{"name": "net_pay", "type": "sum_equals",
                 "terms": ["Gross Pay", "-Total Deductions"], "total": "Net Pay"}]
    if fam == "bank_statement":
        out = [{"name": "opening_to_closing", "type": "sum_equals",
                "terms": ["Opening Balance", "Total Credits", "-Total Debits"],
                "total": "Closing Balance"},
               {"name": "transaction_count", "type": "count_matches",
                "table": "rows", "count": "Number of Transactions"}]
        if "Credit" in doc["columns"]:
            out += [{"name": "credits_sum", "type": "sum_equals",
                     "terms": ["rows.Credit"], "total": "Total Credits"},
                    {"name": "debits_sum", "type": "sum_equals",
                     "terms": ["rows.Debit"], "total": "Total Debits"}]
        return out
    return []
