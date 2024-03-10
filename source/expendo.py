from yandex_tracker_client import TrackerClient
from yandex_tracker_client.exceptions import NotFound
import datetime as dt
from dateutil.rrule import rrule, DAILY
from dateutil.relativedelta import relativedelta
import math
import matplotlib
import matplotlib.pyplot as plt
from matplotlib.dates import DateFormatter
import configparser
import argparse
from prettytable import PrettyTable

from tracker_data import epics, stories, get_start_date, estimate, spent, precashe, sprints, velocity
from prediction import trends


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
        table.add_row([s.name, dt.datetime.strptime(s.startDate, '%Y-%m-%d').date()])
    print(table)


# Data output routines

def plot_details(title: str, d: dict, trend):
    fig, ax = plt.subplots()
    trend_color = 'k'
    for row in d[next(iter(d))].keys():
        p = ax.plot(list(d.keys()),
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


def plot_velocity(title: str, d: dict):
    fig, ax = plt.subplots()
    for row in iter(d):
        if len(d[row]) > 0:
            ax.plot(list(d[row].keys()), list(d[row].values()), label=row, linewidth=1, marker='.')
    formatter = DateFormatter("%d.%m.%y")
    ax.xaxis.set_major_formatter(formatter)
    plt.xlabel('Sprint date')
    plt.ylabel('[hours/sprint]')
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
                        help='output format')
    parser.add_argument('timespan', choices=['today', 'week', 'sprint', 'month', 'quarter', 'all'],
                        help='calculation time range')
    return parser


def get_scope(client, args):
    """Return list of scoped issue objects."""
    if args.scope in [p.name for p in client.projects]:
        # if argument is a project name
        if args.grouping == stories:
            return stories(client, args.scope)
        return epics(client, args.scope)
    # else argument is issues list, and epics or stories grouping ignored
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
        print(f"{trend['name']} {caption.lower()} average velocity {trend['mid'][0]:.1f} hrs/day,"
              f" {14 * trend['mid'][0]:.1f} hrs/sprint.")
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
    if (today.date() - next(iter(est))).days < 7:
        raise Exception('Not enough data for prediction (at least 7 days retro required).')
    dates = list(rrule(DAILY,
                       dtstart=next(iter(est)),
                       until=(today + relativedelta(weeks=-1)).date()))
    predictions = [((tr := trends(est, 'Firmware', date))['start'] +
                    relativedelta(days=math.ceil(tr['min'][1] / -tr['min'][0])),
                    tr['start'] + relativedelta(days=math.ceil(-tr['mid'][1] / tr['mid'][0])),
                    tr['start'] + relativedelta(days=math.ceil(-tr['max'][1] / tr['max'][0]))) for date in dates]
    mind, midd, maxd = zip(*predictions)
    p_range = [(today.date() - date.date()).days for date in dates]
    fig, ax = plt.subplots()
    ax.plot(p_range, midd, color='k', linewidth=1)
    ax.plot(p_range, mind, linestyle='dashed', color='k', linewidth=1)
    ax.plot(p_range, maxd, linestyle='dashed', color='k', linewidth=1)
    formatter = DateFormatter("%d.%m.%y")
    # ax.xaxis.set_major_formatter(formatter)
    ax.yaxis.set_major_formatter(formatter)
    plt.xlabel('Retro range, days')
    plt.title('Firmware finish date')
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
        vel = velocity(issues, args.grouping)
        plot_velocity('Velocity at sprint', vel)
    if args.parameter in ['spent', 'all']:
        spt = spent(issues, dates, args.grouping)
        output(args, 'Spends', spt)
    # plt.ion()  # Turn on interactive plotting - not working, requires events loop for open plots
    if args.output == 'plot':
        print('Close plot widget(s) to continue...')
    plt.show()
    input('Press any key to close...')  # for interactive mode


def dev(issues):
    table = PrettyTable()
    table.field_names = ['Key', 'Type', 'Summary', 'Status', 'Resolution']
    for issue in issues:
        table.add_row([issue.key, issue.type.key, issue.summary, issue.status.key, issue.resolution.key])
    print(table)


if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        print('Execution error:', e)
        input('Press any key to close...')
