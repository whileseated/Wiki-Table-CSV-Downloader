import requests
from bs4 import BeautifulSoup, NavigableString, Tag
import csv
from flask import Flask, request, Response
from io import StringIO
from collections import defaultdict

app = Flask(__name__)

def extract_wiki_title(soup):
    title_tag = soup.find('title')
    if title_tag:
        # e.g. 'Jonathan Demme - Wikipedia' => 'Jonathan Demme'
        return title_tag.text.split(' - ')[0].replace(" ", "_")
    return "wikipedia_page"

@app.route('/')
def index():
    return '''
        <form action="/fetch-tables" method="post">
            Wikipedia URL: <input type="text" name="url">
            <input type="submit" value="Fetch Tables">
        </form><br>

        Tested URLs - 
        <a href="https://en.wikipedia.org/wiki/Jonathan_Demme">Demme</a>
        <a href="https://en.wikipedia.org/wiki/89th_Academy_Awards">Oscars</a> <a href="https://en.wikipedia.org/wiki/Dust-to-Digital">Dust-to-Digital</a><br>
        Broken URLs - <a href="https://en.wikipedia.org/wiki/List_of_30_for_30_films">30 for 30</a> (vevent/child issue)


    '''

@app.route('/fetch-tables', methods=["POST"])
def fetch_tables():
    url = request.form.get('url')

    # Ignoring anything in the URL after "#"
    url = url.split('#')[0]

    response = requests.get(url)
    soup = BeautifulSoup(response.content, 'html.parser')

    tables = soup.find_all("table", {"class": "wikitable"})

    table_titles = []
    row_counts = []

    for table in tables:
 # Process the vevent and expand-child rows
        for vevent_row in table.find_all('tr', class_='vevent'):
            expand_child_row = vevent_row.find_next_sibling('tr', class_='expand-child')
            if expand_child_row:
                expand_child_content = expand_child_row.td.get_text(strip=True)
                last_td = vevent_row.find_all('td')[-1]
                if last_td.string:
                    last_td.string += " " + expand_child_content
                else:
                    last_td.string = expand_child_content


        # Start with the current table and move up to find the nearest h3 or h2
        prev = table.previous_sibling
        title_element = None
        while prev:
            if prev.name == 'h3' or prev.name == 'h2':
                title_element = prev
                # Modify the header content here
                original_text = title_element.get_text()
                modified_text = original_text + ' '
                title_element.clear()  # Clear current content
                title_element.append(modified_text)  # Append new content
                break
            prev = prev.previous_sibling

        if title_element:
            # Removing the nested <span> content
            for span in title_element.find_all('span'):
                span.extract()
            title_text = title_element.get_text(strip=True).replace("[edit]", "").strip()
            table_titles.append(title_text)
        else:
            table_titles.append("Table Title Not Found")

        # Counting the number of rows for the table
        row_counts.append(len(table.find_all('tr')))

    table_selection_html = ''
    for idx, (title, row_count) in enumerate(zip(table_titles, row_counts)):
        table_selection_html += f"<div><strong>{title}</strong></div><button formaction='/table-to-csv/{idx}' name='url' value='{url}'>Download</button> Table {idx + 1}: {row_count} rows<br/><br/>"

    return f'''
        Select a table to download from <a href="{url}" target="_blank">this source</a>:<br/><br/>
        <form method="post">
            {table_selection_html}
        </form>
    '''

def process_rowspans_and_colspans(table):
    """ Pre-process rowspans and colspans in the table for accurate CSV conversion. """
    for row in table.find_all('tr'):
        cells = row.find_all(['td', 'th'], recursive=False)
        for cell in cells:
            rowspan = int(cell.get('rowspan', 1))
            colspan = int(cell.get('colspan', 1))

            # Duplicate the cell for rowspans
            for i in range(rowspan - 1):
                next_row = row.find_next_sibling('tr')
                if next_row:
                    next_row.insert(len(next_row.find_all(['td', 'th'], recursive=False)), cell)

            # Duplicate the cell for colspans
            if colspan > 1:
                for j in range(1, colspan):
                    cell.insert_after(cell.__copy__())

def clean_cell_text(cell):
    """ Clean the cell text and handle special cases like 'br' tags. """
    cell_content = ''
    for element in cell.contents:
        if isinstance(element, NavigableString):
            cell_content += element.strip()
        elif isinstance(element, Tag):
            if element.name == 'br':
                cell_content += '\n'
            else:
                cell_content += element.get_text(' ', strip=True)
    return cell_content


def process_table(table):
    """ Process a BeautifulSoup table and return a list of rows, each as a list of cell values. """
    processed_rows = []
    rowspan_tracker = {}  # Tracks rowspans for each column index

    for tr in table.find_all('tr'):
        row = []
        col_idx = 0

        for cell in tr.find_all(['td', 'th']):
            # Skip columns that are still spanned from previous rows
            while col_idx in rowspan_tracker:
                row.append(rowspan_tracker[col_idx]['text'])
                rowspan_tracker[col_idx]['count'] -= 1
                if rowspan_tracker[col_idx]['count'] == 0:
                    del rowspan_tracker[col_idx]
                col_idx += 1

            cell_text = clean_cell_text(cell)
            rowspan = int(cell.get('rowspan', 1))
            colspan = int(cell.get('colspan', 1))

            # Handle rowspan
            if rowspan > 1:
                rowspan_tracker[col_idx] = {'count': rowspan - 1, 'text': cell_text}

            # Handle colspan and add cell text
            for _ in range(colspan):
                row.append(cell_text)
                col_idx += 1

        # Clean up any remaining spanned columns
        while col_idx in rowspan_tracker:
            row.append(rowspan_tracker[col_idx]['text'])
            rowspan_tracker[col_idx]['count'] -= 1
            if rowspan_tracker[col_idx]['count'] == 0:
                del rowspan_tracker[col_idx]
            col_idx += 1

        processed_rows.append(row)

    return processed_rows

@app.route('/table-to-csv/<int:table_idx>', methods=['POST'])
def table_to_csv(table_idx):
    url = request.form.get('url')

    response = requests.get(url)
    soup = BeautifulSoup(response.text, 'html.parser')
    tables = soup.find_all('table', {'class': 'wikitable'})

    page_title = extract_wiki_title(soup)
    chosen_table = tables[table_idx]

    processed_table = process_table(chosen_table)

    output = StringIO()
    writer = csv.writer(output)

    for row in processed_table:
        writer.writerow(row)

    output.seek(0)
    return Response(
        output,
        mimetype="text/csv",
        headers={"Content-disposition":
                 f"attachment; filename={page_title}_table_{table_idx}.csv"})

if __name__ == '__main__':
    app.run(debug=True)
