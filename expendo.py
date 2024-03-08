from yandex_tracker_client import TrackerClient
from yandex_tracker_client.exceptions import NotFound
import datetime as dt
from dateutil.rrule import rrule, DAILY
from dateutil.relativedelta import relativedelta
import math
from functools import lru_cache
import matplotlib
import matplotlib.pyplot as plt
from matplotlib.dates import DateFormatter
import configparser
from alive_progress import alive_bar
from natsort import natsorted
import argparse
from prettytable import PrettyTable

from tracker_data import epics, stories, get_start_date, estimate, spent, precashe


def read_config(filename):
    config = configparser.ConfigParser()
    config.read(filename)
    assert 'token' in config['DEFAULT']
    assert 'org' in config['DEFAULT']
    return config['DEFAULT']


# Sprints info


def sprint_info(client):
    table = PrettyTable()
    for s in client.sprints:
        table.add_row([s.name, s.startDate, s.startDateTime])
    print(table)


# Data output routines

def plot_details(title: str, d: dict, trend):
    fig, ax = plt.subplots()
    trend_color = 'k'
    for row in d[next(iter(d))].keys():
        p = ax.plot([date for date in d.keys()],
                    [d[date][row] for date in d.keys()],
                    label=row)
        if trend is not None and row == trend['name']:
            trend_color = p[0].get_color()
    if trend is not None:
        dates = list(rrule(DAILY,
                           dtstart=trend['start'],
                           until=trend['end']))
        ax.plot(dates,
                [trend['mid'][1] + i * trend['mid'][0] for i in range(len(dates))],
                linestyle='dashed', color=trend_color, linewidth=1)
        ax.plot(dates,
                [trend['min'][1] + i * trend['min'][0] for i in range(len(dates))],
                linestyle='dashed', color=trend_color, linewidth=1)
        ax.plot(dates,
                [trend['max'][1] + i * trend['max'][0] for i in range(len(dates))],
                linestyle='dashed', color=trend_color, linewidth=1)
    formatter = DateFormatter("%d.%m.%y")
    ax.xaxis.set_major_formatter(formatter)
    plt.xlabel('Date')
    plt.ylabel('[hours]')
    plt.grid()
    plt.legend()
    plt.title(title)
    fig.autofmt_xdate()
    plt.draw()


def tabulate_details(d: dict):
    table = PrettyTable()
    sk = [key for key in d[next(iter(d))].keys()]
    table.field_names = ['Date', *sk, 'Summary']
    for date in d.keys():
        sv = [str(val) for val in d[date].values()]
        table.add_row([date.strftime("%d.%m.%y"), *sv, sum(d[date].values())])
    table.align = 'r'
    print(table)


def tabulate_csv(d: dict):
    print('Date', ",".join(d[next(iter(d))].keys()), 'Summary', sep=',')
    for date in d.keys():
        sval = ",".join([str(val) for val in d[date].values()])
        print(date.strftime("%d.%m.%y"), sval, sum(d[date].values()), sep=',')


# Trends


def linreg(X, Y):
    """
    return a,b in solution to y = ax + b such that root-mean-square distance between trend line and original points is minimized
    """
    N = len(X)
    Sx = Sy = Sxx = Syy = Sxy = 0.0
    for x, y in zip(X, Y):
        Sx = Sx + x
        Sy = Sy + y
        Sxx = Sxx + x * x
        Syy = Syy + y * y
        Sxy = Sxy + x * y
    det = Sxx * N - Sx * Sx
    return (Sxy * N - Sy * Sx) / det, (Sxx * Sy - Sx * Sxy) / det


