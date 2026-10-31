# Inside the $6 Billion Binance Hack | Ari Redbord

Bankless (Ryan Sean Adams, David Hoffman): crypto, Ethereum, DeFi · 0.51 h of audio

---

## analyze · haiku-5.5 ($0.003)

**Security → Crypto exchange hacks** · tags: Binance, North Korea, Lazarus Group, Stablecoins, Crypto hacks, Compliance, AI cyber threats

**Concepts:** Hot wallet, Private key, Stablecoin freeze and burn, Beacon Network, Civil forfeiture, Tornado Cash, OTC broker, Social engineering, GENIUS Act, Offense-defense in cybersecurity, Lazarus Group, Money laundering

### Gist

Binance suffered a hack of roughly $6 billion, the largest crypto theft on record. TRM Labs' Ari Redbord describes how investigators, exchanges, and stablecoin issuers Tether and Circle moved fast to freeze about 40% of the stolen funds, and why the evidence points to North Korea's Lazarus Group. Recovering the rest is much harder because ETH and BTC cannot be frozen the way stablecoins can.

### Key ideas

- **[00:32]** Hacks keep getting bigger. Bybit lost about $1.5 billion a year earlier, and North Korea has stolen roughly $6 to 8 billion over about six years.
- **[02:15]** Beacon Network is a shared alert system among crypto exchanges, companies, and law enforcement. It covers about 85% of centralized crypto volume. Investigators flag stolen funds in real time, and exchanges block those addresses.
- **[04:06]** Blocking is not the same as seizing. Exchanges and issuers need legal process such as a subpoena or seizure warrant. Seized funds often go through civil forfeiture in court, which usually requires prosecutors.
- **[05:11]** Stablecoin issuers can freeze tokens, and Tether and Circle froze about 40% of the stolen funds (about $2.4 billion) within roughly an hour. Stablecoins can be frozen or burned and reissued, but native coins like ETH and BTC cannot.
- **[07:18]** Funds spread out and get laundered through smaller over-the-counter (OTC) brokers, which convert crypto to cash. The longer the funds move, the harder they are to recover.
- **[08:25]** North Korea's goals go beyond greed. The stolen money is said to fund weapons programs and regional destabilization, which makes this a national security issue, not just a crime.
- **[10:44]** Attack signals came before the hack. Small Tornado Cash withdrawals happened about 36 hours earlier. The attack code was tested on wallets, rehearsed with test funds, and only then deployed against a Binance hot wallet (an internet-connected wallet).
- **[12:20]** TRM attributed the hack to North Korea by matching addresses to earlier hacks such as Bybit and Drift, along with the staging and rehearsal pattern. Binance has said an engineer's compromised computer may have exposed private keys, but the exact method is still unclear.
- **[14:00]** North Korea cares less about getting caught because extradition and prosecution are unlikely. Redbord argues the West needs pressure points, such as diplomatic pressure on China and Patriot Act subpoenas against Chinese banks.
- **[17:55]** North Korea often sells stolen funds to Chinese organized crime money-laundering networks, which convert them to cash for a cut.
- **[21:44]** The GENIUS Act, a US stablecoin law, codifies freeze, seize, and burn duties for stablecoin issuers. Redbord says this response is an example of the law working. He also mentions the CLARITY Act, which would certify information-sharing networks like Beacon, but its status is unclear.
- **[25:46]** It is unknown whether AI was used in this hack. North Korea has been using AI for social engineering and exploit work, and Redbord says the industry should prepare as if AI is being used.
- **[27:14]** AI could greatly lower the cost of cyberattacks. Redbord says that if AI agents can do the work of human affiliates, attack volume could rise from thousands to millions, which would be a civilization-level threat.
- **[27:47]** Security is an offense-defense contest. Defense means hardening exchanges and DeFi protocols. Offense means sanctions, indictments, and other national security tools against state hackers.

### Numbers

- **[00:32]** Bybit hack: about $1.5 billion, roughly a year before this one.
- **[00:32]** North Korea stole about $6 to 8 billion over roughly six years, before the Binance hack.
- **[01:43]** The Binance hack was about $6 billion, roughly 2x the previous largest crypto hack.
- **[02:15]** Beacon Network covers about 85% of centralized crypto volume.
- **[05:11]** Tether and Circle froze about 40% of the stolen funds, around $2.4 billion, within about an hour.
- **[08:25]** North Korea's economy is estimated at about $20 billion, so the $6 billion theft is about a third of it.
- **[10:44]** Small Tornado Cash withdrawals came at least 36 hours before the attack.
- **[27:14]** About 7,500 ransomware attacks were seen last year.

