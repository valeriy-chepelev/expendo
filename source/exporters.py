from prettytable import PrettyTable
import pyperclip
import matplotlib.pyplot as plt
from matplotlib.dates import DateFormatter
from dateutil.relativedelta import relativedelta


# ---------------------------------------------------------
#                      dump
# ---------------------------------------------------------


def dump(data: dict, segments=None):
    tbl = PrettyTable()
    titles = [t for t in data.keys() if t[:2] != '__']
    if segments is None or (len(segments) == 0):
        tbl.add_column('Date', [d.strftime('%d.%m.%y') for d in data['__date']], 'r')
        for t in titles:
            tbl.add_column(t, data[t], 'r')
        print(f"{data['__kind'].capitalize()}, {data['__unit']}")
        print(tbl)
    # segments
    else:
        angle_units = 'K,hrs/dt2' if data['__dv'] else 'K,hrs/dt'
        tbl.field_names = ['Row', 'Start', 'End', angle_units, 'Velocity', 'Final date', 'Lambda']
        for idx, row in enumerate(segments):
            for s in row:
                tbl.add_row([titles[idx],
                             data['__date'][s['x1']].strftime('%d.%m.%y'),
                             data['__date'][s['x2']].strftime('%d.%m.%y'),
                             f"{s['a']:.2f}",
                             f"{s['a'] / ((data['__date'][1] - data['__date'][0]).days * 8.0):.2f}"
                             if not data['__dv'] else 'N/A',
                             f"{(data['__date'][0] + relativedelta(
                                 days=s['d0'] * (data['__date'][1] - data['__date'][0]).days)).strftime('%d.%m.%y')}"
                             if (s['a'] < 0) and not data['__dv'] else 'N/A',
                             f"{s['lambda']:.2f}"])
            tbl.add_divider()
        tbl.align = 'r'
        print(f'Linear regression trends of {data['__kind'].capitalize()}:')
        print(tbl)


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
    if segments is not None and len(segments):
        for row in segments:
            for s in row:
                x = [data['__date'][s['x1']], data['__date'][s['x2']]]
                y = [s['y1'], s['y2']]
                ax.plot(x, y, color='k', linewidth=1, linestyle='dashed', marker='|')
                # annotation
                mid = x[0] + relativedelta(days=(x[-1] - x[0]).days // 2)
                if data['__dv']:
                    text = f"{abs(s['a']):.1f}h/dt2"
                else:
                    speed = (data['__date'][1] - data['__date'][0]).days * 8
                    text = f"{abs(s['a']):.1f}h/dt {abs(s['a']) / speed:.1f}v"
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
    # TODO: add window title
    plt.title(data['__kind'].capitalize())
    fig.autofmt_xdate()
    plt.draw()
    plt.ion()
    plt.show()
