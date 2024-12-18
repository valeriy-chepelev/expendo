from tracker_data import _linked_issues, _issue_times, _issue_original, get_start_date
import datetime as dt
from dateutil.rrule import rrule, DAILY, WEEKLY, MONTHLY

TODAY = dt.datetime.now(dt.timezone.utc).date()
ACTIVE_SPRINT_START = TODAY
FUTURE_SPRINT_START = TODAY
SPRINT_DAYS = [TODAY]
ALL_DAYS = [TODAY]
SPRINT_LEN = 14


def tasks(client, request, scan: bool = True) -> list:
    """ Search Tasks and Bugs using YT query.
    Includes all the sibling task within Epics and Stories given by query.
    :param client: TrackerClient object
    :param request: string with YT query language
    :param scan: scan and include all the sibling task within Epics and Stories given by request
    :return: list of YT issues objects"""
    issues = client.issues.find(query=request)
    tickets = {issue.key: issue for issue in issues if issue.type.key in ['task', 'bug']}
    if scan:
        ancestors = [issue for issue in issues if issue.type.key not in ['task', 'bug']]
        while ancestors:
            siblings = _linked_issues(ancestors.pop())
            tickets.update({issue.key: issue for issue in siblings if issue.type.key in ['task', 'bug']})
            ancestors.extend([issue for issue in siblings if issue.type.key not in ['task', 'bug']])
    return list(tickets.values())


def estimate(issues, date=TODAY):
    """
    Summ issues estimate up to the date (including).
    Assumed closed task always has zero estimation.
    :param issues: iterable of YT issues objects
    :param date: date part value of datetime
    :return: int hours
    """
    return sum([next((s['value'] for s in _issue_times(issue)
                      if s['kind'] == 'estimation' and s['date'].date() <= date), 0)
                for issue in issues])


def original(issues, date=TODAY):
    """
    Summ original (first before WIP) issues estimate up to the date (including).
    Consider issue closing date. Ignores rejected issues.
    :param issues: iterable of YT issues objects
    :param date: date part value of datetime
    :return: int hours
    """
    return sum([e.original for issue in issues
                if (e := _issue_original(issue)).valuable & (e.created <= date <= e.end)])


def spent(issues, date=TODAY, period: int = 0):
    """
    Summ issues spent up to the date (including), total or for a period.
    :param issues: iterable of YT issues objects
    :param date: date part value of datetime
    :param period: period length in days, zero means all from the beginning
    :return: int hours
    """
    return sum([next((s['value'] for s in _issue_times(issue)
                      if s['kind'] == 'spent' and s['date'].date() <= date), 0) -
                (next((s['value'] for s in _issue_times(issue)
                       if s['kind'] == 'spent' and s['date'].date() <= date -
                       dt.timedelta(days=period)), 0) if period else 0)
                for issue in issues])


def burned(issues, date=TODAY, period: int = 0):
    """
    Summ closed original (first before WIP) issues estimate up to the date (including),
    total or for a period.
    :param issues: iterable of YT issues objects
    :param date: date part value of datetime
    :param period: period length in days, zero means all from the beginning
    :return: int hours
    """
    return sum([e.original for issue in issues
                if (e := _issue_original(issue)).valuable & e.finished &
                ((date - dt.timedelta(days=period) < e.end <= date) if period else (e.end <= date))])


def count_created(issues, date=TODAY, period: int = 0):
    """
    Count issues created up to the date (including),
    total or for a period.
    :param issues: iterable of YT issues objects
    :param date: date part value of datetime
    :param period: period length in days, zero means all from the beginning
    :return: int issues count
    """
    dates = [dt.datetime.strptime(issue.createdAt, '%Y-%m-%dT%H:%M:%S.%f%z').date() for issue in issues]
    dates.sort()
    predate = date - dt.timedelta(days=period)
    prev = next((i for i, d in enumerate(dates) if d > predate),
                len(dates) if dates[-1] <= predate else 0) if period else 0
    return next((i for i, d in enumerate(dates) if d > date), len(dates) if dates[-1] <= date else 0) - prev


def count_wip(issues, date=TODAY, period: int = 0):
    """
    Count issues InProgress (once WIP, not closed or rejected) up to the date (including),
    total or for a period.
    :param issues: iterable of YT issues objects
    :param date: date part value of datetime
    :param period: period length in days, zero means all from the beginning
    :return: int issues count
    """
    predate = date - dt.timedelta(days=period) if period else dt.date(1973, 11, 29)
    return len([1 for issue in issues if max(predate, (s := _issue_original(issue)).start) <= min(date, s.end)])


