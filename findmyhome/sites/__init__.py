"""Site adapters — one module per site, and nothing else anywhere.

Principle 1: adding a site costs one file here plus one entry in the configuration. What an
adapter may do is deliberately narrow (principle 2): discover URLs and extract fields. Filtering,
deduplication, history and email live in the core.
"""
