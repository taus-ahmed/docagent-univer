"""
DocAgent v2 — Extraction Test Suite (Schema-Driven)
Works for any document of any type without hardcoded values.
Usage:
  python test_extraction.py --url https://loving-grace-production.up.railway.app
  python test_extraction.py --url https://... --doc-type cheque --verbose
  python test_extraction.py --list-types
  python test_extraction.py --url https://... --dry-run
Requirements: pip install requests
"""
import os, re, sys, time, json, argparse, requests
from pathlib import Path
from datetime import datetime
from typing import Optional
from dataclasses import dataclass, field as dc_field

DEFAULT_URL    = "https://loving-grace-production.up.railway.app"
ADMIN_USER     = "admin"
ADMIN_PASS     = "admin123"
PASS_THRESHOLD = 75
POLL_TIMEOUT   = 180
PDF_DIR        = Path(__file__).parent / "test_pdfs"

# ── Validation Schemas ────────────────────────────────────────────────────────
VALIDATION_SCHEMAS = {
    "cheque": {
        "mode": "form",
        "required_fields": ["Cheque Number","Date","Bank Name","Drawer Name",
                            "Payee","Amount","Amount in Words","Memo",
                            "Authorized By","Routing Number","Account Number"],
        "numeric_fields":  ["Amount"],
        "date_fields":     ["Date"],
        "pattern_fields":  {
            "Routing Number": r"^[A-Z]?\d{9}[A-Z]?$",
            "Amount":         r"^\d+(\.\d{1,2})?$",
        },
        "prohibited_values": ["N/A","null","None","n/a","0","0.00"],
        "consistency_checks": [],
    },
    "sales_invoice": {
        "mode": "table",
        "required_fields": [],
        "numeric_fields":  [],
        "date_fields":     [],
        "pattern_fields":  {},
        "prohibited_values": ["N/A","null","None","n/a"],
        "table_min_rows":  1,
        "table_col_rules": {"Item":"non_empty","SKU":"non_empty",
                            "Qty":"numeric","Price":"numeric_positive",
                            "Item Subtotal":"numeric_positive"},
        "consistency_checks": [
            {"type":"row_product","col_a":"Qty","col_b":"Price",
             "result_col":"Item Subtotal","tolerance_pct":2}],
    },
    "purchase_order": {
        "mode": "form",
        "required_fields": ["PO Number","Date","Vendor Name","Buyer Name"],
        "numeric_fields":  ["Total Amount"],
        "date_fields":     ["Date"],
        "pattern_fields":  {},
        "prohibited_values": ["N/A","null","None","n/a"],
        "table_min_rows":  1,
        "table_col_rules": {"Description":"non_empty","Quantity":"numeric",
                            "Unit Price":"numeric_positive"},
        "consistency_checks": [],
    },
    "receipt": {
        "mode": "form",
        "required_fields": ["Merchant Name","Date","Total Amount"],
        "numeric_fields":  ["Total Amount"],
        "date_fields":     ["Date"],
        "pattern_fields":  {"Total Amount": r"^\d+(\.\d{1,2})?$"},
        "prohibited_values": ["N/A","null","None","n/a"],
        "consistency_checks": [],
    },
    "pay_order": {
        "mode": "form",
        "required_fields": ["Pay Order Number","Issue Date","Amount (Figures)",
                            "Amount (Words)","Beneficiary","Issuing Bank"],
        "numeric_fields":  ["Amount (Figures)"],
        "date_fields":     ["Issue Date"],
        "pattern_fields":  {"Amount (Figures)": r"^\d+(\.\d{1,2})?$"},
        "prohibited_values": ["N/A","null","None","n/a","0","0.00"],
        "consistency_checks": [],
    },
    "bank_statement": {
        "mode": "table",
        "required_fields": [],
        "numeric_fields":  [],
        "date_fields":     [],
        "pattern_fields":  {},
        "prohibited_values": ["N/A","null","None","n/a"],
        "table_min_rows":  3,
        "table_col_rules": {"Description":"non_empty"},
        "consistency_checks": [
            {"type":"mutual_exclusive_cols","col_a":"Debit","col_b":"Credit"}],
    },
    "payslip": {
        "mode": "form",
        "required_fields": ["Employee Name","Pay Period From","Pay Period To",
                            "Gross Pay","Net Pay"],
        "numeric_fields":  ["Gross Pay","Net Pay"],
        "date_fields":     ["Pay Period From","Pay Period To"],
        "pattern_fields":  {},
        "prohibited_values": ["N/A","null","None","n/a"],
        "consistency_checks": [],
    },
    "expense_report": {
        "mode": "form",
        "required_fields": ["Employee Name","Report Period From",
                            "Report Period To","Total Claimed"],
        "numeric_fields":  ["Total Claimed"],
        "date_fields":     ["Report Period From","Report Period To"],
        "pattern_fields":  {},
        "prohibited_values": ["N/A","null","None","n/a"],
        "table_min_rows":  1,
        "table_col_rules": {"Description":"non_empty","Amount":"numeric_positive"},
        "consistency_checks": [],
    },
    "tax_form": {
        "mode": "form",
        "required_fields": ["Taxpayer Name","Tax Year"],
        "numeric_fields":  [],
        "date_fields":     [],
        "pattern_fields":  {},
        "prohibited_values": ["N/A","null","None","n/a"],
        "consistency_checks": [],
    },
    "income_statement": {
        "mode": "table",
        "required_fields": [],
        "numeric_fields":  [],
        "date_fields":     [],
        "pattern_fields":  {},
        "prohibited_values": ["N/A","null","None","n/a"],
        "table_min_rows":  5,
        "table_col_rules": {"Description":"non_empty","Current Period":"numeric_or_empty"},
        "consistency_checks": [
            {"type":"required_row_keyword","col":"Description",
             "keywords":["net income","net profit","net loss"]},
            {"type":"required_row_keyword","col":"Description",
             "keywords":["revenue","net sales","total revenue"]}],
    },
    "balance_sheet": {
        "mode": "table",
        "required_fields": [],
        "numeric_fields":  [],
        "date_fields":     [],
        "pattern_fields":  {},
        "prohibited_values": ["N/A","null","None","n/a"],
        "table_min_rows":  10,
        "table_col_rules": {"Description":"non_empty","Amount":"numeric_or_empty"},
        "consistency_checks": [
            {"type":"required_row_keyword","col":"Description","keywords":["total assets"]},
            {"type":"required_row_keyword","col":"Description","keywords":["total liabilities"]},
            {"type":"required_row_keyword","col":"Description",
             "keywords":["total equity","shareholders equity","stockholders equity"]}],
    },
    "audit_report": {
        "mode": "form",
        "required_fields": ["Company Audited","Audit Firm","Audit Opinion","Report Date"],
        "numeric_fields":  [],
        "date_fields":     ["Report Date"],
        "pattern_fields":  {"Audit Opinion": r"(?i)(unqualified|qualified|adverse|disclaimer)"},
        "prohibited_values": ["N/A","null","None","n/a"],
        "consistency_checks": [],
    },
}

