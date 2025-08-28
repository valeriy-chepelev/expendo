from prettytable import PrettyTable
import pyperclip

# ---------------------------------------------------------
#                      dump
# ---------------------------------------------------------


def dump(data: dict):
    tbl = PrettyTable()
    titles = [t for t in data.keys() if t[:2] != '__']
    tbl.add_column('Date', [d.strftime('%d.%m.%y') for d in data['__date']], 'r')
    for t in titles:
        tbl.add_column(t, data[t], 'r')
    print(f"{data['__kind'].capitalize()}, {data['__unit']}")
    print(tbl)