def count_success(issues, date=TODAY, period: int = 0):
    """
    Count resolved issues (not rejected) up to the date (including),
    total or for a period.
    :param issues: iterable of YT issues objects
    :param date: date part value of datetime
    :param period: period length in days, zero means total
    :return: int issues count
    """
    dates = [s.end for issue in issues if (s := _issue_original(issue)).valuable and s.finished]
    dates.sort()
    predate = date - dt.timedelta(days=period)
    prev = next((i for i, d in enumerate(dates) if d > predate),
                len(dates) if dates[-1] <= predate else 0) if period else 0
    return next((i for i, d in enumerate(dates) if d > date), len(dates) if dates[-1] <= date else 0) - prev


def ttr_stat(issues):
    """
    Calculate issues time-to-resolve (from first WIP to last resolution).
    Ignores not resolved or rejected issues.
    :param issues: iterable of YT issues objects
    :return: sorted array of int (days)
    """
    return sorted([(s.end - s.start).days
                   for issue in issues if (s := _issue_original(issue)).valuable and s.finished])


def ttj_stat(issues):
    """
    Calculate issues time-to-job (creation to first WIP).
    Ignores untouched issues.
    :param issues: iterable of YT issues objects
    :return: sorted array of int (days)
    """
    started = {issue.key: next((t['date'] for t in reversed(_issue_times(issue))
                                if t['kind'] == 'status' and t['value'] in ['inProgress', 'testing']),
                               None) for issue in issues}
    return sorted([(started[issue.key].date() -
                    dt.datetime.strptime(issue.createdAt, '%Y-%m-%dT%H:%M:%S.%f%z').date()).days
                   for issue in issues if started[issue.key] is not None])


def update_dates(config, issues):
    # reset globals to default today
    global ACTIVE_SPRINT_START
    global FUTURE_SPRINT_START
    global SPRINT_DAYS
    global ALL_DAYS
    global SPRINT_LEN
    ACTIVE_SPRINT_START = TODAY
    FUTURE_SPRINT_START = TODAY
    SPRINT_DAYS = [TODAY]
    ALL_DAYS = [TODAY]
    # convert values from config
    base_date = dt.datetime.strptime(config['sprint_base'], '%d.%m.%y').date()
    SPRINT_LEN = int(config['sprint_len'])
    # find sprint start by rounding today downward
    ACTIVE_SPRINT_START -= dt.timedelta(days=SPRINT_LEN - abs((ACTIVE_SPRINT_START - base_date).days) % SPRINT_LEN)
    # find sprint end by rounding today forward
    FUTURE_SPRINT_START += dt.timedelta(days=abs((FUTURE_SPRINT_START - base_date).days) % SPRINT_LEN)
    # get first estimation of issues
    start = get_start_date(issues, show_bar=False).date()
    # find first sprint by rounding start downward
    start -= dt.timedelta(days=SPRINT_LEN - abs((start - base_date).days) % SPRINT_LEN)
    # generate days and remove time
    SPRINT_DAYS = [r.date() for r in rrule(DAILY, interval=SPRINT_LEN, dtstart=start, until=FUTURE_SPRINT_START)]
    ALL_DAYS = [r.date() for r in rrule(DAILY, interval=1, dtstart=start, until=FUTURE_SPRINT_START)]


from expendo import read_config
from yandex_tracker_client import TrackerClient
from prettytable import PrettyTable
import pyperclip
from numpy import histogram, median, mean, std
import matplotlib
import matplotlib.pyplot as plt


