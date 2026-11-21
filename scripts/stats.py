"""Generate GitHub stats SVG cards for the profile README.

Reads only aggregate numbers (counts and language sizes) with a read-only
token, so private work is counted without exposing repository names.

Usage: GH_TOKEN=... python scripts/stats.py <login> <out_dir>
"""

import datetime as dt
import json
import os
import sys
import urllib.request
from html import escape

API = "https://api.github.com/graphql"

QUERY = """
query($login: String!, $merged30: String!, $merged365: String!) {
  user(login: $login) {
    createdAt
    contributionsCollection {
      totalCommitContributions
      totalPullRequestContributions
      totalPullRequestReviewContributions
      totalIssueContributions
      contributionCalendar {
        totalContributions
        weeks { contributionDays { contributionCount date } }
      }
    }
    repositories(ownerAffiliations: OWNER, isFork: false, first: 100) {
      totalCount
      nodes {
        languages(first: 10, orderBy: {field: SIZE, direction: DESC}) {
          edges { size node { name color } }
        }
      }
    }
  }
  m30: search(query: $merged30, type: ISSUE) { issueCount }
  m365: search(query: $merged365, type: ISSUE) { issueCount }
}
"""

STYLE = """
<style>
  .bg { fill: #ffffff; stroke: #d0d7de; }
  .t { fill: #1f2328; font: 600 16px 'Segoe UI', Ubuntu, sans-serif; }
  .l { fill: #59636e; font: 400 12px 'Segoe UI', Ubuntu, sans-serif; }
  .v { fill: #1f2328; font: 600 22px 'Segoe UI', Ubuntu, sans-serif; }
  .bar { fill: #2da44e; }
  .grid { stroke: #d0d7de; }
  @media (prefers-color-scheme: dark) {
    .bg { fill: #0d1117; stroke: #30363d; }
    .t, .v { fill: #e6edf3; }
    .l { fill: #9198a1; }
    .bar { fill: #3fb950; }
    .grid { stroke: #30363d; }
  }
</style>
"""


def fetch(login, token):
    today = dt.date.today()
    since30 = (today - dt.timedelta(days=30)).isoformat()
    since365 = (today - dt.timedelta(days=365)).isoformat()
    body = json.dumps({
        "query": QUERY,
        "variables": {
            "login": login,
            "merged30": f"author:{login} is:pr is:merged merged:>={since30}",
            "merged365": f"author:{login} is:pr is:merged merged:>={since365}",
        },
    }).encode()
    req = urllib.request.Request(API, data=body, headers={
        "Authorization": f"bearer {token}",
        "Content-Type": "application/json",
        "User-Agent": "profile-stats",
    })
    with urllib.request.urlopen(req) as resp:
        data = json.load(resp)
    if data.get("errors"):
        sys.exit(f"GraphQL error: {data['errors']}")
    return data["data"]


def streaks(days):
    counts = [d["contributionCount"] for d in days]
    longest = run = 0
    for c in counts:
        run = run + 1 if c else 0
        longest = max(longest, run)
    current = 0
    # Today may still be empty; start counting from yesterday in that case.
    tail = counts[:-1] if counts and counts[-1] == 0 else counts
    for c in reversed(tail):
        if not c:
            break
        current += 1
    return current, longest