### Cards

**Q (mechanism):** Why can Tether and Circle freeze stolen funds while Bitcoin and Ether cannot be frozen this way?

**A:** Stablecoins are issued by a company that controls the token contract, so it can freeze, burn, and reissue balances. Bitcoin and Ether have no central issuer that can block a specific wallet, so recovery depends on exchanges and law enforcement getting legal orders.

**Q (mechanism):** What is the Beacon Network and how does it help recover stolen crypto?

**A:** Beacon is a shared information network among exchanges, crypto firms, private investigators, and law enforcement. Investigators flag stolen-fund addresses in real time, and exchanges freeze or block those accounts. Blocking then leads to seizure through legal process.

**Q (concept):** Why does a hack attacker often rehearse the attack before the real one?

**A:** Rehearsing tests whether the exploit works on the live system without risking the main payload. In this case, North Korea reportedly tested code on wallets and with test funds before using it on a Binance hot wallet, and small Tornado Cash withdrawals came about 36 hours earlier.

**Q (number):** Roughly how much has North Korea stolen from crypto in recent years, and how big is that compared with its economy?

**A:** About $6 to 8 billion over roughly six years before this hack, and the Binance theft alone was about $6 billion. North Korea's economy is estimated at about $20 billion, so this one theft equals roughly a third of it.

---

## analyze · sonnet-5.5 ($0.056)

**Security → Crypto exchange hacks and North Korea** · tags: Binance hack, North Korea, Lazarus Group, TRM Labs, Beacon Network, stablecoin freezes, blockchain forensics, GENIUS Act

**Concepts:** Beacon Network, stablecoin freeze and burn, permissionless assets, hot wallet, social engineering, OTC brokers, off-ramping, civil forfeiture, Tornado Cash, attack staging and rehearsal, cyber letters of marque, GENIUS Act, agentic AI threats

### Gist

TRM Labs' Ari Redbord describes the first hours after a $6 billion Binance hack that investigators attribute to North Korea. Tether and Circle froze about 40% of the stolen money within an hour, which he calls the real story. The rest, in ETH and BTC, is much harder to claw back, and he argues for offensive tools against North Korea and for better cybersecurity.

### Key ideas

- **[0:32]** Hacks keep getting bigger as attackers get more skilled, more money sits in crypto, and AI speeds up their operations. Bybit's $1.5B hack once seemed crazy. Then a $6B one happened.
- **[2:15]** TRM ran a Slack 'war room' and used its Beacon Network. Beacon is an information-sharing group of exchanges, payment firms and law enforcement who alert each other to stolen funds in real time.
- **[4:06]** How Beacon works: investigators (law enforcement, private sleuths like ZachXBT) flag addresses holding illicit funds. Exchanges then block those addresses and work with law enforcement to seize the money.
- **[6:47]** Stablecoin issuers can freeze (or 'burn' and reissue) tokens, pulling them out of a thief's wallet. Permissionless assets like ETH and BTC have no such switch, so recovery depends on catching the thieves when they try to cash out.
- **[5:42]** Laundering gets harder as funds spread out and move through small OTC brokers (over-the-counter dealers who convert crypto to cash). It is hard but not impossible, since cash-out points can still be blocked.
- **[9:00]** Tech and community can only go so far. Seizing funds needs legal process: subpoenas, search or seizure warrants, and civil forfeiture in court. Private sleuths can trace funds but can't serve a subpoena on an exchange.
- **[10:44]** Binance says an engineer's compromised laptop exposed private keys. Redbord says this matches what he saw on-chain. He suggests social engineering (tricking people into giving access) may be the real story, as in other recent hacks.
- **[11:16]** Attribution clues: small Tornado Cash withdrawals at least 36 hours before the attack, and attack code tested on two wallets and rehearsed on a third before going live on Binance's hot wallet (an internet-connected wallet). This staging pattern is a North Korean signature, along with address links to the Bybit and Drift hacks.
- **[14:00]** North Korea cares less about getting caught because there is no extradition or prosecution. It steals as much as it can, as fast as it can, to fund weapons. Redbord says we must 'make them care more'.
- **[15:02]** Proposed levers: offensive cyber operations, cyber 'letters of marque' (licensing private actors to go after cyber criminals), sanctions, indictments, Patriot Act subpoenas on Chinese banks, and diplomatic pressure on China. North Korea hands stolen funds to Chinese organized-crime laundering networks.
- **[21:44]** Redbord argues the response shows the GENIUS Act (US stablecoin law) working. It requires issuers to be able to freeze, seize and burn tokens used for crime. The CLARITY Act would also codify the Beacon-style networks.
- **[24:53]** AI link is unconfirmed here. North Korea already uses AI for social engineering and exploit work. Redbord's worst fear is 'agentic' ransomware affiliates scaling attacks from thousands to millions.

