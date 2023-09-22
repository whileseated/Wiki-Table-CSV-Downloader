from flask import Flask, request, Response
import requests
from bs4 import BeautifulSoup
import csv
from io import StringIO

app = Flask(__name__)

@app.route('/')
def index():
    return '''
        <form action="/fetch-tables" method="post">
            Wikipedia URL: <input type="text" name="url">
            <input type="submit" value="Fetch Tables">
        </form><br>

        Tested URLs - 
        <a href="https://en.wikipedia.org/wiki/Jonathan_Demme">Demme</a>
        <a href="https://en.wikipedia.org/wiki/89th_Academy_Awards">Oscars</a><br>
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



@app.route('/table-to-csv/<int:table_idx>', methods=['POST'])
def table_to_csv(table_idx):
    url = request.form.get('url')

    response = requests.get(url)
    soup = BeautifulSoup(response.text, 'html.parser')
    tables = soup.findAll('table', {'class': 'wikitable'})
    
    chosen_table = tables[table_idx]
    
    output = StringIO()
    writer = csv.writer(output)

    for row in chosen_table.findAll('tr'):
        cells = [cell.text.strip() for cell in row.findAll(['th', 'td'])]
        if cells:  
            writer.writerow(cells)

    output.seek(0)
    return Response(
        output,
        mimetype="text/csv",
        headers={"Content-disposition":
                 f"attachment; filename=wikipedia_table_{table_idx}.csv"})

if __name__ == '__main__':
    app.run(debug=True)
