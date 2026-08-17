import csv
import re
from io import StringIO
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup, NavigableString, Tag
from flask import Flask, request, Response
from markupsafe import escape

app = Flask(__name__)

# Wikipedia rejects the default python-requests User-Agent with a 403.
# See https://foundation.wikimedia.org/wiki/Policy:Wikimedia_Foundation_User-Agent_Policy
USER_AGENT = (
    "WikiTableCSVDownloader/1.0 "
    "(https://github.com/whileseated/Wiki-Table-CSV-Downloader)"
)

session = requests.Session()
session.headers.update({"User-Agent": USER_AGENT})


class FetchError(Exception):
    """A user-facing problem with the requested URL."""


def fetch_soup(url):
    """Fetch a Wikipedia page and return it as soup, or raise FetchError."""
    if not url:
        raise FetchError("No URL was provided.")

    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise FetchError(f"{url!r} is not a valid http(s) URL.")
    if not parsed.netloc.endswith("wikipedia.org"):
        raise FetchError(f"{parsed.netloc} is not a Wikipedia domain.")

    try:
        response = session.get(url, timeout=20)
    except requests.RequestException as exc:
        raise FetchError(f"Could not reach {parsed.netloc}: {exc}")

    if response.status_code != 200:
        raise FetchError(
            f"Wikipedia returned HTTP {response.status_code} for that URL."
        )

    return BeautifulSoup(response.content, "html.parser")


def extract_wiki_title(soup):
    """'Jonathan Demme - Wikipedia' => 'Jonathan_Demme'."""
    title_tag = soup.find("title")
    if not title_tag:
        return "wikipedia_page"
    title = title_tag.get_text().split(" - ")[0].strip()
    # Keep the filename safe for a Content-Disposition header.
    return re.sub(r"[^A-Za-z0-9._-]", "_", title) or "wikipedia_page"


def merge_expand_child_rows(table):
    """Fold 'expand-child' description rows into their 'vevent' parent row.

    Wikipedia renders collapsible tables as a `tr.vevent` data row followed by a
    `tr.expand-child` row holding a prose description. Left alone the description
    becomes its own ragged CSV row, so append it as an extra column instead and
    drop the now-empty child row.
    """
    merged_any = False

    for vevent_row in table.find_all("tr", class_="vevent"):
        child_row = vevent_row.find_next_sibling("tr", class_="expand-child")
        if not child_row or not child_row.td:
            continue

        description = child_row.td.get_text(" ", strip=True)

        # Append as a NEW cell; overwriting the last cell would destroy its value.
        new_cell = Tag(name="td")
        new_cell.string = description
        vevent_row.append(new_cell)

        child_row.decompose()
        merged_any = True

    if merged_any:
        header_row = table.find("tr")
        if header_row and header_row.find_all("th"):
            header_cell = Tag(name="th")
            header_cell.string = "Description"
            header_row.append(header_cell)


def strip_noise(table):
    """Remove citation markers and style blocks that pollute cell text."""
    for sup in table.find_all("sup", class_="reference"):
        sup.decompose()
    for style in table.find_all("style"):
        style.decompose()


def get_tables(soup):
    """Return the page's wikitables, pre-processed and ready to convert."""
    tables = soup.find_all("table", {"class": "wikitable"})
    for table in tables:
        strip_noise(table)
        merge_expand_child_rows(table)
    return tables


def table_title(table):
    """Nearest preceding section heading.

    MediaWiki now wraps headings in `div.mw-heading` and splits article body
    content into `<section>` elements, so the heading is no longer a sibling of
    the table. `find_previous` walks the document in reverse regardless of
    nesting, which survives both the old and new markup.
    """
    heading = table.find_previous(["h2", "h3", "h4"])
    if not heading:
        return "Table Title Not Found"

    text = heading.get_text(" ", strip=True).replace("[edit]", "").strip()
    return text or "Table Title Not Found"


def clean_cell_text(cell):
    """Clean cell text, turning <br> into newlines."""
    parts = []
    for element in cell.contents:
        if isinstance(element, NavigableString):
            text = element.strip()
            if text:
                parts.append(text)
        elif isinstance(element, Tag):
            if element.name == "br":
                parts.append("\n")
            else:
                text = element.get_text(" ", strip=True)
                if text:
                    parts.append(text)

    joined = " ".join(parts)
    # Collapse the spaces introduced around <br> newlines.
    return re.sub(r" *\n *", "\n", joined).strip()


