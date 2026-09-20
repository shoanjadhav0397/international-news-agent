import os
import re
import html
import smtplib
import feedparser
import requests

from datetime import datetime, timezone, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from dateutil import parser as date_parser


# ============================================================
# CONFIGURATION
# ============================================================

OPENROUTER_API_KEY = os.environ["OPENROUTER_API_KEY"]

EMAIL_ADDRESS = os.environ["EMAIL_ADDRESS"]
EMAIL_APP_PASSWORD = os.environ["EMAIL_APP_PASSWORD"]
TO_EMAIL = os.environ["TO_EMAIL"]

OPENROUTER_MODEL = "openrouter/free"


# ============================================================
# NEWS SOURCES
# ============================================================

RSS_FEEDS = {

    "BBC": [
        "https://feeds.bbci.co.uk/news/world/rss.xml"
    ],

    "Al Jazeera": [
        "https://www.aljazeera.com/xml/rss/all.xml"
    ],

    "DW": [
        "https://rss.dw.com/rdf/rss-en-world"
    ],

    "France 24": [
        "https://www.france24.com/en/rss"
    ],

    "NPR": [
        "https://feeds.npr.org/1004/rss.xml"
    ],

    "UN News": [
        "https://news.un.org/feed/subscribe/en/news/all/rss.xml"
    ],

    "Guardian": [
        "https://www.theguardian.com/world/rss"
    ],

}


# ============================================================
# FETCH RSS ARTICLES
# ============================================================

def fetch_articles():

    articles = []

    cutoff = datetime.now(timezone.utc) - timedelta(hours=36)

    for source, feeds in RSS_FEEDS.items():

        for feed_url in feeds:

            try:

                feed = feedparser.parse(feed_url)

                for item in feed.entries:

                    title = item.get("title", "").strip()
                    link = item.get("link", "").strip()

                    description = (
                        item.get("summary", "")
                        or item.get("description", "")
                    )

                    description = re.sub(
                        "<.*?>",
                        "",
                        description
                    )

                    description = html.unescape(description)

                    published = item.get("published")

                    if published:

                        try:
                            published_dt = date_parser.parse(
                                published
                            )

                            if published_dt.tzinfo is None:
                                published_dt = published_dt.replace(
                                    tzinfo=timezone.utc
                                )

                            if published_dt < cutoff:
                                continue

                        except Exception:
                            pass

                    if title and link:

                        articles.append({

                            "source": source,
                            "title": title,
                            "description": description[:1000],
                            "url": link

                        })

            except Exception as e:

                print(
                    f"Could not read {source}: {e}"
                )

    return articles


# ============================================================
# REMOVE DUPLICATES
# ============================================================

def remove_duplicates(articles):

    seen = set()
    unique = []

    for article in articles:

        key = re.sub(
            r"[^a-z0-9]",
            "",
            article["title"].lower()
        )

        if key not in seen:

            seen.add(key)
            unique.append(article)

    return unique


# ============================================================
# PREPARE ARTICLES FOR AI
# ============================================================

def prepare_for_ai(articles):

    text = ""

    for i, article in enumerate(articles):

        text += f"""

ARTICLE {i}

SOURCE:
{article['source']}

TITLE:
{article['title']}

DESCRIPTION:
{article['description']}

URL:
{article['url']}

"""

    return text


# ============================================================
# OPENROUTER
# ============================================================

def ask_openrouter(prompt):
   
    data = response.json()
    content = data["choices"][0]["message"].get("content")
    return content or "No briefing generated (possible API or safety filter block)."

    url = "https://openrouter.ai/api/v1/chat/completions"

    headers = {

        "Authorization":
            f"Bearer {OPENROUTER_API_KEY}",

        "Content-Type":
            "application/json",

        "HTTP-Referer":
            "https://github.com/",

        "X-Title":
            "Daily International News Agent"

    }

    payload = {

        "model": OPENROUTER_MODEL,

        "messages": [

            {
                "role": "system",

                "content": """
You are an international news research assistant.

Your job is to create a factual daily international
news briefing.

Do not invent facts.

Use only the information supplied in the articles.

Prefer stories that have significant implications for:

- international relations
- geopolitics
- international trade
- global supply chains
- economics
- energy
- technology
- security
- diplomacy
- climate
- global business

Avoid:

- celebrity news
- entertainment
- sports
- clickbait
- duplicate stories
- purely local stories

When several articles report the same event,
combine them into one story and cite multiple sources.
"""
            },

            {
                "role": "user",
                "content": prompt
            }

        ],

        "temperature": 0.2,

        "max_tokens": 6000

    }

    response = requests.post(
        url,
        headers=headers,
        json=payload,
        timeout=60
    )

    response.raise_for_status()

    data = response.json()

    return data["choices"][0]["message"]["content"]


