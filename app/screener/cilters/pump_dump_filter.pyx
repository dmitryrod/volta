# cython: language_level=3, boundscheck=True, wraparound=True

import time
from libc.math cimport INFINITY


def pump_dump_filter(
    object klines,
    int pd_interval_sec,
    double pd_min_change_pct,
):
    """
    Полный логический эквивалент Python-функции pump_dump_filter написанный на Cython.
    
    Возвращает:
        (ok: bool, metadata: dict, details: dict)
    """

    cdef double threshold = (time.time() - pd_interval_sec) * 1000
    cdef double start_price = INFINITY
    cdef list valid_klines = []
    
    cdef object kline
    cdef Py_ssize_t i