def process_table(table):
    """Return the table as a list of rows, expanding rowspans and colspans."""
    processed_rows = []
    rowspan_tracker = {}  # column index -> {'count': n, 'text': str}

    for tr in table.find_all("tr"):
        row = []
        col_idx = 0

        def drain_spans():
            """Emit any columns still carried down from earlier rows."""
            nonlocal col_idx
            while col_idx in rowspan_tracker:
                row.append(rowspan_tracker[col_idx]["text"])
                rowspan_tracker[col_idx]["count"] -= 1
                if rowspan_tracker[col_idx]["count"] == 0:
                    del rowspan_tracker[col_idx]
                col_idx += 1

        for cell in tr.find_all(["td", "th"]):
            drain_spans()

            cell_text = clean_cell_text(cell)
            rowspan = int(cell.get("rowspan", 1) or 1)
            colspan = int(cell.get("colspan", 1) or 1)

            for _ in range(colspan):
                if rowspan > 1:
                    rowspan_tracker[col_idx] = {
                        "count": rowspan - 1,
                        "text": cell_text,
                    }
                row.append(cell_text)
                col_idx += 1

        drain_spans()
        processed_rows.append(row)

    return processed_rows


PAGE = """
<!doctype html>
<meta charset="utf-8">
<title>Wikipedia Table Downloader</title>
<style>
  body {{ font: 16px/1.5 -apple-system, system-ui, sans-serif;
         max-width: 46rem; margin: 3rem auto; padding: 0 1rem; }}
  input[type=text] {{ width: 26rem; padding: .4rem; }}
  button, input[type=submit] {{ padding: .35rem .8rem; cursor: pointer; }}
  .table-row {{ padding: .6rem 0; border-bottom: 1px solid #ddd; }}
  .meta {{ color: #666; }}
  .error {{ background: #fdd; border: 1px solid #c00; padding: .8rem; }}
</style>
{body}
"""


def render(body):
    return PAGE.format(body=body)


def error_page(message):
    return render(
        f'<p class="error">{escape(message)}</p><p><a href="/">Try again</a></p>'
    ), 400


@app.route("/")
def index():
    return render(
        """
        <h1>Wikipedia Table Downloader</h1>
        <form action="/fetch-tables" method="post">
          <input type="text" name="url" placeholder="https://en.wikipedia.org/wiki/..." autofocus>
          <input type="submit" value="Fetch Tables">
        </form>
        <p class="meta">Try:
          <a href="https://en.wikipedia.org/wiki/Jonathan_Demme">Demme</a> &middot;
          <a href="https://en.wikipedia.org/wiki/89th_Academy_Awards">Oscars</a> &middot;
          <a href="https://en.wikipedia.org/wiki/Dust-to-Digital">Dust-to-Digital</a> &middot;
          <a href="https://en.wikipedia.org/wiki/List_of_30_for_30_films">30 for 30</a>
        </p>
        """
    )


@app.route("/fetch-tables", methods=["POST"])
def fetch_tables():
    url = (request.form.get("url") or "").split("#")[0].strip()

    try:
        soup = fetch_soup(url)
    except FetchError as exc:
        return error_page(str(exc))

    tables = get_tables(soup)
    if not tables:
        return error_page("No tables with the 'wikitable' class were found on that page.")

    rows_html = ""
    for idx, table in enumerate(tables):
        row_count = len(table.find_all("tr"))
        rows_html += (
            '<div class="table-row">'
            f"<strong>{escape(table_title(table))}</strong><br>"
            f'<span class="meta">Table {idx + 1} &middot; {row_count} rows</span><br>'
            f"<button formaction='/table-to-csv/{idx}' name='url' "
            f"value='{escape(url)}'>Download CSV</button>"
            "</div>"
        )

    return render(
        f'<p>{len(tables)} table(s) found on '
        f'<a href="{escape(url)}" target="_blank">this page</a>. '
        f'<a href="/">Start over</a></p>'
        f'<form method="post">{rows_html}</form>'
    )


@app.route("/table-to-csv/<int:table_idx>", methods=["POST"])
def table_to_csv(table_idx):
    url = (request.form.get("url") or "").split("#")[0].strip()

    try:
        soup = fetch_soup(url)
    except FetchError as exc:
        return error_page(str(exc))

    tables = get_tables(soup)
    if not 0 <= table_idx < len(tables):
        return error_page(
            f"Table {table_idx + 1} no longer exists on that page "
            f"({len(tables)} found). The page may have changed."
        )

    page_title = extract_wiki_title(soup)

    output = StringIO()
    writer = csv.writer(output)
    writer.writerows(process_table(tables[table_idx]))

    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={
            "Content-Disposition": (
                f"attachment; filename={page_title}_table_{table_idx + 1}.csv"
            )
        },
    )


if __name__ == "__main__":
    app.run(debug=True)
