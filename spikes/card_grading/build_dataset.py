"""Build dataset.json: each card with hand-written answers labelled with the expected grade."""

import json

G, P, M = "got_it", "partly", "missed"

# card index -> [got (reworded), got (sloppy dictation), partly, missed]
ANSWERS = {
    0: ["The president's party tends to lose congressional seats because voters take the midterm as a chance to punish or voice displeasure with the president, especially when prices are up.",
        "voters use it to like vent at the president so his party loses seats esp if inflation is bad",
        "People are unhappy with the president so they vote against his party.",
        "Because turnout is lower in midterms and the president isn't on the ballot, so independents all vote for third parties."],
    1: ["Marvell is buying Lumentum, a maker of optical lasers that move data between chips and servers in data centers; it gives Marvell more AI infrastructure, though the price fuels AI bubble worries.",
        "marvel buying lumentum, they make optical stuff that moves data in data centres, AI infra, kinda bubbly price",
        "Marvell is buying Lumentum, which makes optical lasers for data centers.",
        "Marvell is buying Lumentum, a memory chip maker, to compete with Nvidia on GPUs."],
    2: ["Attackers got into the remote management system for the fridges and set them to defrost, and some units also needed physical repairs besides software fixes.",
        "they hacked the remote control system n put the fridges in defrost mode, some needed hands on fixes too",
        "They hacked the system that controls the fridges and turned on defrost mode.",
        "They sent a power surge through the supermarket's electrical grid that fried the compressors."],
    3: ["Revenue was roughly 2.3 billion; US commercial was around 980 million, basically level with US government at about 950 million, so the two are now about equal.",
        "about 2.3 bil total, us commercial like 1 bil, same as government, so even split",
        "Total revenue was about 2.3 billion and US commercial was about a billion.",
        "Government revenue was about three times commercial revenue, around 1.5 billion versus 500 million."],
    4: ["Inclusive time counts everything a function takes including the functions it calls; self time counts just the function's own code.",
        "inclusive is whole time incl callees, self is only its own code not what it calls",
        "Inclusive time is the total time the function takes.",
        "Self time is the time a function waits on I/O and inclusive time is CPU time."],
    5: ["The model only sees syntax and local logic, so the code runs and passes tests, but it has no view of the runtime, call stack or production frequency, so inefficiency only shows at scale.",
        "llm sees the code not the runtime so it compiles n passes tests but cant tell how hot a function is in prod",
        "It can't see how the code behaves at runtime.",
        "LLMs are trained mostly on slow, older code so they reproduce its inefficiencies."],
    6: ["LLMs forget everything between prompts, so a shared catalog of known anti-patterns is fed into prompts so teams share findings and don't rediscover the same bugs.",
        "llm has no memory so the catalog stores known bad patterns and gets put in the prompt so everyone benefits",
        "The catalog stores known anti-patterns that get added to prompts.",
        "The catalog makes the LLM cheaper because it caches previous responses so fewer tokens are billed."],
    7: ["About 46 percent of the service's CPU went to the regex, and the lookup table replacement was around 22x quicker.",
        "regex was 46% cpu, lookup table fix about 22x faster",
        "The regex took 46% of CPU time.",
        "The regex used about 5% of CPU and the fix was twice as fast."],
    8: ["It stops the model wasting effort on garbage collection, kernel and framework overhead that developers can't change, focusing it on the application code that can be fixed.",
        "keeps it focused on our own code not gc and kernel and framework stuff we cant change",
        "It filters out noise like garbage collection from the profile.",
        "They make the profile file smaller so it fits within the model's context window."],
    9: ["Effort compounds: a little every day accumulates over years, like a page a day making a book a year, and since early exponential growth looks flat people undervalue it and give up too soon.",
        "small daily work compounds, page a day = book a year, people quit cause the early part looks flat",
        "A little work each day adds up over time, like a page a day becoming a book.",
        "Because sprints cause burnout and the body needs eight hours of sleep to be creative."],
    10: ["Pick a field matching your aptitude and interest, learn until you reach the frontier, spot gaps in knowledge, then dig into the promising ones; steps two and four are the hard work.",
        "choose field, learn to frontier, notice gaps, explore gaps. 2 and 4 are hard",
        "Choose a field and learn enough to get to the frontier.",
        "Find a mentor, copy the masters, publish early, and iterate on feedback."],
    11: ["We view the world through models that help but also limit us; where they break there are clues that people ignore, and once fixed the new idea seems obvious.",
        "we see thru mental models, breaks in them leave clues we ignore, fix it and the idea looks obvious after",
        "People see things through models that limit them.",
        "Because people are afraid of being wrong in public, so they hide unconventional ideas."],
    12: ["Rather than a fixed plan, you do what's most interesting at each step while keeping the best future options open; it fits discoveries you can't describe up front.",
        "dont plan ahead, just do the most interesting thing that keeps options open",
        "Do whatever seems most interesting at each point.",
        "Choose work that benefits from tailwinds, like trends that are already popular and well funded."],
    13: ["Roughly four to five hours a day, ideally in contiguous blocks so interruptions don't make hard tasks easy to avoid.",
        "4-5 hours, in one block so you dont get interrupted",
        "Around eight hours a day.",
        "Maybe 12 hours if you really love it."],
    14: ["It's malware that gives an attacker secret remote control of a victim's machine, like remote-support software but silent, letting them see files, keystrokes, passwords and the webcam.",
        "malware that lets someone control your pc remotely w/o you knowing, can see files keystrokes webcam",
        "A RAT is malware that lets someone control a computer.",
        "A RAT is ransomware that encrypts your files and demands payment."],
    15: ["Because a RAT can't install on a machine on its own and nobody willingly installs spyware, operators tricked victims into running it with fake photos, delivery emails and pirated software.",
        "rat cant get on a clean pc itself and no one installs spyware on purpose so they trick ppl w fake emails n pirated software",
        "They tricked people into running it.",
        "Because direct infection was too expensive in terms of servers, and social engineering is just cheaper than buying exploits."],
    16: ["Many monitoring tools are legal, so what matters is what the seller knew and what buyers would do; selling to people who'll commit crimes or marketing it for covert spying shows intent to facilitate crime.",
        "lots of monitoring tools are legal so its about what the seller knew and meant, marketing it for spying = intent",
        "Because it depends on how the tool is used.",
        "Because the law bans any software that accesses another computer, and intent only affects the sentence length."],
    17: ["The FBI counted more than half a million infected computers across over 100 countries, though other reporting said a million by May 2014.",
        "fbi said over 500k in 100+ countries",
        "Tens of thousands of computers.",
        "Around five million computers in the US alone."],
    18: ["It's the benchmark rate the Fed sets for overnight interbank lending, which feeds through to mortgages, car loans, savings and business borrowing.",
        "rate the fed sets for banks lending to each other overnight, affects mortgages loans etc",
        "It's the interest rate set by the Fed.",
        "It's the rate the US Treasury pays on 10-year bonds."],
    19: ["It's inflation excluding food and energy because they are volatile, so central banks use it to see the underlying price trend.",
        "inflation without food n energy since those jump around, shows the underlying trend",
        "Core inflation excludes food and energy prices.",
        "It's inflation in the core cities, measured by the cost of housing."],
    20: ["High rates cool borrowing and spending which brings prices down, and cutting early could let inflation come back, so they wait until it's clearly falling.",
        "high rates slow spending and bring down prices, cut too early and inflation bounces back so wait til its clearly falling",
        "Because high rates reduce inflation.",
        "Because the Fed wants to keep the dollar weak to help exporters."],
    21: ["Two percent per year.",
        "2 percent",
        "About 3 percent, I think.",
        "Zero, stable prices means no inflation."],
    22: ["Real interest keeps you on a path you care about and makes you work hard, so pressures like fashion, money or other people's wishes pull on you less.",
        "if your genuinely interested you stay on track and work harder so fashion and money dont pull you off",
        "When you're interested you don't get pulled off course.",
        "Because interest makes you less intelligent about trends, so you ignore criticism."],
    23: ["Not planning far ahead: at each point you do what's most interesting and keeps your options open, like a sailor reading the wind rather than following a set route.",
        "dont plan far ahead, do the most interesting thing keep options open, like a sailor reading the wind",
        "Keeping your options open.",
        "Staying close to the established leaders in your field so you benefit from their momentum."],
    24: ["Delaying a whole project looks like real work because you're busy with other things, so no alarm goes off, and years of a big project can go undone.",
        "per project looks like work since your busy w other stuff so no alarms go off, big thing stays undone for yrs",
        "Because delaying a project for years leaves a lot undone.",
        "Because projects have deadlines set by other people, whereas per-day tasks you control yourself."],
    25: ["It's the edge of what's known; from afar it looks smooth but up close it's full of gaps, and those gaps are where discoveries come from, so you must reach it.",
        "edge of known knowledge, looks smooth far away but full of gaps up close, gaps = discoveries so you need to get there",
        "The frontier is the edge of what is known.",
        "It's the boundary between established companies and startups where funding is available."],
    26: ["Roughly four or five hours a day, after which fatigue gives diminishing returns.",
        "4 to 5 hrs then you get diminishing returns",
        "Around two hours.",
        "Ten to twelve hours."],
}
# Extra answers (card index, answer, expected) beyond the 4 per card.
EXTRA = [
    (3, "revenue 2.31 billion with commercial and government close to even", G),
    (7, "about 45% of cpu and the fix was roughly 20 times faster", G),
    (13, "about 4 hours", G),
    (17, "around 600 thousand", G),
    (21, "two ish percent annual", G),
    (26, "5 hours a day", G),
    (0, "Because the economy is always worse at midterm time.", M),
    (5, "It's slow because of memory leaks the model can't see.", M),
    (14, "it's something that spies on you", P),
    (10, "Choose a field, then explore gaps.", P),
]
WRONG_NUMBER = {13, 17, 21, 26}
IDK = [(1, ""), (6, "I don't know"), (11, "no idea, blank"), (16, "forgot this one"), (19, "idk"), (24, "umm... something about procrastination? not sure")]


def main() -> None:
    cards = json.load(open("cards_all.json"))
    rows = []
    for index, (got, sloppy, partly, missed) in ANSWERS.items():
        for style, text, grade in [("reworded", got, G), ("sloppy", sloppy, G), ("half", partly, P), ("wrong", missed, M)]:
            rows.append((index, style, text, grade))
    for index, text, grade in EXTRA:
        rows.append((index, "extra", text, grade))
    for index, text in IDK:
        rows.append((index, "idk", text, M))
    # A wrong number is a miss, not half an idea.
    rows = [(i, s, t, M if i in WRONG_NUMBER and s == "half" else g) for i, s, t, g in rows]
    dataset = [{"id": n, "card": cards[i], "style": s, "answer": t, "expected": g} for n, (i, s, t, g) in enumerate(rows)]
    json.dump(dataset, open("dataset.json", "w"), indent=1)
    print(len(dataset), len(ANSWERS))


main()
