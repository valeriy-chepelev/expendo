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
from tracker_data import epics, stories, get_start_date, estimate, spent, precashe, burn
from prediction import trends
import logging


def read_config(filename):
    config = configparser.ConfigParser()
    config.read(filename)
    assert 'token' in config['DEFAULT']
    assert 'org' in config['DEFAULT']
    return config['DEFAULT']


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


def plot_velocity(title: str, d: dict, y_units: str):
    fig, ax = plt.subplots()
    for row in iter(d):
        if len(d[row]) > 0:
            ax.plot(list(d[row].keys()), list(d[row].values()), label=row, linewidth=1)
    formatter = DateFormatter("%d.%m.%y")
    ax.xaxis.set_major_formatter(formatter)
    plt.xlabel('Date')
    plt.ylabel(y_units)
    plt.grid()
    plt.legend()
    plt.title(title)
    fig.autofmt_xdate()
    plt.draw()


def table_velocity(d: dict):
    table = PrettyTable()
    table.field_names = ['Date', *d.keys(), 'Summary']
    for date in d[next(iter(d))].keys():
        values = [d[row][date] for row in iter(d)]
        table.add_row([date.strftime("%d.%m.%y"), *values, sum(values)])
    table.float_format = '.1'
    table.align = 'r'
    print(table)


def tabulate_velocity(d: dict):
    print('Date', *d.keys(), 'Summary', sep=',')
    for date in d[next(iter(d))].keys():
        summ = sum([d[row][date] for row in iter(d)])
        values = [f'{d[row][date]:.1f}' for row in iter(d)]
        print(date.strftime("%d.%m.%y"), *values, f'{summ:.1f}', sep=',')


def table_data(d: dict):
    table = PrettyTable()
    sk = [key for key in d[next(iter(d))].keys()]
    table.field_names = ['Date', *sk, 'Summary']
    for date in d.keys():
        sv = [str(val) for val in d[date].values()]
        table.add_row([date.strftime("%d.%m.%y"), *sv, sum(d[date].values())])
    table.align = 'r'
    print(table)


