# 180: Conti

Darknet Diaries (Jack Rhysider): true stories of hacking and cybercrime · 0.98 h of audio

---

## analyze · haiku-5.5 ($0.003)

**Security → Conti ransomware gang** · tags: ransomware, cybercrime, Conti, TrickBot, double extortion, threat intelligence, Darknet Diaries

**Concepts:** ransomware, ransomware-as-a-service, affiliate model, double extortion, money laundering, decryption key, phishing, chat log leak, threat intelligence, sanctions, nesting-doll gang splintering

### Gist

Conti was one of the most successful ransomware gangs, growing out of earlier groups (Dyre, TrickBot) run by a figure known as Bentley and later Stern. It hit Ireland's health system and many others, then collapsed in 2022 after a Ukrainian insider leaked its internal chat logs, which exposed its structure, members, and infighting. The episode shows how a criminal group can split apart into many smaller gangs that keep causing harm.

### Key ideas

- **[0:00]** Ransomware is malware that locks a victim's files and demands payment, often threatening to publish stolen data if the victim refuses.
- **[2:04]** Russian cybercrime gangs are hard for Western police to arrest, since they usually stay inside Russia. Gangs often split and reform, like nesting dolls.
- **[3:35]** Criminal hackers need to launder money. Bentley used profits from the Dyre gang to fund a film company, the 25th Floor Film Company, to make the money look legitimate.
- **[7:39]** The Dyre gang became TrickBot, and TrickBot's ransomware strain was called Conti. The group took Conti's name from the malware it used.
- **[8:11]** Conti recruited programmers through job sites and used fake names. Max, a Latvian programmer, was hired without knowing at first that she was building ransomware.
- **[13:52]** Max was arrested in Miami after US authorities tracked her down, showing that police can still reach gang members who travel outside Russia.
- **[14:23]** Conti ran as ransomware-as-a-service. Affiliates infected networks, and Conti handled negotiation and decryption keys, then paid the affiliate a cut.
- **[15:27]** Conti hit Ireland's health network in 2021 after a phishing email with a malicious Excel file. Systems were encrypted, and hospitals went back to pen and paper.
- **[18:59]** Conti demanded $20 million and claimed to have stolen over 700 GB of data. Ireland refused to pay, and the gang later handed over the decryption key.
- **[23:08]** Double-extortion ransomware steals data before encrypting it. Backups no longer fully protect victims, because the attacker can still threaten to leak the data.
- **[24:08]** Graff, a jewelry company, paid $7.5 million in Bitcoin after Conti leaked some client data. Conti then apologized to the Saudi royal family after a leak exposed their purchases, likely under pressure.
- **[32:29]** Stern was the leader of Conti, later identified as Vitaly Kovalev. He ran TrickBot like a company, with departments and budgets.
- **[34:36]** Conti members argued about attacking hospitals. Some insisted on a rule against targeting healthcare, while others ignored it.
- **[36:38]** By 2022, Conti had hundreds of members and affiliates, and leadership was weak. Stern disappeared from chats in January 2022, and infighting grew.
- **[38:39]** Russia's invasion of Ukraine split Conti. Conti publicly backed Russia, and a Ukrainian insider leaked its chat logs to Twitter as @contileaks in early 2022.
- **[43:51]** The leaks exposed planning, member identities, crypto wallets, and internal structure. They reportedly caused the group to fracture into many smaller gangs.
- **[46:58]** Machine translation struggled with the leaked Russian slang. Terms like cue ball meant Bitcoin, and toad meant the Jabber chat software, so researchers had to read messages by hand.
- **[49:32]** After the leaks, Conti affiliates hit the government of Costa Rica, causing big disruption. Ransomware gangs and affiliates may have acted without full core Conti control.
- **[55:09]** Stern (Vitaly Kovalev) was sanctioned by the EU, UK, and US. He allegedly earned over $300 million in ransomware payments, and some believe he could be a cybercrime billionaire.

### Numbers

