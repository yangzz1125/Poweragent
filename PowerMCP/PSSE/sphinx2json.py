"""
Parse Sphinx-generated PSSE psspy HTML API docs into individual JSON files.

Strategy:
1. Extract only from <div class="body"> to avoid sidebar duplication
2. Parse the Python syntax line to determine input params vs return values
3. Match field-list descriptions to Python param/return names
4. Ignore Fortran/Iplan/Batch syntax entirely
5. Classify each function by its return signature pattern
"""

import json
import os
import re
import sys
from pathlib import Path


def strip_tags(html):
    """Remove HTML tags, decode entities, normalize whitespace."""
    text = re.sub(r"<[^>]+>", "", html)
    text = text.replace("&lt;", "<").replace("&gt;", ">")
    text = text.replace("&amp;", "&").replace("&quot;", '"')
    text = text.replace("&#8212;", "—").replace("&#8211;", "–")
    text = text.replace("&#8216;", "'").replace("&#8217;", "'")
    text = text.replace("&#8220;", '"').replace("&#8221;", '"')
    text = text.replace("&nbsp;", " ")
    text = re.sub(r"&#(\d+);", lambda m: chr(int(m.group(1))), text)
    text = re.sub(r"&#x([0-9a-fA-F]+);", lambda m: chr(int(m.group(1), 16)), text)
    text = text.replace("¶", "")
    return re.sub(r"\s+", " ", text).strip()


def extract_body(html):
    """Extract content inside <div class="body" ...>...</div>, excluding sidebar."""
    m = re.search(r'<div class="body"[^>]*role="main"[^>]*>(.*?)</div>\s*</div>\s*</div>',
                  html, re.DOTALL)
    if not m:
        m = re.search(r'<div class="body"[^>]*>(.*?)<div class="sphinxsidebar"',
                      html, re.DOTALL)
    return m.group(1) if m else html


def extract_category(html):
    """Extract category from navigation breadcrumb (nav-item-2)."""
    m = re.search(r'<li class="nav-item nav-item-2"><a[^>]*>([^<]+)</a>', html)
    return strip_tags(m.group(1)) if m else ""


def extract_signature(body):
    """Extract the Python function signature from the dt.sig element."""
    m = re.search(r'<dt class="sig sig-object py"[^>]*>(.*?)</dt>', body, re.DOTALL)
    if m:
        return strip_tags(m.group(1))
    return ""


def extract_python_syntax(body):
    """Extract the Python syntax line, e.g. 'ierr, rval = brndat(ibus,jbus,ickt,string)'."""
    # Look for "Python syntax:" dt followed by dd
    m = re.search(
        r'<dt[^>]*>\s*Python syntax:\s*</dt>\s*<dd[^>]*>(.*?)</dd>',
        body, re.DOTALL
    )
    if m:
        return strip_tags(m.group(1))
    return ""


def extract_description_paragraphs(body):
    """Extract description paragraphs from the dd block after the signature."""
    # Get the main dd block content
    m = re.search(r'<dt class="sig sig-object py"[^>]*>.*?</dt>\s*<dd>(.*?)</dd>\s*</dl>',
                  body, re.DOTALL)
    if not m:
        return []

    dd_content = m.group(1)
    paragraphs = []
    for pm in re.finditer(r"<p>(.*?)</p>", dd_content, re.DOTALL):
        text = strip_tags(pm.group(1))
        if not text:
            continue
        low = text.lower()
        # Skip table context lines
        if "values are as follows" in low:
            continue
        if low == "notes:":
            continue
        # Skip if this is inside a dl or table (we handle those separately)
        paragraphs.append(text)

    return paragraphs


def extract_field_list_params(body):
    """Extract parameter entries from the Sphinx field-list.
    Returns dict of {PARAM_NAME_UPPER: {type, description, direction}}."""
    params = {}
    # Find the field-list section
    fl_match = re.search(r'<dl class="field-list simple">(.*?)</dl>', body, re.DOTALL)
    if not fl_match:
        return params

    fl_content = fl_match.group(1)
    # Each param is in a <li> tag
    for li in re.finditer(r"<li><p>(.*?)</p></li>", fl_content, re.DOTALL):
        raw = strip_tags(li.group(1))
        # Pattern: NAME (type) – Description. (input/output).
        m = re.match(r"(\w+)\s*\(([^)]*)\)\s*[–\-]\s*(.*)", raw, re.DOTALL)
        if m:
            name = m.group(1).strip()
            ftype = m.group(2).strip()
            desc = m.group(3).strip()
        else:
            m = re.match(r"(\w+)\s*[–\-]\s*(.*)", raw, re.DOTALL)
            if m:
                name = m.group(1).strip()
                ftype = ""
                desc = m.group(2).strip()
            else:
                continue

        # Determine direction from description text
        desc_lower = desc.lower()
        if "(output)" in desc_lower or "(output" in desc_lower:
            direction = "output"
        elif "(input" in desc_lower:
            direction = "input"
        else:
            direction = "unknown"

        params[name.upper()] = {
            "fortran_type": ftype,
            "description": desc,
            "direction": direction,
        }

    return params