### Numbers

- **[4:38]** The hack was about $6B, the largest ever by a wide margin. The heist in the Netflix documentary was about $70M.
- **[4:38]** Tether and Circle froze about 40% of the stolen funds (~$2.4B) within about an hour.
- **[0:32]** North Korea stole roughly $6-8B over the last six years, then about $6B in this one hack. Bybit was $1.5B.
- **[2:15]** Beacon Network covers about 85% of centralized crypto volume and about 100 law enforcement agencies.
- **[8:25]** North Korea's economy is estimated at ~$20B, so $6B is about a third of it.
- **[7:48]** Even with the frozen funds out of play, this is still the largest hack ever by about 2x.
- **[11:16]** Small Tornado Cash withdrawals appeared at least 36 hours before the attack.
- **[27:14]** About 7,500 ransomware attacks occurred last year. Redbord fears agentic AI could push that to 75,000 or 7.5 million.

### Cards

**Q (mechanism):** Why can stolen stablecoins be recovered much more easily than stolen ETH or BTC?

**A:** Stablecoin issuers like Tether and Circle control their tokens' contracts. They can freeze or burn tokens in a thief's wallet and reissue them elsewhere. ETH and BTC are permissionless, so no one can freeze them, and recovery depends on blocking cash-out points and seizing funds through legal process.

**Q (concept):** What is the Beacon Network and how does it help during a hack?

**A:** It is an information-sharing network of exchanges, payment firms and law enforcement. Investigators flag addresses holding stolen funds in real time, and members block them and coordinate seizures. It lets the ecosystem act in hours rather than days.

**Q (mechanism):** What on-chain signs pointed investigators to North Korea in the Binance hack, and why does North Korea behave this way?

**A:** They saw small Tornado Cash withdrawals about 36 hours earlier, attack code tested on test wallets and rehearsed before use on the live hot wallet, and address links to earlier hacks like Bybit and Drift. North Korea takes big risks because it faces no extradition or prosecution and wants as much money as possible for weapons programs.

**Q (concept):** Why does legal process still matter even when tracing tools and community networks are strong?

**A:** Exchanges and issuers generally need subpoenas, search or seizure warrants and court forfeiture to hand over or take funds and records. Private tracers like ZachXBT can follow money but can't compel an exchange, so prosecutors and law enforcement are still essential.

**Q (number):** Roughly how big was the hack, how much was frozen quickly, and why is the scale a national-security issue?

**A:** About $6B was stolen, and about 40% (~$2.4B) was frozen within an hour. North Korea's economy is only ~$20B, so $6B is about a third of it, which can bankroll weapons programs and destabilize the region.

---

## primer · sonnet-5.5 ($0.061)

# Primer: Inside the $6 Billion Binance Hack

This episode is a live-ish debrief on a huge exchange theft, taken from someone who spent the night tracking it. The hosts assume you know how exchanges hold money, why some crypto can be frozen and some can't, and who the usual players are. Here's that background.

## The basics: where exchange money lives

**Binance** is the world's largest crypto exchange. It is a *centralized exchange*: a company that holds customers' crypto for them, much like a bank holds deposits.

Exchanges keep coins in **wallets**. A wallet is controlled by a **private key**, a long secret code. Whoever has the key can move the money, and there's no "forgot password" button.

- **Hot wallets** are connected to the internet so the exchange can process withdrawals quickly. They're convenient and more exposed.
- **Cold wallets** are kept offline. They're safer but slower.

Big thefts from exchanges usually come from stealing keys or tricking staff, not from "breaking" the blockchain. That's why you'll hear the term **social engineering**: manipulating a person (fake job offers, phishing, malware-laden files) to get access to their computer or credentials.

