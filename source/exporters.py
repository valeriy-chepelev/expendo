from prettytable import PrettyTable
import pyperclip
import matplotlib
import matplotlib.pyplot as plt
from matplotlib.dates import DateFormatter
from dateutil.relativedelta import relativedelta
from math import atan, pi


# ---------------------------------------------------------
#                      dump
# ---------------------------------------------------------


def dump(data: dict, segments=None):
    tbl = PrettyTable()
    titles = [t for t in data.keys() if t[:2] != '__']
    tbl.add_column('Date', [d.strftime('%d.%m.%y') for d in data['__date']], 'r')
    for t in titles:
        tbl.add_column(t, data[t], 'r')
    print(f"{data['__kind'].capitalize()}, {data['__unit']}")
    print(tbl)
    # segments
    """    if segments is not None:
        tbl.clear()
        tbl.field_names = ['x1', 'x2', 'a', 'b', 'y1', 'y2', 'd0', 'fin_date']
        for s in segments:
            final = data['__date'][0] + relativedelta(
                days=s['d0'] * (data['__date'][1] - data['__date'][0]).days)
            tbl.add_row(list(s.values()) + [final])
        tbl.align = 'r'
        tbl.float_format = '.2'
        print(f'Segments (lambda={data["__lam"]}):')
        print(tbl)"""


# ---------------------------------------------------------
#                      plot
# ---------------------------------------------------------


def plot(data: dict, segments=None):
    fig, ax = plt.subplots()
    marker = '.' if len(data['__date']) > 1 and (data['__date'][1] - data['__date'][0]).days > 1 else None
    for row in data.keys():
        if row[:2] != '__':
            ax.plot(data['__date'], data[row],
                    label=row, marker=marker)
    # segments
    if segments is not None:
        for row in segments:
            for s in row:
                x = [data['__date'][s['x1']], data['__date'][s['x2']]]
                y = [s['y1'], s['y2']]
                ax.plot(x, y, color='k', linewidth=1, linestyle='dashed', marker='|')
                # annotation
                mid = x[0] + relativedelta(days=(x[-1] - x[0]).days // 2)
                if data['__dv']:
                    text = f"{abs(s['a']):.1f}h/dt"
                else:
                    speed = (data['__date'][1] - data['__date'][0]).days * 8
                    text = f"{abs(s['a']):.1f}h {abs(s['a']) / speed:.1f}v"
                if (s['a'] < 0) and not data['__dv']:
                    final = data['__date'][0] + relativedelta(
                        days=s['d0'] * (data['__date'][1] - data['__date'][0]).days)
                    text += f'\n{final:%d.%m.%y}'
                plt.text(mid, sum(y) // 2, text,
                         bbox={'facecolor': 'lightgray', 'edgecolor': 'none', 'alpha': 0.7, 'pad': 2})
    # formatting
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