def stats_card(d):
    cc = d["user"]["contributionsCollection"]
    cal = cc["contributionCalendar"]
    days = [day for w in cal["weeks"] for day in w["contributionDays"]]
    current, longest = streaks(days)

    items = [
        ("Contributions (1y)", cal["totalContributions"]),
        ("Commits (1y)", cc["totalCommitContributions"]),
        ("PRs merged (30d)", d["m30"]["issueCount"]),
        ("PRs merged (1y)", d["m365"]["issueCount"]),
        ("Active days (1y)", sum(1 for day in days if day["contributionCount"])),
        ("Repositories", d["user"]["repositories"]["totalCount"]),
        ("Current streak", f"{current} d"),
        ("Longest streak", f"{longest} d"),
    ]

    w, h = 495, 330
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
           f'viewBox="0 0 {w} {h}" role="img" aria-label="GitHub stats">', STYLE,
           f'<rect class="bg" x="0.5" y="0.5" width="{w - 1}" height="{h - 1}" rx="6"/>',
           '<text class="t" x="24" y="36">GitHub activity (incl. private repos)</text>']
    for i, (label, value) in enumerate(items):
        x = 24 + (i % 4) * 118
        y = 76 + (i // 4) * 62
        out.append(f'<text class="v" x="{x}" y="{y}">{escape(str(value))}</text>')
        out.append(f'<text class="l" x="{x}" y="{y + 18}">{escape(label)}</text>')

    # Weekly contributions, last 26 weeks.
    weeks = [sum(day["contributionCount"] for day in wk["contributionDays"])
             for wk in cal["weeks"]][-26:]
    top = max(weeks) or 1
    base, height, bw = 300, 90, 16
    out.append('<text class="l" x="24" y="196">Contributions per week, last 26 weeks</text>')
    out.append(f'<line class="grid" x1="24" y1="{base + 0.5}" x2="{w - 24}" y2="{base + 0.5}"/>')
    for i, n in enumerate(weeks):
        bh = round(n / top * height)
        if bh:
            x = 24 + i * (bw + 1.8)
            out.append(f'<rect class="bar" x="{x:.1f}" y="{base - bh}" width="{bw}" '
                       f'height="{bh}" rx="2"><title>{n}</title></rect>')
    out.append("</svg>")
    return "\n".join(out)


# Notebooks store outputs inline, so their byte size drowns every other language.
EXCLUDED_LANGUAGES = {"Jupyter Notebook"}


def languages_card(d, limit=8):
    sizes, colors = {}, {}
    for repo in d["user"]["repositories"]["nodes"]:
        for e in repo["languages"]["edges"]:
            name = e["node"]["name"]
            if name in EXCLUDED_LANGUAGES:
                continue
            sizes[name] = sizes.get(name, 0) + e["size"]
            colors[name] = e["node"]["color"] or "#8b949e"
    total = sum(sizes.values()) or 1
    top = sorted(sizes.items(), key=lambda kv: -kv[1])[:limit]

    w, h = 350, 80 + ((len(top) + 1) // 2) * 26
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
           f'viewBox="0 0 {w} {h}" role="img" aria-label="Top languages">', STYLE,
           f'<rect class="bg" x="0.5" y="0.5" width="{w - 1}" height="{h - 1}" rx="6"/>',
           '<text class="t" x="24" y="36">Top languages</text>',
           '<clipPath id="c"><rect x="24" y="50" width="302" height="10" rx="5"/></clipPath>',
           '<g clip-path="url(#c)">']
    x = 24.0
    for name, size in top:
        bw = size / total * 302
        out.append(f'<rect x="{x:.2f}" y="50" width="{bw:.2f}" height="10" fill="{colors[name]}"/>')
        x += bw
    out.append("</g>")
    for i, (name, size) in enumerate(top):
        cx = 24 + (i % 2) * 155
        cy = 86 + (i // 2) * 26
        pct = size / total * 100
        out.append(f'<circle cx="{cx + 5}" cy="{cy - 4}" r="5" fill="{colors[name]}"/>')
        out.append(f'<text class="l" x="{cx + 16}" y="{cy}">{escape(name)} {pct:.1f}%</text>')
    out.append("</svg>")
    return "\n".join(out)


def main():
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    token = os.environ.get("GH_TOKEN")
    if not token:
        sys.exit("GH_TOKEN is empty: add the STATS_TOKEN secret to the repository.")
    login, out_dir = sys.argv[1], sys.argv[2]
    data = fetch(login, token)
    os.makedirs(out_dir, exist_ok=True)
    for name, svg in (("stats.svg", stats_card(data)), ("languages.svg", languages_card(data))):
        with open(os.path.join(out_dir, name), "w", encoding="utf-8") as f:
            f.write(svg + "\n")
    print(f"Wrote stats.svg and languages.svg to {out_dir}")


if __name__ == "__main__":
    main()
