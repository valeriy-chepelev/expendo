from dateutil.relativedelta import relativedelta


def linreg(X, Y):
    """
    return a,b in solution to y = ax + b such that root-mean-square distance between trend line
    and original points is minimized
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
    if len(d.keys()) < 7:
        raise Exception('Not enough data for prediction (at least 7 days retro required).')
    # TODO: redefine date range
    dates = [date for date in d.keys() if start is None or not (date < start.date())]
    # calculate data regression
    original = [d[date][row] for date in dates]
    midc = linreg(range(len(original)), original)  # middle linear regression a,b
    midval = [midc[0] * i + midc[1] for i in range(len(original))]  # middle data row
    # calculate high regression
    maxval = [(i, val[1]) for i, val in enumerate(zip(midval, original))
              if val[1] > val[0]]  # get (index, value) for values higher middle
    maxc = linreg(*list(zip(*maxval))) if len(maxval) > 1 else midc
    # calculate low regression
    minval = [(i, val[1]) for i, val in enumerate(zip(midval, original))
              if val[1] < val[0]]  # get (index, value) for values lower middle
    minc = linreg(*list(zip(*minval))) if len(minval) > 1 else midc
    # return with fixed angles
    return {'name': row,
            'start': dates[0],
            'end': dates[-1],
            'mid': (min(midc[0], -0.001), midc[1]),
            'min': (min(midc[0], minc[0], -0.001), minc[1]),
            'max': (min(-0.001, max(midc[0], maxc[0])), maxc[1])}


def diff_data(d):
    """Calculate data differential day-to-day for all rows"""
    values = list(d.values())
    dv = [{key: 0 for key, value in values[0].items()}]
    for i in range(1, len(values)):
        dv.append({key: value - values[i - 1][key] for key, value in values[i].items()})
    return dict(zip(d.keys(), dv))


def summ_data(d, base_date):
    """Calculate summary ranges"""
    first = next(iter(d))
    last = next(reversed(d.keys()))
    x_date = base_date
    # move to first date
    while x_date < first:
        x_date += relativedelta(weeks=+2)
    while x_date > first:
        x_date += relativedelta(weeks=-2)
    ranges = []
    while x_date <= last:
        ranges.append(x_date)
        x_date += relativedelta(weeks=2)
    return {ranges[i - 1]: {key: sum([d[date][key] for date in d.keys()
                                      if ranges[i - 1] < date <= ranges[i]])
                            for key in d[next(iter(d))].keys()}
            for i in range(1, len(ranges))}