PREFIX_TO_DOC_TYPE = {
    "INV":"sales_invoice","PO":"purchase_order","CHQ":"cheque",
    "RCP":"receipt","FNBNY":"pay_order","STMT":"bank_statement",
    "PAYSLIP":"payslip","EXP":"expense_report","FORM":"tax_form",
    "IS":"income_statement","BS":"balance_sheet",
    "AUD":"audit_report","INT":"audit_report",
    "MGMT":"audit_report","REV":"audit_report",
}

def get_doc_type(filename):
    return PREFIX_TO_DOC_TYPE.get(filename.split("-")[0].upper())

# ── Helpers ───────────────────────────────────────────────────────────────────
def _valid_date(v):
    try: datetime.strptime(v.strip(),"%Y-%m-%d"); return True
    except: return False

def _valid_num(v):
    try: float(v.replace(",","").strip()); return True
    except: return False

def _positive_num(v):
    try: return float(v.replace(",","").strip()) > 0
    except: return False

def _find(field, data):
    inner = data.get("extracted_data", data)
    if not isinstance(inner, dict): inner = data
    fn = field.lower().replace("_"," ").replace(":","").strip()
    for k,v in inner.items():
        if k.startswith("_label_"): continue
        kn = k.lower().replace("_"," ").replace(":","").strip()
        if kn == fn:
            return str(v.get("value","") if isinstance(v,dict) else (v or "")).strip()
    for k,v in inner.items():
        if k.startswith("_label_"): continue
        kn = k.lower().replace("_"," ").replace(":","").strip()
        if fn in kn or kn in fn:
            return str(v.get("value","") if isinstance(v,dict) else (v or "")).strip()
    return None

