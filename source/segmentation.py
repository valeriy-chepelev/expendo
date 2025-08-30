def _compute_ab(stats):
    """
        Compute linear regression parameters (a, b) from aggregated statistics.

        Args:
            stats: Tuple containing (n, sum_x, sum_y, sum_xy, sum_x2, sum_y2)

        Returns:
            (a, b): Slope, intercept
    """
    n, sum_x, sum_y, sum_xy, sum_x2, _ = stats
    denominator = n * sum_x2 - sum_x * sum_x
    if abs(denominator) < 1e-10:
        # Handle degenerate case (vertical line)
        a = 0.0
        b = sum_y / n
    else:
        a = (n * sum_xy - sum_x * sum_y) / denominator
        b = (sum_y - a * sum_x) / n
    return a, b


def _compute_linreg(stats):
    """
    Compute linear regression parameters (a, b) and SSR from aggregated statistics.

    Args:
        stats: Tuple containing (n, sum_x, sum_y, sum_xy, sum_x2, sum_y2)

    Returns:
        (ssr, a, b): Sum of squared residuals, slope, intercept
    """
    n, _, sum_y, sum_xy, _, sum_y2 = stats
    if n <= 1:
        return 0.0, 0.0, 0.0

    a, b = _compute_ab(stats)

    # Compute SSR (sum of squared residuals)
    ssr = sum_y2 - a * sum_xy - b * sum_y
    return max(0.0, ssr), a, b


def _estimate_variance(data):
    """
    Estimate variance of a dataset.

    Args:
        data: List of numerical values

    Returns:
        Variance of the data
    """
    n = len(data)
    if n <= 1:
        return 0.0

    mean = sum(data) / n
    variance = sum((x - mean) ** 2 for x in data) / (n - 1)
    return variance