def extract_tables(body):
    """Extract all tables from the body, with their preceding context paragraph."""
    tables = []
    # Find each table and the paragraph just before it
    parts = re.split(r"(<table.*?</table>)", body, flags=re.DOTALL)

    for i, part in enumerate(parts):
        if not part.startswith("<table"):
            continue
        # Get context from preceding part
        context = ""
        if i > 0:
            # Last <p> before this table
            prev_ps = re.findall(r"<p>(.*?)</p>", parts[i - 1], re.DOTALL)
            if prev_ps:
                context = strip_tags(prev_ps[-1])

        # Parse table rows
        rows = []
        for tr in re.finditer(r"<tr[^>]*>(.*?)</tr>", part, re.DOTALL):
            cells = []
            for td in re.finditer(r"<t[dh][^>]*>(.*?)</t[dh]>", tr.group(1), re.DOTALL):
                cells.append(strip_tags(td.group(1)))
            if cells and any(c.strip() for c in cells):
                rows.append(cells)
        if rows:
            tables.append({"context": context, "rows": rows})

    return tables


def parse_python_syntax(syntax):
    """Parse 'ierr, rval = brndat(ibus,jbus,ickt,string)' into returns and inputs."""
    if not syntax:
        return [], [], ""

    m = re.match(r"(.+?)\s*=\s*(\w+)\s*\(([^)]*)\)", syntax.strip())
    if m:
        returns_str = m.group(1).strip()
        func_name = m.group(2).strip()
        args_str = m.group(3).strip()
        returns = [r.strip() for r in returns_str.split(",") if r.strip()]
        inputs = [a.strip() for a in args_str.split(",") if a.strip()]
        return returns, inputs, func_name

    # No return value: func(args)
    m = re.match(r"(\w+)\s*\(([^)]*)\)", syntax.strip())
    if m:
        func_name = m.group(1).strip()
        args_str = m.group(2).strip()
        inputs = [a.strip() for a in args_str.split(",") if a.strip()]
        return [], inputs, func_name

    return [], [], ""


def classify_return_pattern(returns, description=""):
    """Classify the return signature into a category for AI understanding.

    For error_only functions, further checks the description to detect
    functions that produce side-effect output (reports, channel setup, etc.).
    """
    if not returns:
        return "void"

    ret_lower = [r.lower() for r in returns]

    # Single return, no ierr
    if len(returns) == 1 and ret_lower[0] != "ierr":
        return "value_only"

    # ierr only — check for report/output side effects
    if returns == ["ierr"]:
        return _classify_error_only(description)

    if ret_lower[0] != "ierr":
        # Multiple returns without ierr
        return "multi_value"

    # ierr + something(s)
    non_ierr = ret_lower[1:]

    # Categorize by what's returned alongside ierr
    if len(non_ierr) == 1:
        val = non_ierr[0]
        if val in ("rarray", "iarray", "carray", "xarray"):
            return "error_and_array"
        if val == "types":
            return "error_and_types"
        if val in ("rval", "ival", "cval", "lval", "cmpval"):
            return "error_and_scalar"
        if val == "string":
            return "error_and_string"
        if val == "model":
            return "error_and_model"
        if val in ("realaro", "intgaro", "intgar"):
            return "error_and_record"
        if val.endswith("s") or val == "count":
            # buses, brnchs, areas, loads, etc. — count values
            return "error_and_count"
        return "error_and_value"

    # ierr + multiple return values
    # Check for array + extra
    if any(v in ("rarray", "iarray", "carray", "xarray") for v in non_ierr):
        return "error_and_array_plus"

    if "realaro" in non_ierr or "intgaro" in non_ierr:
        return "error_and_record"

    return "error_and_multi_value"


# Compiled patterns for report classification (used by _classify_error_only)
_RE_REPORT = re.compile(
    r"\b(print|report|produce|tabulate|calculate and report)\b", re.IGNORECASE
)
_RE_OUTPUT_CHANNEL = re.compile(
    r"\badd (an |a pair of )?output channel", re.IGNORECASE
)
_RE_LISTING = re.compile(
    r"\blist\b(?!.*\badd .* to the list\b)", re.IGNORECASE
)
_RE_WRITE_FILE = re.compile(
    r"\b(write|save|export)\b.*\b(file|data|case|raw)\b", re.IGNORECASE
)