def _out(m=""): print(m)
def _err(m): print(f"[ERROR] {m}", file=sys.stderr)

# ── Validation ────────────────────────────────────────────────────────────────
@dataclass
class Check:
    name:str; passed:bool; status:str; message:str
    value:str=""; expected:str=""

def validate(data, doc_type, ground_truth=None):
    schema = VALIDATION_SCHEMAS.get(doc_type)
    if not schema:
        return [Check("schema",False,"SKIP",f"No schema for {doc_type}")]
    checks = []
    is_table = data.get("table_mode",False)
    rows = data.get("table_rows",[]) if is_table else []

    for f in schema.get("required_fields",[]):
        v = _find(f, data)
        if not v:
            checks.append(Check(f"req:{f}",False,"MISSING",f"'{f}' missing or empty"))
        else:
            checks.append(Check(f"req:{f}",True,"PASS",f"'{f}' present",value=v[:60]))

    for f in schema.get("numeric_fields",[]):
        v = _find(f, data)
        if not v: continue
        ok = _valid_num(v)
        checks.append(Check(f"num:{f}",ok,"PASS" if ok else "FAIL",
                            f"'{f}' numeric check",value=v,expected="number"))

    for f in schema.get("date_fields",[]):
        v = _find(f, data)
        if not v: continue
        ok = _valid_date(v)
        checks.append(Check(f"date:{f}",ok,"PASS" if ok else "FAIL",
                            f"'{f}' date check",value=v,expected="YYYY-MM-DD"))

    for f,pat in schema.get("pattern_fields",{}).items():
        v = _find(f, data)
        if not v: continue
        ok = bool(re.search(pat, v.strip()))
        checks.append(Check(f"pat:{f}",ok,"PASS" if ok else "FAIL",
                            f"'{f}' pattern check",value=v[:60],expected=pat))

    prohibited = schema.get("prohibited_values",[])
    inner = data.get("extracted_data", data)
    if isinstance(inner, dict):
        for k,v in inner.items():
            if k.startswith("_label_"): continue
            actual = v.get("value","") if isinstance(v,dict) else str(v or "")
            if actual.strip() in prohibited:
                checks.append(Check(f"prohib:{k}",False,"FAIL",
                                    f"'{k}' has prohibited value",value=actual))

    if is_table:
        min_r = schema.get("table_min_rows")
        if min_r:
            ok = len(rows) >= min_r
            checks.append(Check("table:rows",ok,"PASS" if ok else "FAIL",
                                f"{len(rows)} rows (min {min_r})",
                                value=str(len(rows)),expected=f">={min_r}"))
        for col,rule in schema.get("table_col_rules",{}).items():
            vals = [str(r.get(col,"")).strip() for r in rows]
            non_empty = [v for v in vals if v]
            rate = len(non_empty)/len(vals) if vals else 0
            if rule == "non_empty":
                ok = rate >= 0.8
                checks.append(Check(f"col:{col}",ok,"PASS" if ok else "FAIL",
                                    f"'{col}' fill rate {rate:.0%}",
                                    value=f"{rate:.0%}",expected=">=80%"))
            elif rule in ("numeric","numeric_positive","numeric_or_empty"):
                bad = [v for v in non_empty if not _valid_num(v)]
                if rule == "numeric_positive":
                    bad = [v for v in non_empty if not _positive_num(v)]
                ok = len(bad) == 0
                checks.append(Check(f"col:{col}",ok,"PASS" if ok else "FAIL",
                                    f"'{col}': {len(bad)} non-numeric",
                                    value=f"{len(bad)} bad",expected="numeric"))

    for cc in schema.get("consistency_checks",[]):
        t = cc["type"]
        if t == "row_product" and rows:
            a,b,rc,tol = cc["col_a"],cc["col_b"],cc["result_col"],cc.get("tolerance_pct",2)/100
            fails = []
            for i,r in enumerate(rows):
                try:
                    av = float(str(r.get(a,"0")).replace(",","") or "0")
                    bv = float(str(r.get(b,"0")).replace(",","") or "0")
                    rv = float(str(r.get(rc,"0")).replace(",","") or "0")
                    if av*bv > 0 and abs(rv - av*bv)/(av*bv) > tol: fails.append(i+1)
                except: pass
            ok = len(fails)==0
            checks.append(Check(f"cons:{a}x{b}={rc}",ok,"PASS" if ok else "WARN",
                                f"{len(fails)} row mismatches"))
        elif t == "required_row_keyword" and rows:
            col,kws = cc["col"],cc["keywords"]
            found = any(any(kw in str(r.get(col,"")).lower() for kw in kws) for r in rows)
            checks.append(Check(f"cons:row:{kws[0]}",found,"PASS" if found else "FAIL",
                                f"Required row {kws}: {'found' if found else 'MISSING'}"))
        elif t == "mutual_exclusive_cols" and rows:
            a,b = cc["col_a"],cc["col_b"]
            both = [r for r in rows if r.get(a,"").strip() and r.get(b,"").strip()]
            ok = len(both)==0
            checks.append(Check(f"cons:{a}_xor_{b}",ok,"PASS" if ok else "WARN",
                                f"{len(both)} rows with both {a} and {b} filled"))

    if ground_truth:
        for f,exp in ground_truth.items():
            v = _find(f, data)
            if v is None:
                checks.append(Check(f"gt:{f}",False,"MISSING","",expected=str(exp)))
            else:
                ok = v.strip() == str(exp).strip()
                checks.append(Check(f"gt:{f}",ok,"PASS" if ok else "FAIL","",
                                    value=v[:60],expected=str(exp)[:60]))
    return checks

