from __future__ import annotations

import argparse
import json

from app.db import init_db
from app.services.pipeline_metrics import PIPELINE_VERSION, latency_report


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Report chapter pipeline P50/P95 latency by scenario."
    )
    parser.add_argument("--chapter", type=int, default=2)
    parser.add_argument("--pipeline-version", default=PIPELINE_VERSION)
    args = parser.parse_args()

    init_db()
    report = latency_report(
        chapter_number=args.chapter,
        pipeline_version=args.pipeline_version,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
