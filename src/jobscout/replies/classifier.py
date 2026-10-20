"""Rule-based reply categories. Stage 1: keyword and phrase patterns, no ML.

Add patterns to PATTERNS below. Each is (category, weight, regex); a message gets the summed weight of
every pattern it matches, per category, and the highest total wins. Patterns are matched case-insensitively
against the subject and the start of the cleaned body.

To swap in a trained model later, give it the same interface as RuleClassifier (predict(subject, body)
returning (category, confidence)) and assign it to MODEL; classify() keeps working unchanged.
"""
import re

CATEGORIES = ("acknowledgement", "assessment", "interview", "offer", "rejection", "other")

# (category, weight, regex). Higher weight = stronger evidence. Rejections often also thank you for
# applying, so rejection phrases weigh more than acknowledgement phrases.
PATTERNS = [
    # Acknowledgement
    ("acknowledgement", 2.0, r"thank you for (your )?(applying|application|interest)"),
    ("acknowledgement", 2.0, r"we (have|'ve) (successfully )?received your application"),
    ("acknowledgement", 2.0, r"(your )?application (has been|was) (successfully )?(received|submitted)"),
    ("acknowledgement", 1.5, r"application (received|confirmation|acknowledg(e)?ment)"),
    ("acknowledgement", 1.0, r"we will (review|be reviewing) your (application|cv|profile)"),
    ("acknowledgement", 1.0, r"only shortlisted candidates will be contacted"),
    ("acknowledgement", 1.0, r"if you (do not|don't) hear from us within"),
    # Rejection
    ("rejection", 3.0, r"regret to (inform|advise)"),
    ("rejection", 3.0, r"(have|has|had|were|was) not been successful|(was|were) not successful|not been selected"),
    ("rejection", 3.0, r"\bunsuccessful\b"),
    ("rejection", 2.5, r"(not|no longer) (be )?(moving|proceeding|progressing) (forward )?with your application"),
    ("rejection", 2.5, r"decided (not )?to (move|proceed|go) forward with other candidates"),
    ("rejection", 2.5, r"(position|role|vacancy) has (now )?been filled"),
    ("rejection", 2.0, r"will not be (taking|considering) your application"),
    ("rejection", 2.0, r"(other|more suitable) candidates (whose|who) (experience|profile)"),
    ("rejection", 1.5, r"\bunfortunately\b"),
    ("rejection", 1.0, r"wish you (every|all the) success in your (future|job search|career)"),
    ("rejection", 1.0, r"keep your (cv|details|profile) on (file|record)"),
    # Assessment
    ("assessment", 3.0, r"online assessment|assessment (link|invitation|invite)"),
    ("assessment", 3.0, r"psychometric"),
    ("assessment", 2.5, r"(cognitive|aptitude|numerical|verbal|logical|technical|coding) (assessment|test)"),
    ("assessment", 2.5, r"(hackerrank|codility|shl|talent ?q|mettl|testgorilla|pymetrics|harver)"),
    ("assessment", 2.0, r"video interview|one-way interview|hirevue|recorded interview"),
    ("assessment", 2.0, r"please complete the (attached|following|online)"),
    ("assessment", 1.5, r"complete (the|an|your) (assessment|test|questionnaire)"),
    ("assessment", 1.0, r"(assessment|test) (must|should) be completed by"),
    # Interview
    ("interview", 3.0, r"invite you (to|for) an? (interview|panel)"),
    ("interview", 3.0, r"interview (invitation|invite|schedule|confirmation)"),
    ("interview", 2.5, r"(schedule|book|arrange) (an|your|a) (interview|meeting|call)"),
    ("interview", 2.5, r"(first|second|final|panel|technical|teams|virtual|face-to-face) (round )?interview"),
    ("interview", 2.0, r"you have been shortlisted|you('ve| have) been short-listed|shortlisted for (the )?(next|an)"),
    ("interview", 1.5, r"\bshortlisted\b"),
    ("interview", 1.5, r"(available|availability) (for|to) (an? )?(interview|call|chat)"),
    ("interview", 1.0, r"\binterview\b"),
    # Offer
    ("offer", 4.0, r"offer of employment|employment offer|letter of offer|offer letter"),
    ("offer", 3.0, r"pleased to (offer|inform you that you have been (selected|successful))"),
    ("offer", 3.0, r"(congratulations|congrats).{0,60}(successful|selected|offer)"),
    ("offer", 2.0, r"(sign|accept) (and return )?the (attached )?(offer|contract)"),
    ("offer", 1.5, r"\bstart(ing)? date\b"),
    # Conditional wording that appears in acknowledgements ("if you do not hear from us within 2 weeks,
    # consider your application unsuccessful", "if shortlisted, we will invite you to an interview").
    # Negative weights cancel the rejection / interview words they contain.
    ("acknowledgement", 3.0, r"(consider|regard) your application (as )?(unsuccessful|not successful)"),
    ("rejection", -3.0, r"(consider|regard) your application (as )?(unsuccessful|not successful)"),
    ("acknowledgement", 3.0, r"(if|should) (you are |you're |you be |your application is )?(shortlisted|successful)"),
    ("interview", -4.0, r"(if|should) (you are |you're |you be |your application is )?(shortlisted|successful)"),
    ("offer", -3.0, r"(if|should) (you are |you're |you be |your application is )?(shortlisted|successful)"),
]

MIN_SCORE = 2.0  # below this the message is "other"
BODY_CHARS = 3000  # how much of the cleaned body the rules look at

_COMPILED = [(cat, w, re.compile(rx, re.I)) for cat, w, rx in PATTERNS]


class RuleClassifier:
    def predict(self, subject: str, body: str) -> tuple[str, float]:
        text = f"{subject or ''}\n{(body or '')[:BODY_CHARS]}"
        scores = {}
        for cat, weight, rx in _COMPILED:
            if rx.search(text):
                scores[cat] = scores.get(cat, 0.0) + weight
        if not scores:
            return "other", 0.1
        ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
        best, top = ranked[0]
        second = ranked[1][1] if len(ranked) > 1 else 0.0
        if top < MIN_SCORE:
            return "other", 0.2
        confidence = min(0.95, 0.45 + 0.08 * top)
        if second > 0:
            confidence *= max(0.5, 1 - second / (top * 2))  # less sure when another category is close
        return best, round(confidence, 2)


MODEL = RuleClassifier()


def classify(subject: str, body: str) -> tuple[str, float]:
    """(category, confidence 0-1) for one message. category is one of CATEGORIES."""
    return MODEL.predict(subject, body)


JOB_RELATED = re.compile(
    r"\b(application|applied|vacanc(y|ies)|recruit(ment|er|ing)|candidate|position|interview|assessment|"
    r"graduate programme|internship|talent acquisition|hiring|job)\b", re.I)


def looks_job_related(subject: str, body: str) -> bool:
    """Used only to count job-related mail that matched none of your applications."""
    category, _conf = classify(subject, body)
    return category != "other" or bool(JOB_RELATED.search(subject or ""))
