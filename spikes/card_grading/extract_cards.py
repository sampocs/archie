"""Pull every generated card out of the recorded analyze responses in the test cassettes."""

import glob
import json

import yaml


def main() -> None:
    cards = []
    seen = set()
    for path in sorted(glob.glob("services/*/tests/**/*.yaml", recursive=True)):
        for interaction in yaml.safe_load(open(path)).get("interactions", []):
            body = interaction["response"]["body"]["string"]
            body = body.decode(errors="ignore") if isinstance(body, bytes) else body
            if not body.startswith('{"model":"claude'):
                continue
            for block in json.loads(body).get("content", []):
                if block.get("type") != "text" or '"cards"' not in block["text"]:
                    continue
                for card in json.loads(block["text"]).get("cards", []):
                    if card["question"] in seen:
                        continue
                    seen.add(card["question"])
                    cards.append({"source": path.split("/")[-1].removesuffix(".yaml"), **card})
    json.dump(cards, open("spikes/card_grading/cards_all.json", "w"), indent=1)
    print(len(cards))


main()