- **[15:27]** Over 70,000 computers were infected at about 4,000 locations, including more than 40 hospitals in Ireland's network.
- **[18:59]** The Irish hospital attack came with a $20 million ransom demand and over 700 GB of stolen data.
- **[24:08]** Graff paid $7.5 million in Bitcoin, and about 70,000 Graff documents were released.
- **[28:20]** In 2021 alone, Conti collected over $180 million from ransomware operations.
- **[33:35]** Alex Holden's team reviewed hundreds of thousands of TrickBot and Conti messages.
- **[55:09]** Stern allegedly took in more than $300 million in ransomware payments, which was only his personal cut.

### Cards

**Q (concept):** What is ransomware, and what is double extortion?

**A:** Ransomware is malware that encrypts a victim's files so they can't use them, then demands payment for a decryption key. Double extortion adds a second threat: the attackers steal the data first and threaten to publish it, so having backups is not enough to make the victim safe.

**Q (mechanism):** Why did Conti use a ransomware-as-a-service model with affiliates?

**A:** Affiliates did the work of breaking into networks. Conti supplied the ransomware, negotiation, and decryption services, then paid affiliates a cut. This let the core group scale to hundreds of members while reducing its own exposure to the break-in work.

**Q (mechanism):** Why do criminal groups like Conti often fall apart?

**A:** Leaks, arrests, sanctions, and internal conflict expose members and make trust impossible. Members who are exposed or disagree often leave to join other gangs, so the group splinters into smaller crews that keep attacking.

**Q (number):** Roughly how big was the Ireland health system attack?

**A:** More than 70,000 computers at about 4,000 locations were infected, including over 40 hospitals. Conti demanded $20 million and claimed to have stolen over 700 GB of data. Ireland refused to pay.

**Q (concept):** Why did the @contileaks breach matter?

**A:** A Ukrainian insider leaked tens of thousands of Conti chat logs after the group backed Russia's invasion of Ukraine. The logs exposed members, money flows, and plans, which researchers used to unmask people and disrupt the gang.

---

## analyze · sonnet-5.5 ($0.069)

**Security → Ransomware gangs** · tags: Conti, ransomware, TrickBot, cybercrime, Russia, data leaks, Ukraine war, extortion

**Concepts:** Ransomware, Ransomware-as-a-service, Affiliates, Double-dip (double extortion) ransomware, Money laundering through front companies, Operational security (OPSEC), Phishing, Threat intelligence and infiltration, Sanctions as a response to cybercrime, Gang splintering

### Gist

Conti was one of the most successful ransomware gangs ever. It grew out of earlier Russian crime groups (Dyre, then TrickBot) and ran like a real company. It collapsed in early 2022 when a Ukrainian insider leaked its internal chats after Conti backed Russia's invasion of Ukraine. The gang splintered into other groups, and its members kept attacking.

### Key ideas

