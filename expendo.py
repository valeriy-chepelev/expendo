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


def read_config(filename):
    config = configparser.ConfigParser()
    config.read(filename)
    assert 'token' in config['DEFAULT']
    assert 'org' in config['DEFAULT']
    return config['DEFAULT']


def _get_iso_split(s, split):
    """ Splitter helper for converting ISO dt notation"""
    if split in s:
        n, s = s.split(split)
    else:
        n = 0
    if n == '':
        n = 0
    return int(n), s


def iso_hrs(s):
    """ Convert ISO dt notation to hours.
    Mean 8 hours per day, 5 day per week.
    Values except Weeks, Days, Hours ignored."""
    if s is None:
        return 0
    # Remove prefix
    s = s.split('P')[-1]
    # Step through letter dividers
    weeks, s = _get_iso_split(s, 'W')
    days, s = _get_iso_split(s, 'D')
    _, s = _get_iso_split(s, 'T')
    hours, s = _get_iso_split(s, 'H')
    # Convert all to hours
    return (weeks * 5 + days) * 8 + hours


def iso_days(s):
    """ Convert ISO dt notation to hours.
    Mean 8 hours per day, 5 day per week.
    Values except Weeks, Days, Hours ignored.
    Hours less than 8 rounded up to 1 day."""
    return math.ceil(iso_hrs(s) / 8)


def epics(client, project):
    """ Return list of all project epics """
    request = f'Project: "{project}" Type: "Epic" "Sort by": Created ASC'
    return client.issues.find(query=request)


def stories(client, project):
    """ Return list of first-level project stories"""
    request = f'Project: "{project}" Type: "Story" "Sort by": Created ASC'
    return [st for st in client.issues.find(query=request)
            if (e := st.parent) is not None and e.type.key == 'epic']


def components(issues: list, w_bar=False):
    """ Return list of components assigned to issues and all of its descendants """
    comp = set()
    if w_bar:
        with alive_bar(len(issues), title='Components', theme='classic') as bar:
            for issue in issues:
                comp.update({comp.name for comp in issue.components})
                comp.update(set(components(_get_linked(issue))))
                bar()
    else:
        for issue in issues:
            comp.update({comp.name for comp in issue.components})
            comp.update(set(components(_get_linked(issue))))
    return sorted(list(comp))


@lru_cache(maxsize=None)  # Cashing access to YT
def cashed_components(issue):
    """ Return one issue components """
    return components([issue])


def queues(issues: list, w_bar=False):
    """ Return list of queues used by issues and all of its descendants """
    q = set()
    if w_bar:
        with alive_bar(len(issues), title='Queues', theme='classic') as bar:
            for issue in issues:
                q.add(issue.queue.key)
                q.update(set(queues(_get_linked(issue))))
                bar()
    else:
        for issue in issues:
            q.add(issue.queue.key)
            q.update(set(queues(_get_linked(issue))))
    return sorted(list(q))


@lru_cache(maxsize=None)  # Cashing access to YT
def cashed_queues(issue):
    """ Return one issue queues """
    return queues([issue])


@lru_cache(maxsize=None)  # Cashing access to YT
def _get_issue_times(issue):
    """ Return reverse-sorted list of issue spent and estimates """
    sp = [{'date': dt.datetime.strptime(log.updatedAt, '%Y-%m-%dT%H:%M:%S.%f%z'),
           'kind': field['field'].id,
           'value': 0 if (v := field['to']) is None else iso_hrs(v)}
          for log in issue.changelog for field in log.fields
          if field['field'].id in ['spent', 'estimation']]
    sp.sort(key=lambda d: d['date'], reverse=True)
    return sp


@lru_cache(maxsize=None)  # Cashing access to YT
def _get_linked(issue):
    """ Return list of issue linked subtasks """
    return [link.object for link in issue.links
            if link.type.id == 'subtask' and
            dict(outward=link.type.inward, inward=link.type.outward)[link.direction] == 'Подзадача']


def issue_spent(issue, date, mode, cat, default_comp=()):
    """ Return summary spent of issue (hours) including spent of all child issues,
    due to the date, containing specified component."""
    if mode == 'components':
        own_cat = cashed_components(issue)
    elif mode == 'queues':
        own_cat = cashed_queues(issue)
    else:
        own_cat = list()
    sp = 0
    if (cat == '' or cat in own_cat) or \
            (mode not in ['components', 'queues']) or \
            (len(own_cat) == 0 and cat in default_comp):
        spends = _get_issue_times(issue)
        sp = next((s['value'] for s in spends
                   if s['kind'] == 'spent' and s['date'].date() <= date.date()), 0) + \
             sum([issue_spent(linked, date, mode, cat,
                              own_cat if mode == 'components' and len(own_cat) > 0 \
                                  else default_comp)
                  for linked in _get_linked(issue)])
    return sp