# ── API Client ────────────────────────────────────────────────────────────────
class DocAgentClient:
    def __init__(self, base_url):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers["Accept"] = "application/json"
        self._use_proxy = False

    def _base(self):
        return (f"{self.base_url}/api/proxy" if self._use_proxy
                else f"{self.base_url}/api")

    def login(self, username, password):
        for label, url in [
            ("proxy",  f"{self.base_url}/api/proxy/auth/login"),
            ("direct", f"{self.base_url}/api/auth/login"),
        ]:
            try:
                r = self.session.post(url, json={"username":username,"password":password}, timeout=15)
                if r.status_code == 200:
                    self.session.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
                    self._use_proxy = (label == "proxy")
                    _out(f"Login OK (via {label})")
                    return True
                _out(f"  [{label}] HTTP {r.status_code}")
            except Exception as e:
                _out(f"  [{label}] {e}")
        _err("Login failed — check URL and credentials")
        return False

    def get_templates(self):
        try:
            r = self.session.get(f"{self._base()}/templates", timeout=10)
            return r.json() if r.status_code==200 else []
        except: return []

    def upload(self, pdf_path, client_id="demo_001", template_id=None):
        try:
            with open(pdf_path,"rb") as f:
                files = {"files": (pdf_path.name, f, "application/pdf")}
                data  = {"client_id": client_id}
                if template_id: data["template_id"] = str(template_id)
                r = self.session.post(f"{self._base()}/extract/upload",
                                      files=files, data=data, timeout=60)
            if r.status_code in (200,202): return r.json().get("job_id")
            _err(f"Upload {r.status_code}: {r.text[:200]}")
            return None
        except Exception as e:
            _err(f"Upload error: {e}"); return None

    def poll(self, job_id, timeout=POLL_TIMEOUT):
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                r = self.session.get(f"{self._base()}/jobs/{job_id}", timeout=10)
                if r.status_code == 200:
                    job = r.json(); s = job.get("status")
                    if s == "completed": return job
                    if s in ("failed","cancelled"):
                        _err(f"Job {job_id} {s}: {job.get('error_message','')}"); return None
            except: pass
            time.sleep(3)
        _err(f"Job {job_id} timed out"); return None

    def get_results(self, job_id):
        try:
            r = self.session.get(f"{self._base()}/jobs/{job_id}/results", timeout=10)
            return r.json() if r.status_code==200 else []
        except: return []

# ── Result types ──────────────────────────────────────────────────────────────
@dataclass
class DocResult:
    filename:str; doc_type:str; passed:bool=False
    checks:list=dc_field(default_factory=list)
    error:str=""; row_count:int=0
    total:int=0; ok:int=0; pct:float=0.0
    duration:float=0.0; method:str=""