- **[3:05]** Conti's lineage: boss 'Bentley' ran the Dyre gang and laundered money through a Moscow film company. After a 2015 Russian raid, Dyre became TrickBot, which became Conti. Bentley later went by 'Stern'. Like nesting dolls, each gang forms inside the shell of the last.
- **[8:11]** Conti recruited like a startup, using job sites and coding tests. Recruits such as Latvian programmer 'Max' were often not told at first that it was crime. Max was later arrested in Miami after US authorities arranged her flight home.
- **[14:23]** Conti worked as ransomware-as-a-service. Affiliates break into networks using Conti's malware, Conti handles negotiation and decryption keys, and the affiliate gets a cut.
- **[14:57]** The 2021 attack on Ireland's health service put Conti on the world stage. It began with a phishing email carrying a malicious Excel file. The attackers lurked for weeks, then encrypted everything. Ireland refused to pay and rebuilt on its own, and Conti eventually handed over the decryption key anyway.
- **[23:08]** 'Double-dip' (double extortion) ransomware: steal data before encrypting it. Backups no longer solve the problem, because the gang can threaten to leak the stolen data. Graff, a UK jeweller, paid after Conti leaked client data.
- **[25:13]** Conti leaked data naming the Saudi royal family, then publicly apologized and pulled it. The likely reason is that powerful people leaned on them. Rare fear from a ransomware gang.
- **[29:53]** Researcher Alex Holden's firm, Hold Security, infiltrated TrickBot by posing as black hats and building trust. Weak operational security helped. One member gave his girlfriend access, and the Jabber server password was '123456' plus a letter.
- **[33:35]** The chats showed Conti was run like a corporation, with departments, offices, budgets and payroll. Internal fights broke out over ethics, such as hitting hospitals, and over an absent boss.
- **[37:39]** Russia's invasion of Ukraine split Conti, which had Ukrainian members. Conti publicly pledged support for the Russian government. A Ukrainian insider then started the @contileaks account and dumped tens of thousands of internal messages.
- **[46:58]** The leak was a goldmine for researchers but hard to read. Messages were in Russian slang, and machine translation produced errors: 'cue balls' meant Bitcoin and 'toad' meant Jabber. Holden argues the leak backfired, because the gang scattered into other groups and became harder to track.
- **[49:32]** After the leak Conti apparently disbanded, but a parting attack on Costa Rica's government forced a state of emergency. It may have been done by affiliates or ex-members using leftover Conti tools, and other gangs piled on.
- **[54:38]** Stern was identified as Vitaly Kovalev and sanctioned by the EU, UK and US. He allegedly made over $300 million personally. Laundering Bitcoin is hard, and Conti-linked crypto operations were reportedly found in Dubai.

### Numbers

- **[15:58]** Ireland attack: ~70,000 computers at ~4,000 locations, with over 40 hospitals affected.
- **[18:29]** Conti demanded $20 million from Ireland and claimed to have stolen over 700 GB of data. Ireland did not pay.
- **[20:01]** Decrypting Ireland's systems without the key was estimated to take one to two years.
- **[24:08]** Graff paid $7.5 million in Bitcoin. Conti had leaked about 70,000 documents.
- **[28:20]** Conti collected over $180 million in 2021.
- **[34:06]** Conti reportedly budgeted $25 million for infrastructure in the first eight months of 2021.
- **[46:58]** Roughly 70,000 messages were leaked in the first dump, and a larger second dump followed. Geoff White read about 47,000.
- **[55:09]** Kovalev (Stern) allegedly took over $300 million in ransom payments personally.

### Cards

**Q (concept):** What is double-dip (double extortion) ransomware, and why did gangs adopt it?

**A:** The attacker steals sensitive data first, then encrypts the systems. Victims with good backups can restore without paying, so the gang threatens to leak the stolen data instead. This keeps the pressure on even when backups work.

**Q (mechanism):** How does the ransomware-as-a-service affiliate model work, and why does it make gangs hard to kill?

**A:** The core group supplies the malware and handles negotiation, payment and decryption keys. Affiliates break into victims and keep a share of the payment. Because affiliates hold the tools and can move to other gangs, taking down the core doesn't stop the attacks.

**Q (mechanism):** Why did the Conti leaks help researchers but also arguably hurt defenders?

**A:** The leaks exposed members, finances, structure and plans, which led to indictments and sanctions. But the gang then splintered into other groups, and Alex Holden argues that losing visibility into them increased the number of victims.

**Q (concept):** How did Conti's lineage show the 'nesting doll' pattern of Russian cybercrime groups?

**A:** Dyre, run by Bentley, was raided in 2015 and reformed as TrickBot. TrickBot was later absorbed by Conti, and the same boss reappeared as Stern. Core people and code carry over, so arrests or collapses lead to new groups.

**Q (number):** Roughly how big was Conti's business, and what did the Ireland health attack involve?

**A:** Conti collected over $180 million in 2021. In Ireland it demanded $20 million after hitting ~70,000 computers across 40+ hospitals, and Ireland refused to pay.

---

## primer · sonnet-5.5 ($0.079)

# Primer: Conti, Ransomware, and the Gangs Behind It

This episode tells the story of one of the most notorious ransomware gangs. The hosts assume you already know what ransomware is, how these gangs make money, and why Russian-speaking criminals are so hard to catch. This primer covers that background.