# ============================================================
# CREATE NEWSLETTER
# ============================================================

def create_newsletter(articles):

    article_text = prepare_for_ai(articles)

    prompt = f"""

You have been given a collection of international news
articles from multiple sources.

Select the 10 most significant international stories
for today's briefing.

Ranking criteria:

1. Global significance
2. Impact on international relations
3. Impact on international trade/business
4. Economic importance
5. Geopolitical importance
6. Energy/security/supply-chain implications
7. Source diversity
8. Recency

IMPORTANT:

Do not create a story that is not supported by the
provided articles.

If several articles describe the same event, combine
them into one story.

For each of the 10 stories provide:

### [NUMBER]. HEADLINE

**Summary:**

Write exactly 4–5 concise sentences.

**Why it matters:**

Write 1–2 sentences explaining the international
business/geopolitical significance.

**Sources:**

List the source names.

**Links:**

Include the original article URLs.

At the beginning include:

GLOBAL NEWS BRIEF
DATE: {datetime.now().strftime("%d %B %Y")}

Here are the articles:

{article_text}

"""

    return ask_openrouter(prompt)


# ============================================================
# CONVERT MARKDOWN TO SIMPLE HTML
# ============================================================

def markdown_to_html(text):

    text = html.escape(text)

    text = text = re.sub(r"(https?://[^\s<]+?)(?=[.,;)]?(?:\s|<|$))", r'<a href="\1">\1</a>', text)

    text = text.replace(
        "\n\n",
        "<br><br>"
    )

    text = text.replace(
        "\n",
        "<br>"
    )

    # Make URLs clickable
    text = re.sub(
        r"(https?://[^\s<]+)",
        r'<a href="\1">\1</a>',
        text
    )

    return text


# ============================================================
# SEND EMAIL
# ============================================================

def send_email(newsletter):

    msg = MIMEMultipart("alternative")

    msg["Subject"] = (
        "🌎 Daily International News Brief"
        f" — {datetime.now().strftime('%d %b %Y')}"
    )

    msg["From"] = EMAIL_ADDRESS
    msg["To"] = TO_EMAIL

    html_body = f"""

    <html>

    <body>

    <div style="
        font-family: Arial;
        max-width: 800px;
        margin: auto;
        line-height: 1.6;
    ">

        <h1>
            🌎 Daily International News Brief
        </h1>

        <p>
            Automated briefing generated using
            multiple international news sources.
        </p>

        <hr>

        {markdown_to_html(newsletter)}

        <hr>

        <p style="font-size:12px;color:gray;">
        This briefing is AI-generated from the
        linked source articles. Always open the
        original articles for full context.
        </p>

    </div>

    </body>

    </html>

    """

    msg.attach(
        MIMEText(
            html_body,
            "html",
            "utf-8"
        )
    )

    with smtplib.SMTP_SSL(
        "smtp.gmail.com",
        465
    ) as server:

        server.login(
            EMAIL_ADDRESS,
            EMAIL_APP_PASSWORD
        )

        server.sendmail(
            EMAIL_ADDRESS,
            TO_EMAIL,
            msg.as_string()
        )


# ============================================================
# MAIN AGENT
# ============================================================

def main():

    print("Starting International News Agent...")

    articles = fetch_articles()

    print(
        f"Collected {len(articles)} articles."
    )

    articles = remove_duplicates(
        articles
    )

    print(
        f"After removing duplicates: "
        f"{len(articles)} articles."
    )

    # Don't overload the AI prompt
    articles = articles[:80]

    if len(articles) < 10:

        raise Exception(
            "Not enough articles were collected."
        )

    newsletter = create_newsletter(
        articles
    )

    print(
        "Newsletter generated."
    )

    send_email(
        newsletter
    )

    print(
        "Email sent successfully."
    )


if __name__ == "__main__":

    main()