# ── Test runner ───────────────────────────────────────────────────────────────
def run_test(client, pdf_path, templates, ground_truth=None):
    filename = pdf_path.name
    doc_type = get_doc_type(filename)
    t0 = time.time()
    r = DocResult(filename=filename, doc_type=doc_type or "unknown")

    if not doc_type:
        r.error = "Cannot determine doc_type from filename"; return r
    if doc_type not in VALIDATION_SCHEMAS:
        r.error = f"No schema for '{doc_type}'"; return r

    tpl_id = next((t["id"] for t in templates
                   if t.get("document_type","").lower().replace(" ","_") == doc_type), None)
    if tpl_id is None:
        r.error = f"No template for '{doc_type}'"; return r

    job_id = client.upload(pdf_path, template_id=tpl_id)
    if not job_id: r.error = "Upload failed"; return r

    job = client.poll(job_id)
    if not job: r.error = "Job failed/timeout"; return r

    results = client.get_results(job_id)
    if not results: r.error = "No results"; return r

    data = results[0].get("extracted_data") or {}
    r.method = data.get("extraction_method","")
    r.row_count = data.get("row_count",0) if data.get("table_mode") else 0

    gt = (ground_truth or {}).get(filename, {})
    r.checks = validate(data, doc_type, gt or None)
    r.total = len([c for c in r.checks if c.status != "SKIP"])
    r.ok    = sum(1 for c in r.checks if c.passed)
    r.pct   = 100*r.ok/r.total if r.total else 0.0
    r.passed = r.pct >= PASS_THRESHOLD
    r.duration = time.time() - t0
    return r

# ── Printing ──────────────────────────────────────────────────────────────────
def print_result(r, verbose=False):
    icon = "✅" if r.passed else "❌"
    acc  = f"{r.pct:.0f}%" if r.total else "N/A"
    rows = f" | {r.row_count} rows" if r.row_count else ""
    meth = f" [{r.method}]" if r.method else ""
    _out(f"\n{icon} {r.filename}  ({r.doc_type}){meth}{rows}")
    _out(f"   Accuracy: {acc} ({r.ok}/{r.total}) | {r.duration:.1f}s")
    if r.error:
        _out(f"   ⚠  {r.error}"); return
    for c in r.checks:
        if c.status == "SKIP": continue
        if not c.passed or verbose:
            ic = "✓" if c.passed else ("!" if c.status=="MISSING" else "✗")
            vs = f" → [{c.value[:50]}]" if c.value else ""
            es = f" (want: {c.expected[:40]})" if not c.passed and c.expected else ""
            _out(f"   {ic} {c.name:<44} {c.status:<8}{vs}{es}")

def print_summary(results, threshold):
    _out("\n" + "="*70)
    _out("SUMMARY")
    _out("="*70)
    valid  = [r for r in results if not r.error]
    errs   = [r for r in results if r.error]
    passed = sum(1 for r in valid if r.passed)
    total_c = sum(r.total for r in valid)
    ok_c    = sum(r.ok for r in valid)
    overall = 100*ok_c/total_c if total_c else 0

    _out(f"\nDocuments: {passed}/{len(results)} passed  ({len(errs)} errors)")
    _out(f"Checks   : {ok_c}/{total_c} ({overall:.1f}%)")
    _out()

    by_type = {}
    for r in results:
        dt = r.doc_type or "unknown"
        s  = by_type.setdefault(dt, {"d":0,"p":0,"c":0,"o":0,"e":0})
        s["d"] += 1
        if r.error: s["e"] += 1
        else:
            if r.passed: s["p"] += 1
            s["c"] += r.total; s["o"] += r.ok

    _out(f"{'Doc Type':<22} {'Docs':>6} {'Checks':>12} {'Acc':>8}")
    _out("-"*52)
    for dt,s in sorted(by_type.items()):
        ds  = f"{s['p']}/{s['d']}"
        cs  = f"{s['o']}/{s['c']}" if s['c'] else "0/0"
        acc = f"{100*s['o']//s['c']}%" if s['c'] else "N/A"
        _out(f"  {dt:<20} {ds:>6} {cs:>12} {acc:>8}")

    failed = [r for r in results if not r.passed]
    if failed:
        _out(f"\nFailed ({len(failed)}):")
        for r in failed:
            _out(f"  ✗ {r.filename:<40} {r.error or f'{r.pct:.0f}%'}")

    _out()
    _out(f"Overall: {overall:.1f}%  {'✅ PASS' if overall>=threshold else '❌ FAIL'}  (threshold {threshold}%)")
    return overall

# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    p = argparse.ArgumentParser(description="DocAgent schema-driven test suite")
    p.add_argument("--url",          default=DEFAULT_URL)
    p.add_argument("--username",     default=ADMIN_USER)
    p.add_argument("--password",     default=ADMIN_PASS)
    p.add_argument("--pdf-dir",      default=str(PDF_DIR))
    p.add_argument("--doc-type",     help="Only test this doc type")
    p.add_argument("--file",         help="Only test this PDF")
    p.add_argument("--verbose","-v", action="store_true")
    p.add_argument("--dry-run",      action="store_true")
    p.add_argument("--threshold",    type=int, default=PASS_THRESHOLD)
    p.add_argument("--ground-truth", metavar="FILE")
    p.add_argument("--output",       default="test_results.json")
    p.add_argument("--list-types",   action="store_true")
    args = p.parse_args()

    if args.list_types:
        _out(f"\n{'Doc Type':<22} {'Mode':<8} Required Fields")
        _out("-"*70)
        for dt,s in sorted(VALIDATION_SCHEMAS.items()):
            if dt == "other": continue
            rf = ", ".join(s.get("required_fields",[])[:3])
            if len(s.get("required_fields",[])) > 3:
                rf += f" +{len(s['required_fields'])-3} more"
            _out(f"  {dt:<20} {s.get('mode','?'):<8} {rf}")
        return 0

    ground_truth = {}
    if args.ground_truth:
        gtp = Path(args.ground_truth)
        if gtp.exists():
            ground_truth = json.loads(gtp.read_text())
            _out(f"Ground truth: {len(ground_truth)} docs")

    pdf_dir = Path(args.pdf_dir)
    if not pdf_dir.exists():
        _err(f"PDF directory not found: {pdf_dir}"); return 1

    pdfs = sorted(pdf_dir.glob("*.pdf"))
    if args.file:     pdfs = [p for p in pdfs if p.name == args.file]
    if args.doc_type: pdfs = [p for p in pdfs if get_doc_type(p.name) == args.doc_type]
    if not pdfs:      _err("No matching PDFs"); return 1

    by_type = {}
    for pdf in pdfs:
        dt = get_doc_type(pdf.name) or "unknown"
        by_type.setdefault(dt, []).append(pdf)

    _out(f"\nDocAgent Extraction Test Suite — Schema-Driven")
    _out(f"URL      : {args.url}")
    _out(f"PDF dir  : {pdf_dir}")
    _out(f"PDFs     : {len(pdfs)} files across {len(by_type)} doc types")
    _out(f"Threshold: {args.threshold}%")
    for dt,files in sorted(by_type.items()):
        _out(f"  {dt}: {len(files)} file(s)")
    _out()

    if args.dry_run:
        _out("DRY RUN — setup looks good."); return 0

    client = DocAgentClient(args.url)
    _out(f"Logging in as {args.username}...")
    if not client.login(args.username, args.password): return 1

    templates = client.get_templates()
    _out(f"Templates: {len(templates)} found")
    tpl_types = {t.get("document_type","").lower().replace(" ","_") for t in templates}
    for dt in by_type:
        if dt not in tpl_types:
            _out(f"  ⚠  No template for '{dt}' — those files will be skipped")
    _out()

    results = []
    for i, pdf in enumerate(pdfs, 1):
        dt = get_doc_type(pdf.name) or "unknown"
        _out(f"[{i:>3}/{len(pdfs)}] {pdf.name:<42} ({dt})")
        sys.stdout.flush()
        result = run_test(client, pdf, templates, ground_truth)
        print_result(result, args.verbose)
        results.append(result)

    overall = print_summary(results, args.threshold)

    out = Path(args.output)
    out.write_text(json.dumps([
        {"filename":r.filename,"doc_type":r.doc_type,"passed":r.passed,
         "accuracy_pct":round(r.pct,1),"passed_checks":r.ok,"total_checks":r.total,
         "row_count":r.row_count,"method":r.method,"duration":round(r.duration,1),
         "error":r.error,
         "checks":[{"name":c.name,"status":c.status,"value":c.value} for c in r.checks]}
        for r in results
    ], indent=2), encoding="utf-8")
    _out(f"\nResults → {out}")
    return 0 if overall >= args.threshold else 1

if __name__ == "__main__":
    sys.exit(main())