def _classify_error_only(description):
    """Sub-classify error_only functions by checking for output side effects."""
    if not description:
        return "error_only"

    if _RE_OUTPUT_CHANNEL.search(description):
        return "error_only_output_channel"
    if _RE_REPORT.search(description):
        return "error_only_report"
    if _RE_LISTING.search(description):
        return "error_only_listing"
    if _RE_WRITE_FILE.search(description):
        return "error_only_write_file"

    return "error_only"


def parse_html_file(filepath):
    """Parse a single Sphinx HTML file and return structured data."""
    with open(filepath, "r", encoding="utf-8") as f:
        html = f.read()

    body = extract_body(html)
    category = extract_category(html)
    signature = extract_signature(body)
    python_syntax = extract_python_syntax(body)
    field_params = extract_field_list_params(body)
    raw_tables = extract_tables(body)
    desc_paragraphs = extract_description_paragraphs(body)

    # Parse function name from signature
    func_name = ""
    m = re.match(r"(\w+)\s*\(", signature)
    if m:
        func_name = m.group(1)

    # Parse Python syntax into returns and inputs
    returns, inputs, _ = parse_python_syntax(python_syntax)

    # Build parameters list (inputs only) with descriptions from field-list
    parameters = []
    for param_name in inputs:
        upper = param_name.upper()
        info = field_params.get(upper, {})
        parameters.append({
            "name": param_name,
            "description": info.get("description", ""),
        })

    # Build returns list with descriptions from field-list
    return_values = []
    for ret_name in returns:
        upper = ret_name.upper()
        info = field_params.get(upper, {})
        return_values.append({
            "name": ret_name,
            "description": info.get("description", ""),
        })

    # Build description early so we can use it for classification
    table_contexts = set()
    for table in raw_tables:
        table_contexts.add(table["context"])
    description = " ".join(p for p in desc_paragraphs if p not in table_contexts)

    # Classify the return pattern
    return_type = classify_return_pattern(returns, description)

    # Process tables into structured sections
    allowed_values = {}
    error_codes = []
    for table in raw_tables:
        ctx = table["context"].lower()
        rows = table["rows"]

        entries = []
        for row in rows:
            if len(row) >= 2:
                entries.append({"value": row[0].strip(), "description": row[1].strip()})

        if not entries:
            continue

        if "error code" in ctx:
            error_codes = entries
        elif "argument" in ctx or "values are as follows" in ctx:
            m_arg = re.search(r"argument\s+(\w+)", ctx, re.IGNORECASE)
            arg_name = m_arg.group(1) if m_arg else "unknown"
            allowed_values[arg_name] = entries

    result = {
        "module": "psspy",
        "function_name": func_name,
        "category": category,
        "description": description,
        "python_syntax": python_syntax,
        "return_type": return_type,
        "parameters": parameters,
        "return_values": return_values,
    }

    if allowed_values:
        result["allowed_values"] = allowed_values
    if error_codes:
        result["error_codes"] = error_codes

    return result


def main():
    input_dir = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), "psspy")
    output_dir = sys.argv[2] if len(sys.argv) > 2 else os.path.join(os.path.dirname(__file__), "json_output")

    input_path = Path(input_dir)
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    html_files = sorted(input_path.glob("*.html"))
    if not html_files:
        print(f"No HTML files found in {input_path}")
        sys.exit(1)

    print(f"Found {len(html_files)} HTML files in {input_path}")

    success = 0
    errors = 0
    for filepath in html_files:
        try:
            data = parse_html_file(filepath)
            fname = data.get("function_name") or filepath.stem
            out_file = output_path / f"{fname}.json"
            with open(out_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            success += 1
        except Exception as e:
            print(f"ERROR parsing {filepath.name}: {e}")
            errors += 1

    print(f"Done. {success} JSON files written to {output_path}")
    if errors:
        print(f"{errors} files had errors.")

    # Write index file (no return_type needed here per user request)
    index = []
    for jf in sorted(output_path.glob("*.json")):
        if jf.name == "_index.json":
            continue
        with open(jf, "r", encoding="utf-8") as f:
            data = json.load(f)
        index.append({
            "function_name": data.get("function_name", ""),
            "category": data.get("category", ""),
            "python_syntax": data.get("python_syntax", ""),
            "description": data.get("description", "")[:200],
            "file": jf.name,
        })

    with open(output_path / "_index.json", "w", encoding="utf-8") as f:
        json.dump(index, f, indent=2, ensure_ascii=False)
    print(f"Index file written with {len(index)} entries.")


if __name__ == "__main__":
    main()