def trends(d, row, start=None):
    """ Calculate linear regression factors of data row.
    row is name of data row
    return tuple (a,b) for y(x)=ax+b
    count x as date index, zero-based"""
    if row not in [key for key in d[next(iter(d))].keys()]:
        raise Exception(f'"{row}" not present in data.')
    if len(d.keys()) < 2:
        raise Excepton("Can't calculate trends based single value.")
    # TODO: redefine date range
    dates = [date for date in d.keys() if start is None or not (date < start.date())]
    # calculate data regression
    original = [d[date][row] for date in dates]
    midc = linreg(range(len(original)), original)  # middle linear regression a,b
    midval = [midc[0] * i + midc[1] for i in range(len(original))]  # middle data row
    # calculate high regression
    maxval = [(i, val[1]) for i, val in enumerate(zip(midval, original))
              if val[1] > val[0]]  # get (index, value) for values higher middle
    assert len(maxval) > 1
    maxc = linreg(*list(zip(*maxval)))
    # calculate low regression
    minval = [(i, val[1]) for i, val in enumerate(zip(midval, original))
              if val[1] < val[0]]  # get (index, value) for values lower middle
    assert len(minval) > 1
    minc = linreg(*list(zip(*minval)))
    # return with fixed angles
    return {'name': row,
            'start': dates[0],
            'end': dates[-1],
            'mid': midc,
            'min': (min(midc[0], minc[0]), minc[1]),
            'max': (max(midc[0], maxc[0]), maxc[1])}


def some_issues(client, keys: list):
    return [client.issues[key] for key in keys]


# g_project = "MT SystemeLogic(ACB)"  # Temporary, will be moved to argument parser
# g_project = "MT БМРЗ-60"  # Temporary, will be moved to argument parser
# g_project = "MT Дуга-О3"  # Temporary, will be moved to argument parser
# g_project = "MT SW SCADA"  # Temporary, will be moved to argument parser
# g_project = "MT 150cry"  # Temporary, will be moved to argument parser
# g_project = "МТ M4Cry"  # Temporary, will be moved to argument parser
# g_project = "МТ IP1810"  # Temporary, will be moved to argument parser
# g_project = "Корпоративный профиль 61850"  # Temporary, will be moved to argument parser
# g_project = "MT FastView"  # Temporary, will be moved to argument parser


def define_parser():
    """ Return CLI arguments parser
    CLI request cases
    expendo project [all] [COMPONENTS] [TODAY] [DUMP]
    expendo project velocities EPICS WEEK PLOT
    expendo project spends STORIES [TODAY] [CSV]
    expendo (MTPD-01,MTPD-02) estimates [COMPONENTS] all [DUMP]
    """
    parser = argparse.ArgumentParser(description='Expendo v.1.0 - Yandex Tracker stat crawler by VCh.',
                                     epilog='Tracker connection settings and params in "expendo.ini".')
    parser.add_argument('scope',
                        help='project name or comma-separated issues keys (no space allowed)')
    parser.add_argument('parameter', choices=['spent', 'estimate', 'burn', 'all'],
                        help='measured value')
    parser.add_argument('grouping', choices=['epics', 'stories', 'components', 'queues'],
                        help='value grouping criteria')
    parser.add_argument('output', choices=['dump', 'plot', 'csv'],
                        help='output fromat')
    parser.add_argument('timespan', choices=['today', 'week', 'sprint', 'month', 'quarter', 'all'],
                        help='calculation time range')
    return parser


def get_scope(client, args):
    """Return list of scoped issue objects."""
    if args.scope in [p.name for p in client.projects]:
        if args.grouping == stories:
            return stories(client, args.scope)
        return epics(client, args.scope)
    try:
        issues = [client.issues[k] for k in str(args.scope).split(',')]
    except NotFound:
        raise Exception(f'"{args.scope}" contain unknown task(s).')
    return issues


def get_dates(issues, args, sprint_days=14) -> list:
    """Return list of dates of interest, according to args."""
    today = dt.datetime.now(dt.timezone.utc)
    if args.timespan == 'today':
        return [today]
    elif args.timespan == 'week':
        start_date = today + relativedelta(weeks=-1)
    elif args.timespan == 'month':
        start_date = today + relativedelta(months=-1)
    elif args.timespan == 'quarter':
        start_date = today + relativedelta(months=-3)
    elif args.timespan == 'sprint':
        start_date = today + relativedelta(days=-sprint_days)
    else:
        start_date = get_start_date(issues)
    return list(rrule(DAILY, dtstart=start_date, until=today))