## What ransomware is

Ransomware is malicious software that **encrypts** your files. Encryption scrambles data so it's unreadable without a secret **decryption key**. The attackers hold the key and demand payment for it, usually in cryptocurrency like Bitcoin. A note appears on every screen with instructions and a deadline.

The attack is rarely instant. A typical one goes like this:

1. **Break in.** Often through **phishing**, a fake email with a booby-trapped attachment or link. Stolen passwords and exposed remote-access tools also work.
2. **Lurk and spread.** The attackers quietly explore the network for days or weeks. They hunt for the most valuable systems and for the backups.
3. **Strike.** They encrypt as many machines as possible at once, ideally when the victim is most vulnerable.

For a hospital, a school, or a factory, the pain isn't the money. It's that the computers stop working.

## Backups and "double extortion"

The classic defense is **backups**: keep a clean copy of your data, wipe the infected machines, restore, and refuse to pay. Attackers adapted. Around 2019, gangs began stealing sensitive data *before* encrypting it. Now they have two threats: "pay for the key" and "pay or we publish your files." This is called **double extortion**, and the hosts call it "double-dip."

Gangs usually run a **leak site** on the dark web, a part of the internet reachable only with special software like Tor. They post victims' names and stolen files there to pressure them.

## How the gangs are organized

Many top gangs work like a franchise, called **ransomware-as-a-service**. One team builds the malware and runs the payment and negotiation side. Outside hackers called **affiliates** do the break-ins and use the malware. When a victim pays, the money is split, with the affiliate typically keeping the larger share. This lets a gang scale up fast. It also means the core group doesn't control exactly who gets hit.

Two earlier names come up in the episode:

- **Dyre** and **TrickBot** were originally **banking trojans**, malware that steals online-banking logins. Both were built on a **botnet**, a network of infected computers controlled remotely. The host loosely calls them "ransomware gangs." TrickBot later became a delivery system for other attackers' ransomware.
- **Conti** is both the name of a ransomware program and the name of the gang that used it. That's why people say "Conti" for both. It emerged around 2020 from the TrickBot ecosystem.

## Why Russian cybercriminals are hard to catch

The episode keeps returning to this point. Many ransomware gangs operate from Russia and nearby countries. Western police can't just go arrest them. Russia generally doesn't extradite its citizens, and the unspoken understanding is that criminals are left alone as long as they don't target Russian-speaking countries.

So Western governments use other tools:

- **Indictments and arrest warrants.** These are mostly symbolic unless the suspect travels somewhere that will detain them. People have been caught this way during layovers or vacations.
- **Sanctions.** Governments publish names and freeze their access to the Western financial system.
- **Infiltration and intelligence-gathering.** Private researchers and police watch the gangs from the inside.

## Operational security and aliases

**Operational security** (opsec) means the habits criminals use to avoid being identified. Hackers in this world go by **handles** (nicknames) and chat over private servers. You'll hear names like Stern, Mingo, Target, and Dollar. Those are aliases, not real names. The episode shows how the rules (use fake identities, never reveal personal details, trust no one) often break down in practice.

Gangs also recruit like normal companies. They post job ads that don't say what the work really is, and they hire programmers, designers, and managers. Not everyone starts out knowing what they've joined.

## Chat tools and the language barrier

The gang members talk to each other through **Jabber** (a long-running open chat system, also called XMPP) and tools like **Rocket.Chat**. They write in Russian, often in hacker slang. Machine translation can mangle this. You'll hear a funny example of how a translation tool turns ordinary words into nonsense. It's a reminder that reading these chats takes real human effort.

## Laundering the money

Ransom payments in Bitcoin are traceable. Bitcoin transactions are recorded on a public ledger, and investigators can follow the money until it hits an exchange or a spending point. So criminals need to **launder** the money, which means making it look like it came from somewhere legitimate.

Common approaches:

- **Front companies**, which are real businesses that mix dirty money with legitimate revenue.
- **Crypto exchanges and mixing services** that blur the trail.
- **Moving funds** through jurisdictions with weak oversight.

