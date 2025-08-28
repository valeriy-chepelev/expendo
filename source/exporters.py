from prettytable import PrettyTable
import pyperclip
import matplotlib
import matplotlib.pyplot as plt
from matplotlib.dates import DateFormatter

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

# ---------------------------------------------------------
#                      plot
# ---------------------------------------------------------


def plot(data: dict):
    fig, ax = plt.subplots()
    marker = '.' if len(data['__date']) > 1 and (data['__date'][1] - data['__date'][0]).days > 1 else None
    for row in data.keys():
        if row[:2] != '__':
            ax.plot(data['__date'], data[row],
                    label=row, marker=marker)
    formatter = DateFormatter("%d.%m.%y")
    ax.xaxis.set_major_formatter(formatter)
    plt.xlabel('Date')
    plt.ylabel(data['__unit'])
    plt.grid()
    plt.legend()
    plt.title(data['__kind'].capitalize())
    fig.autofmt_xdate()
    plt.draw()
    plt.ion()
    plt.show()