def stat_histogram(name, stat):
    max_val = min(70, 7 * (max(stat) // 7))
    bins = sorted(list(set(range(0, max_val, 7)).union({1, max_val, max(stat)})))
    hist, bins = histogram(stat, bins=bins)
    fig, ax = plt.subplots()
    ax.bar([str(x) for x in bins[1:]], hist, align='edge', width=-1)
    text_str = '\n'.join((
        r'$\mathrm{median}=%.2f$' % (median(stat),),
        r'$\mu=%.2f$' % (mean(stat),),
        r'$\sigma=%.2f$' % (std(stat),)))
    props = dict(boxstyle='round', facecolor='wheat', alpha=0.5)
    ax.text(0.95, 0.95, text_str, transform=ax.transAxes, ha='right', va='top', fontsize=14,
            verticalalignment='top', bbox=props)
    # ax.vlines([str(min(bins, key=lambda x: abs(x - med))),
    #           str(min(bins, key=lambda x: abs(x - avg)))],
    #          ymin=0, ymax=max(hist), colors='r')
    plt.grid()
    plt.xlabel('days')
    plt.ylabel('issues')
    plt.title(name)
    plt.draw()


def general_plot(issues):
    bgs = [issue for issue in issues if issue.type.key == 'bug']
    tsks = [issue for issue in issues if issue.type.key == 'task']
    fig, axs = plt.subplots(2, 2)
    ax = axs[0][0]
    patches, *_ = ax.pie([len([1 for s in tsks if s.resolution is not None and s.resolution.key in ['fixed']]),
                          len([1 for s in tsks if s.resolution is not None and s.resolution.key not in ['fixed']]),
                          len([1 for s in tsks if s.resolution is None])],
                         autopct=lambda a: f"{a:.1f}%\n{a * len(tsks) / 100:.0f}", pctdistance=1.3,
                         textprops={'size': 'smaller'})
    ax.legend(patches, ['Resolved', 'Rejected', 'Active'], loc='lower left')
    ax.set_title('Tasks')
    ax = axs[1][0]
    patches, *_ = ax.pie([len([1 for s in bgs if s.resolution is not None and s.resolution.key in ['fixed']]),
                          len([1 for s in bgs if s.resolution is not None and s.resolution.key not in ['fixed']]),
                          len([1 for s in bgs if s.resolution is None])],
                         autopct=lambda a: f"{a:.1f}%\n{a * len(bgs) / 100:.0f}", pctdistance=1.3,
                         textprops={'size': 'smaller'})
    ax.legend(patches, ['Resolved', 'Rejected', 'Active'], loc='lower left')
    ax.set_title('Bugs')
    ax = axs[0][1]
    patches = ax.bar(['Spent', 'Burned'], [(sp := spent(tsks)) // 8, brd := (br := burned(tsks)) // 8],
                     color=['tab:blue', 'tab:orange'])
    ax.bar_label(patches, label_type='center',
                 fmt=lambda a: '\n'.join([f'{a:.0f}', f'{br / sp * 100:.1f}%' if sp and (a == brd) else '']))
    ax.axes.get_yaxis().set_visible(False)
    ax.spines['left'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.spines['top'].set_visible(False)
    ax = axs[1][1]
    patches = ax.bar(['Spent', 'Burned'], [(sp := spent(bgs)) // 8, brd := (br := burned(bgs)) // 8],
                     color=['tab:blue', 'tab:orange'])
    ax.bar_label(patches, label_type='center',
                 fmt=lambda a: '\n'.join([f'{a:.0f}', f'{br / sp * 100:.1f}%' if sp and (a == brd) else '']))
    ax.axes.get_yaxis().set_visible(False)
    ax.spines['left'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.spines['top'].set_visible(False)


def general_stat(issues):
    bgs = [issue for issue in issues if issue.type.key == 'bug']
    tsks = [issue for issue in issues if issue.type.key == 'task']
    tbl = PrettyTable()
    tbl.field_names = ['Type', 'Count', 'Resolved', 'Rejected', 'Active', 'Days spent', 'Days burned', 'B/S, %']
    tbl.add_row(['Tasks', len(tsks),
                 len([1 for s in tsks if s.resolution is not None and s.resolution.key in ['fixed']]),
                 len([1 for s in tsks if s.resolution is not None and s.resolution.key not in ['fixed']]),
                 len([1 for s in tsks if s.resolution is None]),
                 (sp := spent(tsks)) // 8,
                 (br := burned(tsks)) // 8,
                 "{:.1f}".format(100 * br / sp) if sp else 'n/a'])
    tbl.add_row(['Bugs', len(bgs),
                 len([1 for s in bgs if s.resolution is not None and s.resolution.key in ['fixed']]),
                 len([1 for s in bgs if s.resolution is not None and s.resolution.key not in ['fixed']]),
                 len([1 for s in bgs if s.resolution is None]),
                 (sp := spent(bgs)) // 8,
                 (br := burned(bgs)) // 8,
                 "{:.1f}".format(100 * br / sp) if sp else 'n/a'], divider=True)
    tbl.add_row(['Total', len(issues),
                 len([1 for s in issues if s.resolution is not None and s.resolution.key in ['fixed']]),
                 len([1 for s in issues if s.resolution is not None and s.resolution.key not in ['fixed']]),
                 len([1 for s in issues if s.resolution is None]),
                 (sp := spent(issues)) // 8,
                 (br := burned(issues)) // 8,
                 "{:.1f}".format(100 * br / sp) if sp else 'n/a'])
    tbl.align = 'r'
    print(tbl)


cfg = read_config('expendo.ini')
client = TrackerClient(cfg['token'], cfg['org'])

# ts = tasks(client, 'Project: "MT SystemeLogic(ACB)" AND Queue: MTHW')
ts = tasks(client, 'Project: "MT ДУГА-О2 Нео" AND Queue: MTHW')

matplotlib.use('TkAgg')
general_stat(ts)
# general_plot(ts)
stat_histogram('Time To Resolve', ttr_stat(ts))
stat_histogram('Time To Start', ttj_stat(ts))
update_dates(cfg, ts)
table = PrettyTable()
table.field_names = ['Date', 'Created', 'Wip', 'Success']
# x = SPRINT_LEN
x = 0
for day in SPRINT_DAYS:
    table.add_row([day,
                   count_created(ts, day, x),
                   count_wip(ts, day, x),
                   count_success(ts, day, x)])
pyperclip.copy(table.get_csv_string())
table.align = 'r'
print(table)
print('Close plot widget(s) to continue...')
plt.show()
