# Wikipedia Table CSV Downloader
This is a flask app that enableds downloading tabled data from wikipedia as a CSV file.

Created after realizing pasting this into a google sheet performs a similar action:

```
=importhtml("https://en.wikipedia.org/wiki/Jonathan_Demme","table",2)
```

To Do:

- [ ] Incorporate long description rows that span all columns

(This tool currently works with simple tabled data, but doesn't yet work when there are long rows with detailed descriptions that span all the columns, where table rows are classed with "vevent" or "expand-child".)

![Image](wiki_csv_downloader.gif)