## Why freezing some crypto is possible and some isn't

This is the heart of the episode.

**Stablecoins** are tokens pegged to a currency, usually the US dollar. The two giants are **Tether (USDT)** and **Circle (USDC)**. Each is issued by a company, and that company keeps control over the token's code. They can:

- **Freeze** (blacklist) an address so the tokens in it can't move.
- **Burn** the frozen tokens, meaning destroy them, and then **reissue** the same amount to the rightful owner or to authorities.

**Bitcoin and Ether** have no issuer and no off switch. Once they're in a thief's wallet, no company can lock them. That's what "permissionless" and "immutable" mean in the hosts' conversation. Recovery depends on catching the thief when they try to cash out.

## How stolen crypto gets turned into cash

Thieves need to launder funds. Common steps:

- **Spreading the money** across many fresh wallets, so it's hard to follow.
- **Mixers** like **Tornado Cash**, a service that pools deposits and pays them out so the trail is broken. The US Treasury sanctioned it in 2022 and lifted that in 2025. Hackers also use small mixer withdrawals to fund new wallets with the fee money (called **gas**) they need to operate.
- **Swapping** into assets that can't be frozen.
- **OTC brokers.** "Over the counter" brokers trade large amounts privately, outside public exchanges. Some are legitimate; some knowingly launder.
- **Off-ramping**: converting crypto into regular cash (an "off-ramp") through exchanges or brokers. This is the choke point, because it's where real-world institutions and legal pressure come in.

## Who tracks the money

