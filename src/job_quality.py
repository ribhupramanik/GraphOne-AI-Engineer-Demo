import re

AI_TITLE_PATTERN = re.compile(
    r"(?<![A-Za-z0-9])(?:AI|ML|LLM|NLP|MLOps)(?![A-Za-z0-9])|"
    r"\b(?:machine learning|deep learning|data scien(?:ce|tist)|applied scientist|"
    r"research scientist|computer vision|generative ai|artificial intelligence|"
    r"prompt engineer|model training)\b",
    re.IGNORECASE,
)

ROLE_FAMILIES = (
    ("Data Science", r"\b(?:data scientist|data science|applied scientist|research scientist|data analyst|analytics engineer)\b"),
    ("Product Management", r"\b(?:product manager|product owner|product lead)\b"),
    ("Marketing & Growth", r"\b(?:marketing|growth|campaign|seo|ppc|media strategy|user acquisition|advertising)\b"),
    ("Sales & Business Development", r"\b(?:sales|account executive|account manager|business development|sdr|gtm|go.to.market|commercial lead|commercial leader)\b"),
    ("Customer Success & Support", r"\b(?:customer success|customer advocacy|customer support|technical support|client services|support engineering|solutions consultant)\b"),
    ("People & Recruiting", r"\b(?:recruit|talent acquisition|human resources|people partner|hr shared services)\b"),
    ("Legal & Compliance", r"\b(?:legal|counsel|compliance|privacy|policy)\b"),
    ("Security", r"\b(?:security|cryptography|devsecops)\b"),
    ("Engineering", r"\b(?:engineer|developer|architect|devops|software|full.stack|back.end|front.end|programmer|infrastructure|technical lead)\b"),
    ("Design", r"\b(?:designer|design manager|artist|ux|ui designer)\b"),
    ("Finance", r"\b(?:finance|financial|credit|actuarial|accounting|billing|procurement)\b"),
    ("Operations & Delivery", r"\b(?:operations|project manager|program manager|delivery|implementation|strategy|process automation)\b"),
    ("Research", r"\b(?:researcher|scientist|research)\b"),
)


def ai_title_indicated(title):
    return bool(AI_TITLE_PATTERN.search(title or ""))


def role_family_from_title(title):
    title = title or ""
    for family, expression in ROLE_FAMILIES:
        if re.search(expression, title, re.IGNORECASE):
            return family
    return "Other / Unclassified"
