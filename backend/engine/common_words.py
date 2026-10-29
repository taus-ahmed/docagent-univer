"""The closed vocabulary a generated summary may use beyond its facts
(Recheck 2 S2).

A summary's every word must be in the facts, in this list (directly or by a
plain inflection: -s, -es, -ies, -ed, -d, -ing, -ly), a number word the
number check grounds, or the month/weekday of a date the facts hold. Anything
else — "alice approved the payment." — rejects the prose for the plain facts
summary. Over-rejecting costs a plainer summary; under-rejecting shows an
invented party as fact, so the list is deliberately SMALL and leaves out
words that are as often a given name or a surname (mark, bill, frank,
grant, will, may, rose, page, …).

STOPWORDS is NLTK's English stopword list (179 words) as published, with
"will" removed for the reason above. SUMMARY holds the words a document summary
is written in. English only, as the amount-in-words parser and the number
check are.
"""

STOPWORDS = frozenset("""
i me my myself we our ours ourselves you you're you've you'll you'd your yours
yourself yourselves he him his himself she she's her hers herself it it's its
itself they them their theirs themselves what which who whom this that that'll
these those am is are was were be been being have has had having do does did
doing a an the and but if or because as until while of at by for with about
against between into through during before after above below to from up down
in out on off over under again further then once here there when where why
how all any both each few more most other some such no nor not only own same
so than too very s t can just don don't should should've now d ll m o re ve y
ain aren aren't couldn couldn't didn didn't doesn doesn't hadn hadn't hasn
hasn't haven haven't isn isn't ma mightn mightn't mustn mustn't needn needn't
shan shan't shouldn shouldn't wasn wasn't weren weren't won won't wouldn
wouldn't
""".split())

SUMMARY = frozenset("""
about across along also although among another around away back based
behind besides beyond either else enough even ever every everything given
however including instead itself last least less like likely mainly many
much must nearly neither never next nothing often otherwise overall
perhaps rather really several since still therefore though throughout
together toward towards upon whereas whether within without yet would could
might shall one ones none several various almost already always approximately
roughly about exactly only just nearly mostly largely

account accounts activity add adds added addition additional address amount
amounts annual apply applied approve approved approval available average
balance bank banking based begin beginning billed billing block business
buy buyer calculate cash category categories change changed charge charged
cheque check checking client close closed closing column columns combined
company compare compared complete completed contain contains contained cost
costs count counted credit credited creditor current customer daily date
dated day days debit debited decrease decreased deduct deducted deduction
deductions deposit deposited description detail details different direct
document documents due earn earned earning earnings employee employer end
ended ending entire entries entry equal equals estimate exceed exceeded
expense expenses expenditure extract extracted fee fees field fields figure
figures file final financial following follow fund funds general gross group
grouped hold holds held highest high higher hour hours include included
including income increase increased individual interest invoice invoiced
invoices issue issued item itemised itemized items large larger largest
late latest left less level line lines list listed low lower lowest main
major make made majority mid minimum maximum minor month monthly months
net new note noted number numbers occur occurred office open opening order
ordered original outstanding overdue paid part partial pay payable
payee payer paying payment payments payroll per period periods place placed
previous price prices principal print printed purchase purchased purchases
quantity quarterly range rate rates receipt receipts receive received
recent record recorded records reduce reduced refund refunded related remain
remaining rent rental report reported represent represents rest result
results return returned revenue review reviewed row rows run runs running
salary sale sales saving savings sell seller sent separate service services
set share show showed shown shows significant single small smaller smallest
sold source spend spending spent start started starting statement statements
status sub subtotal sum summary supplier supply table tables tax taxes term
terms time times top total totals totalled totaled transaction transactions
transfer transferred transfers type types unit units unpaid unstated
updated use used usual value values vendor week weekly withdraw withdrawal
withdrawals withdrawn worth year yearly years ytd

across appear appears approx biggest broken broadly close combined
compared concentrated consist consists covering covers cover distinct
dominate dominated dominates entire evenly fall falls handful high largest
lump notable notably observed one-off overall portion primarily primary
recurring regular remainder significant similar single smaller spread
substantial total typical various whole

dollar dollars euro euros pound pounds rupee rupees cent cents pence
currency currencies usd eur gbp inr

description no

go goes going gone went come comes came get gets got take takes took taken
give gives gave keep keeps kept bring brought buy bought spent fell fall
grew grow sent hold held made paid told
""".split())

COMMON = STOPWORDS | SUMMARY


def is_common(word: str) -> bool:
    """`word` (casefolded) is in the list directly or by a plain inflection."""
    w = word.casefold().replace("’", "'")
    if w in COMMON:
        return True
    for suf, rep in (("ies", "y"), ("ied", "y"), ("es", ""), ("s", ""), ("ed", ""),
                     ("ed", "e"), ("d", ""), ("ing", ""), ("ing", "e"), ("ly", "")):
        if w.endswith(suf) and len(w) - len(suf) >= 3 and w[: len(w) - len(suf)] + rep in COMMON:
            return True
    return False