def tabulate_data(d: dict):
    print('Date', ",".join(d[next(iter(d))].keys()), 'Summary', sep=',')
    for date in d.keys():
        sval = ",".join([str(val) for val in d[date].values()])
        print(date.strftime("%d.%m.%y"), sval, sum(d[date].values()), sep=',')


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
    """
    parser = argparse.ArgumentParser(description='Expendo v.1.0 - Yandex Tracker stat crawler by VCh.',
                                     epilog='Tracker connection settings and params in "expendo.ini".')
    parser.add_argument('scope',
                        help='project name or comma-separated issues keys (no space allowed)')
    parser.add_argument('parameter', choices=['spent', 'estimate', 'velocity', 'burn', 'all'],
                        help='measured value')
    parser.add_argument('grouping', choices=['epics', 'stories', 'components', 'queues'],
                        help='value grouping criteria (epics, stories for project scope only)')
    parser.add_argument('timespan', choices=['today', 'week', 'sprint', 'month', 'quarter', 'all'],
                        help='time range (for spends and estimates only)')
    parser.add_argument('-t', '--trend',
                        help='make estimate trend projections for TREND issue')
    parser.add_argument('-p', '--plot', default=False, action='store_true',
                        help='plot charts widgets')
    parser.add_argument('-c', '--csv', default=False, action='store_true',
                        help='dump data in CSV format instead of pretty tables (for lazy Excel copy-pasting)')
    parser.add_argument('--debug', default=False, action='store_true',
                        help='logging in debug mode (include tracker and issues info)')
    return parser


def get_scope(client, args):
    """Return list of scoped issue objects."""
    if args.scope in [p.name for p in client.projects]:
        # if argument is a project name
        print(f'Crawling tracker in project "{args.scope}":')
        if args.grouping == stories:
            issues = stories(client, args.scope)  # Project top-level Stories for the 'stories'
        else:
            issues = epics(client, args.scope)  # Project top-level Epics for all except 'stories'
    # else argument is issues list, and epics or stories grouping _ignored_
    else:
        try:
            issues = [client.issues[k] for k in str(args.scope).split(',')]
            print('Crawling tracker in issues:')
        except NotFound:
            raise Exception(f'"{args.scope}" task(s) not found in tracker.')
    table = PrettyTable()
    table.field_names = ['Key', 'Type', 'Summary']
    for issue in issues:
        table.add_row([issue.key, issue.type.key, issue.summary])
    table.align = 'l'
    print(table)
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


def _date_shift(date, shift):
    if shift < 0:
        return "Unknown"
    if shift > 1095:
        return "Exceed 3 years"
    return date + relativedelta(days=shift)


def tabulate_trend(trend):
    print(f'{trend["name"]} estimate projection:')
    mid_days = math.ceil(-trend['mid'][1] / trend['mid'][0])  # x(0) = -b/a for y(x)=ax+b
    min_days = math.ceil(-trend['min'][1] / trend['min'][0])  # x(0) = -b/a for y(x)=ax+b
    max_days = math.ceil(-trend['max'][1] / trend['max'][0])  # x(0) = -b/a for y(x)=ax+b
    table = PrettyTable()
    table.field_names = ['Value', 'Early', 'Average', 'Lately']
    table.add_row(['Velocity, hrs/sprint',
                   f"{14 * trend['min'][0]:.1f}",
                   f"{14 * trend['mid'][0]:.1f}",
                   f"{14 * trend['max'][0]:.1f}"])
    table.add_row(['Projected finish',
                   s if type(s := _date_shift(trend['start'], min_days)) == str else s.strftime("%d.%m.%y"),
                   s if type(s := _date_shift(trend['start'], mid_days)) == str else s.strftime("%d.%m.%y"),
                   s if type(s := _date_shift(trend['start'], max_days)) == str else s.strftime("%d.%m.%y")])
    print(table)


def trend_funnel(est, row_name):
    today = dt.datetime.now(dt.timezone.utc)
    if (today.date() - next(iter(est))).days < 7:
        raise Exception('Not enough data for prediction (at least 7 days retro required).')
    dates = list(rrule(DAILY,
                       dtstart=next(iter(est)),
                       until=(today + relativedelta(weeks=-1)).date()))
    predictions = [(today.date() if type(d := _date_shift((tr := trends(est, row_name, date))['start'],
                                                          math.ceil(-tr['min'][1] / tr['min'][0]))) == str else d,
                    today.date() if type(d := _date_shift(tr['start'],
                                                          math.ceil(-tr['mid'][1] / tr['mid'][0]))) == str else d,
                    today.date() if type(d := _date_shift(tr['start'],
                                                          math.ceil(-tr['max'][1] / tr['max'][0]))) == str else d)
                   for date in dates]
    min_d, mid_d, max_d = zip(*predictions)
    p_range = [(today.date() - date.date()).days for date in dates]
    fig, ax = plt.subplots()
    ax.plot(p_range, mid_d, color='k', linewidth=1)
    ax.plot(p_range, min_d, linestyle='dashed', color='k', linewidth=1)
    ax.plot(p_range, max_d, linestyle='dashed', color='k', linewidth=1)
    formatter = DateFormatter("%d.%m.%y")
    ax.yaxis.set_major_formatter(formatter)
    plt.xlabel('Retro range [days]')
    plt.title('Finish date')
    plt.grid()
    plt.draw()


def main():
    args = define_parser().parse_args()  # get CLI arguments
    # TODO: logging
    logging.basicConfig(filename='expendo.log',
                        filemode='a',
                        format='%(asctime)s %(name)s %(levelname)s %(message)s',
                        datefmt='%H:%M:%S',
                        level=logging.INFO if args.debug else logging.ERROR)
    logging.info('Started with arguments: %s', vars(args))
    cfg = read_config('expendo.ini')
    client = TrackerClient(cfg['token'], cfg['org'])
    if client.myself is None:
        raise Exception('Unable to connect Yandex Tracker.')
    issues = get_scope(client, args)  # get issues objects
    precashe(issues, True)
    dates = get_dates(issues, args)  # get date range
    matplotlib.use('TkAgg')
    if args.parameter in ['spent', 'all']:
        spt = spent(issues, dates, args.grouping)
        print('Spends:')
        if args.csv:
            tabulate_data(spt)
        else:
            table_data(spt)
        if args.plot:
            plot_details('Spends', spt, None)
    if args.parameter in ['estimate', 'all']:
        est = estimate(issues, dates, args.grouping)
        print('Estimates:')
        if args.csv:
            tabulate_data(est)
        else:
            table_data(est)
        # Trends
        tr = None
        if args.trend is not None:
            try:
                tr = trends(est, args.trend)
                tabulate_trend(tr)
                if args.plot:
                    trend_funnel(est, args.trend)
            except Exception as ex:
                print('Execution error:', ex)
                logging.exception('Trends error')
        # Plot estimates with trends
        if args.plot:
            plot_details('Estimates', est, tr)
    if args.parameter in ['burn', 'all']:
        brn = burn(issues, args.grouping, False)
        print('Burned estimates:')
        if args.csv:
            tabulate_velocity(brn)
        else:
            table_velocity(brn)
        if args.plot:
            plot_velocity('Burned estimates', brn, '[hrs]')
    if args.parameter in ['velocity', 'all']:
        vel = burn(issues, args.grouping, True)
        print('Velocity of estimates burning:')
        if args.csv:
            tabulate_velocity(vel)
        else:
            table_velocity(vel)
        if args.plot:
            plot_velocity('Burning velocity', vel, '[hrs/day]')

    # plt.ion()  # Turn on interactive plotting - not working, requires events loop for open plots
    if args.plot:
        print('Close plot widget(s) to continue...')
    plt.show()
    input('Press any key to close...')  # for interactive mode


if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        print('Execution error:', e)
        logging.exception('Common error')
        input('Press any key to close...')
