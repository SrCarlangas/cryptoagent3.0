"""Offline research harness. Not part of the production package or the frozen gate.

Everything here is exploratory backtesting on the frozen historical dataset. It
never places orders, never uses credentials, and its parameter search is confined
to the training split. Out-of-sample numbers are read once for reporting only.
"""
