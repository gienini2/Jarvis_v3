"""Mide el enrutado por temas con casos de tests/ (necesita Ollama).
Uso: python scripts/calibrate_domains.py [-v] [domain_cases.json domain_cases_nuevos.json]"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import domains

TESTS = Path(__file__).resolve().parent.parent / "tests"


def main():
    verbose = "-v" in sys.argv
    files = [a for a in sys.argv[1:] if a != "-v"] or ["domain_cases.json"]
    paths = [Path(f) if Path(f).exists() else TESTS / f for f in files]
    cases = [c for p in paths for c in json.loads(p.read_text(encoding="utf-8"))]
    covered = top1 = routed = 0
    expect_scores, none_scores = [], []
    for case in cases:
        s = domains.scores(case["text"], case.get("prev", ""))
        if not s:
            print(f"SIN EMBEDDING: {case['text']}")
            continue
        ranked = sorted(s.items(), key=lambda kv: kv[1], reverse=True)
        chosen = domains.pick(s) or []
        expect = case["expect"]
        if expect:
            expect_scores.append(ranked[0][1])
            ok_top = ranked[0][0] in expect
            ok_cover = bool(chosen) and all(d in chosen for d in expect)
            top1 += ok_top
            covered += ok_cover
            routed += bool(chosen)
            if verbose or not ok_cover:
                mark = "OK " if ok_cover else "FALLO"
                top3 = ", ".join(f"{n} {v:.2f}" for n, v in ranked[:3])
                print(f"{mark} {case['text'][:55]!r:60} esperado={expect} elegido={chosen} | {top3}")
        else:
            none_scores.append(ranked[0][1])
            if verbose or chosen:
                print(f"{'OK ' if not chosen else 'ENRUTA'} {case['text']!r} elegido={chosen} top={ranked[0][1]:.2f}")
    n = len(expect_scores)
    print(f"\ncon tema esperado: {n} | top1 correcto {top1}/{n} | cubre las tools necesarias {covered}/{n} | enrutados {routed}/{n}")
    if expect_scores:
        print(f"score top con tema: min {min(expect_scores):.2f} media {sum(expect_scores)/n:.2f}")
    if none_scores:
        print(f"score top sin tema: max {max(none_scores):.2f}")


if __name__ == "__main__":
    main()