The first story in the episode is an unusual example of the front-company approach.

## Healthcare and the criminals' "rules"

Many ransomware gangs claim they avoid certain targets, especially hospitals, because the human cost is so high. In practice the rule is loose. Affiliates make their own choices, and some gangs blame mistakes after the fact. During the **COVID-19 pandemic** (2020 onward), hospitals were stretched thin and often ran old systems with little security spending. That made them both a tempting and a widely condemned target.

## Researchers who watch the gangs

A few kinds of people appear in the episode:

- **Geoff White** is a London-based investigative journalist who has covered hackers for years. He hosts a BBC series called *The Conti Files*.
- **Alex Holden** is a Ukrainian-born cybersecurity researcher who runs **Hold Security** in Milwaukee. His firm does **threat intelligence**: watching criminal forums and chats to learn what attackers plan. Sometimes that means posing as a fellow criminal to earn trust. Researchers in this field are careful not to buy or sell illegal goods.

## Russia, Ukraine, and the 2022 invasion

Russia launched a full-scale invasion of Ukraine on **February 24, 2022**. This matters because the cybercrime world in this region is deeply intertwined. Russians and Ukrainians often share languages, schools, careers, and family. A gang can easily include people from both countries who've worked side by side for years.

A few terms you'll hear:

- **Kiev** is the Russian-influenced spelling of Ukraine's capital. The Ukrainian spelling, now standard in English, is **Kyiv**.
- **"Slava Ukraini"** means "Glory to Ukraine." It's a patriotic slogan.
- **Vladimir Putin** is Russia's president. **Alexei Navalny** was Russia's best-known opposition leader. He was poisoned in 2020 and later imprisoned.

## A few smaller references

- **Twitter** was the main public square for the security community in 2022. Researchers there share findings quickly and joke about them.
- **Dubai** has become a hub for crypto businesses and for Russians who relocated after 2022.
- **Nesting dolls** (matryoshka) are the host's metaphor for how gangs form, shed, and reform in layers. Keep it in mind as you listen.

## What to listen for

As you listen, pay attention to three things. First, how much these gangs resemble ordinary businesses. Second, how their security failures are often more human than technical. Third, how events outside the criminal world, such as politics, war, and powerful people, can shape what happens inside it.

---

## primer · opus-5.5 ($0.112)

# Ransomware Gangs 101: A Primer Before You Listen to "Conti"

This episode drops you into the world of Russian-speaking ransomware crime, and it moves fast. The hosts toss around terms like "affiliate," "double-dip," and "decryption key" as if you already know them. Here's the background you'll want first.

---

## What ransomware actually does

**Ransomware** is malicious software that locks up a victim's files and demands money to unlock them.

It locks them using **encryption**. That's math that scrambles data so it looks like gibberish unless you have the right digital "key." Your files are all still there. You just can't read them.

The attackers hold the **decryption key**, the only practical way to unscramble everything. Without it, recovery might mean rebuilding systems from scratch, which can take months or longer for a big organization.

After the attack, a **ransom note** pops up on screens. It explains what happened, names a price, and often shows a countdown clock. You'll hear real examples of these notes read aloud in the episode.

Ransomware isn't new. Primitive versions existed in the late 1980s. It became a huge business around 2013, once Bitcoin made it easy to collect payments from strangers across borders. By the early 2020s, victims were paying roughly **$1 billion a year** in total.

## How attackers get in

A few terms describe the break-in itself:

- **Phishing**: a fake email that tricks someone into clicking a link or opening an attachment, like a booby-trapped Excel file. It's still the most common way in.
- **Malware**: the umbrella term for any malicious software.
- **Backdoor**: a hidden way back into a system after the first break-in, so attackers can come and go.
- **Lateral movement**: spreading from the first infected computer to others on the same network. One machine becomes hundreds.

A key point: serious ransomware crews don't lock files the moment they get in. They often lurk for **days or weeks**. They map the network, find the backups, and steal data. Then they hit everything at once.

## Botnets and "loaders"

You
