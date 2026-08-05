import time
from collections import defaultdict


class PerfTimer:
    timer_data = defaultdict(list)
    timer_tmp = {}

    def start(self, key='time'):
        self.timer_tmp[key] = time.time()

    def stop(self, key='time', max_samples=30):
        self.timer_data[key].append(time.time() - self.timer_tmp[key])

    def __str__(self):
        return '<Timer [' + ', '.join(f'{key}: {sum(samples) / len(samples)}'
                                      for key, samples in self.timer_data.items()) + ']>'


def smoothstep(f, fmin=0, fmax=1):
    f = max(0, min(1, (f - fmin) / (fmax - fmin)))
    return f * f * (3 - 2 * f)


def lerp(a, b, f):
    return (b - a) * f + a


def intersect_point_2d_rectangle(px, py, rx, ry, width, height):
    if px <= rx:
        return False
    if py <= ry:
        return False
    if px - rx >= width:
        return False
    if py - ry >= height:
        return False

    return True


def iter_float_factor(value, max_val, power_fac=1, size=1):
    value = (value / size) ** power_fac * size
    i = 0
    while value > 0:
        yield i, min(value, max_val)
        value -= max_val
        i += 1
