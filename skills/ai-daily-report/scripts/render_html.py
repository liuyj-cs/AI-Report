#!/usr/bin/env python3
"""Render a daily or weekly report JSON to a single-file HTML using Jinja2."""

import argparse
import json
import sys
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

SKILL_ROOT = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = SKILL_ROOT / "templates"
SCHEMAS_DIR = SKILL_ROOT / "schemas"


def load_schema(report_type: str) -> dict:
    filename = "deep_dive.schema.json" if report_type == "deep_dive" else f"{report_type}_report.schema.json"
    path = SCHEMAS_DIR / filename
    return json.loads(path.read_text(encoding="utf-8"))


def render(json_path: Path, output_path: Path | None = None, report_type: str | None = None) -> Path:
    data = json.loads(json_path.read_text(encoding="utf-8"))
    rtype = report_type or data.get("type")
    if rtype not in ("daily", "weekly", "deep_dive"):
        raise ValueError(f"Unknown report type: {rtype}")

    schema = load_schema(rtype)
    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(data), key=lambda e: e.path)
    if errors:
        msgs = [f"- {'/'.join(str(p) for p in e.path)}: {e.message}" for e in errors]
        raise ValidationError("JSON schema validation failed:\n" + "\n".join(msgs))

    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=select_autoescape(["html", "j2"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    template = env.get_template(f"{rtype}.html.j2")
    html = template.render(report=data)

    if output_path is None:
        output_path = json_path.with_suffix(".html") if rtype == "deep_dive" else json_path.with_name("report.html")
    output_path.write_text(html, encoding="utf-8")
    return output_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Render report JSON to HTML")
    parser.add_argument("json_path", type=Path)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--type", choices=["daily", "weekly", "deep_dive"], default=None)
    args = parser.parse_args()

    try:
        out = render(args.json_path, args.output, args.type)
    except json.JSONDecodeError as e:
        print(f"JSON parse error: {e}", file=sys.stderr)
        return 1
    except ValidationError as e:
        print(str(e), file=sys.stderr)
        return 1
    except OSError as e:
        print(f"IO error: {e}", file=sys.stderr)
        return 2

    print(str(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