def output(args, caption, data, trend=None):
    if args.output == 'plot':
        plot_details(caption, data, trend)
    elif args.output == 'dump':
        tabulate_details(data)
    else:
        tabulate_csv(data)
    if trend is not None:
        print(
            f'{trend["name"]} {caption.lower()} average velocity {trend["mid"][0]:.1f} hrs/day, {5 * trend["mid"][0] / 8:.1f} days/week.')
        middays = math.ceil(-trend['mid'][1] / trend['mid'][0])  # x(0) = -b/a for y(x)=ax+b
        mindays = math.ceil(-trend['min'][1] / trend['min'][0])  # x(0) = -b/a for y(x)=ax+b
        maxdays = math.ceil(-trend['max'][1] / trend['max'][0])  # x(0) = -b/a for y(x)=ax+b
        dates = [next(iter(data)) + relativedelta(days=mindays),
                 next(iter(data)) + relativedelta(days=middays),
                 next(iter(data)) + relativedelta(days=maxdays)]
        dates.sort()
        print(f'Projected {trend["name"]} zero-{caption.lower()} date:')
        table = PrettyTable()
        table.field_names = ['Early', 'Average', 'Lately']
        table.add_row([d.strftime("%d.%m.%y") for d in dates])
        print(table)


def trend_funnel(est):
    today = dt.datetime.now(dt.timezone.utc)
    dates = list(rrule(DAILY,
                       dtstart=today + relativedelta(months=-3),
                       until=today + relativedelta(weeks=-1)))
    mind = list()
    midd = list()
    maxd = list()
    for date in dates:
        tr = trends(est, 'Firmware', date)
        midd.append(tr['start'] + relativedelta(days=math.ceil(-tr['mid'][1] / tr['mid'][0])))
        mind.append(tr['start'] + relativedelta(days=math.ceil(-tr['min'][1] / tr['min'][0])))
        maxd.append(tr['start'] + relativedelta(days=math.ceil(-tr['max'][1] / tr['max'][0])))
    fig, ax = plt.subplots()
    ax.plot(dates, midd, color='k', linewidth=1)
    ax.plot(dates, mind, linestyle='dashed', color='k', linewidth=1)
    ax.plot(dates, maxd, linestyle='dashed', color='k', linewidth=1)
    formatter = DateFormatter("%d.%m.%y")
    ax.xaxis.set_major_formatter(formatter)
    ax.yaxis.set_major_formatter(formatter)
    plt.xlabel('Prediction start')
    plt.ylabel('Finish date')
    plt.grid()
    plt.draw()


def main():
    cfg = read_config('expendo.ini')
    client = TrackerClient(cfg['token'], cfg['org'])
    if client.myself is None:
        raise Exception('Unable to connect Yandex Tracker.')
    args = define_parser().parse_args()  # get CLI arguments
    print(f'Crawling tracker "{args.scope}"...')
    issues = get_scope(client, args)  # get issues objects
    precashe(issues, True)
    dates = get_dates(issues, args)  # get date range
    matplotlib.use('TkAgg')
    if args.parameter in ['estimate', 'all']:
        est = estimate(issues, dates, args.grouping)
        tr = trends(est, 'Firmware')
        output(args, 'Estimates', est, tr)  # trend temporary debug
        trend_funnel(est)
    if args.parameter in ['spent', 'all']:
        spt = spent(issues, dates, args.grouping)
        output(args, 'Spends', spt)
    # plt.ion()  # Turn on interactive plotting - not working, requires events loop for open plots
    if args.output == 'plot':
        print('Close plot widget(s) to continue...')
    plt.show()
    input('Press any key to close...')  # for interactive mode


if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        print('Execution error:', e)
        input('Press any key to close...')