**Blockchain intelligence firms** such as **TRM Labs** (the guest's employer), Chainalysis, and Elliptic analyze public blockchains. Every transaction is visible, so they label addresses ("this belongs to Exchange X," "this is linked to a past hack") and follow funds as they move.

**ZachXBT** is a well-known independent on-chain investigator who publicly flags stolen funds, often within minutes.

**Beacon Network** is TRM's information-sharing system. Investigators flag addresses, and exchanges, stablecoin issuers, and law enforcement get alerts so they can block deposits. The guest explains it, but the key idea is that **speed matters**. The faster an address is flagged, the less chance the thief has to cash out.

Even when funds are traced, taking them requires **legal process**: subpoenas, search or seizure warrants, and often a **civil forfeiture** case (a court proceeding to claim stolen property).

## North Korea and the Lazarus Group

**Lazarus Group** is the name for hacking teams tied to North Korea's government. Crypto theft has become a major revenue source for the regime, which is under heavy international sanctions. US officials and UN investigators say the money helps fund weapons programs.

Key reference points:

- **Bybit hack (Feb 2025):** about $1.5 billion in Ether stolen from another exchange. It was the record before this episode's event, and the FBI attributed it to North Korea.
- The guest says North Korea has stolen "six, seven, eight billion" over about six years. That's rough, but it gives the scale.
- Investigators talk about North Korean "signatures": recurring habits in how funds are staged, moved, and laundered, like a painter's style. They also talk about attribution "confidence," because blockchain evidence is circumstantial.
- There's no extradition and almost no chance of arrests, which is why the guest keeps asking what *else* pressure can be applied. The suggestions mentioned include pressing China (which hosts many laundering networks) and "offensive cyber" operations.

## The Bitfinex comparison

The guest compares this event to the **2016 Bitfinex hack**, when about 120,000 Bitcoin were stolen. Years later, US authorities arrested a couple, **Ilya Lichtenstein and Heather Morgan**. Morgan was a rapper and self-styled entrepreneur known online as "Razzlekhan" (the guest says "Rosal Khan"). Authorities recovered billions in Bitcoin, largely because the thieves kept the coins sitting still. That's the "greed" model of hacker, as opposed to a state actor.

## Legal and policy terms in the background

- **GENIUS Act:** a US law passed in 2025 setting rules for stablecoin issuers, including the ability to freeze and seize tokens when required.
- **CLARITY Act:** a broader bill to define how crypto markets are regulated. The guest implies it has stalled in Congress.
- **Patriot Act subpoena:** a US tool that lets authorities demand records from foreign banks that deal with US banks. The guest cites one used in a North Korea laundering case involving a Chinese bank.
- **Letters of marque:** an old concept where governments authorized private ships to attack enemy vessels. The guest's idea is a modern version, where private cyber firms are authorized to go after hackers.

## Technical and industry names you'll hear

- **EIP-7702:** an Ethereum upgrade from 2025. It lets ordinary wallets temporarily behave like programmable "smart contract" wallets. Some people wondered whether it played a role in the attack. The guest declines to speculate.
- **Drift and Kelp:** recent hacks of crypto protocols the guest uses as reference points. Details aren't explained, so treat them as recent examples of social engineering and key theft.
- **DeFi:** decentralized finance, meaning financial apps that run on blockchains instead of through a company.
- **Coinbase:** Binance's biggest US rival. The guest finds it notable when competitors cooperate.
- **Other names:** Nick Carlson is a TRM investigator and former FBI analyst. Ripple and World Liberty are other crypto firms that helped in some way.

## Context for the date

The recording is close to the anniversary of **FTX's collapse** (November 2022). The host brings it up as a reminder of how one big event can trigger a regulatory backlash. FTX was fraud by insiders; a hack is a different kind of failure.

## What to listen for

- How response speed changes what can be recovered.
- The split between assets that can be frozen and assets that can't.
- Why the identity of the attacker (greedy criminal vs. state) changes the whole problem.
- What the guest thinks should happen next: tighter security, government action, and AI-driven risks.

---

## primer · opus-5.5 ($0.122)

# Primer: Crypto Hacks, Frozen Stablecoins, and North Korea's Crypto Heists

This episode drops you into the first chaotic day after a massive theft from Binance. The guest is Ari Redbord, a former U.S. federal prosecutor and Treasury official who now works at TRM Labs. He talks fast and assumes you already know the players, the plumbing, and the recent history. Here's that background.

---

## Binance and centralized exchanges

**Binance** is the world's largest crypto exchange by trading volume. It's a company where people buy, sell, and store crypto. It was founded in 2017 by Changpeng Zhao ("CZ"). In 2023 it pleaded guilty in the U.S. to anti-money-laundering violations and paid about $4.3 billion in penalties.

It's a **centralized exchange**: one company holds customers' coins for them. Other big ones you'll hear named are **Coinbase** (its main U.S. rival), **Kraken**, and **OKX**. When people say "the exchange community," they mean these firms.

## Private keys and hot wallets

- **Wallet / address:** an account on a blockchain, like an account number.
- **Private key:** the secret password that lets you move funds out of an address. Whoever has the key controls the money. There's no "forgot password" button.
- **Hot wallet:** a wallet whose keys sit on internet-connected systems so the exchange can process withdrawals quickly. A **cold wallet** keeps keys offline and is much safer, but slower to use.

Most big exchange hacks come down to one thing: an attacker gets control of keys, or of the systems that approve transactions.

**Social engineering** means tricking people rather than breaking code. Examples include a fake job offer, a booby-trapped file, or a convincing message that gets an employee to compromise their own laptop.

**EIP-7702** is an Ethereum upgrade from 2025. It lets ordinary wallets temporarily run custom code, like a smart contract (a program that lives on the blockchain). It adds flexibility, but it also gives attackers new tricks. The host mentions it as part of the online chatter about how the hack worked.

## Not all crypto can be frozen

This distinction matters more than anything else in the episode.

**Bitcoin and Ether** are **permissionless** and **immutable**. Permissionless means no company sits in the middle. Immutable means a confirmed transaction can't be reversed. Once stolen coins move, nobody can press "undo."

**Stablecoins** are tokens designed to always be worth $1, backed by dollars and Treasury bills held by a company. The two giants:

- **Tether (USDT)**, the largest, with well over $100 billion in circulation.
- **Circle (USDC)**, the second largest, U.S.-based and heavily regulated.

Because a company issues them, the issuer controls the token's code. It can **freeze** an address so the tokens can't move. It can also **burn** the tokens (destroy them) and **reissue** fresh ones to the rightful owner. Bitcoin and Ether have no equivalent. Crypto purists dislike this power, but it's a huge weapon against thieves.

## Following the money on-chain

Every blockchain transaction is public. You can see coins move from address to address, but not who owns each address. **Blockchain analytics firms** fill that gap. They label addresses ("this belongs to Exchange X," "this was used in Hack Y") and trace funds as they hop around. The big names are TRM Labs (Redbord's firm) and Chainalysis.

A few terms come up:

- **ZachXBT** is a famous independent, pseudonymous on-chain detective.
- **The Beacon Network** is TRM's alert system. Investigators flag stolen-fund addresses, and exchanges and police get warned in real time so they can block deposits.
- **"Off-ramp"** means converting crypto into ordinary cash. That step is the thief's weak point, because cash usually has to touch some business that knows its customers.
- **OTC brokers** ("over-the-counter") are private dealers who trade large amounts of crypto for cash outside public exchanges. Shady ones are the classic laundering exit.
- **Tornado Cash** is a "mixer." Users deposit crypto into a shared pool and withdraw it to a fresh address, breaking the visible trail. The U.S. sanctioned it in 2022, and the sanctions were later lifted after court fights. Small Tornado withdrawals are often how attackers get untraceable "gas" money, meaning the tiny fees needed to send transactions.

## The legal side

Tracing isn't the same as getting money back. To force a company to hand over records or funds, you need legal process:

- **Subpoena:** a court-backed order to produce records.
- **Seizure warrant:** an order to take specific property.
- **Civil forfeiture:** a court case to formally take ownership of property tied to a crime, even if no one is convicted.

Private investigators can't issue any of these. That's why the FBI and the Department of Justice (DOJ) matter.

Redbord also mentions two more aggressive tools:

- **Patriot Act subpoena:** a special U.S. power to demand records from foreign banks that have U.S. correspondent accounts.
- **Letters of marque:** an old idea in which governments licensed private ships to attack enemies. Some now propose licensing private hackers against hostile states.

## North Korea and the Lazarus Group

North Korea is heavily sanctioned and cut off from normal finance. For years it has funded itself partly by stealing crypto. Its state hacking units are often lumped together as the **Lazarus Group**.

Rough history:

- **2022, Ronin Bridge** (used by the game Axie Infinity): about $600 million stolen.
- **February 2025, Bybit** (a large exchange in Dubai): about **$1.5 billion** in Ether stolen in one go. It was the biggest crypto theft ever at the time. Attackers compromised a developer machine at a wallet-software provider. The FBI publicly blamed North Korea within days.
- Total crypto stolen by North Korea is estimated in the **billions** over the past several years. Its whole economy is only roughly **$20–30 billion** a year.

U.S. officials say this money feeds the country's weapons programs. That's why these thefts are treated as a national-security problem, not just crime.

Investigators say North Korea leaves recognizable "fingerprints," such as particular preparation habits and reused infrastructure. It also tends to hand stolen funds to **Chinese money-laundering networks** that use OTC brokers to cash out. Those same networks serve drug cartels and **"pig butchering"** scams, where fraudsters build fake relationships online and then drain victims' savings.

## Other hacks and history referenced

- **Bitfinex hack (2016):** about 120,000 bitcoin stolen, worth roughly $70 million then. In 2022 the U.S. recovered most of it, worth around $3.6 billion by then, from a New York couple, Ilya Lichtenstein and Heather Morgan. Netflix made a documentary about it. Redbord appears in it and refers to it in passing.
- **Drift and Kelp** are names of crypto projects hit by earlier attacks that the guest uses as recent comparisons.
- **DeFi** ("decentralized finance") means financial apps that run as code on blockchains with no company in charge. They are frequent hacking targets. The **DeFi Education Fund** is a policy advocacy group for that sector.
- **FTX** was a major exchange that collapsed in November 2022 amid fraud. Its founder, Sam Bankman-Fried, was convicted. It's crypto's shorthand for a catastrophic, reputation-damaging event.

## U.S. crypto laws

- **GENIUS Act (2025):** the first U.S. federal law regulating stablecoins. Among other things, it requires issuers to be able to freeze and seize tokens tied to crime.
- **CLARITY Act:** a broader bill to set rules for crypto markets, including which regulator oversees what. Its passage has been uncertain, which is why the guest jokes "rest in peace."

## AI and ransomware

**Ransomware** is malware that locks up an organization's systems, often hospitals or companies, until a ransom is paid in crypto. Ransomware gangs use **"affiliates,"** freelance hackers who carry out attacks for a cut.

The fear the guest raises is about **"agentic" AI**, meaning AI systems that can take actions on their own. They could replace those human affiliates and multiply attacks. North Korea has already been documented using AI tools for fake job applications and phishing.

---

With these pieces, you'll be able to follow the episode. Listen for three questions: which stolen coins can be frozen and which can't, who has the legal power to act, and why a hack tied to a nation-state plays out differently from an ordinary crime.
