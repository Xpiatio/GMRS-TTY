"""Colloquial nickname → legal first-name lookups.

Used by FCC name-matching so a contact entered as "Dick" still verifies
against an FCC license held under "Richard". The existing prefix rule in
``fcc.crossref.name_matches`` already covers diminutives that ARE prefixes
of their canonical ("Tom"→"Thomas", "Ben"→"Benjamin", "Tim"→"Timothy"),
so this table only carries the non-prefix forms — names where there is no
shared head between the nickname and the canonical.

Mapping is one-to-many because a single nickname can resolve to multiple
canonicals ("Sandy" → Alexander or Sandra; "Pat" → Patrick or Patricia).
The verification path treats any candidate canonical as a match — false
positives at the gender level are tolerable since they only auto-verify
a contact that the operator can still correct in the Contacts editor.

This is a starter set of common American-English nicknames. Adding more
is a one-line edit; please keep the keys lowercase and the values as
lowercase canonical-form sets so the lookup stays case-insensitive.
"""

# Canonical mapping is intentionally one-way (nickname → canonicals).
# canonical_forms() handles both directions: a canonical token isn't in
# the table itself, so it falls through to returning just {token}; a
# nickname token returns its canonicals plus itself, which lets the
# matcher cross-check against either side of the conversation.
NICKNAMES: dict[str, frozenset[str]] = {
    # William family
    "bill": frozenset({"william"}),
    "billy": frozenset({"william"}),
    "will": frozenset({"william"}),
    "willy": frozenset({"william"}),
    "liam": frozenset({"william"}),
    # Robert
    "bob": frozenset({"robert"}),
    "bobby": frozenset({"robert"}),
    "rob": frozenset({"robert"}),
    "robby": frozenset({"robert"}),
    # Richard
    "dick": frozenset({"richard"}),
    "rick": frozenset({"richard"}),
    "ricky": frozenset({"richard"}),
    # James
    "jim": frozenset({"james"}),
    "jimmy": frozenset({"james"}),
    "jamie": frozenset({"james"}),
    # John
    "jack": frozenset({"john"}),
    "johnny": frozenset({"john"}),
    # Henry
    "hank": frozenset({"henry"}),
    "harry": frozenset({"henry", "harold"}),
    # Charles
    "chuck": frozenset({"charles"}),
    "chuckie": frozenset({"charles"}),
    "charlie": frozenset({"charles"}),
    # Michael
    "mike": frozenset({"michael"}),
    "mikey": frozenset({"michael"}),
    "mickey": frozenset({"michael"}),
    # Edward / Edmund
    "ed": frozenset({"edward", "edmund"}),
    "eddie": frozenset({"edward", "edmund"}),
    "ted": frozenset({"edward", "theodore"}),
    "teddy": frozenset({"edward", "theodore"}),
    "ned": frozenset({"edward", "edmund"}),
    # Theodore
    "theo": frozenset({"theodore"}),
    # Anthony
    "tony": frozenset({"anthony"}),
    # Arthur
    "art": frozenset({"arthur"}),
    "artie": frozenset({"arthur"}),
    # Lawrence / Laurence
    "larry": frozenset({"lawrence", "laurence"}),
    # Frederick / Alfred
    "fred": frozenset({"frederick", "alfred"}),
    "freddy": frozenset({"frederick", "alfred"}),
    # Francis / Franklin
    "frank": frozenset({"francis", "franklin"}),
    "frankie": frozenset({"francis", "franklin"}),
    # Nicholas
    "nick": frozenset({"nicholas"}),
    "nicky": frozenset({"nicholas"}),
    # Joseph
    "joe": frozenset({"joseph"}),
    "joey": frozenset({"joseph"}),
    # Daniel
    "dan": frozenset({"daniel"}),
    "danny": frozenset({"daniel"}),
    # Ronald
    "ron": frozenset({"ronald"}),
    "ronnie": frozenset({"ronald"}),
    # Stephen / Steven
    "steve": frozenset({"steven", "stephen"}),
    "stevie": frozenset({"steven", "stephen"}),
    # Christopher (also Christina / Christine — ambiguous but acceptable)
    "chris": frozenset({"christopher", "christina", "christine"}),
    # Gerald / Jerome
    "jerry": frozenset({"gerald", "jerome"}),
    # Alexander / Sandra
    "sandy": frozenset({"alexander", "sandra"}),
    "alex": frozenset({"alexander", "alexandra"}),
    "al": frozenset({"albert", "alfred", "alan", "alexander"}),
    # Vincent
    "vinny": frozenset({"vincent"}),
    "vince": frozenset({"vincent"}),
    # Patrick / Patricia
    "pat": frozenset({"patrick", "patricia"}),
    "patty": frozenset({"patrick", "patricia"}),
    "patsy": frozenset({"patrick", "patricia"}),

    # Female names — non-prefix nicknames where the existing prefix rule
    # in name_matches doesn't already cover the diminutive.
    "peggy": frozenset({"margaret"}),
    "meg": frozenset({"margaret"}),
    "maggie": frozenset({"margaret"}),
    "molly": frozenset({"mary"}),
    "polly": frozenset({"mary"}),
    "sally": frozenset({"sarah"}),
    "betty": frozenset({"elizabeth"}),
    "beth": frozenset({"elizabeth"}),
    "liz": frozenset({"elizabeth"}),
    "liza": frozenset({"elizabeth"}),
    "lisa": frozenset({"elizabeth"}),
    "betsy": frozenset({"elizabeth"}),
    "kate": frozenset({"katherine", "kathryn", "katelyn"}),
    "katie": frozenset({"katherine", "kathryn", "katelyn"}),
    "kat": frozenset({"katherine", "kathryn"}),
    "kathy": frozenset({"katherine", "kathryn"}),
    "ginny": frozenset({"virginia"}),
    "nancy": frozenset({"ann", "agnes"}),
    "sue": frozenset({"susan", "susanne"}),
    "suzie": frozenset({"susan", "susanne"}),
    "becky": frozenset({"rebecca"}),
    "penny": frozenset({"penelope"}),
    "terri": frozenset({"theresa", "teresa"}),
    "terry": frozenset({"theresa", "terrence"}),
    "trish": frozenset({"patricia"}),
}


def canonical_forms(token: str) -> frozenset[str]:
    """Return ``token`` plus any canonical legal-name forms it expands to.

    Tokens not in the table return ``{token}`` so a canonical first name
    (e.g. "Richard") and a non-nickname token (e.g. a last name like
    "Smith") behave identically — the caller can match across the union
    without special-casing the absent-from-table case.

    The returned set always contains the original token (lowercased) so a
    canonical-vs-nickname pair like "Richard" / "Dick" succeeds via set
    intersection from either direction.
    """
    lowered = (token or "").lower()
    if not lowered:
        return frozenset()
    canonicals = NICKNAMES.get(lowered)
    if canonicals is None:
        return frozenset({lowered})
    return canonicals | {lowered}
