# SPDX-License-Identifier: Apache-2.0
"""Produce an isolated tagged-payload version of the production reader."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIELDS = {
    "name": "*CrustName",
    "integer": "u64",
    "integer_type": "u32",
    "bytes": "*u8",
    "byte_count": "usize",
}
DEFAULTS = {
    "name": "null(*CrustName)",
    "integer": "0u64",
    "integer_type": "0u32",
    "bytes": "null(*u8)",
    "byte_count": "0usize",
}
CASES = {
    "Name": {"name": "value"},
    "Number": {"integer": "value.value", "integer_type": "value.type"},
    "String": {"bytes": "value.bytes", "byte_count": "value.count"},
    "Type": {"integer_type": "value"},
    "Empty": {},
}
PAYLOAD = """
record RtNumber { value:u64; type:u32; }
record RtString { bytes:*u8; count:usize; }
union RtPayload { Name:*CrustName; Number:RtNumber; String:RtString; Type:u32; Empty:unit; }
"""


def accessors():
    result = PAYLOAD
    for field, kind in FIELDS.items():
        result += f"\nfn rt_get_{field}(token:*CrustReaderToken)->{kind} {{\n match RtPayload(token->payload) {{\n"
        for case, values in CASES.items():
            bind = "(value)" if field in values else ""
            result += f"  {case}{bind} {{ return {values.get(field, DEFAULTS[field])}; }}\n"
        result += " }\n}\n"
    result += """
fn rt_set_name(token:*CrustReaderToken,value:*CrustName)->unit {
 construct RtPayload.Name(token->payload,value);
}
fn rt_set_integer(token:*CrustReaderToken,value:u64)->unit {
 construct RtPayload.Number(token->payload,make RtNumber{value:value,type:rt_get_integer_type(token)});
}
fn rt_set_integer_type(token:*CrustReaderToken,value:u32)->unit {
 if token->kind==RR_INTEGER || token->kind==RR_COUNT {
  construct RtPayload.Number(token->payload,make RtNumber{value:rt_get_integer(token),type:value});
 } else { construct RtPayload.Type(token->payload,value); }
}
fn rt_set_bytes(token:*CrustReaderToken,value:*u8)->unit {
 construct RtPayload.String(token->payload,make RtString{bytes:value,count:rt_get_byte_count(token)});
}
fn rt_set_byte_count(token:*CrustReaderToken,value:usize)->unit {
 construct RtPayload.String(token->payload,make RtString{bytes:rt_get_bytes(token),count:value});
}
"""
    return result


def transform(text, compare):
    token = r"(\(\*reader\)\.token|\(\*left\)|\(\*right\)|token)"
    if not compare:
        token = r"(\(\*reader\)\.token|token)"
    member = "(" + "|".join(FIELDS) + ")"
    # Setter conversion precedes reads so assignment destinations remain places.
    text = re.sub(
        token + r"\." + member + r"=(?!=)([^;]+);",
        lambda m: f"rt_set_{m[2]}(&{m[1]},{m[3]});",
        text,
    )
    return re.sub(token + r"\." + member + r"\b", lambda m: f"rt_get_{m[2]}(&{m[1]})", text)


def port(output):
    output.mkdir()
    model = (ROOT / "stages/reader/model.crs").read_text()
    start = model.index("// text borrows")
    end = model.index("// Try callbacks", start)
    model = (
        model[:start]
        + """record CrustReaderToken {
    payload:RtPayload;
    offset:usize;
    length:usize;
    text:*u8;
    kind:u32;
}

"""
        + accessors()
        + "\n"
        + model[end:]
    )
    (output / "model.crs").write_text(model)
    empty = "var empty:RtPayload=uninit;construct RtPayload.Empty(empty);\n    "
    for name in ("lex", "parse", "test"):
        text = (ROOT / f"stages/reader/{name}.crs").read_text()
        if name == "lex":
            text = text.replace(
                "name:null(*CrustName),integer:0u64,integer_type:0u32,bytes:null(*u8),byte_count:0usize",
                "payload:empty",
            )
            text = text.replace(
                "    (*reader).token=make CrustReaderToken {",
                "    " + empty + "(*reader).token=make CrustReaderToken {",
            )
            text = text.replace(
                "    (*reader)=make CrustReader {", "    " + empty + "(*reader)=make CrustReader {"
            )
        (output / f"{name}.crs").write_text(transform(text, name == "parse"))
