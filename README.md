# Wiki-Table-CSV-Downloader
This is a flask app that allows you to download tabled data from wikipedia as CSV files.

Created after realizing pasting this into a google sheet performs a similar action:

```
=importhtml("https://en.wikipedia.org/wiki/Jonathan_Demme","table",2)
```

(This tool currently works with simple tabled data, but doesn't yet work when there are long rows with detailed descriptions that span all the columns, where table rows are classed with "vevent" or "expand-child".)

To Do:

- [ ] Incorporate long description rows that span all columns