def _moving_average(data, window_size):
    """
    Calculate moving average of a time series.

    Args:
        data: List of time series values
        window_size: Size of the moving window

    Returns:
        List of smoothed values (same length as input, with edge values padded)
    """
    n = len(data)
    # Handle edge cases
    if window_size <= 1 or n <= window_size:
        return data.copy()

    # Initialize result with zeros
    result = [0.0] * n

    # Calculate moving average for central values
    for i in range(n):
        start = max(0, i - window_size // 2)
        end = min(n, i + window_size // 2 + 1)
        window = data[start:end]
        result[i] = sum(window) / len(window)

    return result


def _estimate_noise_variance(y, method='residuals'):
    """
    Estimate noise variance in time series data without external libraries.

    Args:
        y: List of time series values
        method: Method for variance estimation ('residuals', 'differences', 'residuals_smooth')

    Returns:
        Estimated variance of noise in the data
    """
    n = len(y)
    if n <= 1:
        return 0.0

    if method == 'residuals':
        # Fit a global linear trend and calculate residuals
        x = list(range(n))

        # Calculate linear regression coefficients manually
        sum_x = sum(x)
        sum_y = sum(y)
        sum_xy = sum(x_i * y_i for x_i, y_i in zip(x, y))
        sum_x2 = sum(x_i * x_i for x_i in x)

        # Slope (a) and intercept (b)
        a, b = _compute_ab((n, sum_x, sum_y, sum_xy, sum_x2, 0))

        # Calculate residuals
        residuals = [y_i - (a * x_i + b) for x_i, y_i in zip(x, y)]
        variance = _estimate_variance(residuals)

    elif method == 'differences':
        # Use first differences to estimate noise variance
        differences = [y[i] - y[i - 1] for i in range(1, n)]
        variance = _estimate_variance(differences) / 2

    elif method == 'residuals_smooth':
        # Use residuals from a smoothed version of the data
        window_size = max(3, min(10, n // 10))
        if window_size % 2 == 0:
            window_size += 1  # Ensure odd window size

        # Apply moving average
        smoothed = _moving_average(y, window_size)

        # Calculate residuals
        residuals = [y_i - smoothed_i for y_i, smoothed_i in zip(y, smoothed)]
        variance = _estimate_variance(residuals)

    else:
        raise ValueError("Method must be 'residuals', 'differences', or 'residuals_smooth'")

    return max(variance, 1e-10)  # Ensure non-zero variance


def calculate_lambda(y, c=5, method='residuals'):
    """
    Calculate regularization parameter λ based on estimated noise variance.

    Args:
        y: List of time series values
        c: Multiplier constant (typically 3-10)
        method: Method for variance estimation 'residuals', 'differences', or 'residuals_smooth'

    Returns:
        Lambda value for segmentation regularization
    """
    sigma_squared = _estimate_noise_variance(y, method)
    return c * sigma_squared


def bottom_up_segmentation(y, min_length, lam):
    """
    Perform bottom-up segmentation with linear approximation.

    Args:
        y: List of time series values
        min_length: Minimum segment length
        lam: Penalty parameter for segment creation

    Returns:
        list of segments: list of dicts with keys 'x1', 'x2', 'a', 'b', 'y1, 'y2', 'd0'
    """
    n = len(y)
    segments = []
    i = 0

    # Step 1: Initialize segments with minimum length
    while i < n:
        j = min(i + min_length - 1, n - 1)
        n_seg = j - i + 1
        sx = sy = sxy = sx2 = sy2 = 0.0

        # Compute statistics for the segment
        for idx in range(i, j + 1):
            x_val = idx
            y_val = y[idx]
            sx += x_val
            sy += y_val
            sxy += x_val * y_val
            sx2 += x_val * x_val
            sy2 += y_val * y_val

        stats = (n_seg, sx, sy, sxy, sx2, sy2)
        ssr_val, a, b = _compute_linreg(stats)

        segments.append({
            'start': i,
            'end': j,
            'stats': stats,
            'ssr': ssr_val
        })
        i = j + 1

    # Step 2: Merge segments iteratively
    changed = True
    while changed:
        changed = False
        n_seg = len(segments)
        if n_seg < 2:
            break

        best_delta_cost = float('inf')
        best_idx = -1
        best_merged = None

        # Evaluate all adjacent segment pairs
        for i in range(n_seg - 1):
            s1 = segments[i]
            s2 = segments[i + 1]

            # Merge statistics
            n1, sx1, sy1, sxy1, sx21, sy21 = s1['stats']
            n2, sx2, sy2, sxy2, sx22, sy22 = s2['stats']
            merged_stats = (
                n1 + n2,
                sx1 + sx2,
                sy1 + sy2,
                sxy1 + sxy2,
                sx21 + sx22,
                sy21 + sy22
            )

            merged_ssr, a, b = _compute_linreg(merged_stats)
            delta_ssr = merged_ssr - (s1['ssr'] + s2['ssr'])
            delta_cost = delta_ssr - lam  # Cost reduction from merging

            # Track best candidate
            if delta_cost < best_delta_cost:
                best_delta_cost = delta_cost
                best_idx = i
                best_merged = {
                    'start': s1['start'],
                    'end': s2['end'],
                    'stats': merged_stats,
                    'ssr': merged_ssr
                }

        # Apply merge if it reduces cost
        if best_delta_cost < 0:
            del segments[best_idx: best_idx + 2]
            segments.insert(best_idx, best_merged)
            changed = True

    # Step 3: Prepare results
    # breakpoints = [seg['end'] for seg in segments[:-1]]

    # Compute parameters for final segments
    final_segments = []
    for seg in segments:
        a, b = _compute_ab(seg['stats'])
        final_segments.append({
            'x1': seg['start'],
            'x2': seg['end'],
            'a': a,
            'b': b,
            'y1': a * seg['start'] + b,
            'y2': a * seg['end'] + b,
            'd0': -b / a if abs(a) > 1e-10 else -1,
            'lambda': lam
        })

    return final_segments