def issue_estimate(issue, date, mode, cat, default_comp=()):
    """ Return estimate of issue (hours) as summary estimates of all child issues,
    for the date, containing specified component."""
    if mode == 'components':
        own_cat = cashed_components(issue)
    elif mode == 'queues':
        own_cat = cashed_queues(issue)
    else:
        own_cat = list()
    est = 0
    if (cat == '' or cat in own_cat) or \
            (mode not in ['components', 'queues']) or \
            (len(own_cat) == 0 and cat in default_comp):
        if len(_get_linked(issue)) == 0:
            estimates = _get_issue_times(issue)
            est = next((s['value'] for s in estimates
                        if s['kind'] == 'estimation' and s['date'].date() <= date.date()), 0)
        else:
            est = sum([issue_estimate(linked, date, mode, cat,
                                      own_cat if mode == 'components' and len(own_cat) > 0 \
                                          else default_comp)
                       for linked in _get_linked(issue)])
    return est


def spent(issues: list, dates: list, mode):
    """ Return issues summary spent daily timeline as dictionary of
    {date: {issue_key: spent[days]}} for the listed issues.
    If by_component requested, collect spent for issues components and return
    timeline {date: {component: spent[days]}}.
    Issue in list should be yandex tracker reference."""
    if mode == 'queues':
        cats = queues(issues, True)
    elif mode == 'components':
        cats = components(issues, True)
    else:
        cats = ['']
    with alive_bar(len(issues) * len(cats) * len(dates),
                   title='Spends', theme='classic') as bar:
        if mode in ['queues', 'components']:
            return {date.date(): {cat:
                                      sum([issue_spent(issue, date, mode, cat)
                                           for issue in issues
                                           if bar() not in ['nothing']])
                                  for cat in cats}
                    for date in dates}
        else:
            return {date.date(): {issue.key:
                                      issue_spent(issue, date, mode, '')
                                  for issue in issues
                                  if bar() not in ['nothing']}
                    for date in dates}


def estimate(issues: list, dates: list, mode):
    """ Return issues estimate daily timeline as dictionary of
    {date: {issue_key: estimate[days]}} for the listed issues.
    If by_component requested, collect estimates for issues components and return
    timeline {date: {component: estimate[days]}}.
    Issue in list should be yandex tracker reference."""
    if mode == 'queues':
        cats = queues(issues, True)
    elif mode == 'components':
        cats = components(issues, True)
    else:
        cats = ['']
    with alive_bar(len(issues) * len(cats) * len(dates),
                   title='Estimates', theme='classic') as bar:
        if mode in ['queues', 'components']:
            return {date.date(): {cat:
                                      sum([issue_estimate(issue, date, mode, cat)
                                           for issue in issues
                                           if bar() not in ['nothing']])
                                  for cat in cats}
                    for date in dates}
        else:
            return {date.date(): {issue.key:
                                      issue_estimate(issue, date, mode, '')
                                  for issue in issues
                                  if bar() not in ['nothing']}
                    for date in dates}


def get_start_date(issues: list):
    """ Return start date (first estimation date) of issues """
    with alive_bar(len(issues), title='Start date', theme='classic') as bar:
        try:
            d = min([t[-1]['date'] for issue in issues
                     if (len(t := _get_issue_times(issue)) > 0) ^ (bar() in ['nothing'])])
        except ValueError:
            d = dt.datetime.now(dt.timezone.utc)
    return d


# Sprints info


@lru_cache(maxsize=None)  # Cashing access to YT
def issue_sprints(issue) -> list:
    """ Return list of issue sprints, including all the subtasks,
    according to the logs """
    #TODO: get full sprints info including dates
    spr = {sc[0].name} if (sc := issue.sprint) is not None and len(sc) > 0 else set()
    for log in issue.changelog:
        for field in log.fields:
            if field['field'].id == 'sprint':
                if (to := field['to']) is not None and len(to) > 0:
                    spr.add(to[0].name)
                if (fr := field['from']) is not None and len(fr) > 0:
                    spr.add(fr[0].name)
    for linked in _get_linked(issue):
        spr.update(issue_sprints(linked))
    return natsorted(list(spr))


def sprints(issues: list) -> list:
    """ Return list of sprints, where tasks was present, including all the subtasks,
    according to the logs """
    s = set()
    with alive_bar(len(issues), title='Sprints', theme='classic') as bar:
        for issue in issues:
            s.update(set(issue_sprints(issue)))
            bar()
    return natsorted(list(s))

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
    return a,b in solution to y = ax + b such that root mean square distance between trend line and original points is minimized
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
    return [client.issues[e] for e in keys]


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



def precashe(issues, with_bar=False):
    """ Execute calls to all cashed functions"""
    if with_bar:
        with alive_bar(3 * len(issues), title='Cashing', theme='classic') as bar:
            for issue in issues:
                cashed_queues(issue)
                bar()
                cashed_components(issue)
                bar()
                if len(_get_linked(issue)) == 0:
                    issue_sprints(issue)
                    _get_issue_times(issue)
                else:
                    precashe(_get_linked(issue))
                bar()
    else:
        for issue in issues:
            cashed_queues(issue)
            cashed_components(issue)
            if len(_get_linked(issue)) == 0:
                issue_sprints(issue)
                _get_issue_times(issue)
            else:
                precashe(_get_linked(issue))


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
