"""
    python -m src.analyst "How accurate is the next-price forecast?"          # offline engine
    python -m src.analyst --llm "Does Swiggy Instamart follow Blinkit?"       # Claude tool loop (needs API credentials)
    python -m src.analyst --json "..."                                        # the raw answer object
"""
import argparse
import json
import sys

from src.analyst.agent import answer, render


def main():
    ap = argparse.ArgumentParser(description='Provenance-labelled analyst over the project (deliverable 13).')
    ap.add_argument('question', nargs='+')
    ap.add_argument('--llm', action='store_true', help='answer with claude-opus-5 (falls back offline without credentials)')
    ap.add_argument('--json', action='store_true', help='print the answer object as JSON')
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')    # Windows consoles default to cp1252
    res = answer(' '.join(a.question), llm=a.llm)
    print(json.dumps(res, indent=1, default=str) if a.json else render(res))


if __name__ == '__main__':
    main()
