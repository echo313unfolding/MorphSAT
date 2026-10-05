"""Normal CDF without scipy (Abramowitz & Stegun 7.1.26, |err| < 1.5e-7)."""

import numpy as np


def erf(x):
    x = np.asarray(x, dtype=float)
    s = np.sign(x)
    a = np.abs(x)
    t = 1.0 / (1.0 + 0.3275911 * a)
    y = 1.0 - (((((1.061405429 * t - 1.453152027) * t) + 1.421413741) * t - 0.284496736) * t
               + 0.254829592) * t * np.exp(-a * a)
    return s * y


def ncdf(z):
    return 0.5 * (1.0 + erf(np.asarray(z, dtype=float) / np.sqrt(2.0)))
