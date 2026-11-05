"""Summarise results_<variant>.json files against the dataset's expected grades."""

import json
import pathlib
import statistics
import sys

HERE = pathlib.Path(__file__).parent
GRADES = ["got_it", "partly", "missed"]


def main() -> None:
    dataset = json.loads((HERE / "dataset.json").read_text())
    for variant in [arg for arg in sys.argv[1:] if arg != "-v"]:
        results = json.loads((HERE / f"results_{variant}.json").read_text())
        pairs = [(dataset[r["id"]]["expected"], r) for r in results]
        correct = [expected == r["grade"] for expected, r in pairs]
        secs = sorted(r["seconds"] for r in results)
        print(f"\n== {variant}: n={len(results)} acc={sum(correct)/len(correct):.1%}")
        for grade in GRADES:
            subset = [expected == r["grade"] for expected, r in pairs if expected == grade]
            print(f"  expected {grade}: {sum(subset)}/{len(subset)}")
        print("  confusion (rows expected, cols got):", GRADES)
        for expected in GRADES:
            print("  ", expected, [sum(1 for e, r in pairs if e == expected and r["grade"] == g) for g in GRADES])
        low = [(e == r["grade"]) for e, r in pairs if not r["confident"]]
        print(f"  not confident: {len(low)} ({len(low)/len(pairs):.1%}); of those wrong: {sum(1 for x in low if not x)}")
        print(f"  errors total {len(correct)-sum(correct)}; errors flagged unconfident {sum(1 for x in low if not x)}")
        print(f"  latency p50 {statistics.median(secs):.2f}s p90 {secs[int(len(secs)*0.9)]:.2f}s max {secs[-1]:.2f}s")
        print(f"  cost/grade ${statistics.mean(r['cost'] for r in results):.5f}  in {statistics.mean(r['in'] for r in results):.0f} out {statistics.mean(r['out'] for r in results):.0f} tokens")
        # Missing-sentence presence
        need = [r for e, r in pairs if r["grade"] != "got_it"]
        print(f"  missing filled when not got_it: {sum(1 for r in need if r['missing'])}/{len(need)}; got_it with text: {sum(1 for r in results if r['grade']=='got_it' and r['missing'])}")
        if "-v" in sys.argv:
            for e, r in pairs:
                if e != r["grade"]:
                    row = dataset[r["id"]]
                    print(f"   ERR id{r['id']} exp {e} got {r['grade']} conf={r['confident']} | {row['answer'][:70]!r} | {r['missing']}")


main()
